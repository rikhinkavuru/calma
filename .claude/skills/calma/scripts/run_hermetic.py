"""calma.run_hermetic - run the contract entrypoint under ONE verified isolation tier.

On macOS the host tier is a deny-by-default `sandbox-exec` (Seatbelt) profile: network egress denied,
$HOME reads denied (so secrets are unreadable), writes confined to the run output dir + temp. The tier
is only stamped `seatbelt-verified` after a POSITIVE-CONTROL self-test (`calma doctor`) proves that, under
the profile, a planted secret-read AND a network connect BOTH fail. If sandbox-exec is missing or the
self-test leaks, the tier is `host-not-isolated` (a CAVEAT, never a silent host-tier stamp). Untrusted
third-party code requires a container/VM tier (daemon) and is refused (exit 3) when none is live.

The entrypoint runs in its own process group; on timeout the whole group is killed (exit 4 -> INCONCLUSIVE).
Two more closed surfaces: <base>/.calma is write-DENIED inside the sandbox (code under test can never
plant calma's own verdict state), and the child environment is a WHITELIST (PATH/HOME/LANG/LC_*/TMPDIR/
PYTHON* + contract env.passthrough names) - parent secrets never reach the code under test.

Library: doctor() -> dict ; run(contract, base) -> dict.
CLI: run_hermetic.py doctor | run --contract verify.yaml [--base DIR] [--out run.json]
"""
import argparse
import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

# AST-detected modules. GPU/ML -> uncontrolled (BLAS/cuda nondeterminism); RNG -> measured-band.
NONDET_MODULES = {"torch", "tensorflow", "cupy", "jax"}
# numpy and the numpy-backed scientific stack: BLAS reduction order is not bit-stable across
# threads/builds, so a program touching these cannot be PROVEN bit-deterministic -> measured-band.
RNG_MODULES = {"random", "secrets", "numpy", "pandas", "scipy", "sklearn", "statsmodels"}
# stdlib sources of run-to-run variation: importing any of these means we cannot PROVE bit-determinism
NONDET_STDLIB = {"time", "datetime", "uuid", "socket", "threading", "multiprocessing"}


def _have_sandbox_exec():
    return shutil.which("sandbox-exec") is not None


def _within(base, rel):
    """Resolve rel under base; return (fullpath, ok). ok=False if it escapes (abs path / .. traversal)."""
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    return full, (full == rb or full.startswith(rb + os.sep))


def _ancestors(path):
    """Every proper ancestor directory of `path` from / down to its parent (path itself excluded).
    These are the components a runtime must lstat/readlink to realpath-resolve an entrypoint that
    lives under a denied subtree (e.g. node's CJS loader lstat'ing /Users on the way to the script)."""
    path = os.path.realpath(path)
    out, cur = [], path
    while True:
        parent = os.path.dirname(cur)
        if parent == cur:  # reached "/"
            break
        out.append(parent)
        cur = parent
    return out


