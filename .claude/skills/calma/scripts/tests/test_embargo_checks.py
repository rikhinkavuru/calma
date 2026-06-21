"""WS-C(i) era-embargo / purged-CV leakage. Detection A (the deterministic purge-gap gate) must FIRE on an
un-embargoed split and stay SILENT on a correctly-purged one; the INVALIDATED promotion is scope-guarded on
a validation/OOS/leaderboard claim. Detection B reports the leading-era CORR inflation (the leakage premium)
and, standalone, is a soft CAVEAT. The required-purge formula reproduces Numerai's published 8 (20-day) /
16 (60-day). Pure stdlib. Run: python3 test_embargo_checks.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import draft_contract as DC  # noqa: E402
import embargo_checks as EMB  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# ---- fixtures: write train.csv (era only) + predictions.csv (era,prediction,target) to a temp dir -------
_DIR = tempfile.mkdtemp(prefix="calma_emb_")


def _write(name, header, rows):
    p = os.path.join(_DIR, name)
    with open(p, "w", newline="") as f:
        f.write(",".join(header) + "\n")
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")
    return name


# 6 rows/era. Leading eras: pred ALIGNED with target (high per-era CORR). Tail eras: pred ANTI-aligned
# (low/negative CORR). So mean(all eras) > mean(after dropping the leading `required` eras) -> inflation>0,
# exactly the leakage premium the un-purged leading eras add.
_ALIGN = [(1, 0.1), (2, 0.2), (3, 0.3), (4, 0.4), (5, 0.5), (6, 0.6)]
_ANTI = [(6, 0.1), (5, 0.2), (4, 0.3), (3, 0.4), (2, 0.5), (1, 0.6)]


def _val_rows(first_era, n_lead, n_tail):
    rows = []
    e = first_era
    for _ in range(n_lead):
        for pred, tgt in _ALIGN:
            rows.append(("era%04d" % e, pred, tgt))
        e += 1
    for _ in range(n_tail):
        for pred, tgt in _ANTI:
            rows.append(("era%04d" % e, pred, tgt))
        e += 1
    return rows


# train eras 1..100 (max_train_era = 100), as "era0001".."era0100"
_write("train.csv", ["era"], [("era%04d" % i,) for i in range(1, 101)])
# un-embargoed validation: starts at era 101 (gap = 101-100 = 1 <= required 8); 8 leading + 12 tail eras
_write("preds_leaky.csv", ["era", "prediction", "target"], _val_rows(101, 8, 12))
# correctly-purged validation: starts at era 110 (gap = 110-100 = 10 > 8)
_write("preds_clean.csv", ["era", "prediction", "target"], _val_rows(110, 8, 12))


def _contract(val, **emb):
    e = {"era_col": "era", "horizon_days": 20, "train": "train.csv", "val": val}
    e.update(emb)
    return {"embargo": e,
            "metrics": [{"metric_id": "numerai_corr", "artifact": val,
                         "binding": {"prediction": "prediction", "target": "target", "era": "era"},
                         "claimed_value": 0.03, "headline": True}]}


# ---- required-purge formula: reproduces Numerai's published 8 (20-day) / 16 (60-day) ------------------
truth(EMB._required_purge({"horizon_days": 20}) == 8, "required_purge: 20-day target -> 8 (ceil(20/5)+4)")
truth(EMB._required_purge({"horizon_days": 60}) == 16, "required_purge: 60-day target -> 16 (ceil(60/5)+4)")
truth(EMB._required_purge({"purge_eras": 5}) == 5, "required_purge: declared purge_eras wins")
truth(EMB._required_purge({"horizon_days": 20, "embargo_buffer_eras": 0}) == 4, "required_purge: buffer override")
truth(EMB._required_purge({}) == 8, "required_purge: default horizon 20 -> 8")

# ---- era parsing ('era0123' -> 123) ------------------------------------------------------------------
truth(EMB._parse_era("era0123") == 123 and EMB._parse_era("0123") == 123 and EMB._parse_era("123") == 123,
      "parse_era: trailing integer of era labels")
truth(EMB._parse_era("abc") is None and EMB._parse_era("") is None, "parse_era: no trailing int -> None")

# ---- Detection A: un-embargoed split fires; purged split is silent -----------------------------------
fa = EMB.check_era_gap(_contract("preds_leaky.csv"), _DIR, "c1")
truth(fa and fa["dimension"] == "era-embargo" and fa["embargo_kind"] == "purge-gap"
      and fa["validity_class"] == "authoritative", "A: un-embargoed split (gap 1 <= 8) FIRES authoritative")
truth(fa and "era 101" in fa["locator"] and "era 100" in fa["locator"] and "needs 8 purged eras" in fa["locator"],
      "A: locator names the val-start, train-end, and required purge")
truth(fa and "leakage premium" in fa["locator"] and "inflate the headline" in fa["locator"],
      "A: the leakage-premium inflation number is attached (Detection B evidence)")
truth(EMB.check_era_gap(_contract("preds_clean.csv"), _DIR, "c1") is None,
      "A: correctly-purged split (gap 10 > 8) is SILENT")

# horizon 60 needs 16: even gap 10 now fires
truth(EMB.check_era_gap(_contract("preds_clean.csv", horizon_days=60), _DIR, "c1") is not None,
      "A: 60-day horizon needs 16 -> gap 10 now FIRES")

# ---- Detection B inflation math ----------------------------------------------------------------------
inf = EMB._inflation(_contract("preds_leaky.csv"), _DIR, {"era_col": "era", "horizon_days": 20,
                                                          "val": "preds_leaky.csv"}, 8)
truth(inf and inf["inflation"] > 0 and inf["n_dropped"] == 8 and inf["n_eras"] == 20,
      "B: leading eras inflate the mean CORR (all_mean > dropped_mean)")

# ---- promotion: scope-guarded INVALIDATED --------------------------------------------------------------
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "metric": "numerai_corr", "claimed_value": 0.03,
            "recomputed_value": 0.03, "verdict": V.verdict(vi), "input_binding_status": "independently-bound",
            "headline_confidence": 0.9, "verdict_inputs": vi, "verdict_status": "stable",
            "waivable": False, "reason": "ok"}


def _promote(contract, claim_text, val="preds_leaky.csv"):
    claims = [_confirmed_claim()]
    findings = EMB.run_checks(contract, _DIR, "c1", claim_text)
    EMB.apply_validity(claims, findings, contract, claim_text, base=_DIR)
    return claims[0], findings


hc, hf = _promote(_contract("preds_leaky.csv"), "validation corr 0.03")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "era-embargo",
      "promote: un-embargoed split + a validation claim -> INVALIDATED('era-embargo')")
bc, _ = _promote(_contract("preds_leaky.csv"), "corr 0.03")  # bare number, no OOS scope word
truth(bc["verdict"] == V.CAVEATS, "scope-guard: a bare corr (no validation/OOS scope) -> CAVEATS")
cc, cf = _promote(_contract("preds_clean.csv"), "validation corr 0.03", val="preds_clean.csv")
truth(cc["verdict"] == V.CONFIRMED and cf == [], "promote: a purged split stays CONFIRMED (no finding)")

# ---- Detection B standalone: no train declared -> soft caveat -----------------------------------------
def _contract_no_train(val):
    return {"embargo": {"era_col": "era", "horizon_days": 20, "val": val},
            "metrics": [{"metric_id": "numerai_corr", "artifact": val,
                         "binding": {"prediction": "prediction", "target": "target", "era": "era"},
                         "claimed_value": 0.03, "headline": True}]}


sc, sf = _promote(_contract_no_train("preds_leaky.csv"), "validation corr 0.03")
truth(any(f["embargo_kind"] == "leading-inflation" and f["validity_class"] == "soft" for f in sf),
      "B standalone: material leading inflation w/ no train range -> soft finding")
truth(sc["verdict"] == V.CAVEATS, "B standalone: soft inflation -> CAVEATS (never INVALIDATED)")

# ---- family_status + abstention ----------------------------------------------------------------------
truth(EMB.family_status({}, []) == "not-applicable", "family_status: not-applicable without an embargo block")
truth(EMB.family_status(_contract("preds_leaky.csv"), hf) == "flagged", "family_status: flagged when fired")
truth(EMB.run_checks({}, _DIR, "c1") == [], "ABSTAINS entirely without an embargo block")

# ---- contract validation: shape + unknown-key rejection ----------------------------------------------
truth(DC.validate_contract({"run": {"entrypoint": "x"}, "artifacts": [], "metrics": [],
                            "embargo": {"horizon_days": 20, "train": "t.csv"}}) == [],
      "validate: a well-formed embargo block is accepted")
errs = DC.validate_contract({"run": {"entrypoint": "x"}, "artifacts": [], "metrics": [],
                             "embargo": {"horizon_dayz": 20}})
truth(any("not a recognized key" in e for e in errs), "validate: an unknown embargo key (typo) is rejected")
errs2 = DC.validate_contract({"run": {"entrypoint": "x"}, "artifacts": [], "metrics": [],
                              "embargo": {"horizon_days": -5}})
truth(any("non-negative" in e for e in errs2), "validate: a negative horizon_days is rejected")

print("embargo_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
