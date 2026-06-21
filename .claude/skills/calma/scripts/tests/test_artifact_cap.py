"""Defense-in-depth: the artifact byte-cap is unified across every detector reader (pathsafe.within_cap),
so a hostile multi-GB CSV or a planted FIFO/device emitted by the untrusted entrypoint makes the detector
ABSTAIN (return empty) instead of OOMing the host verifier or blocking open() forever. Pure stdlib.
Run: python3 test_artifact_cap.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import embargo_checks as EMB  # noqa: E402  (a representative detector reader)
import pathsafe as PS  # noqa: E402
import simulation_assumptions_checks as SAC  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


_DIR = tempfile.mkdtemp(prefix="calma_cap_")
_csv = os.path.join(_DIR, "data.csv")
with open(_csv, "w") as f:
    f.write("a,b\n" + "\n".join("%d,%d" % (i, i) for i in range(200)))  # ~1.5 KB
_size = os.path.getsize(_csv)

# ---- within_cap unit ---------------------------------------------------------------------------------
truth(PS.within_cap(_csv) is True, "within_cap: a normal file under the default cap -> True")
truth(PS.within_cap(_csv, max_bytes=10) is False, "within_cap: a file over an explicit small cap -> False")
truth(PS.within_cap(_csv, max_bytes=_size) is True, "within_cap: a file exactly at the cap -> True")
truth(PS.within_cap(os.path.join(_DIR, "missing.csv")) is False, "within_cap: a missing file -> False")
truth(PS.within_cap(_DIR) is False, "within_cap: a directory -> False (not a regular file)")

# ---- a detector reader ABSTAINS over the cap (instead of reading a hostile giant file) ----------------
_saved = PS.MAX_ARTIFACT_BYTES
try:
    PS.MAX_ARTIFACT_BYTES = 10  # pretend the cap is 10 bytes; the ~1.5 KB file is now "too big"
    truth(EMB._read_csv(_csv) == {}, "detector reader: over-cap artifact -> abstain ({}) not a read")
    truth(SAC._read_csv(_csv) == {}, "second detector reader: over-cap -> abstain ({})")
finally:
    PS.MAX_ARTIFACT_BYTES = _saved
truth(EMB._read_csv(_csv) != {}, "detector reader: a within-cap artifact reads normally")

# ---- a FIFO (a planted named pipe that would BLOCK open() forever) is rejected, never opened ----------
_fifo = os.path.join(_DIR, "pipe.csv")
try:
    os.mkfifo(_fifo)
    truth(PS.within_cap(_fifo) is False, "within_cap: a FIFO/named-pipe -> False (never open()'d, no hang)")
    truth(EMB._read_csv(_fifo) == {}, "detector reader: a FIFO artifact -> abstain (no infinite block)")
except (AttributeError, OSError):
    # mkfifo not available on this platform - skip out loud (never a silent pass)
    print("  (mkfifo unavailable - FIFO sub-checks skipped)")

print("artifact_cap: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
