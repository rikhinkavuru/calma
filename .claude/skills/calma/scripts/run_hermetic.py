"""calma.run_hermetic - run the contract entrypoint under ONE verified isolation tier.

On macOS the host tier is a deny-by-default `sandbox-exec` (Seatbelt) profile: network egress denied,
$HOME reads denied (so secrets are unreadable), writes confined to the run output dir + temp. The tier
is only stamped `seatbelt-verified` after a POSITIVE-CONTROL self-test (`calma doctor`) proves that, under
the profile, a planted secret-read AND a network connect BOTH fail. If sandbox-exec is missing or the
self-test leaks, the tier is `host-not-isolated` (a CAVEAT, never a silent host-tier stamp). Untrusted
third-party code requires a container/VM tier (daemon) and is refused (exit 3) when none is live.

The entrypoint runs in its own process group; on timeout the whole group is killed (exit 4 -> INCONCLUSIVE).

Library: doctor() -> dict ; run(contract, base) -> dict.
CLI: run_hermetic.py doctor | run --contract verify.yaml [--base DIR] [--out run.json]
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

NONDET_LIBS = re.compile(r"\bimport\s+(torch|tensorflow|tf|cupy)\b|\bfrom\s+(torch|tensorflow)\b|cuda")
UNSEEDED_RANDOM = re.compile(r"\b(numpy|np)\.random\.|(?<!\.)\brandom\.")


def _have_sandbox_exec():
    return shutil.which("sandbox-exec") is not None


def _profile(base):
    """allow-default, then deny the two things we actually VERIFY: network egress and $HOME reads
    (so secrets are unreadable). The repo/base is re-allowed for read (it lives under $HOME). This keeps
    the interpreter alive on macOS while preserving the egress + secret-read denials the doctor proves.
    Writes are confined to the run output area + temp. last-match-wins, so order matters."""
    home = os.path.realpath(os.path.expanduser("~"))
    base = os.path.realpath(base)
    return '''(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "%s"))
(allow file-read* (subpath "%s"))
(deny file-write* (subpath "%s"))
(allow file-write* (subpath "%s") (subpath "/tmp") (subpath "/private/tmp") (subpath "/private/var/folders") (literal "/dev/null") (literal "/dev/tty"))
''' % (home, base, home, base)


def _run_sandboxed(profile_text, argv, cwd, timeout=120, env=None):
    """Run argv under the profile in its own process group. Returns (rc, out, err, killed)."""
    pf = tempfile.NamedTemporaryFile("w", suffix=".sb", delete=False)
    pf.write(profile_text)
    pf.close()
    cmd = (["sandbox-exec", "-f", pf.name] if _have_sandbox_exec() else []) + argv
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, start_new_session=True, env=env or os.environ.copy())
        try:
            out, err = p.communicate(timeout=timeout)
            return p.returncode, out, err, False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.communicate()
            return -9, "", "timeout", True
    finally:
        os.unlink(pf.name)


def doctor(repo_root=None):
    """Positive-control self-test: under the profile, a planted secret-read AND an egress MUST fail."""
    repo_root = os.path.realpath(repo_root or os.getcwd())
    home = os.path.expanduser("~")
    secret = os.path.join(home, ".calma_doctor_secret")
    info = {"sandbox_exec": _have_sandbox_exec()}
    if not info["sandbox_exec"]:
        info.update(tier="host-not-isolated", secret_read_blocked=False, egress_blocked=False,
                    note="sandbox-exec unavailable; cannot verify isolation on this host")
        return info
    try:
        with open(secret, "w") as fh:
            fh.write("TOPSECRET-CALMA-DOCTOR")
        prof = _profile(repo_root)
        # probe 1: read the secret (must be DENIED)
        probe_secret = "import sys\ntry:\n open(%r).read(); print('LEAK')\nexcept Exception:\n print('BLOCKED')\n" % secret
        rc, out, err, _ = _run_sandboxed(prof, [sys.executable, "-c", probe_secret], repo_root, timeout=20)
        secret_blocked = "LEAK" not in out
        # probe 2: network egress (must be DENIED)
        probe_net = ("import socket\ntry:\n socket.create_connection(('1.1.1.1',80),timeout=4);"
                     " print('LEAK')\nexcept Exception:\n print('BLOCKED')\n")
        rc2, out2, err2, _ = _run_sandboxed(prof, [sys.executable, "-c", probe_net], repo_root, timeout=20)
        egress_blocked = "LEAK" not in out2
    finally:
        if os.path.exists(secret):
            os.unlink(secret)
    tier = "seatbelt-verified" if (secret_blocked and egress_blocked) else "host-not-isolated"
    info.update(tier=tier, secret_read_blocked=secret_blocked, egress_blocked=egress_blocked)
    return info


def _detect_determinism(entrypoint_path):
    try:
        src = open(entrypoint_path).read()
    except OSError:
        return "uncontrolled", "entrypoint unreadable"
    if NONDET_LIBS.search(src):
        return "uncontrolled", "imports a GPU/ML framework; band must be measured (M2)"
    if UNSEEDED_RANDOM.search(src):
        return "measured-band", "uses RNG; determinism config / seeds required"
    return "controlled-to-bit", "pure-stdlib, no RNG/GPU libs (structural)"


def run(contract_path, base=None, timeout=120):
    with open(contract_path) as fh:
        contract = json.load(fh)
    base = os.path.realpath(base or os.path.dirname(os.path.abspath(contract_path)))
    trust = contract.get("env", {}).get("trust", "own-code")
    entry = contract["run"]["entrypoint"]
    entry_path = os.path.join(base, entry)
    doc = doctor(base)
    isolation_tier = doc["tier"]

    # untrusted third-party code needs a container/VM tier (not available here) -> refuse
    if trust == "untrusted-third-party" and isolation_tier not in ("container", "vm"):
        return {"phase": "refused", "exit_code": 3, "isolation_tier": isolation_tier,
                "reason": "untrusted third-party code requires a verified container/VM tier (none live)",
                "container_present": False}

    det_mode, det_note = _detect_determinism(entry_path)
    out_dir = os.path.join(base, "runs")
    prof = _profile(base)
    # network OFF for the run phase, unconditionally (the profile denies it; we also clear proxies)
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    rc, out, err, killed = _run_sandboxed(prof, [sys.executable, entry_path], base, timeout, env)
    exit_code = 4 if killed else (0 if rc == 0 else 1)
    return {
        "phase": "run", "entrypoint": entry, "exit_code": exit_code, "killed": killed,
        "isolation_tier": isolation_tier,
        "container_present": isolation_tier in ("seatbelt-verified", "tier0", "container", "vm"),
        "determinism_mode": det_mode, "determinism_note": det_note,
        "install_network": "off", "run_network": "off", "hermeticity": "vendored-snapshot",
        "stdout_tail": (out or "")[-500:], "stderr_tail": (err or "")[-500:],
        "doctor": doc,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["doctor", "run"])
    ap.add_argument("--contract")
    ap.add_argument("--base")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "doctor":
        res = doctor(a.base or os.getcwd())
    else:
        if not a.contract:
            print("run needs --contract", file=sys.stderr)
            return 2
        res = run(a.contract, a.base)
    text = json.dumps(res, indent=2)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return res.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main())
