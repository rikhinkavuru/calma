"""Accuracy benchmark for calma's recipe suggester (scripts/suggest.py).

Gold set: 1000 blind user-style asks (500 named + 500 paraphrase), 2 per recipe,
authored by domain-expert agents who never saw suggest.py or the alias table -
so this measures generalization, not memorization. Metrics: recall@k and MRR,
broken out by ask kind and by family, with a sample of misses for iteration.

    python3 tests/suggest_bench/bench.py            # full report
    python3 tests/suggest_bench/bench.py --misses   # also dump every miss
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import recipes as RCP  # noqa: E402
import suggest as SUGG  # noqa: E402

K = 8
GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gold.json")


def run(dump_misses=False):
    rows = json.load(open(GOLD))
    fam = {m: (getattr(RCP.get(m), "manifest", {}) or {}).get("family", "other") for m in RCP.ids()}
    agg = {}                       # bucket -> [hit@1, hit@3, hit@5, hit@8, rr, n]
    misses = []

    def bump(key, rank):
        a = agg.setdefault(key, [0, 0, 0, 0, 0.0, 0])
        a[5] += 1
        if rank is not None:
            if rank == 1: a[0] += 1
            if rank <= 3: a[1] += 1
            if rank <= 5: a[2] += 1
            if rank <= 8: a[3] += 1
            a[4] += 1.0 / rank

    for r in rows:
        ranked = [c["metric_id"] for c in SUGG.suggest(r["query"], k=K)]
        rank = (ranked.index(r["gold"]) + 1) if r["gold"] in ranked else None
        bump("ALL", rank)
        bump("kind:" + r.get("kind", "?"), rank)
        bump("fam:" + fam.get(r["gold"], "other"), rank)
        if rank is None:
            misses.append((r["gold"], r.get("kind"), r["query"], ranked[:3]))

    def line(key):
        a = agg[key]
        n = a[5]
        return "%-22s n=%-4d  @1 %5.1f%%  @3 %5.1f%%  @5 %5.1f%%  @8 %5.1f%%  MRR %.3f" % (
            key, n, 100*a[0]/n, 100*a[1]/n, 100*a[2]/n, 100*a[3]/n, a[4]/n)

    print("=" * 92)
    print(line("ALL"))
    print("-" * 92)
    for k in ("kind:named", "kind:paraphrase"):
        if k in agg: print(line(k))
    print("-" * 92)
    for k in sorted(agg, key=lambda x: agg[x][3]/agg[x][5]):
        if k.startswith("fam:"): print(line(k))
    print("=" * 92)
    print("misses (not in top %d): %d / %d" % (K, len(misses), len(rows)))
    if dump_misses:
        for g, kind, q, top in misses:
            print("  [%s] %-26s top3=%s\n      %s" % (kind, g, top, q))
    return agg, misses


if __name__ == "__main__":
    run("--misses" in sys.argv)
