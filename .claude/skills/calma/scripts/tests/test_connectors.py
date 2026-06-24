"""Tests for connectors.py - W7: the connector contract + the local/on-prem connector. Pure stdlib.
Run: python3 test_connectors.py"""
import hashlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import connectors as C  # noqa: E402
import lineage as LIN  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "validation.csv")
with open(src, "wb") as fh:
    fh.write(b"era,pred,target\n0001,0.1,0.2\n0001,0.3,0.4\n")
src_sha = hashlib.sha256(open(src, "rb").read()).hexdigest()

# --- LocalConnector: a real, no-creds pull of a FILE ---
lc = C.LocalConnector()
expect(lc.available()[0] is True, "LocalConnector is available (local filesystem)")
ws = os.path.join(tmp, "workspace")
res = lc.pull(src, ws)
expect(os.path.isfile(res["local_path"]) and res["workspace"] == os.path.realpath(ws),
       "pull copies the artifact into the workspace")
expect(res["local_path"].startswith(os.path.realpath(ws) + os.sep), "the pulled path is CONTAINED in the workspace")
expect(res["uploaded_raw_bytes"] is False, "THE INVARIANT: the connector does not upload raw bytes")
man = res["source_manifest"]
expect(man["uri"].startswith("file://") and man["transport_digest"]["sha256"] == src_sha,
       "the source manifest carries the URI + the transport digest (content hash AT FETCH TIME)")
expect(man.get("retrieved_by", "").startswith("calma-connector-local@"), "the manifest stamps the runner id")
# the manifest chains in a W8(d) statement (transport digest == the subject content hash -> verified)
stmt = LIN.build_statement("validation.csv", src_sha, sources=[man])
expect(LIN.transport_integrity(stmt) == "verified", "the pulled artifact's lineage chains tier-1 <-> tier-2")

# --- LocalConnector: a DIRECTORY pull (per-file hashes go in input_lineage) ---
srcdir = os.path.join(tmp, "bundle")
os.makedirs(srcdir)
open(os.path.join(srcdir, "a.csv"), "w").write("x\n1\n")
rd = lc.pull(srcdir, os.path.join(tmp, "ws2"))
expect(os.path.isdir(rd["local_path"]) and os.path.isfile(os.path.join(rd["local_path"], "a.csv")),
       "a directory source is copied into the workspace")
expect(rd["uploaded_raw_bytes"] is False, "directory pull also uploads no raw bytes")

# a missing source fails cleanly
try:
    lc.pull(os.path.join(tmp, "nope.csv"), os.path.join(tmp, "ws3"))
    expect(False, "pull raises on a missing source")
except ValueError:
    expect(True, "pull raises on a missing source")

# --- the cloud connectors are honest skeletons (need creds + the BYOC runner) ---
for name in ("s3", "sftp", "data-room"):
    conn = C.get(name)
    ok, reason = conn.available()
    expect(ok is False and "not built" in reason, "%s connector available() is truthfully 'not built'" % name)
    try:
        conn.pull({"bucket": "x"}, os.path.join(tmp, "wsX"))
        expect(False, "%s.pull raises NotImplementedError" % name)
    except NotImplementedError:
        expect(True, "%s.pull raises NotImplementedError (honest)" % name)
    expect(bool(conn.mapping), "%s names its concrete source/auth mapping (a fill-in, not a redesign)" % name)

# the skeletons still emit a real source manifest (the shared tier-2)
expect(C.get("s3").source_manifest("s3://b/k", src, version_id="v1")["version_id"] == "v1",
       "a skeleton connector still emits the real source manifest (with the immutability handle)")

# --- get() ---
expect(isinstance(C.get("Local"), C.LocalConnector), "get() is case-insensitive")
try:
    C.get("ftp")
    expect(False, "get() raises on an unknown connector")
except KeyError:
    expect(True, "get() raises on an unknown connector")

print("connectors: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
