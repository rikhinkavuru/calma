"""Regression tests for the round-2 adversarial audit fixes. Pure stdlib.

Each block locks in a defect found by the audit so it can't silently come back:
  - ed25519 low-order / identity public-key rejection (keyless-forgery hole)
  - compare() positional join (duplicate metric_id collapse -> false CONFIRMED)
  - cache fingerprint covers the whole input tree (stale CONFIRMED on an edited input)
  - sniffer 'return' finance-gate (benign engineering prose auto-verified)
  - determinism stamp: getattr-obfuscated urandom / subprocess / os.system
  - validity: declared-but-unreadable corpus/split -> CAN'T-CONFIRM, not silent 'checked'
  - leakage target-leakage excludes the model's OWN prediction column (false positive)
  - realism: negative declared friction is not silently dropped
  - suggest k<1 floored; recipe-count message not hardcoded
  - report.fmt_pair: a REFUTED never prints two identical-looking numbers
  - intake restore env strips parent secrets
  - compiler refuses a world-writable reference venv
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compare as C  # noqa: E402
import compiler as CO  # noqa: E402
import contamination_checks as CC  # noqa: E402
import ed25519  # noqa: E402
import intake  # noqa: E402
import leakage_checks as LC  # noqa: E402
import realism_checks as RL  # noqa: E402
import report as REP  # noqa: E402
import run_hermetic as RH  # noqa: E402
import sniff_claims as SN  # noqa: E402
import suggest as SG  # noqa: E402
import verdict as V  # noqa: E402

import tempfile

_checks = 0
_fails = 0


def truth(cond, label):
    global _checks, _fails
    _checks += 1
    if not cond:
        _fails += 1
        print("  FAIL [%s]" % label)


# --- ed25519: low-order / identity public keys are rejected -------------------
_ident = bytes([1] + [0] * 31)
truth(ed25519.verify(_ident, b"m", b"\x00" * 64) is False, "identity pubkey rejected (no keyless forgery)")
truth(ed25519.verify(bytes(32), b"m", b"\x00" * 64) is False, "all-zero pubkey rejected")
truth(ed25519._is_small_order(ed25519._decompress(_ident)), "identity is flagged small-order")
_seed = bytes.fromhex("9d61b19deffe7e8c0e7e8c0e7e8c0e7e8c0e7e8c0e7e8c0e7e8c0e7e8c0e7e8c"[:64])
_pub = ed25519.secret_to_public(_seed)
_sig = ed25519.sign(_seed, b"hello")
truth(ed25519.verify(_pub, b"hello", _sig) is True, "legitimate signature still verifies")
truth(not ed25519._is_small_order(ed25519._decompress(_pub)), "legit pubkey not flagged small-order")

# --- compare(): two claims on the SAME recipe / different columns don't collapse
_rec = {"metrics": [{"metric_id": "column_mean", "value": 10.0, "terms": {}, "k_spread": 0.0, "degenerate": False},
                    {"metric_id": "column_mean", "value": 2.0, "terms": {}, "k_spread": 0.0, "degenerate": False}],
        "baselines": []}
_con = {"metrics": [{"metric_id": "column_mean", "claimed_value": 2.0, "headline": True, "binding": {"col": "a"},
                     "claim_confirmed": True, "binding_status": "independently-bound"},
                    {"metric_id": "column_mean", "claimed_value": 2.0, "headline": False, "binding": {"col": "b"},
                     "claim_confirmed": True, "binding_status": "independently-bound"}]}
_r = C.compare(_rec, _con, isolation_tier="seatbelt-verified", determinism_mode="controlled-to-bit", m2_calibrated=True)
truth(_r["metrics"][0]["recomputed"] == 10.0, "compare joins positionally (claim a sees its own 10.0)")
truth(_r["metrics"][0]["verdict"] == "REFUTED", "the fabricated claim a (2.0 vs true 10.0) is REFUTED, not collapsed to CONFIRMED")
truth(_r["metrics"][1]["recomputed"] == 2.0 and _r["metrics"][1]["verdict"] == "CONFIRMED", "claim b stays CONFIRMED")

# --- cache fingerprint covers the whole input tree ----------------------------
import calma  # noqa: E402
_d = tempfile.mkdtemp(prefix="calma-r2-")
open(os.path.join(_d, "main.py"), "w").write("x=1\n")
open(os.path.join(_d, "config.json"), "w").write('{"scale": 1.0}')
open(os.path.join(_d, "out.csv"), "w").write("v\n2.0\n")
_cn = {"run": {"entrypoint": "main.py"}, "artifacts": [{"path": "out.csv"}],
       "metrics": [{"metric_id": "column_mean", "artifact": "out.csv", "binding": {"col": "v"}}]}
_fp1 = calma._input_fingerprint(_d, _cn)
truth(calma._input_fingerprint(_d, _cn) == _fp1, "fingerprint is stable on a true no-op (cache still hits)")
open(os.path.join(_d, "config.json"), "w").write('{"scale": 5.0}')  # a NON-output input the entrypoint reads
truth(calma._input_fingerprint(_d, _cn) != _fp1, "editing a non-output input changes the fingerprint (no stale CONFIRMED)")

# --- sniffer: bare-noun 'return' requires a finance subject -------------------
truth(SN.sniff("The API error return was 5% this week.") == [], "'API error return 5%' is silent (benign)")
truth(SN.sniff("The cache hit return was 80%.") == [], "'cache hit return 80%' is silent (benign)")
truth(any(c["metric"] == "total_return" for c in SN.sniff("The strategy return was 23% last year.")),
      "'strategy return 23%' still fires (finance subject present)")

# --- determinism stamp hardening ---------------------------------------------
def _det(code):
    d = tempfile.mkdtemp(prefix="calma-det-")
    p = os.path.join(d, "e.py")
    open(p, "w").write(code)
    return RH._detect_determinism(p, d)[0]


truth(_det("import os\nx=getattr(os,'ur'+'andom')(2)\n") != "controlled-to-bit", "getattr-obfuscated urandom is not controlled-to-bit")
truth(_det("import subprocess\nsubprocess.run(['date'])\n") != "controlled-to-bit", "subprocess is not controlled-to-bit")
truth(_det("import os\nos.system('date')\n") == "uncontrolled", "os.system is uncontrolled")
truth(_det("x=sum([1,2,3])\nopen('o','w').write(str(x))\n") == "controlled-to-bit", "pure stdlib stays controlled-to-bit")
truth(_det("d={}\nv=getattr(d,'get')('k')\n") == "controlled-to-bit", "benign getattr with a constant attr is not downgraded")

# --- validity: declared-but-unreadable corpus / split -> CAN'T-CONFIRM --------
# A realistic verdict_inputs that WOULD be CONFIRMED on its own, so the assertion below proves the
# headline label is actually FLIPPED (the round-2 re-audit caught that setting the flag alone left a
# stale CONFIRMED - the early-return skipped the verdict re-derivation).
def _confirmed_vi():
    return {"gap": 0.0, "effective_budget": 1e-9, "margin": 1.0, "claim_outside_ci": False,
            "sign_agrees": True, "band_coverage_ok": True, "binding_status": "independently-bound",
            "isolation_tier": "seatbelt-verified", "container_present": True, "untrusted": False,
            "exit_codes": [0], "killed": False, "determinism_mode": "controlled-to-bit",
            "sufficient_k": True, "unbounded_op_present": False, "path_dependent": False,
            "m2_calibrated": True, "recompute_degenerate": False, "claim_confirmed_target": True,
            "convention_capped": False, "fraud_multiple_met": False, "outputs_unstable": False,
            "no_claim_reproduced": False}


truth(V.verdict(_confirmed_vi()) == "CONFIRMED", "the baseline verdict_inputs is CONFIRMED on its own")
_base = tempfile.mkdtemp(prefix="calma-val-")
_cc = {"corpus": {"manifest": "MISSING.txt"}, "metrics": [{"metric_id": "accuracy", "headline": True}]}
_cf = CC.run_checks(_cc, _base, "c1")
truth(bool(_cf) and _cf[0].get("contamination_indeterminate"), "unreadable corpus -> indeterminate finding")
truth(CC.family_status(_cc, _cf) == "indeterminate", "unreadable corpus family_status is indeterminate")
_cl = [{"headline": True, "id": "c1", "verdict": "CONFIRMED", "verdict_inputs": _confirmed_vi()}]
CC.apply_validity(_cl, _cf, _cc, "held-out accuracy 0.9")
truth(_cl[0]["verdict_inputs"].get("validity_unresolved"), "unreadable corpus sets validity_unresolved")
truth(_cl[0]["verdict"] == "INCONCLUSIVE", "unreadable corpus FLIPS the headline verdict to INCONCLUSIVE (not a stale CONFIRMED)")
_lc = {"split": {"train": "train.csv", "test": "MISSING_test.csv"}, "metrics": [{"metric_id": "auc", "headline": True}]}
_lf = LC.run_checks(_lc, _base, "c1")
truth(any(x.get("leakage_indeterminate") for x in _lf), "unreadable split -> indeterminate finding")
truth(LC.family_status(_lc, _lf) == "indeterminate", "unreadable split family_status is indeterminate")
_ll = [{"headline": True, "id": "c1", "verdict": "CONFIRMED", "verdict_inputs": _confirmed_vi()}]
LC.apply_validity(_ll, _lf, _lc, "out-of-sample auc 0.9", base=_base)
truth(_ll[0]["verdict"] == "INCONCLUSIVE", "unreadable split FLIPS the headline verdict to INCONCLUSIVE (not a stale CONFIRMED)")

# --- _input_fingerprint must not hang on a FIFO/special file in the tree ------
import signal as _sig  # noqa: E402
_fifo_d = tempfile.mkdtemp(prefix="calma-fifo-")
try:
    os.mkfifo(os.path.join(_fifo_d, "pipe"))
    open(os.path.join(_fifo_d, "real.csv"), "w").write("v\n1\n")

    def _alarm(_s, _f):
        raise TimeoutError("fingerprint hung on a FIFO")
    _sig.signal(_sig.SIGALRM, _alarm)
    _sig.alarm(8)
    _fp = calma._input_fingerprint(_fifo_d, {"run": {"entrypoint": "real.csv"}, "metrics": []})
    _sig.alarm(0)
    truth(isinstance(_fp, str) and len(_fp) == 64, "fingerprint returns (does not hang) with a FIFO in the tree")
    # the attestation manifest walk must ALSO not hang on a FIFO / crash on an unreadable file
    import attest as _AT  # noqa: E402
    _unl = os.path.join(_fifo_d, "secret.bin")
    open(_unl, "w").write("x")
    os.chmod(_unl, 0o000)
    _sig.alarm(8)
    _man = _AT.manifest_for(_fifo_d)
    _sig.alarm(0)
    os.chmod(_unl, 0o644)
    truth(isinstance(_man, dict) and len(_man.get("manifest_sha256", "")) == 64,
          "attest.manifest_for returns (no hang/crash) with a FIFO + unreadable file under the tree")
    # every always-on reader of an attacker-controlled target file must stat-gate a FIFO (open()
    # on a writer-less FIFO blocks forever - their try/except never fires because it BLOCKS).
    import recompute as _RC, backtest_checks as _BT, overfitting_checks as _OF, draft_contract as _DC  # noqa: E402
    import run_hermetic as _RH2  # noqa: E402
    _rfifo = os.path.join(_fifo_d, "p2")
    os.mkfifo(_rfifo)
    _sig.alarm(8)
    _reader_ok = True
    try:
        try:
            _RC._load_cols(_rfifo)
        except ValueError:
            pass
        _BT._read_csv(_rfifo)
        _OF._read_matrix(_rfifo)
        _DC._sample_numeric(_rfifo, 0)
        _DC._sample_strings(_rfifo, 0)
        _RH2._scan_one(_rfifo)
        import intake as _IN  # noqa: E402 - the ALWAYS-ON intake scan (not just --restore)
        _IN._sha256(_rfifo)
        _IN._parse_pyproject(_rfifo)
    except TimeoutError:
        _reader_ok = False
    _sig.alarm(0)
    truth(_reader_ok, "recompute/backtest/overfitting/draft_contract/_scan_one/intake readers stat-gate a FIFO (no hang)")
except (AttributeError, OSError):
    truth(True, "mkfifo unavailable on this platform - FIFO test skipped")

# --- leakage: the model's own prediction column is not flagged as target leak --
_lk_base = tempfile.mkdtemp(prefix="calma-leak-")
open(os.path.join(_lk_base, "preds.csv"), "w").write(
    "score,label\n0.99,1\n0.98,1\n0.02,0\n0.01,0\n0.97,1\n0.03,0\n")
_lk_con = {"keys": {"target": "label"}, "features": ["score"],
           "metrics": [{"metric_id": "auc", "headline": True, "artifact": "preds.csv",
                        "binding": {"score": "score", "label": "label"}}]}
# the score column (~perfectly correlated with the label, because it's a good classifier) must NOT
# be flagged as target leakage now that the prediction column is excluded from features.
_tl = LC.check_target_leakage(LC._load_split(_lk_con, _lk_base) if _lk_con.get("split") else None,
                              _lk_con, _lk_base, "c1")
truth(_tl is None, "a model's own prediction column is excluded from the target-leakage heuristic")

# --- realism: a negative declared friction is not silently dropped ------------
_rl_base = tempfile.mkdtemp(prefix="calma-rl-")
open(os.path.join(_rl_base, "r.csv"), "w").write("return\n0.01\n-0.02\n0.03\n0.01\n-0.01\n0.02\n")
_rl_con = {"frictions": {"fee_bps": -50, "slippage_bps": 0},
           "metrics": [{"metric_id": "total_return", "headline": True, "artifact": "r.csv",
                        "binding": {"return": "return"}}]}
_dfl = RL.deflate(_rl_con, _rl_base)
truth(_dfl is not None and _dfl.get("applied"), "a negative declared friction is APPLIED (not silently dropped)")

# --- suggest: k<1 is floored; recipe-count not hardcoded ----------------------
truth(len(SG.suggest("sharpe ratio", k=0)) >= 1, "suggest(k=0) is floored to >=1, not emptied")
truth(("Browse all %d recipes" % len(__import__("recipes").ids())) in SG.render("zzz nomatch qqq", []),
      "the no-match footer uses the real recipe count, not a hardcoded 500")

# --- report.fmt_pair: a REFUTED never prints two identical-looking numbers -----
_cs, _rs = REP.fmt_pair(100.04, 100.0)
truth(_cs != _rs, "fmt_pair shows the gap for 100.04 vs 100.0 (no 'claimed 100 -> recomputed 100')")
truth(REP.fmt_pair(0.5, 0.5) == ("0.5", "0.5"), "fmt_pair leaves an identical (INVALIDATED-style) pair as-is")

# --- intake: restore env strips parent secrets, keeps what pip needs ----------
os.environ["AWS_SECRET_ACCESS_KEY"] = "sk-should-not-leak"
os.environ["OPENAI_API_KEY"] = "sk-should-not-leak-2"
_env = intake._restore_env()
truth("AWS_SECRET_ACCESS_KEY" not in _env and "OPENAI_API_KEY" not in _env, "restore env drops parent secrets")
truth("PATH" in _env, "restore env keeps PATH (pip still works)")
del os.environ["AWS_SECRET_ACCESS_KEY"], os.environ["OPENAI_API_KEY"]

# --- compiler: refuses a world-writable reference venv ------------------------
_refused = False
try:
    CO._refuse_world_writable_venv("/tmp/calma-ref-venv/bin/python")
except ValueError:
    _refused = True
truth(_refused, "compiler refuses a world-writable (/tmp) reference venv")
_priv_ok = True
try:
    CO._refuse_world_writable_venv(os.path.join(tempfile.mkdtemp(), "v", "bin", "python"))
except ValueError:
    _priv_ok = False
truth(_priv_ok, "compiler allows a private (non-world-writable) reference venv")

# --- verify refuses a symlinked .calma (write-confinement bypass) --------------
_sym_d = tempfile.mkdtemp(prefix="calma-sym-")
_evil_d = tempfile.mkdtemp(prefix="calma-evil-")
open(os.path.join(_sym_d, "main.py"), "w").write("open('out.csv','w').write('v\\n1\\n')\n")
os.symlink(_evil_d, os.path.join(_sym_d, ".calma"))
_sym_refused = False
try:
    calma.verify(_sym_d, claim="x 1")
except ValueError as e:
    _sym_refused = "symlink" in str(e)
truth(_sym_refused, "verify refuses a symlinked .calma (no verdict state redirected outside the target)")
truth(not os.listdir(_evil_d), "no state leaked through the symlinked .calma")

# --- leakage: a DEFINITE authoritative finding wins over an unreadable-split indeterminate
def _confirmed_for_leak():
    return _confirmed_vi()


_indet = {"dimension": "leakage", "validity_class": "indeterminate", "leakage_indeterminate": True}
_authf = {"dimension": "leakage", "validity_class": "authoritative", "leakage_kind": "target",
          "severity": "blocker", "id": "f1"}
_ca = [{"headline": True, "id": "c1", "verdict": "CONFIRMED", "verdict_inputs": _confirmed_for_leak()}]
LC.apply_validity(_ca, [_indet, _authf], {"keys": {"target": "y"}, "split": {"train": "a", "test": "b"}},
                  "out-of-sample auc 0.9")
truth(_ca[0]["verdict"] == "INVALIDATED",
      "a definite leakage finding drives INVALIDATED even when the split was also unreadable")
truth(LC.family_status({"split": {"train": "a"}}, [_indet, _authf]) == "flagged",
      "family_status is 'flagged' (not 'indeterminate') when a real leakage finding is present")

print("audit-round2: %d checks, %d failures" % (_checks, _fails))
sys.exit(1 if _fails else 0)
