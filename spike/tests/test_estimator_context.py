"""Capture the model identity from an estimator OBJECT (its class name), so a model-comparison loop that
never stored a name string still binds per-model. Metadata only — never the value (FCR-safe)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "capture"))
from core import diff as D  # noqa: E402
import calma_capture as C  # noqa: E402


class _Est:
    def fit(self, *a):
        return self

    def predict(self, *a):
        return []


def test_estimator_class_name_becomes_context():
    _Est.__name__ = "RandomForestClassifier"
    ctx = C._extract_context({"clf": _Est(), "n_estimators": 100})
    assert ctx and ctx.get("clf") == "RandomForestClassifier"


def test_non_estimator_object_is_ignored():
    # a local named 'model' that is just a dict of results is NOT an estimator → no bogus context
    assert C._extract_context({"model": {"acc": 0.9}}) is None


def test_camelcase_context_matches_human_label():
    # captured "LogisticRegression" must overlap a README "Logistic Regression"
    toks = D._ctx_tokens("Model=Logistic Regression")
    assert D._ctx_overlap(toks, {"clf": "LogisticRegression"}) == 2


def test_model_class_name_aliases_match_readme_labels():
    # an estimator class name binds to its human README label across the common sklearn zoo
    cases = [("SVC", "SVM"), ("KNeighborsClassifier", "KNN"), ("GaussianNB", "Naive Bayes"),
             ("XGBClassifier", "XGBoost"), ("RandomForestClassifier", "Random Forest")]
    for cls, label in cases:
        assert D._ctx_overlap(D._ctx_tokens("Model=" + label), {"clf": cls}) >= 1, (cls, label)


def test_model_alias_no_false_match():
    # a dataset/feature token must not trip a short model alias (rf/svm/knn) as a substring
    assert D._ctx_overlap(D._ctx_tokens("dataset=surface"), {"clf": "GaussianNB"}) == 0
    assert D._ctx_overlap(D._ctx_tokens("dataset=cifar10"), {"model": "SVC"}) == 0
