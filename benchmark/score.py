"""Score the benchmark: Calma vs LLM-as-judge vs trust-the-number, against ground truth.

A verifier has two ways to be WRONG, both serious:
  - false-confirm: a flawed claim is called honest  (the dangerous one - it launders a wrong number)
  - false-alarm:   an honest claim is called flawed  (cries wolf - erodes trust)
Calma may also ABSTAIN (CAN'T-CONFIRM) - a safe non-answer, never a wrong answer.

Run: python3 benchmark/score.py   (after run_calma.py + the LLM-judge batches)
Writes results/summary.json (per-method) and results/site_data.json (chart-ready, per-tier/family/track).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


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
            "catch_rate": caught / len(flawed) if flawed else None,
            "wrong": fconf + falarm}


def main():
    manifest = {m["id"]: m for m in json.load(open(os.path.join(HERE, "manifest.json")))}
    calma = {r["id"]: r["prediction"] for r in json.load(open(os.path.join(HERE, "results", "calma.json")))}
    judge = _load_judge()
    _agent_path = os.path.join(HERE, "results", "agent.json")
    agent_rows = json.load(open(_agent_path)) if os.path.exists(_agent_path) else []
    agent = {r["id"]: r["prediction"] for r in agent_rows}
    methods = {
        "trust-the-number": lambda mid: "honest",
        "LLM-as-judge (no exec)": lambda mid: judge.get(mid, "abstain"),
        "Calma": lambda mid: calma.get(mid, "abstain"),
    }
    if agent:  # code-running-agent arm (benchmark/run_agent.py); only present once that's been run
        methods["agent-with-exec"] = lambda mid: agent.get(mid, "abstain")

    def rows_for(fn, where=None):
        out = []
        for mid, m in manifest.items():
            if where and not where(m):
                continue
            out.append({"label": m["label"], "tier": m.get("tier"), "family": m.get("family"),
                        "track": m.get("track"), "pred": fn(mid)})
        return out

    n_h = sum(1 for m in manifest.values() if m["label"] == "honest")
    n_f = len(manifest) - n_h
    print("\n" + "=" * 86)
    print("CALMA BENCHMARK - catch a wrong number (%d cases: %d honest, %d flawed; "
          "3 tracks: synthetic / external [UCI+sklearn] / real-world)" % (len(manifest), n_h, n_f))
    print("=" * 86)
    print("%-24s %7s %8s %8s %9s %8s" % ("method", "catch%", "caught", "MISSED", "FALSE-AL", "abstain"))
    print("-" * 86)
    summary = {}
    for name, fn in methods.items():
        c = _confusion(rows_for(fn))
        summary[name] = c
        print("%-24s %6.0f%% %5d/%-2d %8d %9d %8d"
              % (name, (c["catch_rate"] or 0) * 100, c["caught"], c["flawed"],
                 c["false_confirm"], c["false_alarm"], c["abstain_flawed"] + c["abstain_honest"]))
    print("-" * 86)
    print("MISSED = flawed called honest (false-confirm) | FALSE-AL = honest called flawed (false-alarm)")

    # tier table
    print("\nBy flaw tier (catch%% on flawed; false-alarms on honest):")
    print("%-24s %9s %9s %10s %12s" % ("method", "obvious", "subtle", "realworld", "false-alarm"))
    tiers = {}
    for name, fn in methods.items():
        row = {}
        for tier in ("obvious", "subtle"):
            rr = rows_for(fn, lambda m, t=tier: m.get("tier") == t)
            row[tier] = sum(1 for r in rr if r["pred"] == "flawed") / len(rr) if rr else 0
        rw = rows_for(fn, lambda m: m.get("track") == "realworld" and m["label"] == "flawed")
        row["realworld"] = sum(1 for r in rw if r["pred"] == "flawed") / len(rw) if rw else 0
        ho = rows_for(fn, lambda m: m["label"] == "honest")
        row["false_alarm"] = sum(1 for r in ho if r["pred"] == "flawed")
        tiers[name] = row
        print("%-24s %8.0f%% %8.0f%% %9.0f%% %12d"
              % (name, row["obvious"] * 100, row["subtle"] * 100, row["realworld"] * 100,
                 row["false_alarm"]))

    # track table
    print("\nBy track:")
    print("%-24s %12s %18s %12s" % ("method", "synthetic", "external(UCI)", "real-world"))
    tracks = {}
    for name, fn in methods.items():
        row = {}
        line = "%-24s" % name
        for tk in ("synthetic", "external", "realworld"):
            c = _confusion(rows_for(fn, lambda m, t=tk: m.get("track") == t))
            row[tk] = c
            line += " %6.0f%%/%dw " % ((c["catch_rate"] or 0) * 100, c["wrong"])
        tracks[name] = row
        print(line + "   (catch%/wrong-verdicts)")

    # per-family for the site charts
    fams = {}
    for fam in sorted({m["family"] for m in manifest.values()}):
        fams[fam] = {}
        for name, fn in methods.items():
            c = _confusion(rows_for(fn, lambda m, f=fam: m.get("family") == f))
            fams[fam][name] = {"catch_rate": c["catch_rate"], "wrong": c["wrong"],
                               "flawed": c["flawed"], "honest": c["honest"]}

    if agent_rows:
        inst = sum(1 for r in agent_rows if r.get("unstable")) / len(agent_rows)
        usd = sum(r.get("usd", 0) for r in agent_rows)
        ams = sorted(r["ms"] for r in agent_rows)
        vfam = {"leakage", "overfitting", "execution-realism", "contamination"}
        vrows = [r for r in agent_rows if r.get("family") in vfam and r.get("label") == "flawed"]
        line = ("\nagent-with-exec extras: verdict-instability %.0f%% (Calma 0%%) | cost $%.2f | p50 %dms"
                % (inst * 100, usd, ams[len(ams) // 2]))
        if vrows:
            line += " | validity-family catch %d/%d" % (
                sum(1 for r in vrows if r.get("prediction") == "flawed"), len(vrows))
        print(line)
        summary["agent-with-exec_extras"] = {"instability": inst, "usd": usd, "p50_ms": ams[len(ams) // 2]}
    lat = sorted(r["ms"] for r in json.load(open(os.path.join(HERE, "results", "calma.json"))))
    site = {"n_cases": len(manifest), "n_honest": n_h, "n_flawed": n_f,
            "overall": summary, "tiers": tiers, "tracks": {
                name: {tk: {"catch_rate": v[tk]["catch_rate"], "wrong": v[tk]["wrong"]}
                       for tk in v} for name, v in tracks.items()},
            "families": fams, "calma_p50_ms": lat[len(lat) // 2]}
    json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w"), indent=2)
    json.dump(site, open(os.path.join(HERE, "results", "site_data.json"), "w"), indent=2)
    print("\nwrote results/summary.json + results/site_data.json (calma p50 %dms)" % site["calma_p50_ms"])


if __name__ == "__main__":
    main()
