"""S4 — subset-scoped artifact binding: recompute a claim on the SUBSET of rows it's about (the ebv-ms case,
`homology_sensitivity_testable` = recall over `pfam_testable==True`). Hermetic: temp repos, the deterministic
recompute Judge (SYNTH.recompute_any), no run/sandbox/LLM. Asserts the scoped recompute CONFIRMS a subset
claim, a WRONG scoped value REFUTES (never laundered by the all-rows number), and unscoped claims are
unaffected — so the false-confirm surface the subset binding adds is a wrong-scope→REFUTED, not a false CONFIRM."""
import pipeline
from core import artifacts as A
from core import verdict as VD
from synth import formula as SYNTH

# 8 rows. testable=yes (rows 0-5): positives label=1 at 0,1,2,3 → pred 1,1,1,0 → recall 3/4 = 0.75.
# all 8 rows: positives at 0,1,2,3,6,7 → pred 1,1,1,0,0,0 → recall 3/6 = 0.50. The subset number differs.
_CSV = ("label,pred,pfam_testable\n"
        "1,1,yes\n1,1,yes\n1,1,yes\n1,0,yes\n0,0,yes\n0,1,yes\n"
        "1,0,no\n1,0,no\n")


def _repo(tmp_path):
    (tmp_path / "benchmark_classifier.csv").write_text(_CSV)
    return str(tmp_path)


# ── artifacts.py units ────────────────────────────────────────────────────────────────────────────────────────
def test_read_scoped_finds_roles_and_boolean_scope_column(tmp_path):
    roles, scope = A.read_scoped(_repo(tmp_path) + "/benchmark_classifier.csv")
    assert "y_true" in roles and "y_pred" in roles
    assert "pfam_testable" in scope and len(scope["pfam_testable"]) == 8


def test_read_scoped_excludes_all_true_and_all_false_columns(tmp_path):
    (tmp_path / "p.csv").write_text("label,pred,flag_all,flag_none\n1,1,1,0\n0,0,1,0\n1,1,1,0\n")
    _roles, scope = A.read_scoped(str(tmp_path / "p.csv"))
    assert scope == {}                                    # neither all-1 nor all-0 is a real subset split


def test_scope_qualifiers_strips_metric_and_split_words():
    assert A.scope_qualifiers("homology_sensitivity_testable") == ["homology", "testable"]
    assert A.scope_qualifiers("test recall") == []        # metric + split words only → no qualifier


def test_bind_scope_matches_token_to_column_and_refuses_ambiguity():
    assert A.bind_scope(["testable"], ["pfam_testable", "y_true"]) == "pfam_testable"
    assert A.bind_scope(["rare"], ["pfam_testable"]) is None                   # no match
    assert A.bind_scope(["set"], ["trainset", "testset"]) is None             # ambiguous (2 cols) → refuse


def test_recompute_scoped_guards_reject_full_and_tiny_subsets(tmp_path):
    roles, scope = A.read_scoped(_repo(tmp_path) + "/benchmark_classifier.csv")
    allrows = ["1"] * 8
    assert A.recompute_scoped(roles, allrows, "recall", SYNTH.recompute_any) is None        # all rows → not a subset
    assert A.recompute_scoped(roles, ["1", "0", "0", "0", "0", "0", "0", "0"], "recall",
                              SYNTH.recompute_any) is None                                   # <3 rows → unreliable


def test_bind_and_recompute_scoped_end_to_end(tmp_path):
    roles, scope = A.read_scoped(_repo(tmp_path) + "/benchmark_classifier.csv")
    res, col = A.bind_and_recompute_scoped("homology_sensitivity_testable", roles, scope, "recall",
                                           SYNTH.recompute_any)
    assert col == "pfam_testable"
    assert abs(res["value"] - 0.75) < 1e-9                # the SUBSET recall, not the 0.50 all-rows recall


# ── _artifact_verify integration: the verdict ─────────────────────────────────────────────────────────────────
def _claim(value, rawname):
    return {"id": "c1", "metric": "recall", "value": value,
            "location": "results.json::%s" % rawname, "source": "results-json", "confidence": 0.6}


def test_scoped_claim_confirms_on_the_subset(tmp_path):
    out = pipeline._artifact_verify(_repo(tmp_path), [_claim("0.75", "homology_sensitivity_testable")])
    rec = out.get("c1")
    assert rec and rec["verdict"] == VD.CONFIRMED and "subset" in rec.get("reason", "").lower()


def test_scoped_claim_is_not_laundered_by_the_all_rows_number(tmp_path):
    # 0.50 is the ALL-ROWS recall; the claim is about the testable SUBSET (0.75). Scoping to the right rows must
    # REFUTE the all-rows value — a subset claim can never be confirmed by the broad recompute (groundcheck).
    out = pipeline._artifact_verify(_repo(tmp_path), [_claim("0.50", "homology_sensitivity_testable")])
    assert out["c1"]["verdict"] == VD.REFUTED


def test_unscoped_claim_uses_the_full_recompute(tmp_path):
    # a plain recall claim (no subset qualifier) → the unchanged all-rows recompute (0.50) → CONFIRMED.
    out = pipeline._artifact_verify(_repo(tmp_path), [_claim("0.50", "recall")])
    rec = out.get("c1")
    assert rec and rec["verdict"] == VD.CONFIRMED and "subset" not in rec.get("reason", "").lower()
