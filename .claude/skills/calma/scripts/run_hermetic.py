"""calma.run_hermetic - run the contract entrypoint under ONE verified isolation tier.

There are TWO no-daemon host own-code tiers, one per OS, gated by the SAME positive-control self-test
(`calma doctor`): a planted secret-read AND a network connect must BOTH fail under the tier.
  - macOS: a deny-by-default `sandbox-exec` (Seatbelt) profile - network egress denied, $HOME reads
    denied (secrets unreadable), writes confined to the base + temp; stamped `seatbelt-verified`.
  - Linux: an unprivileged `bwrap` (bubblewrap) namespace - net OFF by construction (--unshare-net),
    filesystem ALLOWLIST-by-construction (only system roots + the base are visible, so $HOME/secrets
    are simply absent), writes confined to the base; stamped `bwrap-verified`. (bubblewrap 0.9.0 here.)
If the tier's binary is missing, its self-test leaks, or (Linux) unprivileged userns is disabled so the
probe never runs, the tier is `host-not-isolated` (a CAVEAT, never a silent host-tier stamp). An EXPLICIT
--isolation seatbelt|bwrap that does not verify is REFUSED (exit 3), never a silent host fallback.
Untrusted third-party code requires a container/VM tier (daemon) and is refused (exit 3) when none is
live. Both host tiers share the host kernel and are NOT escape-isolated to microVM strength.

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
import platform
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
try:
    import resource as _resource     # POSIX-only: the bwrap tier's pure-stdlib resource caps
except ImportError:                  # pragma: no cover - non-POSIX host
    _resource = None

# AST-detected modules. GPU/ML -> uncontrolled (BLAS/cuda nondeterminism); RNG -> measured-band.
NONDET_MODULES = {"torch", "tensorflow", "cupy", "jax"}
# numpy and the numpy-backed scientific stack: BLAS reduction order is not bit-stable across
# threads/builds, so a program touching these cannot be PROVEN bit-deterministic -> measured-band.
RNG_MODULES = {"random", "secrets", "numpy", "pandas", "scipy", "sklearn", "statsmodels"}
# stdlib sources of run-to-run variation: importing any of these means we cannot PROVE bit-determinism
NONDET_STDLIB = {"time", "datetime", "uuid", "socket", "threading", "multiprocessing"}

# the isolation tiers that count as VERIFIED for stamp derivation. MUST stay in lockstep with the
# verified-tier sets the verdict layer keys on (calma.VERIFIED_TIERS, hook_stop.VERIFIED_TIERS,
# compare.compare's container_present default, verdict.confidence) - the anti-drift guard test asserts
# every consumer accepts the same names. host-not-isolated is deliberately absent (it is the CAVEAT).
_VERIFIED_TIERS = ("seatbelt-verified", "bwrap-verified", "tier0", "container", "vm")


def _have_sandbox_exec():
    return shutil.which("sandbox-exec") is not None


def _have_bwrap():
    return shutil.which("bwrap") is not None


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


def _symlink_chain_dirs(path):
    """Every directory touched while resolving `path` symlink-by-symlink. execvp readlink()s each
    intermediate link (e.g. a venv's python -> ~/.local/bin/python3.12 -> the uv install), and EACH
    of those dirs must be readable or exec fails EPERM under a /Users read-deny."""
    dirs, seen, cur = set(), set(), os.path.abspath(path)
    for _ in range(40):
        dirs.add(os.path.dirname(cur))
        if cur in seen:
            break
        seen.add(cur)
        try:
            if os.path.islink(cur):
                tgt = os.readlink(cur)
                cur = os.path.normpath(tgt if os.path.isabs(tgt)
                                       else os.path.join(os.path.dirname(cur), tgt))
                continue
        except OSError:
            pass
        break
    return dirs


def _interp_reads(*paths):
    """The interpreter subpaths that must stay readable under the profile. A RESTORED venv's base
    interpreter often lives under $HOME (uv: ~/.local/share/uv/python/..., pyenv: ~/.pyenv/...,
    conda: ~/miniconda3/...), reached through a chain of $HOME symlinks. The profile denies /Users
    reads, so without re-allowing the resolved interpreter's install prefix AND every symlink-chain
    directory on the way to it, the venv python cannot be exec'd (execvp EPERM). We re-allow ONLY
    those specific dirs (the interpreter's stdlib/shared libs + the link chain), never a broad home
    subtree, and only under /Users (system paths like /opt, /usr are not denied)."""
    out = set()
    for p in paths:
        if not p:
            continue
        out |= _symlink_chain_dirs(p)
        try:
            rp = os.path.realpath(p)
        except OSError:
            continue
        out.add(os.path.dirname(rp))                       # .../bin
        out.add(os.path.dirname(os.path.dirname(rp)))      # the install prefix (bin/.. -> lib/include)
    return sorted(d for d in out if d and d.startswith("/Users") and d != "/Users")


def _profile(base, interp_reads=()):
    """allow-default for the system paths the interpreter needs, then DENY the things we verify and
    claim: network egress, and reads of ALL user homes (/Users) + known system-secret dirs. The base is
    re-allowed for read (it lives under /Users). Writes are confined to the run area + temp. last-match-
    wins, so order matters: the FINAL deny on <base>/.calma overrides the base-wide write allow - code
    under test must never be able to plant verdict state (cache.json, ledgers, hook state) in calma's
    own bookkeeping dir. The verifier itself only writes .calma from the PARENT process after the
    sandboxed child exits, so it loses nothing. `interp_reads` re-allows a RESTORED venv's base
    interpreter install prefix when it lives under $HOME (see _interp_reads). NOTE (stamped honestly):
    Seatbelt shares the host kernel and is NOT escape-isolated - untrusted third-party code requires a
    container/VM tier (refused otherwise)."""
    home = os.path.realpath(os.path.expanduser("~"))
    base = os.path.realpath(base)
    # metadata-only (lstat/stat/readlink) on the EXACT ancestor chain of the run base. A runtime that
    # realpath-resolves its entrypoint must lstat every parent directory on the way down (node's CJS
    # loader lstat's /Users -> EPERM under a blanket /Users read-deny). Granting file-read-metadata
    # (NOT file-read-data) on just those literal ancestors lets any language resolve its script while
    # directory listing and file-content reads stay denied across /Users - so secrets cannot be read
    # and the tree cannot be enumerated (the doctor positive-control still proves zero leaks).
    anc = " ".join('(literal "%s")' % a for a in _ancestors(base))
    # language-runtime / interpreter depots under $HOME (package caches + interpreter installs, NOT
    # secrets). A RESTORED venv's base python frequently lives in one of these (uv/pyenv/conda/rye),
    # reached through nested $HOME symlinks that Seatbelt's exact-path matching can't follow - so we
    # re-allow the depot ROOTS (broad but safe: never ~/.ssh, ~/.aws, keychains). Same intent as the
    # existing Julia/Cargo/Node re-allows.
    _DEPOTS = (".julia", ".cargo", ".rustup", ".npm", ".nvm", ".node-gyp",
               ".pyenv", ".conda", "miniconda3", "anaconda3", "miniforge3", ".rye",
               ".local/share/uv", ".local/bin", "Library/Application Support/uv")
    depots = " ".join('(subpath "%s/%s")' % (home, d) for d in _DEPOTS)
    interp = "".join('\n(allow file-read* (subpath "%s"))' % p for p in interp_reads)
    return '''(version 1)
(allow default)
(deny network*)
(deny file-read*
  (subpath "/Users") (subpath "/etc/ssh") (subpath "/private/etc/ssh")
  (subpath "/var/root") (subpath "/private/var/root")
  (subpath "/Library/Keychains") (subpath "/private/var/db/dslocal"))
;; re-allow language-runtime/interpreter depots under $HOME (package caches + interpreter installs,
;; NOT secrets) so R/Julia/Rust/Node/Python(venv) can read their libs; ~/.ssh, ~/.aws, keychains stay denied.
(allow file-read* %s)
;; metadata-only on the base's ancestor directories (entrypoint realpath resolution) - data reads
;; and directory listings under /Users remain denied; this only re-allows lstat/stat/readlink.
(allow file-read-metadata %s)
(allow file-read* (subpath "%s"))%s
(deny file-write* (subpath "/Users"))
(allow file-write* (subpath "%s") (subpath "/tmp") (subpath "/private/tmp") (subpath "/private/var/folders") (literal "/dev/null") (literal "/dev/tty"))
;; AFTER the allow (Seatbelt is last-match-wins): the code under test can never write calma's
;; own verdict state - no planted cache.json, no forged ledgers, no hook-state tampering.
(deny file-write* (subpath "%s/.calma"))
''' % (depots, anc, base, interp, base, base)


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


# ---------------------------------------------------------------------------
# Native-Linux own-code tier (bubblewrap). Beside the macOS Seatbelt tier and gated by the SAME probe
# battery (_PROBE), this is a NO-DAEMON host tier for OWN code - distinct from the --isolation docker
# path (untrusted code, needs a daemon). bubblewrap runs UNPRIVILEGED via user namespaces: network is
# OFF by construction (--unshare-net) and the filesystem is ALLOWLIST-by-construction - only /usr,/lib*,
# /bin,/sbin (read-only) + the run base are visible, so $HOME (secrets), /root, and keychains are simply
# ABSENT from the namespace (strictly stronger than Seatbelt's denylist). Like Seatbelt it shares the
# host kernel and is NOT escape-isolated to microVM strength. The tier is stamped `bwrap-verified` ONLY
# after bwrap_doctor proves zero leaks under the real wrapper on this host; bwrap missing, unprivileged
# userns disabled (the probe never runs), or ANY leak -> host-not-isolated, never a silent host stamp.
# ---------------------------------------------------------------------------

# /usr is hard-required (the interpreter + shared libs live there); the rest are bound only when present
# (--ro-bind-try) so arm64 / usrmerge hosts without /lib64 or a real /bin don't abort bwrap. None of the
# `try` paths is part of the secret boundary - they are read-only SYSTEM roots, never $HOME.
_BWRAP_TRY_ROOTS = ("/lib", "/lib64", "/bin", "/sbin")


def _bwrap_interp_dirs(*paths):
    """The interpreter dirs to bind read-only into the namespace. A restored venv's base python or a
    host python (uv/pyenv/conda) can live OUTSIDE the bound system roots; without re-binding the
    resolved interpreter's install prefix AND every symlink-chain directory on the way to it, execvp
    fails ENOENT inside the namespace. We bind ONLY those exact dirs (never a broad $HOME subtree -
    tighter than Seatbelt's whole-depot re-allow) and skip anything already covered by the system roots.
    Same intent as _interp_reads, minus the macOS /Users-only filter."""
    covered = ("/usr",) + _BWRAP_TRY_ROOTS
    out = set()
    for p in paths:
        if not p:
            continue
        out |= _symlink_chain_dirs(p)
        try:
            rp = os.path.realpath(p)
        except OSError:
            continue
        out.add(os.path.dirname(rp))                       # .../bin
        out.add(os.path.dirname(os.path.dirname(rp)))      # the install prefix (bin/.. -> lib/include)
    res = []
    for d in sorted(out):
        if not d or d == "/":
            continue
        if any(d == c or d.startswith(c + os.sep) for c in covered):
            continue
        res.append(d)
    return res


def _bwrap_argv(base, inner_argv, interp_dirs=(), writable=True, deny_calma=True, seccomp_fd=None):
    """Build the full `bwrap` argv (a pure list of strings, like _docker_argv - no None ever leaks in).
    Network is OFF by construction (--unshare-net); the FS is allowlist-by-construction (only the system
    roots + base are visible, so $HOME/.ssh, /root, keychains, and any planted secret are absent). The
    base is bind-mounted read-WRITE so outputs land for recompute; <base>/.calma is re-bound READ-ONLY
    *after* the base (bwrap is last-mount-wins) so the code under test can never plant calma's own
    verdict state (cache.json, ledgers, hook state). `interp_dirs` re-binds an interpreter prefix that
    lives outside the system roots (see _bwrap_interp_dirs). `writable=False` (the doctor probe) binds
    the base read-only - proving the floor: even with nothing writable, egress + host-secret reads fail."""
    base = os.path.realpath(base)
    argv = [shutil.which("bwrap") or "bwrap",
            "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
            "--die-with-parent", "--new-session"]
    if seccomp_fd is not None:
        # defence in depth: a syscall denylist applied to the sandboxed process (see _seccomp_program)
        argv += ["--seccomp", str(seccomp_fd)]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
             "--ro-bind", "/usr", "/usr"]
    for d in _BWRAP_TRY_ROOTS:
        argv += ["--ro-bind-try", d, d]
    for d in interp_dirs:
        argv += ["--ro-bind-try", d, d]
    argv += [("--bind" if writable else "--ro-bind"), base, base]
    # only meaningful when the base is writable; a read-only base already denies every .calma write.
    if deny_calma and writable:
        calma = os.path.join(base, ".calma")
        argv += ["--ro-bind-try", calma, calma]
    argv += ["--chdir", base, "--"] + list(inner_argv)
    return argv


def _env_int(name, default):
    """A non-negative int env override (CALMA_BWRAP_*); fall back to default on missing/garbage/negative."""
    try:
        v = int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default
    return v if v >= 0 else default


def _bwrap_rlimits():
    """preexec hook - runs in the forked child before bwrap exec, inherited by the sandboxed process.
    Pure-stdlib resource caps for the no-daemon tier (bwrap has none of its own): no core dumps, bounded
    file size, a fork-bomb ceiling (NPROC), and an fd-bomb ceiling (NOFILE). Defaults are generous enough
    never to false-fail the doctor probe or normal own-code, but cap egregious blow-ups; all env-
    overridable. A virtual-address memory cap is OPT-IN (CALMA_BWRAP_MEM_MB) because RLIMIT_AS over-counts
    reserved-but-unused VA (numpy/JIT) and would false-kill - RSS-accurate memory + per-sandbox pids
    limiting is cgroup v2, the documented next ceiling (like the microVM kernel-isolation ceiling)."""
    if _resource is None:
        return
    def _cap(which, val):
        try:
            _soft, hard = _resource.getrlimit(which)
            ceil = val if hard == _resource.RLIM_INFINITY else min(val, hard)
            _resource.setrlimit(which, (ceil, hard))
        except (ValueError, OSError):
            pass
    _cap(_resource.RLIMIT_CORE, 0)                                            # no core dumps (disk + info)
    _cap(_resource.RLIMIT_FSIZE, _env_int("CALMA_BWRAP_FSIZE_MB", 8192) * 1024 * 1024)
    _cap(_resource.RLIMIT_NOFILE, _env_int("CALMA_BWRAP_NOFILE", 16384))      # per-process fd-bomb ceiling
    if hasattr(_resource, "RLIMIT_NPROC"):
        # best-effort only: bwrap's --unshare-user maps the child to uid-0-in-userns, which the kernel
        # EXEMPTS from RLIMIT_NPROC - so this does NOT hard-bound a fork-bomb here. The real per-sandbox
        # pids cap is cgroup v2 pids.max (needs delegation, often absent); the bwrap PID namespace +
        # wall-clock timeout (process-group SIGKILL, --die-with-parent) reap a runaway tree as the proven
        # backstop. We still set it for any non-userns reuse and as defence in depth.
        _cap(_resource.RLIMIT_NPROC, _env_int("CALMA_BWRAP_NPROC", 4096))
    _mem = _env_int("CALMA_BWRAP_MEM_MB", 0)                                  # opt-in (VA over-counts)
    if _mem > 0:
        _cap(_resource.RLIMIT_AS, _mem * 1024 * 1024)


# --- seccomp syscall filter (Fix #3) ---------------------------------------------------------------
# A cBPF seccomp program returning EPERM for syscalls own code never needs and that are escape/attack
# primitives: namespace + mount manipulation, kernel-module + kexec + bpf loading, ptrace / process-vm
# peeking, key management, swap / reboot / accounting. Defence in depth BEHIND the namespace walls (net
# is already off via --unshare-net, so net syscalls are NOT denied - and the probe imports socket).
# Per-arch syscall numbers; on an arch with no table we emit nothing and skip seccomp (the walls still
# hold and the doctor still verifies). The doctor self-test empirically proves the interpreter survives.
_SECCOMP_DENY = (
    "mount", "umount2", "pivot_root", "chroot", "setns", "unshare",
    "init_module", "finit_module", "delete_module", "kexec_load", "kexec_file_load",
    "bpf", "perf_event_open", "add_key", "keyctl", "request_key",
    "ptrace", "process_vm_readv", "process_vm_writev",
    "open_tree", "move_mount", "fsopen", "fsconfig", "fsmount", "mount_setattr",
    "swapon", "swapoff", "reboot", "acct", "quotactl", "_sysctl", "uselib", "nfsservctl",
)
_SECCOMP_NR = {
    "x86_64": {"mount": 165, "umount2": 166, "pivot_root": 155, "chroot": 161, "setns": 308,
               "unshare": 272, "init_module": 175, "finit_module": 313, "delete_module": 176,
               "kexec_load": 246, "kexec_file_load": 320, "bpf": 321, "perf_event_open": 298,
               "add_key": 248, "keyctl": 250, "request_key": 249, "ptrace": 101,
               "process_vm_readv": 310, "process_vm_writev": 311, "open_tree": 428, "move_mount": 429,
               "fsopen": 430, "fsconfig": 431, "fsmount": 432, "mount_setattr": 442, "swapon": 167,
               "swapoff": 168, "reboot": 169, "acct": 163, "quotactl": 179, "_sysctl": 156,
               "uselib": 134, "nfsservctl": 180},
    "aarch64": {"mount": 40, "umount2": 39, "pivot_root": 41, "chroot": 51, "setns": 268, "unshare": 97,
                "init_module": 105, "finit_module": 273, "delete_module": 106, "kexec_load": 104,
                "kexec_file_load": 294, "bpf": 280, "perf_event_open": 241, "add_key": 217,
                "keyctl": 219, "request_key": 218, "ptrace": 117, "process_vm_readv": 270,
                "process_vm_writev": 271, "open_tree": 428, "move_mount": 429, "fsopen": 430,
                "fsconfig": 431, "fsmount": 432, "mount_setattr": 442, "swapon": 224, "swapoff": 225,
                "reboot": 142, "acct": 89, "quotactl": 60},
}
_SECCOMP_AUDIT_ARCH = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}


def _seccomp_arch():
    return {"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine(), platform.machine())


def _seccomp_program():
    """Return the cBPF program bytes (an array of struct sock_filter {u16 code;u8 jt;u8 jf;u32 k}, the
    format bwrap's --seccomp reads) for THIS arch - EPERM for the denied syscalls, ALLOW for the rest,
    KILL on an arch mismatch (guards against a 32/64-bit syscall-number confusion). b'' for an arch we
    have no table for (seccomp then skipped)."""
    arch = _seccomp_arch()
    nrs = _SECCOMP_NR.get(arch)
    audit = _SECCOMP_AUDIT_ARCH.get(arch)
    if not nrs or audit is None:
        return b""
    denied = sorted({nrs[n] for n in _SECCOMP_DENY if n in nrs})
    LD_W_ABS, JEQ_K, RET_K = 0x20, 0x15, 0x06         # BPF_LD|W|ABS, BPF_JMP|JEQ|K, BPF_RET|K
    ALLOW, ERRNO_EPERM, KILL = 0x7FFF0000, (0x00050000 | 1), 0x80000000
    prog = [(LD_W_ABS, 0, 0, 4),                       # A = arch (seccomp_data offset 4)
            (JEQ_K, 1, 0, audit),                      # arch == ours -> skip the kill
            (RET_K, 0, 0, KILL),                       # arch mismatch -> kill the process
            (LD_W_ABS, 0, 0, 0)]                       # A = syscall nr (offset 0)
    n = len(denied)
    for i, nr in enumerate(denied):
        prog.append((JEQ_K, n - i, 0, nr))             # nr matches -> jump to the ERRNO return
    prog.append((RET_K, 0, 0, ALLOW))                  # default: allow
    prog.append((RET_K, 0, 0, ERRNO_EPERM))            # the EPERM target
    return b"".join(struct.pack("<HBBI", *ins) for ins in prog)


def _seccomp_fd():
    """Write the program to a temp file and return (fd, path) for bwrap's --seccomp, or (None, None)
    when there is no program for this arch / on any error (seccomp is then skipped, walls still hold)."""
    prog = _seccomp_program()
    if not prog:
        return None, None
    try:
        fd, path = tempfile.mkstemp(suffix=".bpf")
    except OSError:
        return None, None
    try:
        os.write(fd, prog)
        os.lseek(fd, 0, os.SEEK_SET)
        os.set_inheritable(fd, True)
        return fd, path
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        return None, None


def _bwrap_hardening():
    """The defense-in-depth layers the bwrap tier applies on THIS host (machine-readable, for the report
    / agents): net-off (--unshare-net) + filesystem allowlist + pure-stdlib rlimit caps, plus a seccomp
    syscall denylist when a filter was built for this architecture. Claims only what actually holds."""
    layers = ["net-off", "fs-allowlist", "rlimits"]
    if _seccomp_program():
        layers.append("seccomp")
    return layers


def _run_bwrapped(argv, cwd, timeout=120, env=None, pass_fds=()):
    """Run a bwrap argv in its own process group, under the pure-stdlib resource caps (preexec). Returns
    (rc, out, err, killed). --die-with-parent + --unshare-pid tear the sandboxed tree down with the
    parent; the process-group SIGKILL on timeout is belt-and-suspenders (same discipline as
    _run_sandboxed). A bwrap that cannot even start (missing binary / kernel support) returns rc!=0 with
    no output -> the doctor's `produced` check fails it. `pass_fds` keeps the seccomp program fd open."""
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True, env=env or os.environ.copy(),
                             preexec_fn=_bwrap_rlimits, pass_fds=tuple(pass_fds))
    except OSError as e:
        return -1, "", "bwrap failed to start: %s" % e, False
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


def _run_bwrap(base, inner_argv, cwd, timeout=120, env=None, interp_dirs=(), writable=True):
    """Launch inner_argv under bubblewrap with the SAME hardening the doctor verifies: the allowlist
    binds (_bwrap_argv) + a seccomp syscall denylist + pure-stdlib resource caps (preexec setrlimit).
    Single source of truth, so the self-test exercises exactly what the real run does."""
    sec_fd, sec_path = _seccomp_fd()
    try:
        argv = _bwrap_argv(base, inner_argv, interp_dirs=interp_dirs, writable=writable, seccomp_fd=sec_fd)
        pass_fds = (sec_fd,) if sec_fd is not None else ()
        return _run_bwrapped(argv, cwd, timeout, env, pass_fds=pass_fds)
    finally:
        if sec_fd is not None:
            try:
                os.close(sec_fd)
            except OSError:
                pass
        if sec_path:
            try:
                os.unlink(sec_path)
            except OSError:
                pass


def _bwrap_userns_hint(err):
    """Map a failed-to-start bwrap stderr to a human cause + the exact one-line fix. The dominant reason
    a *present* bwrap cannot run is that unprivileged user namespaces are disabled (Ubuntu 24.04's
    AppArmor restriction, or a hardened/locked-down kernel) - so the tier degrades to host-not-isolated
    and we tell the operator how to turn it on (Calma always emits the fix, never just the failure)."""
    e = (err or "").lower()
    if any(s in e for s in ("namespace", "permission", "userns", "uid map", "newuidmap",
                            "clone", "operation not permitted")):
        return ("unprivileged user namespaces appear to be disabled on this host",
                "enable them then re-run `calma doctor` - "
                "`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` (Ubuntu 24.04+) "
                "or `sudo sysctl -w kernel.unprivileged_userns_clone=1` (Debian/older kernels)")
    tail = ((err or "").strip().splitlines() or ["no diagnostic output"])[-1][:160]
    return ("bwrap exited without running the probe (%s)" % tail,
            "ensure unprivileged user namespaces are enabled, or verify on a host/CI that allows them")


def bwrap_doctor(base):
    """Native-Linux own-code positive-control (no daemon): under bubblewrap, the SAME probe battery as
    the Seatbelt doctor - planted $HOME secret + keychain/root reads, and egress (raw IP, DNS, curl) -
    must ALL fail. The secret is planted on the HOST under $HOME, which is NOT bound into the namespace,
    so a clean pass also proves the allowlist exposes no host state. A probe that never produced a
    LEAKS= line (bwrap could not create the namespaces - e.g. unprivileged userns disabled) is NOT a
    verified tier. Any leak (or no probe) -> host-not-isolated, never a silent bwrap stamp."""
    base = os.path.realpath(base)
    info = {"backend": "bwrap", "bwrap_available": _have_bwrap()}
    if not info["bwrap_available"]:
        info.update(tier="host-not-isolated", secret_read_blocked=False, egress_blocked=False,
                    note="bwrap (bubblewrap) not found on PATH; cannot verify a native Linux tier",
                    fix="install bubblewrap (`apt-get install -y bubblewrap` / `dnf install bubblewrap`), "
                        "then re-run `calma doctor`")
        return info
    secret = os.path.join(os.path.realpath(os.path.expanduser("~")), ".calma_doctor_secret")
    out, err = "", ""
    try:
        with open(secret, "w") as fh:
            fh.write("TOPSECRET-CALMA-DOCTOR")
        _rc, out, err, _killed = _run_bwrap(base, [sys.executable, "-c", _PROBE.format(secret=secret)],
                                            base, timeout=30,
                                            interp_dirs=_bwrap_interp_dirs(sys.executable), writable=False)
    finally:
        if os.path.exists(secret):
            os.unlink(secret)
    produced = "LEAKS=" in (out or "")
    leaks = ""
    for line in (out or "").splitlines():
        if line.startswith("LEAKS="):
            leaks = line[len("LEAKS="):].strip()
    leak_list = [x for x in leaks.split(",") if x]
    secret_blocked = not any(x.startswith("read:") for x in leak_list)
    egress_blocked = not any(x.startswith("egress:") for x in leak_list)
    # `bwrap-verified` ONLY when the probe ran AND leaked nothing. A probe that never produced a LEAKS=
    # line (userns disabled / kernel lockdown -> bwrap aborts) is NOT a verified tier.
    tier = "bwrap-verified" if (produced and not leak_list) else "host-not-isolated"
    fix = None
    if tier == "bwrap-verified":
        note = ("bubblewrap unprivileged user namespaces (no daemon): verified = egress denied + "
                "host-secret unreadable + writes confined to <base>; shares the host kernel, NOT "
                "escape-isolated to microVM strength (Firecracker tier not built yet).")
    elif leak_list:
        # the probe RAN but something got through - a leaking sandbox is a bug, never stamp it verified.
        note = "bwrap ran but the self-test LEAKED (%s); refusing to stamp verified" % ",".join(leak_list)
        fix = "do not trust this tier - a leaking sandbox is a bug; report it with the leak list above"
    else:
        # the probe never produced a LEAKS line: bwrap could not create the namespaces. Say why + the fix.
        why, fix = _bwrap_userns_hint(err)
        note = "bwrap is installed but the self-test could not run: %s" % why
    info.update(tier=tier, secret_read_blocked=secret_blocked, egress_blocked=egress_blocked,
                leaks=leak_list, probe_ran=produced, note=note)
    if tier == "bwrap-verified":
        info["hardening"] = _bwrap_hardening()   # the defense-in-depth layers actually applied
    if fix:
        info["fix"] = fix
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


# ---------------------------------------------------------------------------
# Container backend (WS1): a real Linux-isolated tier for untrusted counterparty code.
# colima/Docker gives us, TODAY: network-egress denial, a read-only overlay FS (only the run
# output subtree is writable), non-root, cap-drop-ALL, the default seccomp filter, and
# pid/memory/cpu limits. It does NOT give kernel-escape isolation - containers share the colima
# VM's Linux kernel, so a kernel/namespace 0-day escapes into that VM. That stronger boundary
# needs a microVM tier (Firecracker), which is NOT built yet. Every stamp below says so honestly.
# The backend is selected behind a tiny (available, doctor, exec) protocol so a microVM backend
# can drop in later without touching the verdict layer (verdict.py already treats tier=="container"
# + container_present as a verified tier).
# ---------------------------------------------------------------------------

# Pinned by digest (a tag can drift). Override with CALMA_DOCKER_IMAGE. --network=none forbids a
# run-time pull, so the image MUST be pre-pulled; _docker_available() fails loud if it is absent.
_DOCKER_IMAGE = os.environ.get(
    "CALMA_DOCKER_IMAGE",
    "python:3.11-slim@sha256:f9fa7f851e38bfb19c9de3afbc4b86ae7176ea7aaf94535c31df5458d5849457")
_DOCKER_RUN_SEQ = [0]


def _docker_bin():
    return shutil.which("docker")


def _docker_available(image=None):
    """(usable, reason). Distinguishes CLI-missing / daemon-down / image-not-present so a required
    container tier can FAIL LOUD with an actionable message - never a silent fallback to the host."""
    image = image or _DOCKER_IMAGE
    docker = _docker_bin()
    if not docker:
        return False, "docker CLI not found on PATH"
    try:
        p = subprocess.run([docker, "info"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return False, "docker daemon not reachable (is colima started? run: colima start) [%s]" % e
    if p.returncode != 0:
        return False, "docker daemon not reachable (is colima started? run: colima start)"
    try:
        pi = subprocess.run([docker, "image", "inspect", image], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return False, "cannot inspect docker image %s [%s]" % (image, e)
    if pi.returncode != 0:
        return False, ("container image %s not present; pre-pull it (network is denied at run time): "
                       "docker pull %s" % (image, image.split("@")[0]))
    return True, ""


def _docker_user():
    """Run as the host uid:gid - non-root, AND it makes writes on the writable runs/ overlay land
    with correct host ownership under colima's mount. root-in-container is never used."""
    try:
        uid, gid = os.getuid(), os.getgid()
    except AttributeError:
        return "65534:65534"            # non-POSIX host fallback: nobody
    return "65534:65534" if uid == 0 else ("%d:%d" % (uid, gid))


def _docker_hardening():
    """Every flag deliberate. The container is disposable, network-denied, read-only-root, non-root,
    capability-stripped, seccomp-filtered, and resource-bounded."""
    return [
        "--rm",                                       # removed on exit - no leftover writable state
        "--network=none",                             # egress DENIED (no DNS/IP/curl) - the core wall
        "--read-only",                                # root FS immutable
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",  # scratch without a writable root; no exec
        "--cap-drop=ALL",                             # no Linux capabilities
        "--security-opt", "no-new-privileges",        # setuid binaries can't escalate
        "--pids-limit=512",                           # fork-bomb containment
        "--memory=2g", "--memory-swap=2g",            # OOM bound (swap==mem disables swap)
        "--cpus=2",                                   # CPU bound
        "--ipc=none",                                 # no shared IPC namespace
        # the default seccomp profile stays ON - we NEVER pass seccomp=unconfined.
    ]


def _docker_env(contract=None):
    """Container env WHITELIST: only PYTHON*/LANG/LC_* + contract env.passthrough survive. Host
    PATH/HOME/TMPDIR are dropped (they are host paths, meaningless in-container), and every parent
    secret is stripped - the env is a second exfil surface, closed by default (same discipline as
    _child_env, minus the host-path vars the container provides itself)."""
    declared = set()
    if isinstance(contract, dict):
        pt = (contract.get("env") or {}).get("passthrough") or []
        if isinstance(pt, list):
            declared = {str(x) for x in pt}
    env = {}
    for k, v in os.environ.items():
        if k.startswith("PYTHON") or k.startswith("LC_") or k == "LANG" or k in declared:
            env[k] = v
    env.update({"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
                "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "TZ": "UTC"})
    return env


def _docker_argv(base, inner_argv, env, image, out_dir, probe=False):
    """Build the full `docker run` argv. base is mounted READ-ONLY at /work; the ONLY writable host
    surface is the run-output subtree (out_dir -> /work/runs) so outputs reach the host for recompute
    while the engagement source (incl. .calma) can never be tampered with. The probe omits the
    writable mount (it proves the floor: even with nothing writable, egress + host-secret read fail)."""
    name = "calma_%d_%d" % (os.getpid(), _docker_next())
    # `_docker_bin()` is None when docker isn't on PATH (e.g. a docker-less CI runner); the real
    # run path gates on `_docker_available()` and fails loud, but the argv builder itself must stay
    # a clean list of strings so structural/pure tests (and `" ".join`) never see a None.
    argv = [_docker_bin() or "docker", "run", "--name", name] + _docker_hardening()
    argv += ["--user", _docker_user(), "-w", "/work", "-v", "%s:/work:ro" % base]
    if not probe and out_dir:
        argv += ["-v", "%s:/work/runs:rw" % out_dir]
    for k, v in (env or {}).items():
        argv += ["-e", "%s=%s" % (k, v)]
    argv += [image] + list(inner_argv)
    return name, argv


def _docker_next():
    _DOCKER_RUN_SEQ[0] += 1
    return _DOCKER_RUN_SEQ[0]


def _docker_kill(name):
    docker = _docker_bin()
    if not docker:
        return
    for sub in (["kill", name], ["rm", "-f", name]):
        try:
            subprocess.run([docker] + sub, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass


def _run_docker(name, argv, cwd, timeout):
    """Run the container in its own process group; on timeout kill + remove it (no leftover). The
    `--rm` flag removes it after a normal exit; the finally is belt-and-suspenders cleanup."""
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
        try:
            out, err = p.communicate(timeout=timeout)
            return p.returncode, out, err, False
        except subprocess.TimeoutExpired:
            _docker_kill(name)
            p.communicate()
            return -9, "", "timeout", True
    finally:
        _docker_kill(name)


def docker_doctor(base, image=None):
    """In-container positive-control: under the hardened, network-denied container, a BATTERY of
    egress attempts (raw IP, DNS hostname, curl subprocess) AND host-secret reads must ALL fail. The
    secret is planted on the HOST - its path is unreachable because nothing outside `base` is mounted -
    so a clean pass also proves no stray mount exposes host state. Any leak (or a probe that never ran)
    -> host-not-isolated, never a silent container stamp."""
    image = image or _DOCKER_IMAGE
    base = os.path.realpath(base)
    avail, why = _docker_available(image)
    info = {"backend": "docker", "image": image, "docker_available": avail}
    if not avail:
        info.update(tier="host-not-isolated", secret_read_blocked=False, egress_blocked=False,
                    note=why)
        return info
    secret = os.path.join(os.path.realpath(os.path.expanduser("~")), ".calma_doctor_secret")
    out = ""
    try:
        with open(secret, "w") as fh:
            fh.write("TOPSECRET-CALMA-DOCTOR")
        name, argv = _docker_argv(base, ["python", "-c", _PROBE.format(secret=secret)],
                                  {"PYTHONHASHSEED": "0"}, image, None, probe=True)
        _rc, out, _err, _killed = _run_docker(name, argv, base, 60)
    finally:
        if os.path.exists(secret):
            os.unlink(secret)
    produced = "LEAKS=" in (out or "")
    leaks = ""
    for line in (out or "").splitlines():
        if line.startswith("LEAKS="):
            leaks = line[len("LEAKS="):].strip()
    leak_list = [x for x in leaks.split(",") if x]
    secret_blocked = not any(x.startswith("read:") for x in leak_list)
    egress_blocked = not any(x.startswith("egress:") for x in leak_list)
    # tier is `container` ONLY when the probe ran AND leaked nothing. A probe that never produced a
    # LEAKS line (image/python failed to start) is NOT a verified container.
    tier = "container" if (produced and not leak_list) else "host-not-isolated"
    info.update(tier=tier, secret_read_blocked=secret_blocked, egress_blocked=egress_blocked,
                leaks=leak_list, probe_ran=produced,
                note=("container backend (colima/Linux): verified = egress denied + no host-secret "
                      "read under namespace isolation; shares the colima VM kernel; NOT escape-"
                      "isolated to microVM strength (Firecracker tier not built yet)."))
    return info


def native_doctor(base=None):
    """The native host own-code doctor for THIS OS: bubblewrap on Linux, Seatbelt on macOS. Callers
    that just want 'is this host's own-code tier verified?' (the `calma doctor` CLI, the Stop hook)
    use this instead of hard-coding the macOS path - so Linux is no longer pinned to host-not-isolated
    when a working bwrap tier is present."""
    base = base or os.getcwd()
    return bwrap_doctor(base) if sys.platform.startswith("linux") else doctor(base)


def _run_unwrapped(argv, cwd, timeout=120, env=None):
    """Run argv directly on the host (NO isolation) in its own process group. Used ONLY when the
    achieved tier is host-not-isolated; the stamps upstream say so - this never claims isolation."""
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True, env=env or os.environ.copy())
    except OSError as e:
        return -1, "", "exec failed: %s" % e, False
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


def _exec_native(isolation_tier, base, argv, cwd, timeout=120, env=None, interp_paths=()):
    """Run argv under the achieved host own-code tier. `seatbelt-verified` -> the sandbox-exec profile;
    `bwrap-verified` -> bubblewrap; anything else (host-not-isolated) -> unwrapped on the host (the
    honest CAVEAT path - the run still happens, the stamp upstream says NOT isolated). The doctor that
    set `isolation_tier` ran the probe under this SAME wrapper, so the self-test proves exactly what the
    run does. `interp_paths` re-allows a (possibly $HOME-resident) restored/host interpreter - the
    Seatbelt profile re-allows its depot, bwrap re-binds its prefix; both deny everything else."""
    if isolation_tier == "seatbelt-verified":
        prof = _profile(os.path.realpath(base), _interp_reads(*interp_paths))
        return _run_sandboxed(prof, argv, cwd, timeout, env)
    if isolation_tier == "bwrap-verified":
        return _run_bwrap(base, argv, cwd, timeout, env,
                          interp_dirs=_bwrap_interp_dirs(*interp_paths), writable=True)
    return _run_unwrapped(argv, cwd, timeout, env)


def _select_backend(isolation, trust):
    """Backend selection. Explicit `isolation` wins (and FAILS LOUD if unavailable - never falls back).
    Otherwise untrusted third-party code auto-escalates to the container tier; own code stays on the
    native HOST own-code tier for THIS OS - macOS Seatbelt, Linux bubblewrap (no daemon either way),
    byte-identical to the prior default on macOS."""
    if isolation in ("seatbelt", "bwrap", "docker", "firecracker"):
        return isolation
    if trust == "untrusted-third-party":
        return "docker"
    return "bwrap" if sys.platform.startswith("linux") else "seatbelt"


def _run_docker_backend(contract, base, entry, entry_path, trust, timeout, image=None):
    """The container tier of run(). Same return-dict contract as the Seatbelt path; only the
    tier-derived stamps differ (isolation_tier='container', hermeticity='container-readonly-overlay')."""
    image = image or _DOCKER_IMAGE
    avail, why = _docker_available(image)
    if not avail:
        # FAIL LOUD - an explicitly-requested or required container tier never degrades to the host.
        return {"phase": "refused", "exit_code": 3, "isolation_tier": "host-not-isolated",
                "container_present": False, "killed": False,
                "reason": "container isolation requested but unavailable: %s" % why}
    # in-container interpreter: WS1 covers python + shell; other languages stamp honestly and refuse
    # (the image has no R/julia/node/cc toolchain, and --network=none forbids installing one).
    ext = os.path.splitext(entry_path)[1].lower()
    rel = os.path.relpath(entry_path, base)
    inner = {".py": ["python", "/work/" + rel], ".sh": ["sh", "/work/" + rel]}.get(ext)
    lang = {".py": "python", ".sh": "shell"}.get(ext, ext.lstrip("."))
    if inner is None:
        return {"phase": "refused", "exit_code": 3, "isolation_tier": "container",
                "container_present": True, "killed": False, "language": lang,
                "reason": "the container backend (WS1) runs python/shell only; .%s needs the "
                          "seatbelt tier (own-code) or the microVM tier (untrusted)" % lang}
    doc = docker_doctor(base, image)
    isolation_tier = doc["tier"]
    # a leaking container is NOT a verified container: untrusted code is refused outright.
    if trust == "untrusted-third-party" and isolation_tier != "container":
        return {"phase": "refused", "exit_code": 3, "isolation_tier": isolation_tier,
                "container_present": False, "killed": False, "doctor": doc,
                "reason": "untrusted third-party code requires a VERIFIED container tier; the "
                          "in-container self-test did not hold (%s)"
                          % (",".join(doc.get("leaks") or []) or "probe did not run")}
    if lang == "python":
        det_mode, det_note = _detect_determinism(entry_path, base)
    else:
        det_mode, det_note = "uncontrolled", "shell: bit-determinism not statically provable"
    out_dir = os.path.join(base, "runs")
    os.makedirs(out_dir, exist_ok=True)
    env = _docker_env(contract)
    name, argv = _docker_argv(base, inner, env, image, out_dir, probe=False)
    rc, out, err, killed = _run_docker(name, argv, base, timeout)
    tier_verified = isolation_tier == "container"
    exit_code = 4 if killed else (0 if rc == 0 else 1)
    return {
        "phase": "run", "entrypoint": entry, "exit_code": exit_code, "killed": killed,
        "language": lang, "run_exit_status": rc,
        "isolation_tier": isolation_tier, "container_present": tier_verified,
        "interpreter": "container:%s" % image.split("@")[0],
        "determinism_mode": det_mode, "determinism_note": det_note,
        "install_network": "off", "run_network": "off",
        "hermeticity": "container-readonly-overlay" if tier_verified else "unverified",
        "stdout_tail": (out or "")[-500:], "stderr_tail": (err or "")[-500:],
        "doctor": doc,
    }


def run(contract_path, base=None, timeout=120, trust_override=None, isolation=None):
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
    # backend selection (WS1): explicit --isolation wins (fail loud, no fallback); else untrusted
    # third-party code auto-escalates to the container tier; else the host Seatbelt tier (default).
    backend = _select_backend(isolation, trust)
    if backend == "firecracker":
        return {"phase": "refused", "exit_code": 3, "isolation_tier": "none",
                "container_present": False, "killed": False,
                "reason": "the firecracker/microVM backend is not built yet (funded tier); "
                          "use --isolation docker (container) or seatbelt (host)"}
    if backend == "docker":
        return _run_docker_backend(contract, base, entry, entry_path, trust, timeout)
    # native host own-code tier: bubblewrap on Linux, Seatbelt on macOS. The SAME probe battery gates
    # both, and the run will use the SAME wrapper the doctor just proved (_exec_native).
    doc = bwrap_doctor(base) if backend == "bwrap" else doctor(base)
    isolation_tier = doc["tier"]
    # FAIL LOUD: an EXPLICIT --isolation seatbelt|bwrap that did not verify never degrades to an
    # unisolated host run (parity with the container tier's missing-image refusal). The AUTO path
    # (isolation is None) instead proceeds and stamps host-not-isolated honestly below - that is
    # today's behavior on a host without the tier, never a silent verified claim.
    if isolation in ("seatbelt", "bwrap") and isolation_tier not in _VERIFIED_TIERS:
        reason = "%s isolation requested but unavailable: %s" % (backend, doc.get("note", "self-test did not verify"))
        if doc.get("fix"):
            reason += " - fix: %s" % doc["fix"]
        return {"phase": "refused", "exit_code": 3, "isolation_tier": isolation_tier,
                "container_present": False, "killed": False, "doctor": doc, "reason": reason}

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
    # the interpreter the run will exec (run_argv[0]) and a restored venv python may live under $HOME
    # (uv/pyenv/conda); _exec_native re-allows exactly those to the achieved tier (Seatbelt depot /
    # bwrap prefix) and denies everything else.
    _interp_paths = (run_argv[0], venv_py)
    env = _child_env(contract)
    # determinism hardening for the re-execution: pinned hash seed (stable set/dict iteration order),
    # no bytecode writes into the target, pinned locale. Free reproducibility, no behavior loss.
    env.update({"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
                "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "TZ": "UTC"})
    # the network/hermeticity stamps are DERIVED from the achieved tier, never asserted: on a host
    # with no verified sandbox (e.g. Linux without sandbox-exec) the truth is "not blocked".
    tier_verified = isolation_tier in _VERIFIED_TIERS
    net_stamp = "off" if tier_verified else "host-default (NOT blocked - no verified sandbox on this host)"
    herm_stamp = "vendored-snapshot" if tier_verified else "unverified"
    # compile step (C/C++/Rust) under the same verified tier; failure -> run-gate fail
    if compile_cmd:
        crc, cout, cerr, ckill = _exec_native(isolation_tier, base, compile_cmd, base, timeout, env,
                                              _interp_paths)
        if ckill or crc != 0:
            return {"phase": "run", "entrypoint": entry, "exit_code": 1, "killed": ckill, "language": lang,
                    "isolation_tier": isolation_tier, "determinism_mode": det_mode,
                    "container_present": tier_verified,
                    "install_network": net_stamp, "run_network": net_stamp,
                    "stderr_tail": ("compile failed: " + (cerr or ""))[-500:], "doctor": doc}
    rc, out, err, killed = _exec_native(isolation_tier, base, run_argv, base, timeout, env, _interp_paths)
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
    ap.add_argument("--isolation", choices=["auto", "seatbelt", "bwrap", "docker", "firecracker"],
                    default="auto")
    a = ap.parse_args()
    iso = None if a.isolation == "auto" else a.isolation
    if a.cmd == "doctor":
        _b = a.base or os.getcwd()
        if iso == "docker":
            res = docker_doctor(_b)
        elif iso == "bwrap":
            res = bwrap_doctor(_b)
        elif iso == "seatbelt":
            res = doctor(_b)
        else:  # auto: report THIS OS's native own-code tier (bwrap on Linux, Seatbelt on macOS)
            res = native_doctor(_b)
    else:
        if not a.contract:
            print("run needs --contract", file=sys.stderr)
            return 2
        res = run(a.contract, a.base, isolation=iso)
    text = json.dumps(res, indent=2)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return res.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main())
