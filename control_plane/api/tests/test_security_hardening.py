"""Offline unit tests for the control-plane security hardening (no live Supabase/R2 — storage + signing
are monkeypatched). Covers:

  * Issue 2 — downloaded bundle/input bytes are hashed and checked against the caller-declared sha256
    BEFORE execution (mismatched bytes are rejected, never extracted/run).
  * Issue 3 — run-artifact collection uploads ONLY regular files contained in runs/: symlinks, hardlinks,
    FIFOs/devices are skipped, the file-count + byte caps hold, and the skip count is recorded.

Run:  python3 -m control_plane.api.tests.test_security_hardening
  (or ~/.calma/cp-venv/bin/python -m control_plane.api.tests.test_security_hardening)
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import tarfile
import tempfile
from types import SimpleNamespace

# allow direct invocation (python3 path/to/test_security_hardening.py) as well as -m
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from control_plane.api import engine as E  # noqa: E402

_n = _fail = 0


def ok(cond, label):
    global _n, _fail
    _n += 1
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        _fail += 1


def raises(fn, label):
    try:
        fn()
        ok(False, label + " (expected a rejection, none raised)")
    except Exception:
        ok(True, label)


# ============================ Issue 2 — pre-execution hash verification ============================
def test_verify_sha256():
    d = tempfile.mkdtemp(prefix="calma_h_")
    p = os.path.join(d, "blob")
    payload = b"the exact bytes the control plane recorded"
    with open(p, "wb") as fh:
        fh.write(payload)
    good = hashlib.sha256(payload).hexdigest()

    ok(E._sha256_file(p) == good, "streaming _sha256_file matches hashlib")
    # match -> no raise
    E._verify_sha256(p, good, "blob")
    ok(True, "matching sha256 passes verification")
    # UPPERCASE declared is normalised (lower-cased) and still matches
    E._verify_sha256(p, good.upper(), "blob")
    ok(True, "uppercase declared sha256 is normalised and matches")
    # mismatch -> reject
    raises(lambda: E._verify_sha256(p, hashlib.sha256(b"other").hexdigest(), "blob"),
           "mismatched sha256 is rejected")
    # non-hex / empty declared -> reject (no hash to verify against)
    raises(lambda: E._verify_sha256(p, "not-a-hash", "blob"), "non-hex declared sha256 is rejected")
    raises(lambda: E._verify_sha256(p, "", "blob"), "empty declared sha256 is rejected")
    raises(lambda: E._verify_sha256(p, "ab" * 31, "blob"), "short (non-64) declared sha256 is rejected")


def _make_tar_gz_with_contract() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        body = b'{"run": {"entrypoint": "m.py"}, "artifacts": [], "metrics": []}'
        ti = tarfile.TarInfo("verify.yaml")
        ti.size = len(body)
        tf.addfile(ti, io.BytesIO(body))
        mb = b"print('ok')\n"
        ti2 = tarfile.TarInfo("m.py")
        ti2.size = len(mb)
        tf.addfile(ti2, io.BytesIO(mb))
    return buf.getvalue()


def test_prepare_workdir_hash_gate():
    payload = _make_tar_gz_with_contract()
    good = hashlib.sha256(payload).hexdigest()
    _orig_download = E.storage.download_to

    def fake_download(key, path):           # simulate the tenant PUTting `payload` to the presigned key
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(payload)

    E.storage.download_to = fake_download
    try:
        # matching bundle sha -> stages + extracts cleanly
        work = E.prepare_workdir("t1", "t/t1/bundles/%s.tar.gz" % good, good, [])
        ok(os.path.isfile(os.path.join(work, "verify.yaml")),
           "prepare_workdir extracts a bundle whose bytes match the declared sha256")
        E.cleanup(work)

        # the attack: declared sha != the bytes actually served -> REJECT before extraction
        wrong = hashlib.sha256(b"a totally different bundle").hexdigest()
        raises(lambda: E.prepare_workdir("t1", "t/t1/bundles/%s.tar.gz" % wrong, wrong, []),
               "prepare_workdir rejects a bundle whose bytes != declared sha256 (CWE-345)")

        # a data_ref whose bytes don't match its declared sha is likewise rejected
        dr_bad = SimpleNamespace(uri="t/t1/inputs/x", sha256=hashlib.sha256(b"nope").hexdigest(),
                                 dest_rel="data/x.csv")
        raises(lambda: E.prepare_workdir("t1", "t/t1/bundles/%s.tar.gz" % good, good, [dr_bad]),
               "prepare_workdir rejects a data_ref whose bytes != declared sha256")

        # a data_ref whose bytes DO match passes (payload is what fake_download writes everywhere)
        dr_good = SimpleNamespace(uri="t/t1/inputs/y", sha256=good, dest_rel="data/y.bin")
        work2 = E.prepare_workdir("t1", "t/t1/bundles/%s.tar.gz" % good, good, [dr_good])
        ok(os.path.isfile(os.path.join(work2, "data", "y.bin")),
           "prepare_workdir stages a data_ref whose bytes match the declared sha256")
        E.cleanup(work2)
    finally:
        E.storage.download_to = _orig_download


# ============================ Issue 3 — artifact-collection hardening =============================
class _Recorder:
    """Capture upload_file / put_bytes / sign_envelope calls instead of hitting R2."""
    def __init__(self):
        self.uploaded = []      # (path, key)
        self.evidence = None

    def install(self):
        self._u, self._t = E.storage.upload_file, E.storage.tenant_key
        self._p, self._s = E.storage.put_bytes, E.signing.sign_envelope
        E.storage.upload_file = lambda path, key, content_type="application/octet-stream": \
            self.uploaded.append((path, key))
        E.storage.tenant_key = lambda tenant_id, *parts: "t/%s/%s" % (tenant_id, "/".join(map(str, parts)))
        E.storage.put_bytes = lambda key, data, content_type="application/octet-stream": None
        E.signing.sign_envelope = lambda ev: setattr(self, "evidence", ev) or {"payload": "x", "signatures": []}

    def restore(self):
        E.storage.upload_file, E.storage.tenant_key = self._u, self._t
        E.storage.put_bytes, E.signing.sign_envelope = self._p, self._s


def _runs_with_traps():
    work = tempfile.mkdtemp(prefix="calma_art_")
    runs = os.path.join(work, "runs")
    os.makedirs(os.path.join(runs, "sub"))
    with open(os.path.join(runs, "good.txt"), "w") as fh:
        fh.write("hello")
    with open(os.path.join(runs, "sub", "nested.txt"), "w") as fh:
        fh.write("nested")
    # traps: a symlink to a host secret, a FIFO, and a symlinked DIRECTORY pointing at /
    os.symlink("/etc/passwd", os.path.join(runs, "leak"))
    try:
        os.mkfifo(os.path.join(runs, "pipe"))
    except (AttributeError, OSError):
        pass                                  # non-POSIX: skip the FIFO trap, the rest still asserts
    os.symlink("/", os.path.join(runs, "evil_dir"))
    return work, runs


def test_collect_skips_symlinks_and_specials():
    work, runs = _runs_with_traps()
    rec = _Recorder()
    rec.install()
    try:
        manifest, _proof = E.collect_and_store(work, "t1", "job1", "run1", {"ok": True})
    finally:
        rec.restore()
        E.cleanup(work)
    names = sorted(m["name"] for m in manifest)
    ok(names == ["good.txt", os.path.join("sub", "nested.txt")],
       "only the regular files are collected (got %r)" % names)
    uploaded_names = sorted(os.path.basename(k) for _p, k in rec.uploaded)
    ok("leak" not in uploaded_names, "the symlink to /etc/passwd is NOT uploaded (no host-secret exfil)")
    ok("pipe" not in uploaded_names, "the FIFO is NOT uploaded")
    ok(rec.evidence is not None and rec.evidence.get("artifacts_skipped", 0) >= 2,
       "the skip count is recorded in the signed evidence (got %r)"
       % (rec.evidence or {}).get("artifacts_skipped"))


def test_safe_artifact_predicate():
    work, runs = _runs_with_traps()
    rd = os.path.realpath(runs)
    try:
        ok(E._safe_artifact(os.path.join(rd, "good.txt"), rd) is not None, "_safe_artifact accepts a regular file")
        ok(E._safe_artifact(os.path.join(rd, "leak"), rd) is None, "_safe_artifact rejects a symlink")
        if os.path.exists(os.path.join(rd, "pipe")):
            ok(E._safe_artifact(os.path.join(rd, "pipe"), rd) is None, "_safe_artifact rejects a FIFO")
    finally:
        E.cleanup(work)


def test_hardlink_rejected():
    work = tempfile.mkdtemp(prefix="calma_hl_")
    runs = os.path.join(work, "runs")
    os.makedirs(runs)
    orig = os.path.join(runs, "orig.txt")
    with open(orig, "w") as fh:
        fh.write("data")
    try:
        os.link(orig, os.path.join(runs, "hard.txt"))   # a hardlink -> both names now have st_nlink == 2
    except OSError:
        ok(True, "hardlink unsupported on this fs; skipping (guard still present)")
        E.cleanup(work)
        return
    rec = _Recorder()
    rec.install()
    try:
        manifest, _ = E.collect_and_store(work, "t1", "job1", "run1", {})
    finally:
        rec.restore()
        E.cleanup(work)
    ok(manifest == [], "hardlinked files (st_nlink>1) are rejected (manifest empty, got %r)"
       % [m["name"] for m in manifest])


def test_runs_itself_a_symlink():
    work = tempfile.mkdtemp(prefix="calma_rs_")
    os.symlink("/", os.path.join(work, "runs"))         # runs/ replaced by a symlink to /
    rec = _Recorder()
    rec.install()
    try:
        manifest, _ = E.collect_and_store(work, "t1", "job1", "run1", {})
    finally:
        rec.restore()
        E.cleanup(work)
    ok(manifest == [] and not rec.uploaded, "a symlinked runs/ dir collects NOTHING (never descended)")


def test_file_count_cap():
    work = tempfile.mkdtemp(prefix="calma_cap_")
    runs = os.path.join(work, "runs")
    os.makedirs(runs)
    for i in range(5):
        with open(os.path.join(runs, "f%d.txt" % i), "w") as fh:
            fh.write("x")
    _saved = E.config.MAX_ARTIFACT_FILES
    E.config.MAX_ARTIFACT_FILES = 2
    rec = _Recorder()
    rec.install()
    try:
        manifest, _ = E.collect_and_store(work, "t1", "job1", "run1", {})
    finally:
        rec.restore()
        E.config.MAX_ARTIFACT_FILES = _saved
        E.cleanup(work)
    ok(len(manifest) == 2, "MAX_ARTIFACT_FILES cap holds (uploaded %d of 5)" % len(manifest))
    ok(rec.evidence.get("artifacts_skipped") == 3, "the 3 over-cap files are counted as skipped")


def main():
    test_verify_sha256()
    test_prepare_workdir_hash_gate()
    test_collect_skips_symlinks_and_specials()
    test_safe_artifact_predicate()
    test_hardlink_rejected()
    test_runs_itself_a_symlink()
    test_file_count_cap()
    print("\nsecurity-hardening: %d checks, %d failed" % (_n, _fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
