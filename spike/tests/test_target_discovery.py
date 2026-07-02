"""runner.target_discovery — Cycle-2 binding fix: NAME-matched (never value-matched) fallback capture targets
for hand-rolled metric functions. Pure static analysis; no execution."""
import os
import tempfile

from runner import target_discovery as TD


def _write(dirpath, name, src):
    path = os.path.join(dirpath, name)
    with open(path, "w") as fh:
        fh.write(src)
    return path


def test_finds_a_hand_rolled_metric_function():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "eval.py", """
def accuracy(y_true, y_pred):
    correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)
    return correct / len(y_true)
""")
        props = TD.propose(d, known_metrics=set())
    assert len(props) == 1
    assert props[0]["target"] == "accuracy"
    assert props[0]["metric"] == "accuracy"
    assert props[0]["static"] is True
    assert props[0]["inputs"] == {"y_true": "arg0", "y_pred": "arg1"}


def test_matches_a_prefixed_name_via_keyword_fallback():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "metrics.py", """
def compute_f1(y_true, y_pred):
    return 0.5
""")
        props = TD.propose(d, known_metrics=set())
    assert len(props) == 1
    assert props[0]["metric"] == "f1"


def test_skips_metrics_already_covered_by_the_sklearn_hook():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "eval.py", """
def accuracy(y_true, y_pred):
    return 1.0
""")
        # accuracy is in the default known_metrics (sklearn-covered) set — a real library call is always
        # the higher-trust source, so the static fallback must not compete with it.
        props = TD.propose(d, known_metrics={"accuracy"})
    assert props == []


def test_auto_skips_sklearn_covered_metrics_when_the_repo_actually_uses_sklearn():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "eval.py", """
import sklearn.metrics

def accuracy(y_true, y_pred):
    return 1.0
""")
        # no explicit known_metrics — auto-detects sklearn usage from the import and skips accuracy, since
        # sklearn's own hook is the higher-trust source and will capture the real accuracy_score call.
        props = TD.propose(d)
    assert props == []


def test_auto_includes_metrics_when_the_repo_never_touches_sklearn():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "eval.py", """
def accuracy(y_true, y_pred):
    return 1.0
""")
        # the digits-softmax shape: zero sklearn usage anywhere in the repo, so nothing pre-excludes
        # accuracy — this IS the fallback's reason to exist.
        props = TD.propose(d)
    assert len(props) == 1
    assert props[0]["target"] == "accuracy"


def test_skips_non_metric_functions():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "model.py", """
def softmax(x, axis):
    return x

def forward(x, weights):
    return x

def _private_accuracy(y_true, y_pred):
    return 1.0

def no_return(y_true, y_pred):
    pass

def too_many_args(a, b, c, d):
    return a
""")
        props = TD.propose(d)
    # softmax/forward aren't metric names; a leading underscore is skipped (private/internal helper); a
    # function with no return statement can't be a metric; 4 args is outside the (y_true, y_pred[, extra])
    # shape this fallback targets.
    assert props == []


def test_ignores_unparseable_files():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "broken.py", "def accuracy(y_true, y_pred\n    this is not valid python")
        _write(d, "eval.py", "def accuracy(y_true, y_pred):\n    return 1.0\n")
        props = TD.propose(d, known_metrics=set())
    assert len(props) == 1   # the broken file is silently skipped, the valid one still found


def test_caps_at_max_targets():
    with tempfile.TemporaryDirectory() as d:
        names = ["accuracy", "precision", "recall", "f1", "roc_auc", "r2", "mae", "mse"]
        src = "\n".join("def %s(y_true, y_pred):\n    return 0.5\n" % n for n in names)
        _write(d, "eval.py", src)
        props = TD.propose(d, known_metrics=set())    # nothing pre-covered, so all 8 are candidates
    assert len(props) <= TD._MAX_TARGETS
