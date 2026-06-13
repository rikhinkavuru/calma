"""calma.intake - reproduce someone else's repo without hand-holding.

Detect the interpreter, RESTORE + PIN the repo's declared dependencies into <base>/.calma_venv (the
verified run then executes under that interpreter, via run_hermetic._venv_python), capture the
resolved environment, and BIND the claimed input data by content hash. The restore step is the ONE
phase that may touch the network (pip / Rscript downloads) - it runs BEFORE the verified,
network-denied re-execution and NEVER during it, so the run's hermeticity stamp is unaffected.

Fail-soft: a restore that cannot complete returns ok=False with a concrete reason; verify() then
proceeds and the run gate reports the missing dependency honestly (never a false CONFIRM).

CLI:  intake.py detect --base DIR
      intake.py restore --base DIR [--timeout N]
Library: detect(base) -> dict ; intake(base, contract, do_restore=False) -> dict
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

# files that declare a Python dependency set, in rough order of precedence.
_PY_REQ_NAMES = ("requirements.txt", "requirements.lock", "requirements-dev.txt")
_DATA_EXTS = (".csv", ".parquet", ".feather", ".json", ".jsonl", ".ndjson", ".npy", ".npz",
              ".tsv", ".arrow", ".pkl", ".h5", ".db", ".sqlite")
_VENV_DIR = ".calma_venv"


def _sha256(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _walk_files(base, skip=(".git", ".calma", _VENV_DIR, "__pycache__", "node_modules", "runs")):
    for dp, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".calma")]
        for n in names:
            yield os.path.join(dp, n)


def _parse_pyproject(path):
    """Best-effort PEP 621 / poetry dependency extraction. Uses tomllib when available (py3.11+),
    else a tolerant regex for `dependencies = [ ... ]`. Returns a list of requirement strings."""
    try:
        import tomllib  # py3.11+
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        deps = (data.get("project", {}) or {}).get("dependencies") or []
        if not deps:  # poetry
            poetry = ((data.get("tool", {}) or {}).get("poetry", {}) or {}).get("dependencies", {}) or {}
            deps = [k for k in poetry if k.lower() != "python"]
        return [str(d) for d in deps]
    except Exception:
        pass
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    m = re.search(r"dependencies\s*=\s*\[(.*?)\]", txt, re.S)
    if not m:
        return []
    return [s.strip().strip('"\'') for s in re.findall(r'["\']([^"\']+)["\']', m.group(1))]


def _py_dep_sources(base):
    """Find the dependency declarations a Python repo ships. Returns [(kind, path), ...]."""
    out = []
    for n in _PY_REQ_NAMES:
        p = os.path.join(base, n)
        if os.path.exists(p):
            out.append(("requirements", p))
    pp = os.path.join(base, "pyproject.toml")
    if os.path.exists(pp) and _parse_pyproject(pp):
        out.append(("pyproject", pp))
    for n in ("setup.py", "setup.cfg"):
        if os.path.exists(os.path.join(base, n)):
            out.append(("setup", os.path.join(base, n)))
    for n in ("environment.yml", "environment.yaml"):
        if os.path.exists(os.path.join(base, n)):
            out.append(("conda", os.path.join(base, n)))
    return out


def _entrypoint_ext(contract):
    ep = ((contract or {}).get("run") or {}).get("entrypoint") or ""
    return os.path.splitext(ep)[1].lower()


def detect(base, contract=None):
    """What stack is this repo, and what would intake restore? Read-only - never installs."""
    base = os.path.realpath(base)
    ext = _entrypoint_ext(contract)
    language = {".py": "python", ".r": "r"}.get(ext)
    if language is None:
        # fall back to a file census
        has_py = any(f.endswith(".py") for f in _walk_files(base))
        has_r = any(f.lower().endswith(".r") for f in _walk_files(base))
        language = "python" if has_py else ("r" if has_r else "unknown")
    info = {"language": language, "base": base, "dep_sources": [], "r_sources": [],
            "data_files": []}
    if language == "python":
        info["dep_sources"] = [{"kind": k, "path": os.path.relpath(p, base)}
                               for k, p in _py_dep_sources(base)]
    if language == "r":
        for n in ("renv.lock", "DESCRIPTION"):
            p = os.path.join(base, n)
            if os.path.exists(p):
                info["r_sources"].append({"kind": n, "path": n})
    # data census (inputs the repo reads): data-shaped files NOT under the run-output subtree.
    for f in _walk_files(base):
        if os.path.splitext(f)[1].lower() in _DATA_EXTS:
            info["data_files"].append(os.path.relpath(f, base))
    info["data_files"].sort()
    return info


def _pip_install_args(base, sources):
    """The pip install spec for the strongest source available, plus a human 'method' label."""
    kinds = {k: p for k, p in [(s["kind"], os.path.join(base, s["path"])) for s in sources]}
    if "requirements" in kinds:
        return (["-r", kinds["requirements"]], "requirements.txt")
    if "pyproject" in kinds or "setup" in kinds:
        return (["."], "pip install . (pyproject/setup)")
    return (None, None)


def restore_python(base, sources, timeout=600, py=None):
    """Create <base>/.calma_venv and install the declared deps into it, then PIN with `pip freeze`.
    Returns {ok, venv, method, pinned:[...], installed_count, log_tail}. Network is used HERE only."""
    base = os.path.realpath(base)
    venv = os.path.join(base, _VENV_DIR)
    vpy = os.path.join(venv, "bin", "python")
    py = py or sys.executable
    report = {"ok": False, "venv": venv, "method": None, "pinned": [], "installed_count": 0,
              "log_tail": ""}
    spec, method = _pip_install_args(base, sources)
    report["method"] = method
    if spec is None:
        report.update(ok=True, note="no Python dependency declaration found - stdlib repo")
        return report
    try:
        if not os.path.exists(vpy):
            r = subprocess.run([py, "-m", "venv", venv], capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                report["log_tail"] = (r.stderr or "")[-800:]
                report["note"] = "could not create venv"
                return report
        # upgrade pip quietly (best-effort), then install
        subprocess.run([vpy, "-m", "pip", "install", "-q", "--upgrade", "pip"],
                       capture_output=True, text=True, timeout=180)
        inst = subprocess.run([vpy, "-m", "pip", "install"] + spec, cwd=base,
                              capture_output=True, text=True, timeout=timeout)
        report["log_tail"] = ((inst.stdout or "") + (inst.stderr or ""))[-1200:]
        if inst.returncode != 0:
            report["note"] = "pip install failed (see log_tail)"
            return report
        fr = subprocess.run([vpy, "-m", "pip", "freeze"], capture_output=True, text=True, timeout=120)
        pinned = [ln.strip() for ln in (fr.stdout or "").splitlines() if ln.strip() and "==" in ln]
        report.update(ok=True, pinned=pinned, installed_count=len(pinned))
        return report
    except (OSError, subprocess.SubprocessError) as e:
        report["note"] = "restore error: %s" % e
        return report


def restore_r(base, sources, timeout=600):
    """Best-effort R restore: renv.lock -> renv::restore(); DESCRIPTION -> install declared Imports.
    Requires Rscript. Returns {ok, method, note}."""
    import shutil
    base = os.path.realpath(base)
    rscript = shutil.which("Rscript")
    report = {"ok": False, "method": None}
    if not rscript:
        report["note"] = "Rscript not on PATH - cannot restore R deps"
        return report
    kinds = {s["kind"] for s in sources}
    try:
        if "renv.lock" in kinds:
            report["method"] = "renv::restore()"
            r = subprocess.run([rscript, "-e", "if (requireNamespace('renv', quietly=TRUE)) "
                                "renv::restore(prompt=FALSE) else quit(status=3)"],
                               cwd=base, capture_output=True, text=True, timeout=timeout)
            report["log_tail"] = ((r.stdout or "") + (r.stderr or ""))[-1200:]
            report["ok"] = r.returncode == 0
            if r.returncode == 3:
                report["note"] = "renv not installed in the R library"
            return report
        report["note"] = "no renv.lock - declared R deps are not pinned (DESCRIPTION install skipped)"
        report["ok"] = True
        return report
    except (OSError, subprocess.SubprocessError) as e:
        report["note"] = "R restore error: %s" % e
        return report


def data_bindings(base, contract=None):
    """Bind the claimed input data by content hash: every data-shaped file the repo carries (outside
    the run-output subtree) is recorded path+sha256, so a recompute is pinned to the same bytes."""
    base = os.path.realpath(base)
    out = []
    for f in _walk_files(base):
        if os.path.splitext(f)[1].lower() in _DATA_EXTS:
            out.append({"path": os.path.relpath(f, base), "sha256": _sha256(f),
                        "bytes": (os.path.getsize(f) if os.path.exists(f) else None)})
    out.sort(key=lambda d: d["path"])
    return out


def intake(base, contract=None, do_restore=False, timeout=600):
    """Full intake report. With do_restore, restores+pins deps (network used here, before the run).
    Always captures the interpreter, the declared sources, the resolved pins, and the data bindings.
    Caller persists the returned dict (e.g. to run_dir/intake.json)."""
    base = os.path.realpath(base)
    det = detect(base, contract)
    report = {"schema": "calma/intake@1", "language": det["language"],
              "dep_sources": det["dep_sources"], "r_sources": det["r_sources"],
              "data_bindings": data_bindings(base, contract),
              "restored": False, "restore": None,
              "interpreter": {"host": sys.executable,
                              "version": "%d.%d.%d" % sys.version_info[:3]}}
    if do_restore:
        if det["language"] == "python":
            rr = restore_python(base, [{"kind": s["kind"], "path": s["path"]}
                                       for s in det["dep_sources"]], timeout=timeout)
        elif det["language"] == "r":
            rr = restore_r(base, det["r_sources"], timeout=timeout)
        else:
            rr = {"ok": False, "note": "unknown language - nothing to restore"}
        report["restore"] = rr
        report["restored"] = bool(rr.get("ok"))
        if det["language"] == "python" and rr.get("ok") and rr.get("installed_count"):
            report["interpreter"]["restored_venv"] = os.path.join(base, _VENV_DIR, "bin", "python")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["detect", "restore"])
    ap.add_argument("--base", required=True)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out")
    a = ap.parse_args()
    res = intake(a.base, do_restore=(a.cmd == "restore"), timeout=a.timeout)
    text = json.dumps(res, indent=2)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    if a.cmd == "restore" and res.get("restore") and not res["restore"].get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
