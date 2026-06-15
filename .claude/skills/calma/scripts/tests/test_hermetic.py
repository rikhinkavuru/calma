"""Tests for run_hermetic.py: verified isolation (doctor), sandboxed re-emit, egress denial, and the
untrusted-third-party refusal. On a host without sandbox-exec these degrade to host-not-isolated (still
asserted honestly). Pure stdlib. Run: python3 test_hermetic.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import run_hermetic as H  # noqa: E402

BTC = os.path.join(SCR, "..", "assets", "btc")
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


doc = H.doctor(BTC)
if doc["sandbox_exec"]:
    truth(doc["secret_read_blocked"], "doctor: planted secret-read is BLOCKED")
    truth(doc["egress_blocked"], "doctor: network egress is BLOCKED")
    truth(doc["tier"] == "seatbelt-verified", "doctor: tier seatbelt-verified")
else:
    truth(doc["tier"] == "host-not-isolated", "no sandbox-exec -> host-not-isolated (honest)")

# run the BTC entrypoint network-off -> re-emits artifacts, exit 0
res = H.run(os.path.join(BTC, "verify.yaml"), base=BTC)
truth(res["exit_code"] == 0, "BTC entrypoint runs clean under the tier (exit %s)" % res["exit_code"])
truth(res["determinism_mode"] == "controlled-to-bit", "pure-stdlib entrypoint -> controlled-to-bit")
truth(os.path.exists(os.path.join(BTC, "runs", "oos", "returns.csv")), "raw artifact re-emitted")
truth("claimed_in_sample_return" in res["stdout_tail"], "entrypoint output captured")

# egress denial: an entrypoint that tries to reach the network FAILS under the tier
if doc["sandbox_exec"]:
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "fetch.py"), "w") as fh:
        fh.write("import socket\nsocket.create_connection(('1.1.1.1',80),timeout=4)\nprint('REACHED')\n")
    with open(os.path.join(d, "verify.yaml"), "w") as fh:
        json.dump({"run": {"entrypoint": "fetch.py", "network": "off"},
                   "env": {"trust": "own-code"}, "artifacts": [], "metrics": []}, fh)
    r2 = H.run(os.path.join(d, "verify.yaml"), base=d, timeout=30)
    truth(r2["exit_code"] in (1, 4) and "REACHED" not in r2.get("stdout_tail", ""),
          "network-fetch entrypoint is blocked by the egress boundary (exit %s)" % r2["exit_code"])

# P1-1: the code under test must NOT be able to write calma's own state (<base>/.calma) -
# the deny comes AFTER the base-wide write allow, and Seatbelt is last-match-wins. Real probe.
if doc["sandbox_exec"]:
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, ".calma"))
    with open(os.path.join(d, ".calma", "cache.json"), "w") as fh:
        fh.write('{"planted": false}')
    with open(os.path.join(d, "evil.py"), "w") as fh:
        fh.write("import os\n"
                 "try:\n"
                 "    open('.calma/cache.json', 'w').write('{\"planted\": true}')\n"
                 "    print('CALMA_WRITTEN')\n"
                 "except Exception:\n"
                 "    print('CALMA_DENIED')\n"
                 "try:\n"
                 "    os.makedirs('.calma/run', exist_ok=True)\n"
                 "    open('.calma/run/ledger.json', 'w').write('{}')\n"
                 "    print('LEDGER_PLANTED')\n"
                 "except Exception:\n"
                 "    print('LEDGER_DENIED')\n"
                 "open('ok.txt', 'w').write('ok')\n"
                 "print('BASE_WRITABLE')\n")
    with open(os.path.join(d, "verify.yaml"), "w") as fh:
        json.dump({"run": {"entrypoint": "evil.py", "network": "off"},
                   "env": {"trust": "own-code"}, "artifacts": [], "metrics": []}, fh)
    r4 = H.run(os.path.join(d, "verify.yaml"), base=d, timeout=30)
    out4 = r4.get("stdout_tail", "")
    truth("CALMA_DENIED" in out4 and "CALMA_WRITTEN" not in out4,
          "sandboxed code cannot overwrite .calma/cache.json (last-match-wins deny holds)")
    truth("LEDGER_DENIED" in out4 and "LEDGER_PLANTED" not in out4,
          "sandboxed code cannot plant a ledger under .calma/")
    truth("BASE_WRITABLE" in out4 and os.path.exists(os.path.join(d, "ok.txt")),
          "the base dir itself stays writable (only .calma is denied)")
    truth(open(os.path.join(d, ".calma", "cache.json")).read() == '{"planted": false}',
          "pre-existing cache.json bytes are untouched after the sandboxed run")

# P2: env whitelist - parent secrets never reach the child; contract passthrough does
de = tempfile.mkdtemp()
with open(os.path.join(de, "envprobe.py"), "w") as fh:
    fh.write("import os\n"
             "print('SECRET=' + repr(os.environ.get('CALMA_TEST_SECRET')))\n"
             "print('DECLARED=' + repr(os.environ.get('CALMA_TEST_DECLARED')))\n"
             "print('HAS_PATH=' + str(bool(os.environ.get('PATH'))))\n")
with open(os.path.join(de, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "envprobe.py", "network": "off"},
               "env": {"trust": "own-code", "passthrough": ["CALMA_TEST_DECLARED"]},
               "artifacts": [], "metrics": []}, fh)
os.environ["CALMA_TEST_SECRET"] = "leak-me"
os.environ["CALMA_TEST_DECLARED"] = "declared-ok"
try:
    r5 = H.run(os.path.join(de, "verify.yaml"), base=de, timeout=30)
finally:
    del os.environ["CALMA_TEST_SECRET"]
    del os.environ["CALMA_TEST_DECLARED"]
out5 = r5.get("stdout_tail", "")
truth("SECRET=None" in out5 and "leak-me" not in out5,
      "undeclared parent env vars are stripped from the child (no secret exfil surface)")
truth("DECLARED='declared-ok'" in out5, "contract env.passthrough vars ARE forwarded")
truth("HAS_PATH=True" in out5, "the whitelist keeps PATH (toolchains still resolve)")

# untrusted third-party code: with a live container tier it RUNS in the container (auto-escalation);
# with NO container tier it is REFUSED (exit 3). Either branch must be honest - never host-executed.
# NOTE: tempdirs under /tmp are not mounted into the colima VM, so the container run needs a base
# under $HOME; we put it under the repo (which is mounted).
dk_ok, dk_why = H._docker_available()
du = os.path.join(SCR, "..", "assets", ".hermtest_untrusted")
os.makedirs(du, exist_ok=True)
with open(os.path.join(du, "x.py"), "w") as fh:
    fh.write("print('hi')\n")
with open(os.path.join(du, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "x.py"}, "env": {"trust": "untrusted-third-party"},
               "artifacts": [], "metrics": []}, fh)
r3 = H.run(os.path.join(du, "verify.yaml"), base=du, timeout=120)
if dk_ok:
    truth(r3.get("phase") == "run" and r3.get("isolation_tier") == "container"
          and r3.get("exit_code") == 0,
          "untrusted + live container -> runs in container (exit %s, tier %s)"
          % (r3.get("exit_code"), r3.get("isolation_tier")))
    truth("hi" in (r3.get("stdout_tail") or ""), "container captured the entrypoint output")
else:
    truth(r3["exit_code"] == 3 and r3["phase"] == "refused",
          "untrusted + no container -> refused exit 3")

# isolation profile: metadata-only ancestor reads (lets node etc. realpath-resolve the entrypoint
# without opening directory listing / content reads under /Users). Structural guards so a future edit
# can't silently regress either side.
prof = H._profile(BTC)
ancs = H._ancestors(BTC)
truth("(allow file-read-metadata" in prof, "profile grants file-read-metadata on ancestors")
truth(all(('(literal "%s")' % a) in prof for a in ancs), "every base ancestor is a metadata literal")
truth("(deny file-read*\n  (subpath \"/Users\")" in prof, "directory listing / content reads under /Users still denied")
_rbtc = os.path.realpath(BTC)
truth(os.path.dirname(_rbtc) in ancs and "/" in ancs and _rbtc not in ancs,
      "_ancestors spans from / down to the parent (excludes the base itself)")

# WS3: a RESTORED venv's base interpreter (uv/pyenv/conda) lives under $HOME; the profile re-allows
# the interpreter DEPOT roots (broad but safe - never secret dirs) so the venv python can be exec'd.
_home = os.path.realpath(os.path.expanduser("~"))
truth(('(subpath "%s/.local/share/uv")' % _home) in prof, "profile re-allows the uv interpreter depot")
truth(('(subpath "%s/.pyenv")' % _home) in prof, "profile re-allows the pyenv depot")
truth(('(subpath "%s/.ssh")' % _home) not in prof and ('(subpath "%s/.aws")' % _home) not in prof,
      "profile never re-allows ~/.ssh or ~/.aws (secrets stay denied)")
# _symlink_chain_dirs follows a real symlink chain (the mechanism behind restored-venv exec)
_lkdir = tempfile.mkdtemp()
os.makedirs(os.path.join(_lkdir, "real", "bin"))
open(os.path.join(_lkdir, "real", "bin", "python"), "w").close()
os.symlink(os.path.join(_lkdir, "real", "bin", "python"), os.path.join(_lkdir, "link"))
_chain = H._symlink_chain_dirs(os.path.join(_lkdir, "link"))
truth(os.path.join(_lkdir, "real", "bin") in _chain and _lkdir in _chain,
      "_symlink_chain_dirs collects every dir on the resolution chain")
import shutil as _sh2
_sh2.rmtree(_lkdir, ignore_errors=True)

# on a sandbox host, the metadata grant must NOT open directory listing or secret reads (the boundary)
if doc["sandbox_exec"]:
    sec = os.path.join(os.path.realpath(os.path.expanduser("~")), ".calma_hermtest_secret")
    open(sec, "w").write("TOP")
    probe = ("import os,json;r={};\n"
             "try:\n os.lstat('/Users');r['lstat']='ok'\nexcept Exception:\n r['lstat']='denied'\n"
             "try:\n os.listdir('/Users');r['list']='LEAK'\nexcept Exception:\n r['list']='denied'\n"
             "try:\n open(%r).read();r['read']='LEAK'\nexcept Exception:\n r['read']='denied'\n"
             "print(json.dumps(r))" % sec)
    rc, out, err, _ = H._run_sandboxed(H._profile(BTC), [sys.executable, "-c", probe], BTC, 30)
    os.unlink(sec)
    pr = json.loads([ln for ln in out.splitlines() if ln.startswith("{")][0]) if out.strip() else {}
    truth(pr.get("lstat") == "ok", "ancestor metadata (lstat) is allowed under the profile")
    truth(pr.get("list") == "denied", "directory listing under /Users stays denied (no enumeration)")
    truth(pr.get("read") == "denied", "secret-content read under /Users stays denied")

# venv-aware run: a restored project venv is used for the run interpreter when present
truth(H._venv_python(du) is None, "no .calma_venv -> host interpreter")
vbin = os.path.join(du, ".calma_venv", "bin")
os.makedirs(vbin, exist_ok=True)
open(os.path.join(vbin, "python"), "w").close()
truth(H._venv_python(du) == os.path.join(vbin, "python"), "restored .calma_venv -> its interpreter is used")

import shutil as _sh
_sh.rmtree(du, ignore_errors=True)

# === WS1: container backend ============================================================
# (a) backend selection is pure - testable with no docker.
_native = "bwrap" if sys.platform.startswith("linux") else "seatbelt"
truth(H._select_backend(None, "own-code") == _native,
      "auto + own-code -> native host tier (bwrap on linux, seatbelt on mac)")
truth(H._select_backend(None, "untrusted-third-party") == "docker", "auto + untrusted -> docker")
truth(H._select_backend("seatbelt", "untrusted-third-party") == "seatbelt", "explicit seatbelt wins")
truth(H._select_backend("bwrap", "own-code") == "bwrap", "explicit bwrap wins")
truth(H._select_backend("bwrap", "untrusted-third-party") == "bwrap", "explicit bwrap wins over auto-escalation")
truth(H._select_backend("docker", "own-code") == "docker", "explicit docker wins")
truth(H._select_backend("firecracker", "own-code") == "firecracker", "explicit firecracker wins")

# (b) the hardening flag-set is structurally locked (a future edit can't silently drop a wall).
_hard = H._docker_hardening()
for _flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--pids-limit=512",
              "--security-opt", "no-new-privileges", "--rm", "--ipc=none"):
    truth(_flag in _hard, "docker hardening includes %s" % _flag)
truth("65534:65534" == H._docker_user() or ":" in H._docker_user(), "docker user is non-root uid:gid")
truth(H._docker_user() != "0:0", "docker never runs as root")
# the writable overlay is ONLY runs/; the probe argv has no writable mount at all.
_pn, _pargv = H._docker_argv("/X", ["python", "-c", "x"], {}, "img", None, probe=True)
truth(":/work:ro" in " ".join(_pargv) and ":/work/runs:rw" not in " ".join(_pargv),
      "probe argv mounts base read-only and has NO writable overlay")
_rn, _rargv = H._docker_argv("/X", ["python", "/work/m.py"], {}, "img", "/X/runs", probe=False)
truth("/X/runs:/work/runs:rw" in " ".join(_rargv), "run argv mounts runs/ as the only writable surface")

# (c) FAIL LOUD: an explicitly-required container tier with a missing image refuses (exit 3),
# never falls back to the host. Works whether or not the daemon is up.
fl = os.path.join(SCR, "..", "assets", ".hermtest_faill")
os.makedirs(fl, exist_ok=True)
open(os.path.join(fl, "m.py"), "w").write("print('x')\n")
json.dump({"run": {"entrypoint": "m.py"}, "env": {"trust": "own-code"}, "artifacts": [], "metrics": []},
          open(os.path.join(fl, "verify.yaml"), "w"))
_img_save = H._DOCKER_IMAGE
H._DOCKER_IMAGE = "calma/definitely-not-present:nope"
rfl = H.run(os.path.join(fl, "verify.yaml"), base=fl, timeout=60, isolation="docker")
H._DOCKER_IMAGE = _img_save
truth(rfl["exit_code"] == 3 and rfl["phase"] == "refused", "missing image -> refused exit 3 (fail loud)")
truth("host" not in rfl.get("isolation_tier", "") or rfl["isolation_tier"] == "host-not-isolated",
      "fail-loud never stamps a host-executed tier")
truth(rfl.get("container_present") is False, "fail-loud: container_present is False")
# firecracker stub fails loud too
rfc = H.run(os.path.join(fl, "verify.yaml"), base=fl, timeout=60, isolation="firecracker")
truth(rfc["exit_code"] == 3 and "not built" in rfc.get("reason", ""), "firecracker stub -> refused, 'not built'")
_sh.rmtree(fl, ignore_errors=True)

# (d) MARQUEE: a deliberately hostile repo is fully contained (egress, host-secret read, writes
# outside runs/, all denied), the run is stamped `container`, and no container is left behind.
# Skipped (honestly) when no container tier is live; the dispatch + fail-loud walls above still run.
if dk_ok:
    cdoc = H.docker_doctor(SCR)  # SCR is under $HOME -> colima-mounted
    truth(cdoc["tier"] == "container", "docker doctor: tier container")
    truth(cdoc["egress_blocked"] and cdoc["secret_read_blocked"], "docker doctor: egress + secret-read both blocked")

    hostile = os.path.join(SCR, "..", "assets", ".hermtest_hostile")
    _sh.rmtree(hostile, ignore_errors=True)
    os.makedirs(os.path.join(hostile, ".calma"), exist_ok=True)
    open(os.path.join(hostile, ".calma", "cache.json"), "w").write('{"planted": false}')
    host_secret = os.path.join(os.path.realpath(os.path.expanduser("~")), ".calma_hostile_secret")
    open(host_secret, "w").write("HOST-SECRET")
    _evil = (
        "import socket, subprocess, os\n"
        "res = []\n"
        "for tag, h in [('ip', ('1.1.1.1', 80)), ('dns', ('example.com', 80))]:\n"
        "    try: socket.create_connection(h, timeout=3); res.append('EGRESS_' + tag)\n"
        "    except Exception: pass\n"
        "try:\n"
        "    r = subprocess.run(['curl', '-s', '-m', '3', 'http://1.1.1.1'], capture_output=True)\n"
        "    if r.returncode == 0 and r.stdout: res.append('EGRESS_curl')\n"
        "except Exception: pass\n"
        "for p in [%r, '/work/.calma_hostile_secret', '/work/../.calma_hostile_secret']:\n"
        "    try: open(p).read(); res.append('READ_SECRET')\n"
        "    except Exception: pass\n"
        "try: open('/work/evil.txt', 'w').write('x'); res.append('WROTE_BASE')\n"
        "except Exception: pass\n"
        "try: open('/work/.calma/cache.json', 'w').write('{\"planted\": true}'); res.append('WROTE_CALMA')\n"
        "except Exception: pass\n"
        "try: os.makedirs('/work/runs', exist_ok=True); open('/work/runs/out.csv', 'w').write('ok'); res.append('RUNS_OK')\n"
        "except Exception: pass\n"
        "print('HOSTILE=' + (','.join(res) if res else 'CONTAINED'))\n"
    ) % host_secret
    open(os.path.join(hostile, "evil.py"), "w").write(_evil)
    json.dump({"run": {"entrypoint": "evil.py"}, "env": {"trust": "untrusted-third-party"},
               "artifacts": [], "metrics": []}, open(os.path.join(hostile, "verify.yaml"), "w"))
    rh = H.run(os.path.join(hostile, "verify.yaml"), base=hostile, timeout=120)
    try:
        os.unlink(host_secret)
    except OSError:
        pass
    out_h = rh.get("stdout_tail", "")
    truth(rh.get("isolation_tier") == "container" and rh.get("exit_code") == 0,
          "hostile repo runs in the container (tier %s, exit %s)" % (rh.get("isolation_tier"), rh.get("exit_code")))
    truth("EGRESS" not in out_h, "hostile: ALL network egress blocked (ip/dns/curl)")
    truth("READ_SECRET" not in out_h, "hostile: planted host secret is UNREADABLE")
    truth("WROTE_BASE" not in out_h, "hostile: cannot write the read-only engagement base")
    truth("WROTE_CALMA" not in out_h, "hostile: cannot write/plant .calma verdict state")
    truth(open(os.path.join(hostile, ".calma", "cache.json")).read() == '{"planted": false}',
          "hostile: pre-existing .calma bytes untouched")
    truth("RUNS_OK" in out_h, "hostile: only the runs/ overlay is writable (outputs land for recompute)")
    leftover = subprocess.run(["docker", "ps", "-a", "--filter", "name=calma_", "--format", "{{.Names}}"],
                              capture_output=True, text=True)
    truth("calma_" not in leftover.stdout, "hostile: no container left behind (--rm + cleanup)")
    _sh.rmtree(hostile, ignore_errors=True)

# === Native Linux own-code tier (bubblewrap) ===========================================
# Structural locks run EVERYWHERE (incl. macOS where bwrap is absent); the live blocks below skip
# honestly off a verified bwrap host - same discipline as the `if dk_ok:` container blocks.
# (a) the _bwrap_argv wall-set is structurally locked - a future edit can't silently drop a wall.
_bargv = H._bwrap_argv("/X/base", ["python", "-c", "x"], interp_dirs=["/opt/py/bin"], writable=True)
_bj = " ".join(_bargv)
for _flag in ("--unshare-net", "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
              "--die-with-parent", "--new-session", "--proc", "--dev", "--tmpfs"):
    truth(_flag in _bargv, "bwrap argv includes %s" % _flag)
truth("--ro-bind /usr /usr" in _bj, "bwrap binds /usr read-only")
truth("--bind /X/base /X/base" in _bj, "bwrap bind-mounts the base read-write")
truth("--ro-bind-try /X/base/.calma /X/base/.calma" in _bj, "bwrap re-binds <base>/.calma read-only")
truth(_bj.index("--bind /X/base /X/base") < _bj.index("/X/base/.calma"),
      ".calma ro-bind comes AFTER the base bind (bwrap is last-mount-wins -> write-deny holds)")
truth("--ro-bind-try /opt/py/bin /opt/py/bin" in _bj, "bwrap re-binds an out-of-root interpreter dir")
# the boundary: $HOME / home / root are NEVER a bind target (allowlist-by-construction)
_bw_home = os.path.realpath(os.path.expanduser("~"))
truth(("--bind %s %s" % (_bw_home, _bw_home)) not in _bj
      and ("--ro-bind %s %s" % (_bw_home, _bw_home)) not in _bj
      and ("--ro-bind-try %s %s" % (_bw_home, _bw_home)) not in _bj,
      "bwrap never binds $HOME (secrets stay outside the namespace)")
truth("/root" not in _bj, "bwrap never binds /root")
# probe variant: base mounted READ-ONLY (whole base ro -> no .calma re-bind needed)
_pbargv = H._bwrap_argv("/X/base", ["python", "-c", "x"], writable=False)
_pbj = " ".join(_pbargv)
truth("--ro-bind /X/base /X/base" in _pbj, "bwrap probe mounts the base read-only")
truth("/X/base/.calma" not in _pbj, "bwrap probe needs no .calma re-bind (base is already read-only)")

# (b) _bwrap_interp_dirs skips system-root-covered paths, keeps $HOME-resident interpreters
truth(H._bwrap_interp_dirs("/usr/bin/python3") == [],
      "interp dirs under /usr are already covered -> not re-bound")
_iD = H._bwrap_interp_dirs(os.path.join(_bw_home, ".pyenv", "versions", "3.12", "bin", "python"))
truth(any(d.startswith(_bw_home) for d in _iD),
      "a $HOME-resident interpreter prefix IS bound (else execvp ENOENT in the namespace)")

# (c) bwrap_doctor is honest about availability (runs everywhere; macOS has no bwrap)
_bdoc = H.bwrap_doctor(BTC)
truth(_bdoc["backend"] == "bwrap", "bwrap_doctor reports its backend")
if H._have_bwrap():
    truth(_bdoc["tier"] in ("bwrap-verified", "host-not-isolated"), "bwrap doctor returns a real tier")
    if _bdoc["tier"] == "bwrap-verified":
        truth(_bdoc["secret_read_blocked"] and _bdoc["egress_blocked"],
              "bwrap verified -> planted-secret read AND egress both blocked")
        truth(_bdoc.get("probe_ran") is True, "bwrap verified -> the probe actually ran (not a false pass)")
        truth("fix" not in _bdoc, "a verified tier carries NO fix-line (nothing to fix)")
    else:
        truth(bool(_bdoc.get("fix")), "host-not-isolated (bwrap present) -> doctor emits an actionable fix-line")
else:
    truth(_bdoc["tier"] == "host-not-isolated", "no bwrap -> host-not-isolated (honest)")
    truth(_bdoc["bwrap_available"] is False, "bwrap_available is False when bwrap is absent")
    truth("bubblewrap" in (_bdoc.get("fix") or ""), "bwrap absent -> doctor tells you to install bubblewrap")

# (c1) _bwrap_userns_hint maps the dominant failure (userns disabled) to the exact sysctl fix
_why, _fx = H._bwrap_userns_hint("bwrap: No permissions to create new namespace, likely because the kernel...")
truth("user namespaces" in _why and "sysctl" in _fx and "apparmor_restrict_unprivileged_userns" in _fx,
      "_bwrap_userns_hint: namespace error -> 'enable userns' cause + the exact sysctl fix")

# (c2) FAIL-LOUD (acceptance b): an EXPLICIT --isolation bwrap that does not verify refuses (exit 3)
# and never silently runs unisolated on the host. Force bwrap "absent" so this is deterministic on
# EVERY host (incl. a real bwrap CI runner where the auto path would otherwise verify).
_flb = tempfile.mkdtemp()
open(os.path.join(_flb, "m.py"), "w").write("print('x')\n")
json.dump({"run": {"entrypoint": "m.py"}, "env": {"trust": "own-code"}, "artifacts": [], "metrics": []},
          open(os.path.join(_flb, "verify.yaml"), "w"))
_save_hb = H._have_bwrap
H._have_bwrap = lambda: False
try:
    _rbf = H.run(os.path.join(_flb, "verify.yaml"), base=_flb, timeout=30, isolation="bwrap")
finally:
    H._have_bwrap = _save_hb
truth(_rbf["exit_code"] == 3 and _rbf["phase"] == "refused",
      "explicit --isolation bwrap with no verified tier -> refused exit 3 (fail loud, no host fallback)")
truth(_rbf.get("container_present") is False, "fail-loud bwrap: container_present False")
truth(_rbf.get("isolation_tier") == "host-not-isolated", "fail-loud bwrap: stamps host-not-isolated")
_sh.rmtree(_flb, ignore_errors=True)

# (c3) the `produced` guard: bwrap present but the probe never emitted a LEAKS= line (namespaces could
# not be created - e.g. unprivileged userns disabled -> bwrap aborts) is NOT a verified tier. This is
# the false-pass catch the macOS Seatbelt doctor never needed.
_save_hb2, _save_rb = H._have_bwrap, H._run_bwrapped
H._have_bwrap = lambda: True
H._run_bwrapped = lambda *a, **k: (1, "", "bwrap: setting up uid map: Permission denied\n", False)
try:
    _udoc = H.bwrap_doctor(BTC)
finally:
    H._have_bwrap, H._run_bwrapped = _save_hb2, _save_rb
truth(_udoc["tier"] == "host-not-isolated" and _udoc.get("probe_ran") is False,
      "bwrap present but userns blocked (no LEAKS=) -> host-not-isolated (no false pass)")
truth("user namespaces" in (_udoc.get("note") or ""),
      "userns-blocked -> note explains the cause (not the verified-guarantees text)")
truth("sysctl" in (_udoc.get("fix") or ""),
      "userns-blocked -> fix-line gives the exact sysctl to enable it")

# (d) ANTI-DRIFT: `bwrap-verified` must be accepted as VERIFIED by EVERY consumer of the tier set.
# A new verified tier lifts Linux off the host-not-isolated CAVEAT cap ONLY if all five layers
# recognize it; this fails loudly if any site is missed now or silently regresses later.
import compare as _CMP      # noqa: E402
import verdict as _V        # noqa: E402
import calma as _CALMA      # noqa: E402
import hook_stop as _HOOK   # noqa: E402

truth("bwrap-verified" in H._VERIFIED_TIERS, "run_hermetic: bwrap-verified is a verified tier")
truth("bwrap-verified" in _CALMA.VERIFIED_TIERS, "calma: bwrap-verified in VERIFIED_TIERS")
truth("bwrap-verified" in _HOOK.VERIFIED_TIERS, "hook_stop: bwrap-verified in VERIFIED_TIERS")
_rec1 = {"metrics": [{"metric_id": "m1", "value": 1.0}]}
_con1 = {"metrics": [{"metric_id": "m1", "claimed_value": 1.0}]}
_cd_bw = _CMP.compare(_rec1, _con1, isolation_tier="bwrap-verified")
_cd_host = _CMP.compare(_rec1, _con1, isolation_tier="host-not-isolated")
truth(_cd_bw["metrics"][0]["verdict_inputs"]["container_present"] is True,
      "compare: bwrap-verified -> container_present True")
truth(_cd_host["metrics"][0]["verdict_inputs"]["container_present"] is False,
      "compare: host-not-isolated -> container_present False (control)")
# verdict: bwrap-verified earns the isolation confidence bump AND is not a host-not-isolated caveat
_vi = {"isolation_tier": "bwrap-verified", "determinism_mode": "controlled-to-bit",
       "binding_status": "independently-bound", "claim_outside_ci": False}
_conf_bw = _V.confidence(_vi, _V.CONFIRMED)
_conf_host = _V.confidence(dict(_vi, isolation_tier="host-not-isolated"), _V.CONFIRMED)
truth(round(_conf_bw - _conf_host, 2) == 0.15, "verdict: bwrap-verified earns the +0.15 isolation bump")
truth("host tier not isolated" not in _V._caveat_reasons(_V._norm(_vi)),
      "verdict: bwrap-verified is NOT flagged as host-not-isolated")

# (e) MARQUEE: a deliberately hostile OWN-CODE repo is fully contained under bwrap - egress (ip/dns/
# curl), host-secret reads (abs + ~), writes outside <base> (/etc, $HOME), and .calma writes are ALL
# denied; only the base itself is writable; the run stamps bwrap-verified. Skipped honestly off a
# verified bwrap host (macOS / a host without unprivileged userns) - the structural + fail-loud walls
# above still run there.
_bw_live = H._have_bwrap() and H.bwrap_doctor(BTC).get("tier") == "bwrap-verified"
if _bw_live:
    _bh = tempfile.mkdtemp()
    os.makedirs(os.path.join(_bh, ".calma"), exist_ok=True)
    open(os.path.join(_bh, ".calma", "cache.json"), "w").write('{"planted": false}')
    _bsec = os.path.join(os.path.realpath(os.path.expanduser("~")), ".calma_bwrap_hostile_secret")
    open(_bsec, "w").write("HOST-SECRET")
    _bevil = (
        "import socket, subprocess, os\n"
        "res = []\n"
        "for tag, h in [('ip', ('1.1.1.1', 80)), ('dns', ('example.com', 80))]:\n"
        "    try: socket.create_connection(h, timeout=3); res.append('EGRESS_' + tag)\n"
        "    except Exception: pass\n"
        "try:\n"
        "    r = subprocess.run(['curl', '-s', '-m', '3', 'http://1.1.1.1'], capture_output=True)\n"
        "    if r.returncode == 0 and r.stdout: res.append('EGRESS_curl')\n"
        "except Exception: pass\n"
        "for p in [%r, os.path.expanduser('~/.calma_bwrap_hostile_secret')]:\n"
        "    try: open(p).read(); res.append('READ_SECRET')\n"
        "    except Exception: pass\n"
        "for p in ['/etc/calma_evil', os.path.expanduser('~/calma_evil')]:\n"
        "    try: open(p, 'w').write('x'); res.append('WROTE_OUTSIDE')\n"
        "    except Exception: pass\n"
        "try: open('.calma/cache.json', 'w').write('{\"planted\": true}'); res.append('WROTE_CALMA')\n"
        "except Exception: pass\n"
        "try: open('ok.txt', 'w').write('ok'); res.append('WROTE_BASE')\n"
        "except Exception: pass\n"
        "print('HOSTILE=' + (','.join(res) if res else 'CONTAINED'))\n"
    ) % _bsec
    open(os.path.join(_bh, "evil.py"), "w").write(_bevil)
    json.dump({"run": {"entrypoint": "evil.py"}, "env": {"trust": "own-code"}, "artifacts": [], "metrics": []},
              open(os.path.join(_bh, "verify.yaml"), "w"))
    _rbh = H.run(os.path.join(_bh, "verify.yaml"), base=_bh, timeout=60, isolation="bwrap")
    try:
        os.unlink(_bsec)
    except OSError:
        pass
    _obh = _rbh.get("stdout_tail", "")
    truth(_rbh.get("isolation_tier") == "bwrap-verified" and _rbh.get("exit_code") == 0,
          "bwrap marquee: hostile own-code runs under bwrap (tier %s exit %s)"
          % (_rbh.get("isolation_tier"), _rbh.get("exit_code")))
    truth("EGRESS" not in _obh, "bwrap marquee: ALL network egress blocked (ip/dns/curl)")
    truth("READ_SECRET" not in _obh, "bwrap marquee: planted host secret UNREADABLE ($HOME not in namespace)")
    truth("WROTE_OUTSIDE" not in _obh, "bwrap marquee: cannot write outside <base> (/etc, $HOME)")
    truth("WROTE_CALMA" not in _obh, "bwrap marquee: cannot write/plant .calma verdict state")
    truth(open(os.path.join(_bh, ".calma", "cache.json")).read() == '{"planted": false}',
          "bwrap marquee: pre-existing .calma bytes untouched")
    truth("WROTE_BASE" in _obh, "bwrap marquee: the base itself stays writable (outputs land for recompute)")
    _sh.rmtree(_bh, ignore_errors=True)

print("run_hermetic: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
