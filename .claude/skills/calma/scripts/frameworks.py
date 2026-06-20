"""calma.frameworks - starter verify.yaml templates per ML/quant framework, for `calma init <framework>`.

The "it works on my stack" on-ramp (C4): instead of learning the contract format, a Backtrader / VectorBT
/ zipline / PyTorch / XGBoost / scikit-learn user runs `calma init <framework>` and gets a runnable
contract SKELETON tuned to that framework's output layout, the right headline metric + binding, and the
validity blocks that framework's results need (split/trials for ML; frictions/windows for quant). They
fill in a couple of paths and run `calma verify . "<claim>"`.

A template is the same dict `draft_contract.load_contract` reads (written as JSON to verify.yaml). The
`_note` field carries the fill-in instructions - verify.yaml is JSON, so a starter explains itself there.
Bindings match the engine's canonical recipe inputs (accuracy/f1 -> {prediction,label} argmax; auc ->
{score,label} roc-auc; return metrics -> {return}). Pure stdlib data; every template validates against
draft_contract.validate_contract (asserted in tests/test_frameworks.py)."""

import copy

_QUANT_ENV = {"ecosystem": "python", "trust": "own-code"}
_ML_ENV = {"ecosystem": "python", "trust": "own-code"}
# ML starters declare a split skeleton so the leakage check can run once the user points it at real
# train/test files; a missing file degrades leakage to NOT-APPLICABLE (never an error), so the
# placeholder is safe and instructive.
_ML_SPLIT = {"train": "train.csv", "test": "test.csv"}

FRAMEWORKS = {
    "backtrader": {
        "_note": ("Backtrader starter. (1) Have your strategy WRITE per-period strategy returns to "
                  "results/returns.csv (one `return` column) - e.g. via a bt.Analyzer or a writer. "
                  "(2) Point run.entrypoint at the script that runs Cerebro. (3) For a NET-of-cost claim "
                  "add a `frictions` block; for walk-forward robustness add a `windows` block. Then: "
                  "calma verify . \"Sharpe 1.8\""),
        "run": {"entrypoint": "backtest.py", "network": "off"},
        "env": _QUANT_ENV,
        "artifacts": [{"path": "results/returns.csv", "columns": {"return": {"tag": "return"}}}],
        "metrics": [{"metric_id": "sharpe", "artifact": "results/returns.csv",
                     "binding": {"return": "return"}, "headline": True}],
    },
    "vectorbt": {
        "_note": ("VectorBT starter. Write your portfolio returns to returns.csv "
                  "(`pf.returns().to_csv('returns.csv', header=['return'])`). Add a `frictions` block for "
                  "a net-of-cost claim and a `windows` block for walk-forward. Then: calma verify . "
                  "\"Sharpe 2.1\""),
        "run": {"entrypoint": "backtest.py", "network": "off"},
        "env": _QUANT_ENV,
        "artifacts": [{"path": "returns.csv", "columns": {"return": {"tag": "return"}}}],
        "metrics": [{"metric_id": "sharpe", "artifact": "returns.csv",
                     "binding": {"return": "return"}, "headline": True}],
    },
    "zipline": {
        "_note": ("zipline starter. Write the perf returns to perf.csv "
                  "(`perf['returns'].to_csv('perf.csv', header=['return'])`). Add `frictions`/`windows` "
                  "for validity. Then: calma verify . \"total return 35%\""),
        "run": {"entrypoint": "run_algo.py", "network": "off"},
        "env": _QUANT_ENV,
        "artifacts": [{"path": "perf.csv", "columns": {"return": {"tag": "return"}}}],
        "metrics": [{"metric_id": "total_return", "artifact": "perf.csv",
                     "binding": {"return": "return"}, "headline": True}],
    },
    "pytorch": {
        "_note": ("PyTorch starter. Write HELD-OUT predictions to predictions.csv with two columns "
                  "y_true,y_pred (argmax labels, not logits). The `split` block lets the leakage check "
                  "run - point it at your real train/test files (or remove it). Add `trials: N` if you "
                  "searched N configs (overfitting). Then: calma verify . \"accuracy 0.94\""),
        "run": {"entrypoint": "train.py", "network": "off"},
        "env": _ML_ENV,
        "artifacts": [{"path": "predictions.csv",
                       "columns": {"y_true": {"tag": "label"}, "y_pred": {"tag": "prediction"}}}],
        "metrics": [{"metric_id": "accuracy", "artifact": "predictions.csv",
                     "binding": {"prediction": "y_pred", "label": "y_true"}, "convention": "argmax",
                     "headline": True}],
        "split": dict(_ML_SPLIT),
    },
    "xgboost": {
        "_note": ("XGBoost starter. Write held-out predictions to predictions.csv: y_true,y_score "
                  "(predicted probabilities) for AUC, or y_true,y_pred (labels) for accuracy. Point "
                  "`split` at your real train/test files so the leakage check runs; add `trials: N` for a "
                  "tuned model (overfitting). Then: calma verify . \"AUC 0.91\""),
        "run": {"entrypoint": "train.py", "network": "off"},
        "env": _ML_ENV,
        "artifacts": [{"path": "predictions.csv",
                       "columns": {"y_true": {"tag": "label"}, "y_score": {"tag": "score"}}}],
        "metrics": [{"metric_id": "auc", "artifact": "predictions.csv",
                     "binding": {"score": "y_score", "label": "y_true"}, "convention": "roc-auc",
                     "headline": True}],
        "split": dict(_ML_SPLIT),
    },
    "sklearn": {
        "_note": ("scikit-learn starter. Write held-out predictions to predictions.csv with y_true,y_pred. "
                  "Point `split` at your real train/test files for the leakage check; add `trials: N` if "
                  "you grid-searched. Then: calma verify . \"f1 0.88\""),
        "run": {"entrypoint": "train.py", "network": "off"},
        "env": _ML_ENV,
        "artifacts": [{"path": "predictions.csv",
                       "columns": {"y_true": {"tag": "label"}, "y_pred": {"tag": "prediction"}}}],
        "metrics": [{"metric_id": "f1", "artifact": "predictions.csv",
                     "binding": {"prediction": "y_pred", "label": "y_true"}, "convention": "argmax",
                     "headline": True}],
        "split": dict(_ML_SPLIT),
    },
}

# common spellings -> the canonical key (so `calma init torch` / `init scikit-learn` just work)
ALIASES = {"bt": "backtrader", "vbt": "vectorbt", "torch": "pytorch", "xgb": "xgboost",
           "lightgbm": "xgboost", "lgbm": "xgboost", "scikit-learn": "sklearn", "scikit": "sklearn",
           "sk-learn": "sklearn", "skl": "sklearn"}


def list_frameworks():
    """The canonical framework keys, sorted."""
    return sorted(FRAMEWORKS)


def starter_contract(framework):
    """A deep copy of the starter contract for `framework` (case-insensitive, alias-aware), or None for
    an unknown framework. Deep-copied so a caller can mutate it without touching the shared template."""
    if not isinstance(framework, str):
        return None
    key = framework.strip().lower()
    key = ALIASES.get(key, key)
    tmpl = FRAMEWORKS.get(key)
    return copy.deepcopy(tmpl) if tmpl else None