def _profile(base):
    """allow-default for the system paths the interpreter needs, then DENY the things we verify and
    claim: network egress, and reads of ALL user homes (/Users) + known system-secret dirs. The base is
    re-allowed for read (it lives under /Users). Writes are confined to the run area + temp. last-match-
    wins, so order matters: the FINAL deny on <base>/.calma overrides the base-wide write allow - code
    under test must never be able to plant verdict state (cache.json, ledgers, hook state) in calma's
    own bookkeeping dir. The verifier itself only writes .calma from the PARENT process after the
    sandboxed child exits, so it loses nothing. NOTE (stamped honestly): Seatbelt shares the host
    kernel and is NOT escape-isolated - untrusted third-party code requires a container/VM tier
    (refused otherwise)."""
    home = os.path.realpath(os.path.expanduser("~"))
    base = os.path.realpath(base)
    # metadata-only (lstat/stat/readlink) on the EXACT ancestor chain of the run base. A runtime that
    # realpath-resolves its entrypoint must lstat every parent directory on the way down (node's CJS
    # loader lstat's /Users -> EPERM under a blanket /Users read-deny). Granting file-read-metadata
    # (NOT file-read-data) on just those literal ancestors lets any language resolve its script while
    # directory listing and file-content reads stay denied across /Users - so secrets cannot be read
    # and the tree cannot be enumerated (the doctor positive-control still proves zero leaks).
    anc = " ".join('(literal "%s")' % a for a in _ancestors(base))
    return '''(version 1)
(allow default)
(deny network*)
(deny file-read*
  (subpath "/Users") (subpath "/etc/ssh") (subpath "/private/etc/ssh")
  (subpath "/var/root") (subpath "/private/var/root")
  (subpath "/Library/Keychains") (subpath "/private/var/db/dslocal"))
;; re-allow language-runtime/toolchain depots under $HOME (package caches, NOT secrets) so R/Julia/
;; Rust/Node can read their libs; the actual secret dirs (~/.ssh, ~/.aws, keychains) stay denied.
(allow file-read*
  (subpath "%s/.julia") (subpath "%s/.cargo") (subpath "%s/.rustup")
  (subpath "%s/.npm") (subpath "%s/.nvm") (subpath "%s/.node-gyp"))
;; metadata-only on the base's ancestor directories (entrypoint realpath resolution) - data reads
;; and directory listings under /Users remain denied; this only re-allows lstat/stat/readlink.
(allow file-read-metadata %s)
(allow file-read* (subpath "%s"))
(deny file-write* (subpath "/Users"))
(allow file-write* (subpath "%s") (subpath "/tmp") (subpath "/private/tmp") (subpath "/private/var/folders") (literal "/dev/null") (literal "/dev/tty"))
;; AFTER the allow (Seatbelt is last-match-wins): the code under test can never write calma's
;; own verdict state - no planted cache.json, no forged ledgers, no hook-state tampering.
(deny file-write* (subpath "%s/.calma"))
''' % (home, home, home, home, home, home, anc, base, base, base)


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


_PROBE = r'''
import socket, subprocess, os
leaks = []
SECRET = {secret!r}
# secret reads (multiple paths that MUST be denied)
for path in [SECRET, "/Library/Keychains", "/var/root"]:
    try:
        if os.path.isdir(path):
            os.listdir(path); leaks.append("read:" + path)
        else:
            open(path).read(); leaks.append("read:" + path)
    except Exception:
        pass
# egress: raw IP, hostname (DNS+TCP), and a curl subprocess - ALL must be denied
try:
    socket.create_connection(("1.1.1.1", 80), timeout=4); leaks.append("egress:ip")
except Exception:
    pass
try:
    socket.create_connection(("example.com", 80), timeout=4); leaks.append("egress:dns")
except Exception:
    pass
try:
    r = subprocess.run(["/usr/bin/curl", "-s", "-m", "4", "http://1.1.1.1"], capture_output=True)
    if r.returncode == 0 and r.stdout:
        leaks.append("egress:curl")
except Exception:
    pass
print("LEAKS=" + ",".join(leaks))
'''


def doctor(repo_root=None):
    """Positive-control self-test: under the profile, a BATTERY of secret-reads (planted $HOME secret,
    keychains, /var/root) AND egress attempts (raw IP, DNS hostname, curl subprocess) must ALL fail.
    Any leak -> host-not-isolated (never a silent verified stamp)."""
    repo_root = os.path.realpath(repo_root or os.getcwd())
    secret = os.path.join(os.path.realpath(os.path.expanduser("~")), ".calma_doctor_secret")
    info = {"sandbox_exec": _have_sandbox_exec()}
    if not info["sandbox_exec"]:
        info.update(tier="host-not-isolated", secret_read_blocked=False, egress_blocked=False,
                    note="sandbox-exec unavailable; cannot verify isolation on this host")
        return info
    try:
        with open(secret, "w") as fh:
            fh.write("TOPSECRET-CALMA-DOCTOR")
        prof = _profile(repo_root)
        rc, out, err, _ = _run_sandboxed(prof, [sys.executable, "-c", _PROBE.format(secret=secret)],
                                         repo_root, timeout=30)
    finally:
        if os.path.exists(secret):
            os.unlink(secret)
    leaks = ""
    for line in (out or "").splitlines():
        if line.startswith("LEAKS="):
            leaks = line[len("LEAKS="):].strip()
    leak_list = [x for x in leaks.split(",") if x]
    secret_blocked = not any(x.startswith("read:") for x in leak_list)
    egress_blocked = not any(x.startswith("egress:") for x in leak_list)
    tier = "seatbelt-verified" if (not leak_list) else "host-not-isolated"
    info.update(tier=tier, secret_read_blocked=secret_blocked, egress_blocked=egress_blocked,
                leaks=leak_list,
                note="host-kernel shared; verified = egress+secret-read denial, NOT escape isolation")
    return info


