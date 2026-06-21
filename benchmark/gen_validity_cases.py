"""Add two NEW validity-cut benchmark cases for the families shipped this cycle - era-embargo (WS-C i) and
risk-sim simulation_assumptions (WS-C ii). Both are constructed so the HEADLINE NUMBER REPRODUCES (a
recompute-only verifier / an LLM judge calls them honest) while Calma INVALIDATES them via the validity
layer - exactly the cut that separates calma from every recompute-or-judge substitute.

Writes benchmark/cases/{emb_a,sim_a}/ (artifacts + a committed verify.yaml) and PRINTS the two manifest
entries to splice into manifest.json. The claim values are computed from the data by the engine itself, so
they reproduce to floating-point noise. Run: python3 benchmark/gen_validity_cases.py
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", ".claude", "skills", "calma", "scripts")
sys.path.insert(0, SKILL)
import numeric as N  # noqa: E402
import recompute as RC  # noqa: E402

CASES = os.path.join(HERE, "cases")


def _w(path, rows):
    with open(path, "w", newline="") as f:
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")


# ---- era-embargo case: un-purged Numerai split (val starts 1 era after train; horizon 20 needs 8) -------
def gen_embargo():
    d = os.path.join(CASES, "emb_a")
    os.makedirs(d, exist_ok=True)
    # train eras 1..100; validation eras 101..120 - a gap of 1 <= the required 8-era purge for the 20-day
    # target, so Detection A (the deterministic era-gap GATE) fires regardless of the metric value. The
    # predictions weakly track the target (a realistic small positive validation CORR ~0.05 that REPRODUCES
    # exactly); the result is invalid purely because the split is un-purged.
    rng = random.Random(7)
    _w(os.path.join(d, "train.csv"), [["era"]] + [["era%04d" % i] for i in range(1, 101)])
    rows = [["era", "prediction", "target"]]
    targets = [0.0, 0.25, 0.5, 0.75, 1.0]
    for e in range(101, 121):                      # 20 validation eras, 25 rows each
        for _ in range(25):
            t = rng.choice(targets)
            pred = round(min(max(0.5 * t + rng.gauss(0.0, 0.35), 0.0), 1.0), 4)  # weak signal + noise
            rows.append(["era%04d" % e, pred, t])
    _w(os.path.join(d, "predictions.csv"), rows)
    contract = {"run": {"entrypoint": "predict.py", "network": "off"}, "env": {"ecosystem": "python"},
                "artifacts": [{"path": "predictions.csv", "columns": {
                    "era": {"tag": "era"}, "prediction": {"tag": "prediction"}, "target": {"tag": "target"}}}],
                "embargo": {"horizon_days": 20, "era_col": "era", "train": "train.csv", "val": "predictions.csv"},
                "metrics": [{"metric_id": "numerai_corr", "artifact": "predictions.csv",
                             "binding": {"prediction": "prediction", "target": "target", "era": "era"},
                             "headline": True}]}
    json.dump(contract, open(os.path.join(d, "verify.yaml"), "w"))
    open(os.path.join(d, "predict.py"), "w").write("pass\n")  # no-op entrypoint so the run exits 0
    claim = round(RC.recompute_contract(os.path.join(d, "verify.yaml"), base=d)["metrics"][0]["value"], 4)
    return {"id": "emb_a_invalid", "dir": d, "claim": claim,
            "claim_text": "validation corr %.4f (out-of-sample, embargoed)" % claim, "display": "numerai corr",
            "family": "stats", "metric": "numerai_corr", "label": "flawed", "n_rows": 120, "tier": "subtle",
            "track": "synthetic", "true_value": claim, "validity_family": "era-embargo",
            "artifact": "predictions.csv"}


# ---- risk-sim case: the VaR reproduces, but two liquidations hit one account in one block (Chaos #6) -----
def gen_simassume():
    d = os.path.join(CASES, "sim_a")
    os.makedirs(d, exist_ok=True)
    # a per-iteration P&L return series with a fat negative (loss) tail, so the p99 VaR is a realistic
    # positive loss figure that REPRODUCES; the result is invalid because of the liquidation invariant below.
    rng = random.Random(11)
    losses = [round(rng.gauss(0.002, 0.03), 4) for _ in range(94)] + [-0.18, -0.21, -0.15, -0.25, -0.19, -0.17]
    rng.shuffle(losses)
    _w(os.path.join(d, "losses.csv"), [["loss"]] + [[x] for x in losses])
    # an event log with a DOUBLE liquidation of one account in one block (the invariant violation)
    _w(os.path.join(d, "events.csv"),
       [["account", "block", "event", "repaid", "pre_debt"],
        ["0xA", 100, "liquidation", 40, 100], ["0xA", 100, "liquidation", 30, 60],
        ["0xB", 101, "liquidation", 20, 100], ["0xC", 102, "liquidation", 15, 50]])
    contract = {"run": {"entrypoint": "sim.py", "network": "off"}, "env": {"ecosystem": "python"},
                "artifacts": [{"path": "losses.csv", "columns": {"loss": {"tag": "return"}}}],
                "simulation_assumptions": {"firm": "chaos", "event_log": "events.csv",
                                           "var": {"loss_log": "losses.csv", "percentile": 0.99}},
                "metrics": [{"metric_id": "value_at_risk", "artifact": "losses.csv",
                             "binding": {"return": "loss"}, "convention": "p99", "headline": True}]}
    json.dump(contract, open(os.path.join(d, "verify.yaml"), "w"))
    open(os.path.join(d, "sim.py"), "w").write("pass\n")
    claim = round(RC.recompute_contract(os.path.join(d, "verify.yaml"), base=d)["metrics"][0]["value"], 4)
    return {"id": "sim_a_invalid", "dir": d, "claim": claim,
            "claim_text": "p99 VaR %.4f (methodology-sound, conservative)" % claim, "display": "p99 VaR",
            "family": "quant", "metric": "value_at_risk", "label": "flawed", "n_rows": 100, "tier": "subtle",
            "track": "synthetic", "true_value": claim, "validity_family": "simulation-assumptions",
            "artifact": "losses.csv"}


def main():
    entries = [gen_embargo(), gen_simassume()]
    print("Generated %d validity cases. Manifest entries (dir paths made portable):" % len(entries))
    for e in entries:
        printable = dict(e, dir="benchmark/cases/%s" % os.path.basename(e["dir"]))
        print(json.dumps(printable))
    # splice into manifest.json (idempotent: replace any existing entry with the same id)
    mpath = os.path.join(HERE, "manifest.json")
    man = json.load(open(mpath))
    by_id = {c["id"]: c for c in man}
    for e in entries:
        by_id[e["id"]] = e
    json.dump(list(by_id.values()), open(mpath, "w"), indent=2)  # match the existing pretty-print
    print("Spliced %d entries into manifest.json (now %d cases)." % (len(entries), len(by_id)))


if __name__ == "__main__":
    main()
