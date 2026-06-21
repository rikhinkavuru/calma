"""WS-A parquet ingestion + THE FIREWALL. The load-bearing invariant: importing the pure-stdlib recompute
core (and io_parquet itself) must pull ZERO third-party modules - pyarrow is imported lazily, only on an
actual .parquet read. With pyarrow installed, a Numerai-style parquet (id index, int8 features) verifies
end-to-end and gives the byte-identical metric to the equivalent CSV. Without pyarrow, a read raises a clean
'install calma[parquet]' ImportError. Pure stdlib (skips the e2e when pyarrow is absent). Run: python3 test_parquet_io.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

# --- THE FIREWALL: importing the core must not pull any heavy third-party module (assert BEFORE we probe
#     for pyarrow's availability, which would itself import it). ---
import recompute as RC  # noqa: E402
import recipes  # noqa: E402,F401
import embargo_checks  # noqa: E402,F401
import simulation_assumptions_checks  # noqa: E402,F401
import io_parquet as IOPQ  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


_THIRD_PARTY = ("pyarrow", "numpy", "pandas", "scipy", "sklearn")
_leaked = [m for m in _THIRD_PARTY if m in sys.modules]
truth(not _leaked, "firewall: importing the recompute core + io_parquet + the families pulls zero "
                   "third-party (%s leaked)" % (",".join(_leaked) or "none"))

# availability probe (this DOES import pyarrow if present - after the firewall assertion above)
try:
    import pyarrow  # noqa: F401
    import pyarrow.parquet as _pq
    import pyarrow as _pa
    HAVE_PA = True
except ImportError:
    HAVE_PA = False

if not HAVE_PA:
    raised = False
    try:
        IOPQ.read_columns(os.path.join(tempfile.mkdtemp(), "x.parquet"))
    except ImportError as e:
        raised = "calma[parquet]" in str(e)
    except Exception:  # noqa: BLE001
        raised = False
    truth(raised, "no-pyarrow: read_columns raises a clean 'install calma[parquet]' ImportError (not a traceback)")
    print("  (pyarrow not installed - end-to-end parquet verify skipped; firewall + install-hint checked)")
else:
    d = tempfile.mkdtemp(prefix="calma_pq_")
    eras = ["era0001"] * 4 + ["era0002"] * 4
    pred = [0.1, 0.5, 0.3, 0.9, 0.2, 0.7, 0.4, 0.6]
    tgt = [0.0, 0.25, 0.5, 1.0, 0.25, 0.75, 0.5, 1.0]
    feat = [1, 2, 3, 4, 5, 6, 7, 8]  # an int8 feature - must NOT be promoted to 1.0/2.0
    tbl = _pa.table({"era": eras, "prediction": pred, "target": tgt,
                     "feature_x": _pa.array(feat, _pa.int8())})
    pqpath = os.path.join(d, "validation.parquet")
    _pq.write_table(tbl, pqpath)

    cols = IOPQ.read_columns(pqpath, columns=["era", "prediction", "target"])
    truth(set(cols) == {"era", "prediction", "target"}, "projection: only the requested columns materialize")
    allcols = IOPQ.read_columns(pqpath)
    truth(allcols["feature_x"][0] == "1", "int8 trap: an int8 feature stays '1', not '1.0' (no float promotion)")

    contract = {"run": {"entrypoint": "x"}, "artifacts": [{"path": "validation.parquet", "columns": {}}],
                "metrics": [{"metric_id": "numerai_corr", "artifact": "validation.parquet",
                             "binding": {"prediction": "prediction", "target": "target", "era": "era"},
                             "headline": True}]}
    cpath = os.path.join(d, "verify.json")
    json.dump(contract, open(cpath, "w"))
    m = RC.recompute_contract(cpath, base=d)["metrics"][0]
    truth(not m["degenerate"] and isinstance(m["value"], float) and m["value"] == m["value"],
          "end-to-end: numerai_corr recomputes from a .parquet artifact (no hand-flattening)")

    import csv as _csv
    with open(os.path.join(d, "validation.csv"), "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["era", "prediction", "target"])
        for e, p, t in zip(eras, pred, tgt):
            w.writerow([e, p, t])
    c2 = dict(contract, artifacts=[{"path": "validation.csv", "columns": {}}],
              metrics=[dict(contract["metrics"][0], artifact="validation.csv")])
    cpath2 = os.path.join(d, "verify2.json")
    json.dump(c2, open(cpath2, "w"))
    m2 = RC.recompute_contract(cpath2, base=d)["metrics"][0]
    truth(m["value"] == m2["value"], "parquet == csv: byte-identical numerai_corr from both artifact formats")
    print("  (pyarrow %s - end-to-end parquet verify exercised)" % _pa.__version__)

print("parquet_io: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
