"""Score the benchmark: Calma vs LLM-as-judge vs trust-the-number, against ground truth.

A verifier has two ways to be WRONG, both serious:
  - false-confirm: a flawed claim is called honest  (the dangerous one - it launders a wrong number)
  - false-alarm:   an honest claim is called flawed  (cries wolf - erodes trust)
Calma may also ABSTAIN (CAN'T-CONFIRM) - a safe non-answer, never a wrong answer.

Run: python3 benchmark/score.py   (after run_calma.py + the LLM-judge batches)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIND = {"accuracy", "precision", "recall", "f1", "auc", "total_return", "sharpe"}  # calma can REFUTE
VALUEFAM = {"rmse", "mae", "r2", "column_sum", "column_mean"}                       # calma abstains (today)


def _load_judge():
    mapping = json.load(open(os.path.join(HERE, "judge_map.json")))
    pred = {}
    for f in sorted(os.listdir(os.path.join(HERE, "results"))):
        if f.startswith("judge_batch_"):
            for r in json.load(open(os.path.join(HERE, "results", f))):
                pred[mapping[r["id"]]] = r["judgment"]
    return pred


def _confusion(rows):
    flawed = [r for r in rows if r["label"] == "flawed"]
    honest = [r for r in rows if r["label"] == "honest"]
    caught = sum(1 for r in flawed if r["pred"] == "flawed")
    fconf = sum(1 for r in flawed if r["pred"] == "honest")
    abf = sum(1 for r in flawed if r["pred"] == "abstain")
    passed = sum(1 for r in honest if r["pred"] == "honest")
    falarm = sum(1 for r in honest if r["pred"] == "flawed")
    abh = sum(1 for r in honest if r["pred"] == "abstain")
    return {"flawed": len(flawed), "honest": len(honest), "caught": caught,
            "false_confirm": fconf, "abstain_flawed": abf, "passed": passed,
            "false_alarm": falarm, "abstain_honest": abh,
            "catch_rate": caught / len(flawed) if flawed else 0.0}


def main():
    manifest = {m["id"]: m for m in json.load(open(os.path.join(HERE, "manifest.json")))}
    calma = {r["id"]: r["prediction"] for r in json.load(open(os.path.join(HERE, "results", "calma.json")))}
    judge = _load_judge()

    methods = {
        "trust-the-number": lambda mid: "honest",
        "LLM-as-judge (no exec)": lambda mid: judge.get(mid, "abstain"),
        "Calma": lambda mid: calma.get(mid, "abstain"),
    }

    def rows_for(pred_fn, subset=None):
        out = []
        for mid, m in manifest.items():
            if subset and m["metric"] not in subset:
                continue
            out.append({"label": m["label"], "tier": m.get("tier"), "metric": m["metric"],
                        "pred": pred_fn(mid)})
        return out

    print("\n" + "=" * 78)
    print("CALMA BENCHMARK - catch a wrong number (36 cases: 12 honest, 12 obvious, 12 subtle)")
    print("=" * 78)
    hdr = "%-24s %7s %8s %8s %8s %8s" % ("method", "catch%", "caught", "MISSED", "FALSE-AL", "abstain")
    print(hdr)
    print("-" * 78)
    summary = {}
    for name, fn in methods.items():
        c = _confusion(rows_for(fn))
        summary[name] = c
        print("%-24s %6.0f%% %5d/%-2d %8d %8d %8d"
              % (name, c["catch_rate"] * 100, c["caught"], c["flawed"],
                 c["false_confirm"], c["false_alarm"], c["abstain_flawed"] + c["abstain_honest"]))
    print("-" * 78)
    print("MISSED = flawed called honest (false-confirm, the dangerous error)")
    print("FALSE-AL = honest called flawed (false-alarm) | abstain = safe non-answer (Calma only)")

    # by tier
    print("\nBy flaw tier (catch% on flawed; false-alarms on honest):")
    print("%-24s %10s %10s %10s" % ("method", "obvious", "subtle", "false-alarm"))
    for name, fn in methods.items():
        obv = _confusion(rows_for(fn))  # placeholder
        ob = [r for r in rows_for(fn) if r["tier"] == "obvious"]
        su = [r for r in rows_for(fn) if r["tier"] == "subtle"]
        ho = [r for r in rows_for(fn) if r["tier"] == "honest"]
        oc = sum(1 for r in ob if r["pred"] == "flawed") / len(ob)
        sc = sum(1 for r in su if r["pred"] == "flawed") / len(su)
        fa = sum(1 for r in ho if r["pred"] == "flawed")
        print("%-24s %9.0f%% %9.0f%% %10d" % (name, oc * 100, sc * 100, fa))

    # calma where it's designed to refute (bindable) vs the value-family it abstains on
    print("\nCalma on the metrics it binds for refutation (classification + quant):")
    cb = _confusion(rows_for(methods["Calma"], subset=BIND))
    print("  flawed %d: caught %d, false-confirm %d, abstain %d | honest %d: passed %d, false-alarm %d"
          % (cb["flawed"], cb["caught"], cb["false_confirm"], cb["abstain_flawed"],
             cb["honest"], cb["passed"], cb["false_alarm"]))
    jb = _confusion(rows_for(methods["LLM-as-judge (no exec)"], subset=BIND))
    print("  (same subset) LLM-judge: caught %d/%d, false-confirm %d, false-alarm %d"
          % (jb["caught"], jb["flawed"], jb["false_confirm"], jb["false_alarm"]))

    json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w"), indent=2)
    print("\nwrote results/summary.json")


if __name__ == "__main__":
    main()