def _scan_one(path):
    """AST-scan a single file -> (modules:set, urandom:bool, dynamic:str|None, parsed:bool). Catches
    aliased/from-imports a regex would miss (import random as r; from random import random; numpy
    aliases; os.urandom) plus dynamic import/exec."""
    try:
        tree = ast.parse(open(path).read())
    except (OSError, SyntaxError):
        return set(), False, None, False
    mods, urandom, dynamic = set(), False, None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute):
            if node.attr == "urandom":
                urandom = True
            elif node.attr == "import_module":   # importlib.import_module(...)
                dynamic = "importlib.import_module"
        elif isinstance(node, ast.Name) and node.id in ("__import__", "exec", "eval", "compile"):
            dynamic = node.id
    return mods, urandom, dynamic, True


def _project_pyfiles(base):
    """Every .py file under base that is part of the program under test - EXCLUDING calma's own
    bookkeeping and the restored dependency venv (.calma, .calma_venv) and bytecode caches. Determinism
    is a property of the whole program, not just the entry file: a thin entrypoint over local modules
    that import numpy is NOT bit-deterministic, and stamping it controlled-to-bit would overclaim."""
    out = []
    for dp, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for n in names:
            if n.endswith(".py"):
                out.append(os.path.join(dp, n))
    return out


def _detect_determinism(entrypoint_path, base=None):
    """Conservative whole-program AST scan: controlled-to-bit ONLY when EVERY .py file under the
    program tree is pure-stdlib with no RNG/GPU/scientific-stack imports. The entrypoint is
    authoritative for parse failure (unparseable entry -> uncontrolled, fail safe); other files are
    best-effort. Bias is always toward the weaker (more-caveated) stamp.

    Whole-tree scan happens ONLY when `base` is supplied (real runs always pass the contract base).
    A bare single-file call (base=None) scans just the entrypoint - so callers pointing at a file in a
    shared/unrelated directory don't get tarred by neighbors."""
    e_mods, e_urandom, e_dynamic, e_ok = _scan_one(entrypoint_path)
    if not e_ok:
        return "uncontrolled", "entrypoint unparseable"
    mods, urandom, dynamic = set(e_mods), e_urandom, e_dynamic
    contributors = {entrypoint_path: e_mods}
    for f in (_project_pyfiles(base) if base else []):
        if os.path.abspath(f) == os.path.abspath(entrypoint_path):
            continue
        fm, fu, fd, ok = _scan_one(f)
        if not ok:
            continue
        mods |= fm
        urandom = urandom or fu
        dynamic = dynamic or fd
        contributors[f] = fm

    _rel_base = base or os.path.dirname(os.path.abspath(entrypoint_path))

    def _where(name):
        hits = [os.path.relpath(p, _rel_base) for p, ms in contributors.items() if name in ms]
        return (" (in %s)" % hits[0]) if hits else ""

    if dynamic:
        return "uncontrolled", "uses %s (dynamic import/exec); determinism cannot be proven statically" % dynamic
    if "importlib" in mods:
        return "uncontrolled", "imports importlib (dynamic import); determinism cannot be proven statically"
    gpu = mods & NONDET_MODULES
    if gpu:
        return "uncontrolled", "imports a GPU/ML framework (%s%s); band must be measured (M2)" % \
            (", ".join(sorted(gpu)), _where(sorted(gpu)[0]))
    rng = (mods & (RNG_MODULES | NONDET_STDLIB)) | ({"os.urandom"} if urandom else set())
    if rng:
        first = sorted(rng)[0]
        return "measured-band", "uses %s%s; bit-determinism cannot be proven, band must be measured (M2)" % \
            (", ".join(sorted(rng)), _where(first))
    return "controlled-to-bit", "pure-stdlib, no RNG/GPU imports (whole-program structural)"


