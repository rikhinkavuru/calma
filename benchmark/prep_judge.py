"""Prepare LLM-judge batches — ANONYMIZED so the judge cannot cheat.

Each case becomes an opaque id (case_NN) under a deterministic shuffle, so the label-revealing
suffix (_honest/_obvious/_subtle) is hidden AND the three variants that share a dataset are spread
across different batches with different sample windows (so they don't read as "same data, 3 claims").
The judge sees only: opaque id, metric, claim, n_rows, columns, a sample of the data. Ground-truth
mapping (opaque -> real id) is written to judge_map.json and is NOT given to the judges.

Run: python3 benchmark/prep_judge.py
"""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = 150


def _read_body(case_dir, artifact=None):
    if artifact:
        path = os.path.join(case_dir, artifact)
    else:
        runs = os.path.join(case_dir, "runs")
        path = os.path.join(runs, next(f for f in sorted(os.listdir(runs)) if f.endswith(".csv")))
    with open(path) as f:
        lines = f.read().splitlines()
    return lines[0], lines[1:]


def main():
    manifest = json.load(open(os.path.join(HERE, "manifest.json")))
    # deterministic shuffle by a hash of the real id (no RNG/date; stable across runs)
    order = sorted(range(len(manifest)),
                   key=lambda i: hashlib.sha256(manifest[i]["id"].encode()).hexdigest())
    mapping = {}
    cases = []
    for opaque_idx, mi in enumerate(order):
        m = manifest[mi]
        opaque = "case_%02d" % opaque_idx
        mapping[opaque] = m["id"]
        header, body = _read_body(m["dir"], m.get("artifact"))
        # a per-case contiguous window (offset by the opaque index) so sibling variants that share a
        # dataset don't present byte-identical samples
        off = (opaque_idx * 7) % max(1, len(body) - SAMPLE) if len(body) > SAMPLE else 0
        sample = body[off:off + SAMPLE]
        cases.append({"id": opaque, "metric": m.get("display") or m["metric"], "claim": m["claim"],
                      "n_rows": m["n_rows"], "columns": header,
                      "sample_note": "showing %d of %d rows" % (len(sample), m["n_rows"]),
                      "sample_csv": "\n".join([header] + sample)})
    json.dump(mapping, open(os.path.join(HERE, "judge_map.json"), "w"), indent=2)
    os.makedirs(os.path.join(HERE, "judge_batches"), exist_ok=True)
    for f in os.listdir(os.path.join(HERE, "judge_batches")):
        os.remove(os.path.join(HERE, "judge_batches", f))
    k = 10
    batches = [cases[i:i + k] for i in range(0, len(cases), k)]
    for i, b in enumerate(batches):
        json.dump(b, open(os.path.join(HERE, "judge_batches", "batch_%d.json" % i), "w"), indent=2)
    print("wrote %d anonymized batches (%d cases); mapping -> judge_map.json" % (len(batches), len(cases)))


if __name__ == "__main__":
    main()
