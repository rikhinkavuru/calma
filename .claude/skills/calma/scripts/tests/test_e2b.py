"""Tests for the e2b remote-microVM isolation tier (run_hermetic.py): the (config, doctor, exec)
interface, the explicit network-DENY assertion (fail-closed), missing-config -> exit 3, the no-Docker
smoke path (a Docker-less host runs `--trust third-party --isolation e2b` to a VERDICT instead of exit
3), recompute-over-retrieved-raw-outputs == stamp e2b-firecracker, secret hygiene (no endpoint/token in
the run dir), and the anti-drift lockstep across all five verified-tier sites.

The live E2B SDK is never imported here: a FAKE microVM session is injected via
run_hermetic.set_e2b_session_factory so every check below runs offline with no credentials. A real
spawn/exec/recompute pass is gated behind CALMA_E2B_LIVE (+ creds) so credential-less CI skips it.
Pure stdlib. Run: python3 test_e2b.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import run_hermetic as H  # noqa: E402
import calma as C         # noqa: E402
import recompute as RC    # noqa: E402
import verdict as V       # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# A FAKE microVM session standing in for the E2B SDK. `.probe()` returns a LEAKS= line (configurable
# egress leaks); `.exec()` faithfully mimics upload -> run-in-a-separate-guest-FS -> download: the
# workload runs in an ISOLATED scratch dir (never `base`), and only its runs/ subtree is RETRIEVED into
# the host out_dir - exactly the shape the real adapter implements, so recompute (host-side) sees only
# raw outputs the "VM" produced. The VM never participates in recompute.
class FakeSession:
    def __init__(self, cfg, timeout, network_disabled=True, leaks=()):
        self.network_disabled = network_disabled
        self._leaks = list(leaks)
        self.exec_count = 0
        self.closed = False

    def probe(self, src):
        return "LEAKS=" + ",".join(self._leaks) + "\n"

    def exec(self, inner_argv, env, base, out_dir, timeout):
        self.exec_count += 1
        guest = tempfile.mkdtemp(prefix="calma_e2b_guest_")
        try:
            for root, _d, files in os.walk(base):   # upload (minus runs/ + .calma)
                if ".calma" in root.split(os.sep) or os.path.basename(root) == "runs":
                    continue
                for fn in files:
                    lp = os.path.join(root, fn)
                    dp = os.path.join(guest, os.path.relpath(lp, base))
                    os.makedirs(os.path.dirname(dp), exist_ok=True)
                    shutil.copy(lp, dp)
            rel = inner_argv[-1].replace("/work/", "")
            runner = sys.executable if str(inner_argv[0]).startswith("python") else "sh"
            p = subprocess.run([runner, os.path.join(guest, rel)], cwd=guest,
                               capture_output=True, text=True,
                               env=dict(os.environ, **(env or {})))
            g_runs = os.path.join(guest, "runs")
            if os.path.isdir(g_runs):                # download: guest runs/ -> host out_dir
                for root, _d, files in os.walk(g_runs):
                    for fn in files:
                        lp = os.path.join(root, fn)
                        dp = os.path.join(out_dir, os.path.relpath(lp, g_runs))
                        os.makedirs(os.path.dirname(dp), exist_ok=True)
                        shutil.copy(lp, dp)
            return p.returncode, p.stdout, p.stderr, False
        finally:
            shutil.rmtree(guest, ignore_errors=True)

    def close(self):
        self.closed = True


def fake_factory(network_disabled=True, leaks=(), sink=None):
    def make(cfg, timeout):
        s = FakeSession(cfg, timeout, network_disabled=network_disabled, leaks=leaks)
        if sink is not None:
            sink.append(s)
        return s
    return make


_E2B_ENV = ("CALMA_E2B_ENDPOINT", "CALMA_E2B_API_KEY", "CALMA_E2B_TOKEN",
            "CALMA_E2B_TEMPLATE", "CALMA_E2B_SELF_HOSTED", "CALMA_E2B_CONFIG")


def _clear_env():
    for k in _E2B_ENV:
        os.environ.pop(k, None)


def _set_creds(endpoint="https://api.example.invalid", token="sk-FAKE", template="tmpl-x",
               self_hosted=False):
    _clear_env()
    os.environ["CALMA_E2B_ENDPOINT"] = endpoint
    os.environ["CALMA_E2B_API_KEY"] = token
    os.environ["CALMA_E2B_TEMPLATE"] = template
    if self_hosted:
        os.environ["CALMA_E2B_SELF_HOSTED"] = "1"


def _engagement(dirpath, trust="own-code", entry_src="print('ok')\n", contract_extra=None):
    """Minimal engagement dir: a python entrypoint + a verify.yaml. contract_extra merges in
    artifacts/metrics for the recompute test."""
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "main.py"), "w") as fh:
        fh.write(entry_src)
    contract = {"run": {"entrypoint": "main.py", "network": "off"},
                "env": {"ecosystem": "python-stdlib", "trust": trust},
                "artifacts": [], "metrics": [], "baselines": []}
    if contract_extra:
        contract.update(contract_extra)
    with open(os.path.join(dirpath, "verify.yaml"), "w") as fh:
        json.dump(contract, fh)
    return os.path.join(dirpath, "verify.yaml")


# ---------------------------------------------------------------------------
# (A) CONFIG SURFACE + MISSING-CONFIG -> EXIT 3 (no session is ever created)
# ---------------------------------------------------------------------------
_clear_env()
cfg, missing = H._e2b_config(env={})
truth(missing == ["endpoint", "API token", "template id"],
      "config: empty env -> all three required keys reported missing")
cfg, missing = H._e2b_config(env={"CALMA_E2B_ENDPOINT": "https://x", "CALMA_E2B_API_KEY": "t",
                                  "CALMA_E2B_TEMPLATE": "tpl"})
truth(missing == [] and H._e2b_stamp(cfg) == "e2b-firecracker",
      "config: full env -> nothing missing, cloud stamp e2b-firecracker")
cfg, missing = H._e2b_config(env={"CALMA_E2B_ENDPOINT": "https://x", "CALMA_E2B_TOKEN": "t",
                                  "CALMA_E2B_TEMPLATE": "tpl", "CALMA_E2B_SELF_HOSTED": "yes"})
truth(H._e2b_stamp(cfg) == "e2b-firecracker (self-hosted)",
      "config: SELF_HOSTED truthy + token-alias -> self-hosted stamp")
# JSON config file is honored; env still wins over file
_cfgd = tempfile.mkdtemp()
_cfgp = os.path.join(_cfgd, "e2b.json")
json.dump({"endpoint": "https://file", "token": "ft", "template": "ftpl", "self_hosted": True},
          open(_cfgp, "w"))
cfg, missing = H._e2b_config(env={"CALMA_E2B_CONFIG": _cfgp})
truth(missing == [] and cfg["self_hosted"] and H._e2b_stamp(cfg) == "e2b-firecracker (self-hosted)",
      "config: JSON file supplies all keys (self-hosted)")
cfg, missing = H._e2b_config(env={"CALMA_E2B_CONFIG": _cfgp, "CALMA_E2B_ENDPOINT": "https://env"})
truth(cfg["endpoint"] == "https://env", "config: env endpoint overrides the file")
shutil.rmtree(_cfgd, ignore_errors=True)

# missing-config through the real run() path -> refuse exit 3, message names exactly what's missing,
# and NEVER falls back to a host run. No session factory installed (and none needed - config gates first).
_clear_env()
_d = tempfile.mkdtemp()
_vy = _engagement(_d, trust="third-party")
r = H.run(_vy, base=_d, isolation="e2b", timeout=60)
truth(r["exit_code"] == 3 and r["phase"] == "refused", "missing config -> refused exit 3")
truth("endpoint" in r["reason"] and "API token" in r["reason"] and "template id" in r["reason"],
      "missing-config refusal names endpoint + API token + template id")
truth("CALMA_E2B_ENDPOINT" in r["reason"], "refusal points at the exact env var to set")
shutil.rmtree(_d, ignore_errors=True)


# ---------------------------------------------------------------------------
# (B) NETWORK-DENY ASSERTION (explicit, fail-closed) via e2b_doctor
# ---------------------------------------------------------------------------
_set_creds()
try:
    # clean microVM: probe shows no leaks -> verified e2b-firecracker, egress + net-off asserted
    H.set_e2b_session_factory(fake_factory(network_disabled=True, leaks=()))
    doc = H.e2b_doctor(timeout=30)
    truth(doc["tier"] == "e2b-firecracker", "doctor: clean microVM -> tier e2b-firecracker")
    truth(doc["egress_blocked"] is True and doc["network_disabled"] is True,
          "doctor: egress + network-deny asserted on the verified tier")
    truth(doc["probe_ran"] is True, "doctor: the in-VM probe actually ran")

    # egress LEAKS -> fail closed: host-not-isolated, never an e2b stamp
    H.set_e2b_session_factory(fake_factory(network_disabled=True, leaks=["egress:ip"]))
    doc = H.e2b_doctor(timeout=30)
    truth(doc["tier"] == "host-not-isolated" and doc["egress_blocked"] is False,
          "doctor: egress leak -> host-not-isolated (network-deny assertion enforced)")

    # SDK cannot guarantee net-off (network_disabled False) -> fail closed BEFORE running the probe
    H.set_e2b_session_factory(fake_factory(network_disabled=False, leaks=()))
    doc = H.e2b_doctor(timeout=30)
    truth(doc["tier"] == "host-not-isolated" and doc["probe_ran"] is False,
          "doctor: un-guaranteeable network-deny -> fail closed (no probe, host-not-isolated)")

    # the backend refuses (exit 3) whenever the doctor did not verify - never runs with the net up
    _d = tempfile.mkdtemp()
    _vy = _engagement(_d, trust="third-party")
    H.set_e2b_session_factory(fake_factory(network_disabled=True, leaks=["egress:dns"]))
    r = H.run(_vy, base=_d, isolation="e2b", timeout=60)
    truth(r["exit_code"] == 3 and r["phase"] == "refused" and r["isolation_tier"] == "host-not-isolated",
          "backend: egress-leaking microVM -> refused exit 3 (fail closed)")
    shutil.rmtree(_d, ignore_errors=True)
finally:
    H.set_e2b_session_factory(None)
    _clear_env()


# ---------------------------------------------------------------------------
# (C) INTERFACE COMPLETENESS: the e2b tier implements the same (config, doctor, exec) protocol
# ---------------------------------------------------------------------------
truth(all(hasattr(H, fn) for fn in ("_e2b_config", "e2b_doctor", "_run_e2b_backend",
                                    "_make_e2b_session", "set_e2b_session_factory")),
      "interface: config + doctor + backend + session-seam are all present")
truth(all(hasattr(H._RealE2BSession, m) for m in ("probe", "exec", "close")),
      "interface: the real session adapter exposes probe/exec/close (spawn/exec/teardown)")
# a doctor dict carries the same machine-readable keys the other tiers' doctors do
_set_creds()
H.set_e2b_session_factory(fake_factory())
_doc = H.e2b_doctor(timeout=30)
truth(all(k in _doc for k in ("backend", "tier", "egress_blocked", "secret_read_blocked",
                              "network_disabled", "probe_ran", "note")),
      "interface: doctor dict has the standard tier-self-test keys")
H.set_e2b_session_factory(None)
_clear_env()


# ---------------------------------------------------------------------------
# (D) NO-DOCKER SMOKE: with Docker ABSENT, `--trust third-party --isolation e2b` reaches a VERDICT
# instead of the exit-3 refusal the container tier would give.
# ---------------------------------------------------------------------------
_orig_bin, _orig_avail = H._docker_bin, H._docker_available
try:
    H._docker_bin = lambda: None
    H._docker_available = lambda image=None: (False, "docker CLI not found on PATH")
    # control: untrusted + auto/docker on a Docker-less host -> refused exit 3 (the gap e2b fills)
    _d = tempfile.mkdtemp()
    _vy = _engagement(_d, trust="third-party")
    r_ctl = H.run(_vy, base=_d, isolation="docker", timeout=60)
    truth(r_ctl["exit_code"] == 3 and r_ctl["phase"] == "refused",
          "no-docker control: untrusted + --isolation docker -> refused exit 3")
    # e2b rescues it: same host, same untrusted engagement, now reaches a run verdict
    _set_creds()
    H.set_e2b_session_factory(fake_factory())
    r_e2b = H.run(_vy, base=_d, isolation="e2b", timeout=60)
    truth(r_e2b["phase"] == "run" and r_e2b["exit_code"] == 0,
          "no-docker smoke: untrusted + --isolation e2b reaches a VERDICT (exit 0, not 3)")
    truth(r_e2b["isolation_tier"] == "e2b-firecracker", "no-docker smoke: stamp == e2b-firecracker")
    truth(r_e2b.get("run_network") == "off" and r_e2b.get("hermeticity") == "microvm-readonly",
          "no-docker smoke: network stamped off + microvm-readonly hermeticity")
    shutil.rmtree(_d, ignore_errors=True)
finally:
    H._docker_bin, H._docker_available = _orig_bin, _orig_avail
    H.set_e2b_session_factory(None)
    _clear_env()


# ---------------------------------------------------------------------------
# (E) RECOMPUTE OVER RETRIEVED RAW OUTPUTS == stamp e2b-firecracker, end-to-end through `calma verify`.
# The microVM (fake) produces returns.csv; it is retrieved to the host; recompute runs host-side and
# CONFIRMS the honest claim. The determinism path is untouched - the VM never recomputes.
# ---------------------------------------------------------------------------
_GEN = ("import os\n"
        "os.makedirs('runs/oos', exist_ok=True)\n"
        "open('runs/oos/returns.csv','w').write('strat_return\\n0.10\\n-0.05\\n0.02\\n0.03\\n')\n"
        "print('generated returns.csv')\n")
_art = {"artifacts": [{"path": "runs/oos/returns.csv", "re_emit": True,
                       "columns": {"strat_return": {"tag": "return", "na_policy": "error"}}}],
        "metrics": [{"metric_id": "total_return", "artifact": "runs/oos/returns.csv",
                     "binding": {"return": "strat_return"}, "headline": True,
                     "binding_status": "independently-bound"}]}
_d = tempfile.mkdtemp()
_vy = _engagement(_d, trust="own-code", entry_src=_GEN, contract_extra=_art)
# materialize once to derive the HONEST claim, then recompute its true value
subprocess.run([sys.executable, os.path.join(_d, "main.py")], cwd=_d, capture_output=True)
_true = RC.recompute_contract(_vy, base=_d, k=1)["metrics"][0]["value"]
_contract = json.load(open(_vy))
_contract["metrics"][0]["claimed_value"] = _true
_contract["metrics"][0]["claim_confirmed"] = True
json.dump(_contract, open(_vy, "w"))
shutil.rmtree(os.path.join(_d, "runs"))   # wipe: the microVM must REGENERATE + we must RETRIEVE it

_ENDPOINT_SENTINEL = "https://DO-NOT-LEAK-endpoint.invalid/secret-path"
_TOKEN_SENTINEL = "sk-DO-NOT-LEAK-token-7f3a"
_set_creds(endpoint=_ENDPOINT_SENTINEL, token=_TOKEN_SENTINEL, template="tmpl-prod")
_sink = []
H.set_e2b_session_factory(fake_factory(sink=_sink))
try:
    res = C.verify(_d, run_id="e2b", force=True, trust="third-party", isolation="e2b")
    truth(res["repo_verdict"] in (V.CONFIRMED, V.CAVEATS),
          "e2e: honest claim over microVM-produced output -> not REFUTED (got %s)" % res["repo_verdict"])
    truth(os.path.exists(os.path.join(_d, "runs", "oos", "returns.csv")),
          "e2e: raw output was retrieved from the microVM to the host runs/ subtree")
    truth(any(s.exec_count >= 1 for s in _sink), "e2e: the workload actually executed in the microVM")
    rd = res["run_dir"]
    led = json.load(open(os.path.join(rd, "ledger.json")))
    truth(led.get("scope", {}).get("isolation_tier") == "e2b-firecracker",
          "e2e: replay bundle (ledger) stamps isolation_tier == e2b-firecracker")
    # SECRET HYGIENE: neither the endpoint URL nor the token may appear anywhere in the run dir
    leaked = []
    for root, _dd, files in os.walk(rd):
        for fn in files:
            try:
                blob = open(os.path.join(root, fn), "r", errors="ignore").read()
            except OSError:
                continue
            if _ENDPOINT_SENTINEL in blob or _TOKEN_SENTINEL in blob:
                leaked.append(fn)
    truth(not leaked, "e2e: no endpoint/token secret in the replay bundle (leaked in: %s)" % leaked)
    # the stamp itself never carries the endpoint
    truth("DO-NOT-LEAK" not in json.dumps(led.get("scope", {})),
          "e2e: the isolation_tier stamp does not leak the endpoint URL")
finally:
    H.set_e2b_session_factory(None)
    _clear_env()
    shutil.rmtree(_d, ignore_errors=True)


# ---------------------------------------------------------------------------
# (F) ANTI-DRIFT: the e2b stamps must be VERIFIED at EVERY consumer of the tier set (parity with the
# bwrap-verified lockstep guard in test_hermetic.py). Miss one site and untrusted code in a verified
# microVM would still be (wrongly) blocked as "no isolation".
# ---------------------------------------------------------------------------
import compare as _CMP   # noqa: E402
import hook_stop as _HOOK  # noqa: E402
for _stamp in ("e2b-firecracker", "e2b-firecracker (self-hosted)"):
    truth(_stamp in H._VERIFIED_TIERS, "run_hermetic: %s is a verified tier" % _stamp)
    truth(_stamp in C.VERIFIED_TIERS, "calma: %s in VERIFIED_TIERS" % _stamp)
    truth(_stamp in _HOOK.VERIFIED_TIERS, "hook_stop: %s in VERIFIED_TIERS" % _stamp)
    _rec1 = {"metrics": [{"metric_id": "m1", "value": 1.0}]}
    _con1 = {"metrics": [{"metric_id": "m1", "claimed_value": 1.0}]}
    _cd = _CMP.compare(_rec1, _con1, isolation_tier=_stamp)
    truth(_cd["metrics"][0]["verdict_inputs"]["container_present"] is True,
          "compare: %s -> container_present True" % _stamp)
    _vi = {"isolation_tier": _stamp, "determinism_mode": "controlled-to-bit",
           "binding_status": "independently-bound", "claim_outside_ci": False}
    _bump = round(V.confidence(_vi, V.CONFIRMED)
                  - V.confidence(dict(_vi, isolation_tier="host-not-isolated"), V.CONFIRMED), 2)
    truth(_bump == 0.15, "verdict: %s earns the +0.15 isolation confidence bump" % _stamp)
    truth("host tier not isolated" not in V._caveat_reasons(V._norm(_vi)),
          "verdict: %s is NOT flagged host-not-isolated" % _stamp)
# the untrusted gate (G3) lifts for a verified microVM: untrusted + e2b stamp -> NOT INCONCLUSIVE
_vi_unt = V._norm({"isolation_tier": "e2b-firecracker", "untrusted": True,
                   "container_present": True, "determinism_mode": "controlled-to-bit"})
truth("untrusted" not in (V._inconclusive_reason(_vi_unt) or "")
      if hasattr(V, "_inconclusive_reason") else True,
      "verdict: untrusted code in a verified microVM is not blocked for missing isolation")


# ---------------------------------------------------------------------------
# (G) LIVE INTEGRATION (gated): real spawn/exec/recompute/stamp against a real E2B (or self-hosted)
# endpoint. Skipped unless CALMA_E2B_LIVE is set AND the three creds are present, so credential-less
# CI skips cleanly.
# ---------------------------------------------------------------------------
_live = os.environ.get("CALMA_E2B_LIVE") and all(
    os.environ.get(k) for k in ("CALMA_E2B_ENDPOINT", "CALMA_E2B_TEMPLATE")) and (
    os.environ.get("CALMA_E2B_API_KEY") or os.environ.get("CALMA_E2B_TOKEN"))
if _live:
    H.set_e2b_session_factory(None)  # use the REAL SDK
    _d = tempfile.mkdtemp()
    _vy = _engagement(_d, trust="third-party", entry_src=_GEN, contract_extra=_art)
    subprocess.run([sys.executable, os.path.join(_d, "main.py")], cwd=_d, capture_output=True)
    _true = RC.recompute_contract(_vy, base=_d, k=1)["metrics"][0]["value"]
    _c = json.load(open(_vy)); _c["metrics"][0]["claimed_value"] = _true
    _c["metrics"][0]["claim_confirmed"] = True; json.dump(_c, open(_vy, "w"))
    shutil.rmtree(os.path.join(_d, "runs"))
    res = C.verify(_d, run_id="e2b_live", force=True, trust="third-party", isolation="e2b")
    led = json.load(open(os.path.join(res["run_dir"], "ledger.json")))
    _stamp = led.get("scope", {}).get("isolation_tier")
    truth(_stamp in ("e2b-firecracker", "e2b-firecracker (self-hosted)"),
          "LIVE: real microVM stamps an e2b-firecracker tier (got %s)" % _stamp)
    truth(res["repo_verdict"] in (V.CONFIRMED, V.CAVEATS),
          "LIVE: honest claim recompute matches over real microVM output (got %s)" % res["repo_verdict"])
    shutil.rmtree(_d, ignore_errors=True)
else:
    print("  SKIP live e2b integration (set CALMA_E2B_LIVE + CALMA_E2B_ENDPOINT/API_KEY/TEMPLATE)")


print("run_hermetic e2b: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
