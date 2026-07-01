"""Feature 5 — the learning flywheel. Banks reusable pre-verdict experience (plans / conventions) and, in a
SEPARATE firewalled namespace, observed known values. These pin bank/retrieve/telemetry and that known values
are never returned by the reusable lookup path."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from synth import experience as EXP  # noqa: E402


def test_bank_and_lookup_reusable(tmp_path):
    b = EXP.ExperienceBank(str(tmp_path / "bank.json"))
    b.bank("famA", EXP.PLAN, {"entry": ["eval.py"], "pip_install": ["numpy"]})
    got = b.lookup("famA", EXP.PLAN)
    assert got and got.payload["entry"] == ["eval.py"]
    assert b.lookup("famA", EXP.TARGETS) is None            # nothing banked for that kind


def test_telemetry_tiers_competing_records(tmp_path):
    b = EXP.ExperienceBank(str(tmp_path / "b.json"))
    b.bank("fam", EXP.PLAN, {"entry": ["good.py"]})
    b.bank("fam", EXP.PLAN, {"entry": ["bad.py"]})
    # mark the first a success, the second a failure
    b.records[0].telemetry["successes"] = 3
    b.records[1].telemetry["failures"] = 2
    assert b.lookup("fam", EXP.PLAN).payload["entry"] == ["good.py"]


def test_known_value_is_a_separate_namespace(tmp_path):
    b = EXP.ExperienceBank(str(tmp_path / "b.json"))
    b.bank_known_value("fam", "accuracy", 0.91, dataset="iris")
    # known values are NEVER returned by the reusable lookup path
    assert b.lookup("fam", EXP.KNOWN_VALUE) is None
    assert b.lookup("fam", "known_value") is None
    # they are reachable only via the firewalled hints() API
    hs = b.hints("fam", "accuracy")
    assert len(hs) == 1 and hs[0].value == 0.91


def test_bank_refuses_known_value_via_reusable_path(tmp_path):
    b = EXP.ExperienceBank(str(tmp_path / "b.json"))
    try:
        b.bank("fam", EXP.KNOWN_VALUE, {"value": 0.9})
        assert False, "bank() must refuse the known_value kind"
    except ValueError:
        pass


def test_bank_experience_writes_conventions_and_hints(tmp_path):
    b = EXP.ExperienceBank(str(tmp_path / "b.json"))
    result = {"claims": [
        {"metric": "sharpe", "verdict": "CONFIRMED", "convention": {"ddof": 0},
         "diff": {"produced": 1.2, "recomputed": 1.2}},
        {"metric": "accuracy", "verdict": "REFUTED", "diff": {"produced": 0.9, "recomputed": 0.8}},
    ]}
    EXP.bank_experience(result, str(tmp_path), b)
    key = EXP.key_signature(str(tmp_path))
    assert b.lookup(key, EXP.CONVENTIONS).payload["sharpe"] == {"ddof": 0}
    # only the VERIFIED claim contributed a known-value hint (the REFUTED one did not)
    assert [h.metric for h in b.hints(key)] == ["sharpe"]