def _which(*names):
    for n in names:
        if shutil.which(n):
            return shutil.which(n)
    return None


def _venv_python(base):
    """If a restored project venv exists under <base>/.calma_venv, return its interpreter. Restoring
    deps then running under a DIFFERENT interpreter is unsound (the run can't import what restore
    installed); a dep-heavy repo would silently fail the run gate. When the restore step built a venv,
    the run must use it. Returns None when there is no venv (stdlib repos keep the host interpreter)."""
    cand = os.path.join(base, ".calma_venv", "bin", "python")
    return cand if os.path.exists(cand) else None


def _lang_dispatch(entry_path, base):
    """Return (interpreter_ok, compile_cmd_or_None, run_argv, language). Calma runs the program as a
    BLACK BOX and recomputes in its own Python layer, so any language that emits a machine-readable file
    is verifiable - the language only touches the run + env gates."""
    ext = os.path.splitext(entry_path)[1].lower()
    binp = os.path.join(base, ".calma_bin")
    cc = _which("cc", "clang")
    cxx = _which("c++", "clang++")
    table = {
        ".py": (sys.executable, (None, [sys.executable, entry_path]), "python"),
        ".r": (_which("Rscript"), (None, [_which("Rscript") or "Rscript", entry_path]), "r"),
        ".jl": (_which("julia"), (None, [_which("julia") or "julia", entry_path]), "julia"),
        ".js": (_which("node"), (None, [_which("node") or "node", entry_path]), "node"),
        ".sh": (_which("sh"), (None, ["sh", entry_path]), "shell"),
        ".c": (cc, ([cc, entry_path, "-O2", "-o", binp] if cc else None, [binp]), "c"),
        ".cpp": (cxx, ([cxx, entry_path, "-O2", "-std=c++17", "-o", binp] if cxx else None, [binp]), "cpp"),
        ".cc": (cxx, ([cxx, entry_path, "-O2", "-std=c++17", "-o", binp] if cxx else None, [binp]), "cpp"),
        ".rs": (_which("rustc"), ([_which("rustc"), "-O", entry_path, "-o", binp] if _which("rustc") else None, [binp]), "rust"),
    }
    interp, (compile_cmd, run_argv), lang = table.get(ext, (None, (None, None), ext.lstrip(".")))
    return interp, compile_cmd, run_argv, lang


def _child_env(contract=None):
    """The environment WHITELIST for the code under test: only PATH/HOME/LANG/LC_*/TMPDIR/PYTHON*
    survive, plus any names the contract explicitly declares under env.passthrough. The parent's
    secrets (API keys, tokens, cloud credentials) never reach the sandboxed child - the env is a
    second exfiltration surface next to the filesystem, and it is closed by default."""
    declared = set()
    if isinstance(contract, dict):
        pt = (contract.get("env") or {}).get("passthrough") or []
        if isinstance(pt, list):
            declared = {str(x) for x in pt}
    env = {}
    for k, v in os.environ.items():
        if k in ("PATH", "HOME", "LANG", "TMPDIR") or k.startswith("LC_") \
                or k.startswith("PYTHON") or k in declared:
            env[k] = v
    return env


