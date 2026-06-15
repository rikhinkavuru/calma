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
  STAY QUIET    CONFIRMED, CAN'T-CONFIRM, INCONCLUSIVE, unbindable, timeout, error: silent
                (breadcrumbed to .calma/auto_history.jsonl, surfaced by `calma stats`).
  OPT OUT       env CALMA_HOOK=0|off|false, a `.calma/hook-off` file in the project or in
                $HOME/.calma, or `.calma/config.json` {"hook": {"enabled": false}}.
  STAY CHEAP    preflight (entrypoint + a CSV artifact, or an existing contract/.calma)
                gates the expensive step; the verify itself is cache-first and runs under
                a hard wall-clock budget (default 30s, config `timeout_s`; the child's
                --timeout is capped at 30s regardless), killed by process group on overrun.
  NO LITTER     breadcrumbs (and the .calma dir they live in) are only created AFTER the
                verifiable-target gate passes - a metric mention in an unrelated repo
                leaves nothing behind.
  SANDBOX FIRST auto-execution requires a VERIFIED sandbox tier (run_hermetic doctor,
                cached in hook state with a TTL). No verified sandbox -> skip with a
                "no-verified-sandbox" breadcrumb; config {"hook": {"force_unverified":
                true}} overrides on hosts the operator explicitly trusts.

stdin:  the Stop-hook JSON from Claude Code (session_id, transcript_path, cwd,
        stop_hook_active, ...).
stdout: nothing (silent pass), or {"decision": "block", "reason": ...} on a catch.
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
DEFAULT_TIMEOUT_S = 30
HOOK_TIMEOUT_CAP_S = 30              # hard cap on the child verify's --timeout (the hook must
                                     # stay imperceptible regardless of the CLI's 120s default)
DEFAULT_MAX_CLAIMS = 1               # verifications per stop - keep the hook imperceptible
STATE_NAME = "hook_state.json"
HISTORY_NAME = "auto_history.jsonl"
_CSV_SCAN_CAP = 400                  # dir entries examined during artifact preflight
SANDBOX_TTL_S = 24 * 3600            # how long a cached doctor (sandbox tier) result is trusted
VERIFIED_TIERS = ("seatbelt-verified", "bwrap-verified", "tier0", "container", "vm")

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


def _hook_config(cwd):
    """Merged hook config: defaults <- .calma/config.json {"hook": {...}}."""
    cfg = {"enabled": True, "timeout_s": DEFAULT_TIMEOUT_S, "max_claims": DEFAULT_MAX_CLAIMS,
           "force_unverified": False}
    try:
        with open(os.path.join(cwd, ".calma", "config.json")) as f:
            user = json.load(f).get("hook", {})
        if isinstance(user, dict):
            for k in cfg:
                if k in user:
                    cfg[k] = user[k]
    except (OSError, ValueError, AttributeError):
        pass
    return cfg


def _opted_out(cwd):
    for base in (cwd, os.path.expanduser("~")):
        if os.path.exists(os.path.join(base, ".calma", "hook-off")):
            return True
    return False


def _final_assistant_text(transcript_path):
    """The agent's final message: trailing run of assistant entries in the JSONL
    transcript (skipping sidechain/subagent lines), text blocks joined in order.
    Reads only the tail of large transcripts. Returns "" when unavailable."""
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
        rec = {"ts": _now_iso(), "event": event}
        rec.update({k: v for k, v in fields.items() if v is not None})
        with open(os.path.join(d, HISTORY_NAME), "a") as f:
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
    tier = H.doctor(cwd).get("tier", "host-not-isolated")
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
    The child's own re-execution budget is capped at HOOK_TIMEOUT_CAP_S regardless of the
    CLI's larger default - a stop hook must never hold a session for minutes."""
    argv = [sys.executable or "python3", os.path.join(_HERE, "calma.py"), "verify", cwd,
            cand["claim"], "--metric", cand["metric"], "--json", "--run-id", "hook",
            "--timeout", str(min(int(timeout_s), HOOK_TIMEOUT_CAP_S))]
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
    # Prefer the harness-provided final message: on current Claude Code the
    # transcript file is not yet flushed when the Stop hook runs, so parsing
    # the transcript silently misses the very message that states the claim.
    text = data.get("last_assistant_message")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        text = _final_assistant_text(data.get("transcript_path") or "")
    if not text:
        return 0
    import sniff_claims as SN
    claims = SN.sniff(text)
    if not claims:
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
    try:
        timeout_s = max(5, min(int(cfg.get("timeout_s", DEFAULT_TIMEOUT_S)), 300))
    except (TypeError, ValueError):
        timeout_s = DEFAULT_TIMEOUT_S
    try:
        max_claims = max(1, min(int(cfg.get("max_claims", DEFAULT_MAX_CLAIMS)), 3))
    except (TypeError, ValueError):
        max_claims = DEFAULT_MAX_CLAIMS
    for cand in claims[:max_claims]:
        res, ms, err = _run_verify(cwd, cand, timeout_s)
        if res is None:
            _breadcrumb(cwd, "error", reason=err, claim=cand["claim"],
                        metric=cand["metric"], ms=ms)
            continue
        verdict = res.get("verdict")
        _breadcrumb(cwd, "verified", claim=cand["claim"], metric=cand["metric"],
                    verdict=verdict, claimed=res.get("claimed"),
                    recomputed=res.get("recomputed"), cached=bool(res.get("cached")),
                    ms=ms, run_dir=res.get("run_dir"))
        if verdict not in ("REFUTED", "MIXED", "INVALIDATED"):
            continue
        key = _claim_key(cand)
        if res.get("cached") and key in informed:
            continue  # already reported this exact break; nothing changed since
        informed[key] = {"verdict": verdict, "ts": _now_iso(), "claim": cand["claim"]}
        state["informed"] = informed
        _save_state(cwd, state)
        print(json.dumps(_block_payload(cand, res)))
        return 0
    return 0


if __name__ == "__main__":
    try:
        rc = main() or 0
    except BaseException:  # fail open: a guardrail that crashes sessions is worse
        if os.environ.get("CALMA_HOOK_DEBUG"):  # than no guardrail
            raise
        rc = 0
    sys.exit(rc)
