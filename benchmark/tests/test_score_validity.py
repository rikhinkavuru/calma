"""G2: the validity cut MEASURES something. (1) every validity_family case is engine-derived - Calma's
recorded verdict is INVALIDATED (-> prediction flawed); (2) score.py reports reproducibility vs validity
as two separate axes, reading the engine's `validity_family` tag (NOT the metric `family`, which was the
dead-code bug); a recompute-only method false-confirms the validity cut while Calma catches it 100%.
Snapshots + restores the tracked result files so the tree is left unchanged. Run: python3 this_file.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
RES = os.path.join(BENCH, "results")

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


manifest = json.load(open(os.path.join(BENCH, "manifest.json")))
calma = {r["id"]: r["prediction"] for r in json.load(open(os.path.join(RES, "calma.json")))}
vcases = [m for m in manifest if m.get("validity_family")]

# (1) engine-derived: every tagged validity case is one Calma actually INVALIDATES (prediction flawed)
truth(len(vcases) >= 8, "the validity cut is non-empty (got %d tagged cases)" % len(vcases))
missing = [m["id"] for m in vcases if calma.get(m["id"]) != "flawed"]
truth(not missing, "Calma INVALIDATES every validity_family case (engine-derived tag); offenders: %s" % missing)
fams = sorted({m["validity_family"] for m in vcases})
truth(len(fams) >= 6, "validity cut spans the M3-M4 families (got %s)" % fams)

# (2) the two-axis cut renders, reading validity_family. Use a CONTROLLED synthetic agent that
# false-confirms every validity case (calls it honest) but catches the core recompute flaws.
snap = {}
for f in ("summary.json", "site_data.json", "agent.json"):
    p = os.path.join(RES, f)
    snap[f] = open(p, "rb").read() if os.path.exists(p) else None

synthetic = []
for m in manifest:
    if m.get("validity_family"):
        pred = "honest"                                   # recompute-only -> false-confirm (misses invalidity)
    else:
        pred = "flawed" if m["label"] == "flawed" else "honest"
    synthetic.append({"id": m["id"], "prediction": pred, "label": m["label"], "family": m.get("family"),
                      "tier": m.get("tier"), "track": m.get("track"), "validity_family": m.get("validity_family"),
                      "recomputed": None, "reruns": [pred], "unstable": False, "ms": 1, "usd": 0.0,
                      "isolation_tier": "seatbelt-verified"})
try:
    json.dump(synthetic, open(os.path.join(RES, "agent.json"), "w"))
    p = subprocess.run([sys.executable, os.path.join(BENCH, "score.py")], capture_output=True, text=True)
    truth(p.returncode == 0, "score.py exits 0 (got %d: %s)" % (p.returncode, p.stderr[-200:]))
    site = json.load(open(os.path.join(RES, "site_data.json")))
    truth("axes" in site and "validity_by_family" in site, "site_data carries the two-axis cut + per-family table")
    truth(site.get("validity_cut_n") == len(vcases), "validity_cut_n matches the tagged-case count")
    ax = site.get("axes", {})
    truth(ax.get("Calma", {}).get("validity_catch") == 1.0, "Calma validity catch-rate = 1.0 (INVALIDATES all)")
    truth(ax.get("Calma", {}).get("validity_n") == len(vcases), "Calma validity cut n = tagged count")
    truth(ax.get("agent-with-exec", {}).get("validity_catch") == 0.0,
          "the recompute-only agent false-confirms the validity cut -> 0%% (the measured cell)")
    truth((ax.get("agent-with-exec", {}).get("reproducibility_catch") or 0) > 0.5,
          "...yet the same agent catches the core recompute cut (the two axes genuinely differ)")
finally:
    for f, b in snap.items():
        p = os.path.join(RES, f)
        if b is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            open(p, "wb").write(b)

print("score_validity(G2): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
