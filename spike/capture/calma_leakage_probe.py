"""In-sandbox data-validity probe (leakage on MATERIALIZED data).

The host-side leakage check only sees a repo's COMMITTED splits. But most real repos DOWNLOAD their data at
runtime (a gated HF dataset, genomic_benchmarks, an S3 pull) — so the split that actually gets evaluated never
touches the host, and the leakage that inflates the reported number goes unchecked. This probe runs INSIDE the
verification sandbox, AFTER the data is materialized, over /work + the common download caches, and reports any
train/test contamination (exact duplicate rows + k-mer homology near-duplicates) — the independent check the
whole "audit the data, not just the number" thesis rests on.

Self-contained: imports the shipped pure-stdlib leakage detector (core/leakage.py → /capture/calma_leakage.py)
and writes findings JSON the runner pulls back. Best-effort — any error just yields no findings, never a crash.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/capture")


def _roots():
    homes = [os.path.expanduser("~"), "/root", "/home/user"]
    caches = []
    for h in homes:
        for sub in (".genomic_benchmarks", ".cache", ".keras/datasets", "tensorflow_datasets",
                    "scikit_learn_data", ".cache/huggingface/datasets"):
            caches.append(os.path.join(h, sub))
    return ["/work", "/work/data", "/tmp/data", *caches]


def main() -> int:
    out_path = os.environ.get("CALMA_LEAKAGE_OUT", "/capture/leakage.json")
    try:
        import calma_leakage as L
    except Exception as e:  # noqa: BLE001 — detector not shipped → no findings
        sys.stderr.write("leakage probe: detector unavailable (%s)\n" % e)
        json.dump([], open(out_path, "w"))
        return 0
    try:
        results = L.scan_locations(_roots())
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("leakage probe: scan error (%s)\n" % e)
        results = []
    with open(out_path, "w") as fh:
        json.dump(results, fh)
    n_find = sum(len(r.get("findings") or []) for r in results)
    print("calma-leakage: scanned %d split(s), %d contamination finding(s)" % (len(results), n_find))
    return 0


if __name__ == "__main__":
    sys.exit(main())
