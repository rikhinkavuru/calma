"""calma zero-touch guardrail - the Claude Code Stop hook.

When an agent finishes a turn, this hook sniffs the final message for checkable numeric
claims (sniff_claims.py - precision-tuned, fires rarely) and, when one is found in a
verifiable project, re-executes it with `calma verify` and recomputes the number. On a
definitive break (REFUTED / MIXED) it blocks the stop and hands the agent the verdict plus
the reporting contract, so a wrong number cannot be reported as fact. On everything else
it stays completely silent.

Operating rules (each one is load-bearing - see tests/test_hook.py):
  FAIL OPEN     any exception, timeout, malformed input, unreadable transcript, missing
                interpreter -> exit 0, no output. The hook must never break or slow a
                session it cannot help.
  NEVER LOOP    `stop_hook_active` set (we already blocked once this stop cycle) -> exit 0
                immediately. One verification round per stop, ever.
  NEVER NAG     a claim we already blocked on stays blocked-once: if the verify comes back
                from cache (code+data+claim unchanged) and the state file shows the claim
                was already reported, stay silent. New code or data -> a fresh verdict may
                block again, legitimately.
  NEVER BLOCK   on anything but a definitive break: CONFIRMED / CAN'T-CONFIRM / INCONCLUSIVE /
  BUT REPORT    unbindable / timeout / error never block (all breadcrumbed to
                .calma/auto_history.jsonl, surfaced by `calma stats`). When the hook ENGAGED
                (ran >=1 verify) it prints a one-line, non-blocking "what got checked this turn"
                coverage note (a systemMessage) so a team can SEE the guardrail is alive and
                leave it on - default on; CALMA_HOOK_COVERAGE=0 or config
                {"hook": {"coverage": false}} turns it off. A re-checked, already-reported
                break stays silent (never-nag).
  OPT OUT       env CALMA_HOOK=0|off|false, a `.calma/hook-off` file in the project or in
                $HOME/.calma, or `.calma/config.json` {"hook": {"enabled": false}}.
  STAY CHEAP    preflight (entrypoint + a data artifact, or an existing contract/.calma) gates
                the expensive step; the verify is cache-first and runs under a wall-clock budget
                (default 120s; env CALMA_TIMEOUT, else project config `timeout_s`), killed by
                process group on overrun. The child verify gets the FULL resolved budget - a real
                minutes-long backtest is verified, not silently killed at 30s.
  NO LITTER     breadcrumbs (and the .calma dir they live in) are only created AFTER the
                verifiable-target gate passes - a metric mention in an unrelated repo
                leaves nothing behind.
  SANDBOX FIRST auto-execution requires a VERIFIED sandbox tier (run_hermetic doctor,
                cached in hook state with a TTL). No verified sandbox -> skip with a
                "no-verified-sandbox" breadcrumb; config {"hook": {"force_unverified":
                true}} overrides on hosts the operator explicitly trusts.

stdin:  the Stop-hook JSON from Claude Code (session_id, transcript_path, cwd,
        stop_hook_active, ...).
stdout: nothing (silent pass), {"systemMessage": ...} carrying the coverage note when it ran
        a verify, or {"decision": "block", "reason": ...} on a catch.
exit:   always 0.
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

MAX_TRANSCRIPT_TAIL = 256 * 1024     # bytes of transcript read (the final turn lives here)
SNIFF_MAX_CHARS = 8 * 1024           # chars actually fed to the sniffer (a headline claim is short
                                     # and lives at the END; the sniffer also caps term-occurrences
                                     # internally + we bound wall-clock below - defense in depth)
SNIFF_BUDGET_S = 2                   # hard ceiling on the inline sniff so it never stalls a turn-end
DEFAULT_TIMEOUT_S = 120              # re-execution budget when nothing is configured. Real ML evals
                                     # and medium backtests finish well inside this; a long run raises
                                     # it via env CALMA_TIMEOUT or .calma/config.json {"hook":{"timeout_s"}}.
MIN_TIMEOUT_S = 5
MAX_TIMEOUT_S = 1800                 # operator (env CALMA_TIMEOUT) ceiling: 30 min.
PROJECT_MAX_TIMEOUT_S = 600          # a PROJECT's own timeout_s is bounded lower (10 min) so an
                                     # untrusted repo can't make the Stop hook hang the session.
DEFAULT_MAX_CLAIMS = 1               # verifications per stop - keep the hook imperceptible
STATE_NAME = "hook_state.json"
HISTORY_NAME = "auto_history.jsonl"
HISTORY_MAX_BYTES = 1024 * 1024      # cap auto_history.jsonl (one line per verifiable turn, incl.
                                     # cached no-ops) - rotate in place, keeping the recent tail
_CSV_SCAN_CAP = 400                  # dir entries examined during artifact preflight
SANDBOX_TTL_S = 24 * 3600            # how long a cached doctor (sandbox tier) result is trusted
import tiers as _tiers  # noqa: E402 - sibling leaf module (imports nothing); single source of the gate
VERIFIED_TIERS = _tiers.VERIFIED_TIERS

# machine-readable artifacts calma can recompute from - a metric claim is only worth
# auto-verifying where one of these exists (broadened past .csv: real projects emit Parquet/
# JSON-lines/npy/feather/sqlite too, which kept the hook from ever engaging on them).
_DATA_EXT = (".csv", ".tsv", ".parquet", ".npy", ".npz", ".feather", ".arrow", ".jsonl",
             ".ndjson", ".db", ".sqlite", ".sqlite3")
# .json is data OR config; count it only when it isn't an obvious config/manifest file
_CONFIG_JSON = {"package.json", "package-lock.json", "tsconfig.json", "composer.json",
                "manifest.json", "vercel.json", "renovate.json", "babel.config.json"}


def _is_data_artifact(name):
    low = name.lower()
    if low.endswith(_DATA_EXT):
        return True
    if low.endswith(".json") and name not in _CONFIG_JSON and not low.endswith(".config.json"):
        return True
    return False


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _killed_off_by_env():
    return os.environ.get("CALMA_HOOK", "").strip().lower() in ("0", "off", "false",
                                                                "disabled", "no")


def _trusted_force_unverified():
    """force_unverified BYPASSES the sandbox gate (auto-executes a project's code without a verified
    tier), so it is honored ONLY from a source the OPERATOR controls: the env var
    CALMA_HOOK_FORCE_UNVERIFIED, or the HOST-level config ($CALMA_STATE_DIR, else ~/.calma)/config.json
    - NEVER a project-local .calma/config.json. Otherwise an untrusted repo could opt ITSELF into
    unsandboxed auto-execution merely by being opened in an agent session."""
    if os.environ.get("CALMA_HOOK_FORCE_UNVERIFIED", "").strip().lower() in ("1", "on", "true", "yes"):
        return True
    base = os.environ.get("CALMA_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".calma")
    try:
        with open(os.path.join(base, "config.json")) as f:
            return bool((json.load(f).get("hook") or {}).get("force_unverified", False))
    except (OSError, ValueError, AttributeError):
        return False


def _hook_config(cwd):
    """Merged hook config: defaults <- project .calma/config.json {"hook": {...}}. A project may only
    DISABLE or LIMIT the hook (enabled / timeout_s / max_claims, all clamped downstream) - it can NEVER
    escalate. force_unverified (a sandbox-gate bypass) comes from a TRUSTED source ONLY (see
    _trusted_force_unverified), never from the project tree."""
    # max_claims default is None = "unset": the VERIFY SCOPE (autonomy) drives the per-turn budget, and
    # an explicit project max_claims only further LOWERS it (a project can limit the hook, never escalate).
    # timeout_s defaults to None ("unset") so _resolve_timeout owns the precedence
    # (env CALMA_TIMEOUT > this project value > DEFAULT_TIMEOUT_S). coverage defaults on.
    cfg = {"enabled": True, "timeout_s": None, "max_claims": None,
           "coverage": True, "force_unverified": False}
    try:
        with open(os.path.join(cwd, ".calma", "config.json")) as f:
            user = json.load(f).get("hook", {})
        if isinstance(user, dict):
            for k in ("enabled", "timeout_s", "max_claims", "coverage"):
                if k in user:
                    cfg[k] = user[k]
    except (OSError, ValueError, AttributeError):
        pass
    cfg["force_unverified"] = _trusted_force_unverified()
    return cfg


def _resolve_timeout(cfg):
    """The child verify's re-execution budget (seconds). Precedence:
        env CALMA_TIMEOUT  (operator, up to MAX_TIMEOUT_S)
        > project .calma/config.json {"hook": {"timeout_s"}}  (bounded lower - an untrusted repo
          must not be able to make the Stop hook hang the session for half an hour)
        > DEFAULT_TIMEOUT_S.
    The child gets the FULL resolved value - there is no silent 30s down-cap, so a real
    minutes-long backtest is actually re-executed and verified instead of killed mid-run."""
    env = os.environ.get("CALMA_TIMEOUT", "").strip()
    if env:
        try:
            return max(MIN_TIMEOUT_S, min(int(float(env)), MAX_TIMEOUT_S))
        except ValueError:
            pass
    raw = cfg.get("timeout_s")
    if raw is not None:
        try:
            return max(MIN_TIMEOUT_S, min(int(float(raw)), PROJECT_MAX_TIMEOUT_S))
        except (TypeError, ValueError):
            pass
    return DEFAULT_TIMEOUT_S


def _coverage_on(cfg):
    """Whether to print the one-line 'what got checked this turn' note. Default ON: a team has to be
    able to SEE the guardrail run to trust it and leave it on (the Turbo `>>> FULL TURBO` move - one
    terse line builds trust without nagging). env CALMA_HOOK_COVERAGE=0|off|false, the global
    CALMA_QUIET=1 (the inverse of HUSKY=0), or .calma/config.json {"hook": {"coverage": false}}
    turns it off."""
    if os.environ.get("CALMA_QUIET", "").strip().lower() in ("1", "on", "true", "yes"):
        return False
    env = os.environ.get("CALMA_HOOK_COVERAGE", "").strip().lower()
    if env in ("0", "off", "false", "no", "disabled"):
        return False
    if env in ("1", "on", "true", "yes"):
        return True
    return bool(cfg.get("coverage", True))


_COVERAGE_WORDS = {
    "CONFIRMED": "confirmed", "CONFIRMED-WITH-CAVEATS": "confirmed (caveats)",
    "REFUTED": "refuted", "INVALIDATED": "invalidated", "MIXED": "mixed",
    "FLAG_FOR_DECLARATION": "flag-for-declaration",
    "CAN'T-CONFIRM": "can't-confirm", "INCONCLUSIVE": "can't-confirm",
}


def _coverage_line(tally, budget, detected=None, max_claims=None):
    """One human line summarizing what calma checked this turn - the visible heartbeat that tells a
    team the guardrail is alive (vs. having silently no-op'd). Suppressed already-reported breaks are
    not counted here (never-nag). CR2: when more checkable numbers were DETECTED than the per-turn
    budget verified, say so explicitly ("the headline (1 of 4)") and point at CALMA_VERIFY=all, so a
    client is never misled into thinking every number was checked. Never raises."""
    bits = []
    for v, c in sorted(tally.get("verdicts", {}).items()):
        bits.append("%d %s" % (c, _COVERAGE_WORDS.get(v, str(v).lower())))
    if tally.get("timeout"):
        bits.append("%d timed out" % tally["timeout"])
    if tally.get("error"):
        bits.append("%d couldn't run" % tally["error"])
    n = (sum(tally.get("verdicts", {}).values()) + tally.get("timeout", 0)
         + tally.get("error", 0))
    body = ", ".join(bits) if bits else "nothing conclusive"
    if detected and max_claims and detected > max_claims:
        # the per-turn budget left some detected numbers unverified - be honest about coverage
        head = ("calma checked the headline (1 of %d numbers this turn)" % detected
                if max_claims == 1 else
                "calma checked %d of %d numbers this turn" % (n, detected))
        msg = "%s: %s. Set CALMA_VERIFY=all to verify the rest." % (head, body)
    else:
        msg = "calma checked %d number%s this turn: %s." % (
            n, "" if n == 1 else "s", body)
    if tally.get("timeout"):
        msg += (" The slow one hit the %ds budget - raise it with CALMA_TIMEOUT "
                "(or .calma/config.json {\"hook\":{\"timeout_s\"}}) to verify it." % budget)
    return msg


def _near_miss_line(near):
    """CR1: a one-line, non-blocking 'I saw a number I couldn't auto-verify' note. Fires only when
    NO claim bound but a result-shaped number sat next to a metric word in a verifiable repo - so a
    recall miss is visible (the client knows to run `calma verify`) instead of silently shipping."""
    n0 = near[0]
    extra = " (+%d more)" % (len(near) - 1) if len(near) > 1 else ""
    return ("calma saw a number it couldn't auto-verify - \"%s\" near \"%s\"%s. "
            "Run `calma verify` (or rephrase the claim) to check it."
            % (n0.get("value"), n0.get("term"), extra))


def _opted_out(cwd):
    for base in (cwd, os.path.expanduser("~")):
        if os.path.exists(os.path.join(base, ".calma", "hook-off")):
            return True
    return False


def _final_assistant_text(transcript_path):
    """The agent's final message: trailing run of assistant entries in the JSONL
    transcript (skipping sidechain/subagent lines), text blocks joined in order.
    Reads only the tail of large transcripts. Returns "" when unavailable."""
    if not os.path.isfile(transcript_path):
        return ""  # FIFO/socket/device (or absent): never open() (would block the Stop hook)
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            if size > MAX_TRANSCRIPT_TAIL:
                f.seek(size - MAX_TRANSCRIPT_TAIL)
                f.readline()  # drop the partial first line
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    texts = []
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict) or obj.get("isSidechain"):
            continue
        typ = obj.get("type")
        if typ == "assistant":
            content = (obj.get("message") or {}).get("content") or []
            chunk = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            if chunk:
                texts.append("\n".join(chunk))
            continue  # keep walking the trailing assistant run
        if typ in ("user", "human", "system"):
            break  # the turn boundary - we have the final message
    return "\n".join(reversed(texts)).strip()


def _verifiable_target(cwd):
    """Cheap preflight: only auto-verify where calma plausibly binds - an existing
    contract or run history, or an entrypoint candidate PLUS a CSV artifact nearby.
    `main.py` alone in some web project must never trigger an auto-execution."""
    try:
        # .calma alone is NOT evidence - the hook's own breadcrumbs create it; only a
        # verification cache (a prior real run) or a contract qualifies
        if os.path.exists(os.path.join(cwd, "verify.yaml")) \
                or os.path.exists(os.path.join(cwd, ".calma", "cache.json")):
            return True
        import draft_contract as DC
        has_entry = any(os.path.exists(os.path.join(cwd, c))
                        for c in DC.ENTRYPOINT_CANDIDATES)
        if not has_entry:
            return False
        seen = 0
        for root, dirs, files in os.walk(cwd):
            dirs[:] = [d for d in dirs
                       if not d.startswith(".") and d not in ("node_modules", "venv",
                                                              "__pycache__", "dist",
                                                              "build", "target")]
            depth = os.path.relpath(root, cwd).count(os.sep)
            if depth >= 2:
                dirs[:] = []
            for name in files:
                seen += 1
                if seen > _CSV_SCAN_CAP:
                    return False
                if _is_data_artifact(name):
                    return True
        return False
    except Exception:
        return False


def _claim_key(cand):
    s = "%s|%s" % (cand.get("metric"), cand.get("claim", "").strip().lower())
    return hashlib.sha256(s.encode()).hexdigest()[:24]


def _load_state(cwd):
    try:
        with open(os.path.join(cwd, ".calma", STATE_NAME)) as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(cwd, state):
    try:
        d = os.path.join(cwd, ".calma")
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, STATE_NAME + ".tmp")
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, os.path.join(d, STATE_NAME))
    except OSError:
        pass


def _breadcrumb(cwd, event, **fields):
    """Append one line to .calma/auto_history.jsonl - the seed of claims-as-code.
    Never raises; never blocks the verdict path."""
    try:
        d = os.path.join(cwd, ".calma")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, HISTORY_NAME)
        rec = {"ts": _now_iso(), "event": event}
        rec.update({k: v for k, v in fields.items() if v is not None})
        # cap the breadcrumb log: it's appended on every verifiable turn (incl. cached no-ops), so
        # rotate in place when it crosses HISTORY_MAX_BYTES, keeping the recent tail (calma stats
        # summarizes recent activity, not all of history).
        try:
            if os.path.getsize(path) > HISTORY_MAX_BYTES:
                with open(path, "rb") as f:
                    f.seek(-(HISTORY_MAX_BYTES // 2), os.SEEK_END)
                    tail = f.read()
                nl = tail.find(b"\n")
                with open(path, "wb") as f:
                    f.write(tail[nl + 1:] if nl >= 0 else b"")  # drop the partial first line
        except OSError:
            pass
        with open(path, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    except OSError:
        pass


def _host_state_path():
    base = os.environ.get("CALMA_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".calma")
    return os.path.join(base, STATE_NAME)


def _fresh(cached):
    try:
        return (time.time() - float(cached.get("ts", 0))) < SANDBOX_TTL_S
    except (TypeError, ValueError):
        return False


def _sandbox_tier(cwd, state):
    """The achieved isolation tier, cached. The tier is a property of the HOST (does sandbox-exec
    exist and deny egress + secret reads), not the project, so the probe is cached at user level
    (~/.calma) and reused across every project - the ~30s positive-control runs once per machine,
    not once per repo (the previous per-project cache made every new project pay it). Returns
    (tier, project_state_changed)."""
    host = {}
    try:
        with open(_host_state_path()) as f:
            host = (json.load(f).get("sandbox_tier") or {})
    except (OSError, ValueError, AttributeError):
        host = {}
    if host.get("tier") and _fresh(host):
        return host["tier"], False
    # fall back to a (legacy) per-project cache before paying for a fresh probe
    cached = state.get("sandbox_tier") or {}
    if cached.get("tier") and _fresh(cached):
        return cached["tier"], False
    import run_hermetic as H
    # native_doctor picks THIS OS's own-code tier (Seatbelt on macOS, bubblewrap on Linux) so the hook
    # is no longer pinned to host-not-isolated on Linux when a working bwrap tier is present.
    tier = H.native_doctor(cwd).get("tier", "host-not-isolated")
    rec = {"tier": tier, "ts": time.time()}
    state["sandbox_tier"] = rec
    try:  # persist host-wide so other projects skip the probe
        os.makedirs(os.path.dirname(_host_state_path()), exist_ok=True)
        try:
            with open(_host_state_path()) as f:
                hs = json.load(f)
            if not isinstance(hs, dict):
                hs = {}
        except (OSError, ValueError):
            hs = {}
        hs["sandbox_tier"] = rec
        tmp = _host_state_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(hs, f, indent=2)
        os.replace(tmp, _host_state_path())
    except OSError:
        pass
    return tier, True


def _run_verify(cwd, cand, timeout_s):
    """`calma verify <cwd> "<claim>" --metric <id> --json --run-id hook` under a process
    group with a hard kill. Returns (result dict | None, elapsed_ms, error string|None).
    No shell anywhere - transcript text can never inject into the command.
    The child gets the FULL resolved budget (see _resolve_timeout); the parent waits the same
    wall-clock and SIGKILLs the process group on overrun, so a hang can never wedge the session."""
    argv = [sys.executable or "python3", os.path.join(_HERE, "calma.py"), "verify", cwd,
            cand["claim"], "--metric", cand["metric"], "--json", "--run-id", "hook",
            "--timeout", str(int(timeout_s))]
    t0 = time.time()
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            out, _ = p.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except OSError:
                pass
            p.wait()
            return None, int((time.time() - t0) * 1000), "timeout"
    except OSError as e:
        return None, int((time.time() - t0) * 1000), "spawn: %s" % e
    ms = int((time.time() - t0) * 1000)
    try:
        res = json.loads(out.decode("utf-8", "replace"))
        if not isinstance(res, dict) or "verdict" not in res:
            return None, ms, "malformed-result"
        return res, ms, None
    except ValueError:
        return None, ms, "no-json (exit %s)" % p.returncode


def _fmt_num(v):
    if v is None:
        return "?"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return ("%d" % f) if f == int(f) and abs(f) < 1e15 else ("%g" % f)


def _block_payload(cand, res):
    claimed = _fmt_num(res.get("claimed"))
    recomputed = _fmt_num(res.get("recomputed"))
    verdict = res.get("verdict")
    conf = res.get("confidence")
    reason_bits = [
        'calma auto-verification re-executed the work and checked the number you just '
        'reported: "%s".' % cand["claim"],
        "VERDICT: %s - claimed %s, recomputed %s%s."
        % (verdict, claimed, recomputed,
           (" (confidence %d/100)" % round(conf * 100)) if isinstance(conf, (int, float)) else ""),
    ]
    if res.get("reason"):
        reason_bits.append("engine reason: %s" % res["reason"])
    if res.get("run_dir"):
        reason_bits.append("proof and raw outputs: %s (reproduce: calma replay %s)"
                           % (res["run_dir"], res["run_dir"]))
    reason_bits.append(
        "Before finishing, follow the calma reporting contract (SKILL.md): "
        "(1) state the verdict line plainly to the user; "
        "(2) read the producing code and name the exact line or choice that made the "
        "claimed number wrong; "
        "(3) state the honest recomputed number; "
        "(4) offer `calma seal %s` for the signed proof object. "
        "Do not restate the refuted number as fact. If you believe THIS verification "
        "mis-bound the claim (wrong metric or column), say so explicitly and show why."
        % (res.get("run_dir") or "<run_dir>"))
    return {
        "decision": "block",
        "reason": "\n".join(reason_bits),
        "systemMessage": "calma caught a number: claimed %s -> recomputed %s (%s)"
                         % (claimed, recomputed, verdict),
    }


def _sniff_bounded(text):
    """Run the sniffer with a hard wall-clock ceiling. The sniffer is ~O(n^2) on degenerate
    all-metric input; the turn-end hook must never stall on a long/adversarial final message.
    Fail-open: a timeout or any error -> no claims, no near-misses (the user can still run calma)."""
    import sniff_claims as SN
    if len(text) > SNIFF_MAX_CHARS:
        text = text[-SNIFF_MAX_CHARS:]
    if not hasattr(signal, "SIGALRM"):
        try:
            return SN.sniff(text, with_near=True)
        except Exception:
            return [], []

    def _timed_out(signum, frame):
        raise TimeoutError("sniff budget exceeded")

    old = signal.signal(signal.SIGALRM, _timed_out)
    try:
        signal.setitimer(signal.ITIMER_REAL, SNIFF_BUDGET_S)
        return SN.sniff(text, with_near=True)
    except Exception:
        return [], []
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def main():
    if _killed_off_by_env():
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("stop_hook_active"):
        return 0
    cwd = data.get("cwd") or os.getcwd()
    if not os.path.isdir(cwd) or _opted_out(cwd):
        return 0
    cfg = _hook_config(cwd)
    if not cfg.get("enabled", True):
        return 0
    # VERIFY SCOPE (autonomy): off -> never auto-verify (silent, leaves no .calma litter); headline
    # (default) -> the one headline claim; all -> every checkable claim this turn (capped). Resolved
    # from --verify / env CALMA_VERIFY / .calma/config.json {"verify"} (and the legacy CALMA_HOOK=0).
    import autonomy as AU
    scope = AU.resolve_verify_scope(base=cwd)
    if scope == "off":
        return 0
    # Prefer the harness-provided final message: on current Claude Code the
    # transcript file is not yet flushed when the Stop hook runs, so parsing
    # the transcript silently misses the very message that states the claim.
    text = data.get("last_assistant_message")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        text = _final_assistant_text(data.get("transcript_path") or "")
    if not text:
        return 0
    # Bound the sniffer's input. last_assistant_message is harness-provided and uncapped, so a very
    # large final message (long reports, embedded tables/data) would add seconds to EVERY turn end.
    # A headline claim lives near the END of the message, same as in the transcript tail, so cap to
    # the same tail budget the transcript reader uses.
    if len(text) > MAX_TRANSCRIPT_TAIL:
        text = text[-MAX_TRANSCRIPT_TAIL:]
    # bounded: tighter char cap + a hard wall-clock ceiling (the sniffer is ~O(n^2) on degenerate
    # all-metric input; a turn-end must never stall). Fail-open to no-claims.
    claims, near = _sniff_bounded(text)
    if not claims:
        # CR1: nothing bound. If a result-shaped number sat next to a metric word in a VERIFIABLE
        # repo, surface a one-line "saw a number I couldn't auto-verify" (non-blocking) so a recall
        # miss is VISIBLE - the client knows to run `calma verify` instead of silently shipping it.
        # Gated on verifiable-target (no .calma litter elsewhere), on coverage being on, and de-duped
        # in state so an unchanged near-miss doesn't nag every turn.
        if near and _coverage_on(cfg) and _verifiable_target(cwd):
            st = _load_state(cwd)
            seen = st.get("near_informed", {})
            nkey = "%s=%s" % (near[0].get("metric"), near[0].get("value"))
            if nkey not in seen:
                seen[nkey] = _now_iso()
                while len(seen) > 64:  # bound the dedupe map
                    del seen[next(iter(seen))]
                st["near_informed"] = seen
                _save_state(cwd, st)
                print(json.dumps({"systemMessage": _near_miss_line(near)}))
        return 0
    # the verifiable-target gate comes FIRST and is breadcrumb-free: a mere metric mention in
    # an unrelated repo must never create a .calma dir there (breadcrumbs only after this gate)
    if not _verifiable_target(cwd):
        return 0
    state = _load_state(cwd)
    # isolation gate: never auto-execute a project's code without a verified sandbox tier.
    # The doctor result is cached in hook state with a TTL; config {"hook":
    # {"force_unverified": true}} overrides for hosts the operator explicitly trusts.
    try:
        tier, changed = _sandbox_tier(cwd, state)
    except Exception:
        tier, changed = "host-not-isolated", False
    if changed:
        _save_state(cwd, state)
    if tier not in VERIFIED_TIERS and not cfg.get("force_unverified"):
        _breadcrumb(cwd, "skip", reason="no-verified-sandbox", tier=tier,
                    claim=claims[0]["claim"], metric=claims[0]["metric"])
        return 0
    informed = state.get("informed", {})
    timeout_s = _resolve_timeout(cfg)
    # the per-turn verification budget comes from the VERIFY SCOPE (headline -> 1, all -> capped);
    # an explicit project {"hook":{"max_claims"}} only LOWERS it further (never escalates).
    max_claims = AU.max_claims_for(scope, cfg.get("max_claims"))
    if max_claims < 1:
        return 0
    # tally every check, to emit ONE non-blocking "what got checked this turn" coverage note after the
    # loop. A suppressed (already-reported) break is intentionally NOT tallied -> a re-check of a known
    # break stays fully silent (never-nag).
    tally = {"verdicts": {}, "timeout": 0, "error": 0}
    for cand in claims[:max_claims]:
        res, ms, err = _run_verify(cwd, cand, timeout_s)
        if res is None:
            tally["timeout" if err == "timeout" else "error"] += 1
            _breadcrumb(cwd, "error", reason=err, claim=cand["claim"],
                        metric=cand["metric"], ms=ms)
            continue
        verdict = res.get("verdict")
        _breadcrumb(cwd, "verified", claim=cand["claim"], metric=cand["metric"],
                    verdict=verdict, claimed=res.get("claimed"),
                    recomputed=res.get("recomputed"), cached=bool(res.get("cached")),
                    ms=ms, run_dir=res.get("run_dir"))
        if verdict not in ("REFUTED", "MIXED", "INVALIDATED", "FLAG_FOR_DECLARATION"):
            tally["verdicts"][verdict] = tally["verdicts"].get(verdict, 0) + 1
            continue
        key = _claim_key(cand)
        prior = informed.get(key)
        # Never-nag: the same break must not block twice. Tie suppression to the BREAK IDENTITY
        # (verdict + the recomputed number), NOT the engine's `cached` flag. cache.json is
        # evictable (cleanup, .gitignore, a sibling claim overwriting the shared run dir); a
        # re-execution then returns cached=False and would re-block an UNCHANGED break every single
        # turn. Fixing the code changes the recomputed value (or flips the verdict out of this
        # branch entirely), so a genuinely new/different break still blocks as intended.
        if prior and prior.get("verdict") == verdict and prior.get("recomputed") == res.get("recomputed"):
            continue
        informed[key] = {"verdict": verdict, "recomputed": res.get("recomputed"),
                         "ts": _now_iso(), "claim": cand["claim"]}
        state["informed"] = informed
        _save_state(cwd, state)
        print(json.dumps(_block_payload(cand, res)))
        return 0
    # no fresh break: surface the one-line coverage note (non-blocking) so the team can SEE the
    # guardrail ran this turn - the heartbeat that keeps it switched on. Engaged turns only; a lone
    # suppressed re-break leaves the tally empty and stays silent.
    if _coverage_on(cfg) and (tally["verdicts"] or tally["timeout"] or tally["error"]):
        print(json.dumps({"systemMessage": _coverage_line(
            tally, timeout_s, detected=len(claims), max_claims=max_claims)}))
    return 0


if __name__ == "__main__":
    try:
        rc = main() or 0
    except BaseException:  # fail open: a guardrail that crashes sessions is worse
        if os.environ.get("CALMA_HOOK_DEBUG"):  # than no guardrail
            raise
        rc = 0
    sys.exit(rc)
