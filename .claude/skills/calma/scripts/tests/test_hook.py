"""Suite for the zero-touch Stop hook (hook_stop.py).

Every operating rule in the hook's docstring is enforced here:
  - the BTC fixture catch fires end-to-end (REFUTED -> block payload with the reporting
    contract), and the SAME claim never blocks twice while code+data are unchanged;
  - CONFIRMED and unbindable claims stay silent;
  - every kill-switch works (env, hook-off file, config enabled:false, stop_hook_active);
  - fail-open: malformed stdin, missing/corrupt transcripts, unverifiable targets and
    timeouts all exit 0 with no output;
  - breadcrumbs land in .calma/auto_history.jsonl for fired AND skipped events;
  - the no-claim fast path stays imperceptible (< 2s including interpreter startup).

The hook is exercised the way Claude Code runs it: a real subprocess fed Stop-hook JSON on
stdin. Pure stdlib. Run: python3 test_hook.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, SCR)
import hook_stop as HK  # noqa: E402
import recompute as RC  # noqa: E402

HOOK = os.path.join(SCR, "hook_stop.py")
BTC_SRC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


_tcount = [0]


def write_transcript(dirpath, final_text, extra_lines=None):
    """A minimal Claude Code transcript: user turn, tool noise, sidechain noise, then the
    final assistant message (split across two assistant entries, as real turns are)."""
    _tcount[0] += 1
    p = os.path.join(dirpath, "transcript%d.jsonl" % _tcount[0])
    lines = [
        {"type": "user", "message": {"role": "user", "content": "do the thing"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "fake tool accuracy 0.32 output"}]}},
        {"type": "assistant", "isSidechain": True, "message": {"content": [
            {"type": "text", "text": "sidechain says accuracy 0.11 - must be ignored"}]}},
        {"type": "user", "message": {"role": "user", "content": "and report"}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Here is the summary."}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": final_text}]}},
    ]
    with open(p, "w") as f:
        for ln in (extra_lines or []) + lines:
            f.write(json.dumps(ln) + "\n")
    return p


def run_hook(cwd, transcript, stop_active=False, env_extra=None, stdin_raw=None):
    payload = stdin_raw if stdin_raw is not None else json.dumps(
        {"session_id": "s1", "transcript_path": transcript, "cwd": cwd,
         "hook_event_name": "Stop", "stop_hook_active": stop_active})
    env = dict(os.environ)
    env.pop("CALMA_HOOK", None)
    env.update(env_extra or {})
    t0 = time.time()
    p = subprocess.run([sys.executable, HOOK], input=payload.encode(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                       timeout=180)
    return p.stdout.decode().strip(), p.returncode, time.time() - t0


def history(cwd):
    try:
        with open(os.path.join(cwd, ".calma", HK.HISTORY_NAME)) as f:
            return [json.loads(l) for l in f if l.strip()]
    except OSError:
        return []


tmp_root = tempfile.mkdtemp(prefix="calma_hook_test_")

# --- a fresh copy of the BTC fixture so hook state/runs never pollute the repo ---
btc = os.path.join(tmp_root, "btc")
shutil.copytree(BTC_SRC, btc, ignore=shutil.ignore_patterns(".calma"))
tdir = os.path.join(tmp_root, "transcripts")
os.makedirs(tdir)

# ---------------------------------------------------------------------------
# 1. the flagship catch: inflated backtest claim -> block with the contract
# ---------------------------------------------------------------------------
tp = write_transcript(tdir, "Done! The backtest returned +14,698% on the held-out period.")
out, rc, _ = run_hook(btc, tp)
truth(rc == 0, "catch: exit code is always 0")
blocked = {}
try:
    blocked = json.loads(out)
except ValueError:
    pass
truth(blocked.get("decision") == "block", "catch: decision is block")
truth("REFUTED" in blocked.get("reason", ""), "catch: reason carries the verdict")
truth("recomputed" in blocked.get("reason", "").lower(), "catch: reason carries recompute")
truth("reporting contract" in blocked.get("reason", ""), "catch: reason cites the contract")
truth("calma caught a number" in blocked.get("systemMessage", ""),
      "catch: user-facing systemMessage present")
ev = history(btc)
truth(any(e["event"] == "verified" and e.get("verdict") == "REFUTED" for e in ev),
      "catch: breadcrumb records the verified REFUTED")
truth(os.path.exists(os.path.join(btc, ".calma", HK.STATE_NAME)),
      "catch: informed state persisted")

# --- 2. NEVER NAG: same claim, unchanged code+data -> cache hit, silence ---
out2, rc2, _ = run_hook(btc, tp)
truth(rc2 == 0 and out2 == "", "renag: second stop on the same break is silent")
ev = history(btc)
truth(any(e["event"] == "verified" and e.get("cached") for e in ev),
      "renag: the silent re-check came from the cache")

# --- 3. stop_hook_active short-circuits (no double-block loop, ever) ---
out3, rc3, dt3 = run_hook(btc, tp, stop_active=True)
truth(rc3 == 0 and out3 == "", "loop guard: stop_hook_active -> instant silence")
truth(dt3 < 2.0, "loop guard: short-circuits before any work (%.2fs)" % dt3)

# ---------------------------------------------------------------------------
# 4. kill-switches
# ---------------------------------------------------------------------------
out, rc, _ = run_hook(btc, tp, env_extra={"CALMA_HOOK": "0"})
truth(rc == 0 and out == "", "kill-switch: CALMA_HOOK=0")
out, rc, _ = run_hook(btc, tp, env_extra={"CALMA_HOOK": "off"})
truth(rc == 0 and out == "", "kill-switch: CALMA_HOOK=off")
off = os.path.join(btc, ".calma", "hook-off")
open(off, "w").close()
out, rc, _ = run_hook(btc, tp)
truth(rc == 0 and out == "", "kill-switch: .calma/hook-off file")
os.remove(off)
cfgp = os.path.join(btc, ".calma", "config.json")
with open(cfgp, "w") as f:
    json.dump({"hook": {"enabled": False}}, f)
out, rc, _ = run_hook(btc, tp)
truth(rc == 0 and out == "", "kill-switch: config enabled:false")
os.remove(cfgp)

# ---------------------------------------------------------------------------
# 5. silence on everything that is not a definitive break
# ---------------------------------------------------------------------------
# no claim in the final message -> fast silent path
tp_none = write_transcript(tdir, "Refactored the parser and tidied the imports.")
out, rc, dt = run_hook(btc, tp_none)
truth(rc == 0 and out == "", "silent: no claim in message")
truth(dt < 2.0, "silent: no-claim path is imperceptible (%.2fs)" % dt)

# claim in an unverifiable directory -> silent, and NO .calma dir is littered there
# (a mere metric mention in an unrelated repo must never create calma state)
empty = os.path.join(tmp_root, "empty")
os.makedirs(empty)
tp_claim = write_transcript(tdir, "Final accuracy is 0.91 on the test set.")
out, rc, _ = run_hook(empty, tp_claim)
truth(rc == 0 and out == "", "silent: unverifiable target")
truth(not os.path.exists(os.path.join(empty, ".calma")),
      "no-litter: unverifiable target gets NO .calma dir (no breadcrumbs before the gate)")

# isolation gate: a verifiable target whose cached doctor says "no verified sandbox" is
# skipped with a breadcrumb (the hook never auto-executes code without a verified tier). The
# tier is a HOST property, cached at CALMA_STATE_DIR (a temp dir here) so the fixture controls it
# without touching the real ~/.calma and the costly probe doesn't re-run per project.
gated = os.path.join(tmp_root, "gated")
shutil.copytree(BTC_SRC, gated, ignore=shutil.ignore_patterns(".calma"))
host_dir = os.path.join(tmp_root, "host_state")
os.makedirs(host_dir)
with open(os.path.join(host_dir, HK.STATE_NAME), "w") as f:
    json.dump({"sandbox_tier": {"tier": "host-not-isolated", "ts": time.time()}}, f)
host_env = {"CALMA_STATE_DIR": host_dir}
tp_gate = write_transcript(tdir, "Done! The backtest returned +14,698% on the held-out period.")
out, rc, _ = run_hook(gated, tp_gate, env_extra=host_env)
truth(rc == 0 and out == "", "isolation gate: no verified sandbox -> silent")
truth(any(e["event"] == "skip" and e.get("reason") == "no-verified-sandbox"
          for e in history(gated)), "isolation gate: skip breadcrumbed as no-verified-sandbox")
# SECURITY (M5): a PROJECT-LOCAL .calma/config.json must NOT bypass the sandbox gate - an untrusted
# repo cannot opt ITSELF into unsandboxed auto-execution merely by being opened.
os.makedirs(os.path.join(gated, ".calma"), exist_ok=True)
with open(os.path.join(gated, ".calma", "config.json"), "w") as f:
    json.dump({"hook": {"force_unverified": True}}, f)
out, rc, _ = run_hook(gated, tp_gate, env_extra=host_env)
truth(rc == 0 and out == "",
      "isolation gate: project-local force_unverified is IGNORED (no untrusted unsandboxed auto-exec)")
# but a TRUSTED override (an operator-set env var) DOES lift the gate on a host they explicitly trust
out, rc, _ = run_hook(gated, tp_gate, env_extra=dict(host_env, CALMA_HOOK_FORCE_UNVERIFIED="1"))
forced = {}
try:
    forced = json.loads(out)
except ValueError:
    pass
truth(forced.get("decision") == "block",
      "isolation gate: a TRUSTED force_unverified (env) verifies (and catches) anyway")
os.remove(os.path.join(gated, ".calma", "config.json"))
# a stale (past-TTL) host-cached tier is re-probed: the real doctor result governs
stale_host = os.path.join(tmp_root, "host_stale")
os.makedirs(stale_host)
with open(os.path.join(stale_host, HK.STATE_NAME), "w") as f:
    json.dump({"sandbox_tier": {"tier": "host-not-isolated",
                                "ts": time.time() - HK.SANDBOX_TTL_S - 10}}, f)
_prev_state_dir = os.environ.get("CALMA_STATE_DIR")
os.environ["CALMA_STATE_DIR"] = stale_host
try:
    st = HK._load_state(gated)
    tier, changed = HK._sandbox_tier(gated, st)
finally:
    if _prev_state_dir is None:
        os.environ.pop("CALMA_STATE_DIR", None)
    else:
        os.environ["CALMA_STATE_DIR"] = _prev_state_dir
truth(changed and tier and tier != "", "isolation gate: stale TTL re-probes the real tier")

# CONFIRMED -> silent (honest claim equal to the true recomputed value)
honest = os.path.join(tmp_root, "honest")
os.makedirs(os.path.join(honest, "runs", "oos"))
shutil.copy(os.path.join(btc, "runs", "oos", "returns.csv"),
            os.path.join(honest, "runs", "oos", "returns.csv"))
rec = RC.recompute_contract(os.path.join(btc, "verify.yaml"), base=btc, k=1)
true_val = rec["metrics"][0]["value"]
with open(os.path.join(honest, "noop.py"), "w") as f:
    f.write("pass\n")
with open(os.path.join(honest, "verify.yaml"), "w") as f:
    json.dump({"run": {"entrypoint": "noop.py", "network": "off"},
               "env": {"ecosystem": "python-stdlib", "trust": "own-code"},
               "artifacts": [{"path": "runs/oos/returns.csv", "re_emit": False,
                              "columns": {"strat_return": {"tag": "return",
                                                           "na_policy": "error"}}}],
               "metrics": [{"metric_id": "total_return",
                            "artifact": "runs/oos/returns.csv",
                            "binding": {"return": "strat_return"},
                            "claimed_value": true_val, "headline": True,
                            "binding_status": "independently-bound",
                            "claim_confirmed": True}],
               "baselines": []}, f)
tp_honest = write_transcript(tdir, "The strategy returned %+.1f%% on the held-out window."
                             % (true_val * 100))
out, rc, _ = run_hook(honest, tp_honest)
truth(rc == 0 and out == "", "silent: honest claim (not REFUTED) never blocks")
truth(any(e["event"] == "verified" and e.get("verdict") not in ("REFUTED", "MIXED")
          for e in history(honest)), "silent: honest verification breadcrumbed")

# ---------------------------------------------------------------------------
# 6. fail-open hardening
# ---------------------------------------------------------------------------
out, rc, _ = run_hook(btc, tp, stdin_raw="this is not json {{{")
truth(rc == 0 and out == "", "fail-open: malformed stdin")
out, rc, _ = run_hook(btc, os.path.join(tdir, "missing.jsonl"))
truth(rc == 0 and out == "", "fail-open: missing transcript")
corrupt = os.path.join(tdir, "corrupt.jsonl")
with open(corrupt, "w") as f:
    f.write("not json\n{\"type\": \"assistant\"\n\x00\x01garbage\n")
out, rc, _ = run_hook(btc, corrupt)
truth(rc == 0 and out == "", "fail-open: corrupt transcript")
out, rc, _ = run_hook(os.path.join(tmp_root, "nonexistent-dir"), tp)
truth(rc == 0 and out == "", "fail-open: cwd does not exist")
out, rc, _ = run_hook(btc, tp, stdin_raw="")
truth(rc == 0 and out == "", "fail-open: empty stdin")

# timeout: a verifiable target whose entrypoint hangs -> killed silently, breadcrumbed
slow = os.path.join(tmp_root, "slow")
os.makedirs(slow)
with open(os.path.join(slow, "main.py"), "w") as f:
    f.write("import time\ntime.sleep(120)\n")
with open(os.path.join(slow, "results.csv"), "w") as f:
    f.write("accuracy\n0.5\n")
os.makedirs(os.path.join(slow, ".calma"), exist_ok=True)
with open(os.path.join(slow, ".calma", "config.json"), "w") as f:
    json.dump({"hook": {"timeout_s": 5}}, f)
t0 = time.time()
out, rc, _ = run_hook(slow, tp_claim)
dt = time.time() - t0
truth(rc == 0 and out == "", "fail-open: hung entrypoint stays silent")
truth(dt < 30, "fail-open: hung entrypoint killed by budget (%.1fs)" % dt)
truth(any(e["event"] == "error" and e.get("reason") == "timeout" for e in history(slow)),
      "fail-open: timeout breadcrumbed")

# ---------------------------------------------------------------------------
# 7. transcript extraction unit checks (the parsing the subprocess runs rely on)
# ---------------------------------------------------------------------------
text = HK._final_assistant_text(tp)
truth("backtest returned +14,698%" in text, "extract: final claim text found")
truth("Here is the summary." in text, "extract: trailing assistant run joined")
truth("sidechain says" not in text, "extract: sidechain ignored")
truth("fake tool accuracy" not in text, "extract: tool results ignored")
truth(HK._final_assistant_text("/nope/missing.jsonl") == "", "extract: missing file -> ''")

# large transcript: only the tail is read, the final message still lands
big = os.path.join(tdir, "big.jsonl")
with open(big, "w") as f:
    filler = json.dumps({"type": "user", "message": {"content": "x" * 2000}})
    for _ in range(300):
        f.write(filler + "\n")
    f.write(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Final AUC is 0.93."}]}}) + "\n")
truth("Final AUC is 0.93." in HK._final_assistant_text(big),
      "extract: tail-read finds the final message in a large transcript")

# preflight unit checks
truth(HK._verifiable_target(btc), "preflight: fixture with contract is verifiable")
truth(not HK._verifiable_target(empty), "preflight: empty dir is not")
webish = os.path.join(tmp_root, "webish")
os.makedirs(webish)
with open(os.path.join(webish, "main.py"), "w") as f:
    f.write("print('hi')\n")
truth(not HK._verifiable_target(webish),
      "preflight: entrypoint without artifacts never auto-executes")

# ---------------------------------------------------------------------------
# 8. transcript-flush race: on current Claude Code the transcript file is NOT yet
#    flushed when the Stop hook runs, so the final message exists only in the
#    payload's last_assistant_message. The hook must prefer that field — this is
#    the regression that silently killed every real-session catch (2026-06-12).
# ---------------------------------------------------------------------------
btc_race = os.path.join(tmp_root, "btc_race")
shutil.copytree(BTC_SRC, btc_race, ignore=shutil.ignore_patterns(".calma"))
stale = os.path.join(tdir, "stale.jsonl")
with open(stale, "w") as f:  # transcript ends at the USER turn - final reply unflushed
    f.write(json.dumps({"type": "user", "message": {
        "role": "user", "content": "run it and report"}}) + "\n")
race_payload = json.dumps({
    "session_id": "s-race", "transcript_path": stale, "cwd": btc_race,
    "hook_event_name": "Stop", "stop_hook_active": False,
    "last_assistant_message":
        "The backtest shows a total return of +14,698% on the held-out window."})
out, rc, _ = run_hook(btc_race, stale, stdin_raw=race_payload)
blocked = {}
try:
    blocked = json.loads(out)
except ValueError:
    pass
truth(rc == 0, "race: exit code is always 0")
truth(blocked.get("decision") == "block",
      "race: claim in last_assistant_message blocks despite unflushed transcript")
truth("REFUTED" in blocked.get("reason", ""), "race: verdict carried in reason")

# and the field must win over a stale transcript that contains an OLD message
tp_old = write_transcript(tdir, "Working on it - no numbers yet.")
race2 = json.dumps({
    "session_id": "s-race2", "transcript_path": tp_old, "cwd": btc_race,
    "hook_event_name": "Stop", "stop_hook_active": False,
    "last_assistant_message": "All done, nothing numeric to report."})
out, rc, _ = run_hook(btc_race, tp_old, stdin_raw=race2)
truth(rc == 0 and out == "",
      "race: harness-provided text wins over transcript (no false fire)")

# widened target gate: data artifacts beyond .csv count; config jsons do NOT (else the hook
# would engage on every web repo with a package.json)
for ext in ("data.csv", "preds.parquet", "out.jsonl", "scores.npy", "results.json", "db.sqlite"):
    truth(HK._is_data_artifact(ext), "data artifact recognized: %s" % ext)
for cfg in ("package.json", "tsconfig.json", "next.config.json", "vercel.json"):
    truth(not HK._is_data_artifact(cfg), "config json is NOT a data artifact: %s" % cfg)

shutil.rmtree(tmp_root, ignore_errors=True)
print("hook: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