def run(contract_path, base=None, timeout=120, trust_override=None):
    import draft_contract as _DC
    contract = _DC.load_contract(contract_path)
    base = os.path.realpath(base or os.path.dirname(os.path.abspath(contract_path)))
    # trust_override: the CLI's runtime posture (`calma verify --trust third-party`) - it
    # tightens the loaded contract's posture without ever rewriting the contract file
    trust = trust_override or contract.get("env", {}).get("trust", "own-code")
    entry = contract["run"]["entrypoint"]
    entry_path, _ok = _within(base, entry)
    if not _ok:
        return {"phase": "refused", "exit_code": 2, "isolation_tier": "n/a",
                "container_present": False, "killed": False,
                "reason": "entrypoint escapes the contract base: %r" % entry}
    doc = doctor(base)
    isolation_tier = doc["tier"]

    # untrusted third-party code needs a container/VM tier (not available here) -> refuse
    if trust == "untrusted-third-party" and isolation_tier not in ("container", "vm"):
        return {"phase": "refused", "exit_code": 3, "isolation_tier": isolation_tier,
                "reason": "untrusted third-party code requires a verified container/VM tier (none live)",
                "container_present": False}

    interp, compile_cmd, run_argv, lang = _lang_dispatch(entry_path, base)
    if interp is None or run_argv is None:
        return {"phase": "refused", "exit_code": 3, "isolation_tier": isolation_tier, "language": lang,
                "container_present": False, "killed": False,
                "reason": "no toolchain for .%s entrypoints on this host" % lang}
    # restore/run interpreter consistency: a Python repo whose deps were restored into <base>/.calma_venv
    # must RUN under that venv, not the host interpreter (else it can't import what restore installed).
    venv_py = _venv_python(base) if lang == "python" else None
    if venv_py:
        run_argv = [venv_py] + run_argv[1:]
    # determinism: AST proof for Python; non-Python cannot be statically proven -> uncontrolled
    if lang == "python":
        det_mode, det_note = _detect_determinism(entry_path, base)
    else:
        det_mode, det_note = "uncontrolled", "%s: bit-determinism not statically provable (non-Python)" % lang
    out_dir = os.path.join(base, "runs")
    prof = _profile(base)
    env = _child_env(contract)
    # determinism hardening for the re-execution: pinned hash seed (stable set/dict iteration order),
    # no bytecode writes into the target, pinned locale. Free reproducibility, no behavior loss.
    env.update({"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
                "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "TZ": "UTC"})
    # the network/hermeticity stamps are DERIVED from the achieved tier, never asserted: on a host
    # with no verified sandbox (e.g. Linux without sandbox-exec) the truth is "not blocked".
    tier_verified = isolation_tier in ("seatbelt-verified", "tier0", "container", "vm")
    net_stamp = "off" if tier_verified else "host-default (NOT blocked - no verified sandbox on this host)"
    herm_stamp = "vendored-snapshot" if tier_verified else "unverified"
    # compile step (C/C++/Rust) under the same verified tier; failure -> run-gate fail
    if compile_cmd:
        crc, cout, cerr, ckill = _run_sandboxed(prof, compile_cmd, base, timeout, env)
        if ckill or crc != 0:
            return {"phase": "run", "entrypoint": entry, "exit_code": 1, "killed": ckill, "language": lang,
                    "isolation_tier": isolation_tier, "determinism_mode": det_mode,
                    "container_present": tier_verified,
                    "install_network": net_stamp, "run_network": net_stamp,
                    "stderr_tail": ("compile failed: " + (cerr or ""))[-500:], "doctor": doc}
    rc, out, err, killed = _run_sandboxed(prof, run_argv, base, timeout, env)
    exit_code = 4 if killed else (0 if rc == 0 else 1)
    return {
        "phase": "run", "entrypoint": entry, "exit_code": exit_code, "killed": killed, "language": lang,
        "run_exit_status": rc,
        "isolation_tier": isolation_tier,
        "container_present": tier_verified,
        "interpreter": "restored-venv" if venv_py else "host",
        "determinism_mode": det_mode, "determinism_note": det_note,
        "install_network": net_stamp, "run_network": net_stamp, "hermeticity": herm_stamp,
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
