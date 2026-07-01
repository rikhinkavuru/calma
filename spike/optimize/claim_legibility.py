#!/usr/bin/env python
"""optimize.claim_legibility — feature 4 meta-eval: does the salience ranker put the HEADLINE first?

Weak-labels a synthetic-but-realistic claim set (results.json test keys = headline; deep table cells / train
splits / stdout scrape = noise), ranks it with discovery.salience, and reports head-precision + recall@head.
The guardrail that matters for the franchise: ranking is IDENTITY-PRESERVING — it never changes a claim's
(metric, value), so no verdict and thus no false-confirm can move. `identity_preserved` MUST be True.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from discovery import salience as SAL  # noqa: E402


def corpus():
    """(claim, is_headline) weak-labeled candidates spanning the real source mix."""
    rows = [
        ({"id": "h1", "metric": "accuracy", "value": "0.94", "source": "results-json",
          "confidence": 0.9, "location": "results.json::test.accuracy", "split": "test"}, True),
        ({"id": "h2", "metric": "roc_auc", "value": "0.88", "source": "results-json",
          "confidence": 0.9, "location": "metrics.json::val_auc", "split": "val"}, True),
        ({"id": "h3", "metric": "f1", "value": "0.81", "source": "table", "confidence": 0.72,
          "location": "README.md", "split": "test"}, True),
        ({"id": "n1", "metric": "accuracy", "value": "0.99", "source": "results-json",
          "confidence": 0.9, "location": "results.json::train.accuracy", "split": "train"}, False),
        ({"id": "n2", "metric": "accuracy", "value": "0.6", "source": "stdout", "confidence": 0.6,
          "location": "stdout"}, False),
        ({"id": "n3", "metric": "mae", "value": "12.0", "source": "prose", "confidence": 0.42,
          "location": "README.md", "split": "train"}, False),
    ]
    return rows


def measure(head_k=3):
    rows = corpus()
    claims = [dict(c) for c, _ in rows]
    labels = {c["id"]: hl for c, hl in rows}
    before = {(c["id"], c["metric"], c["value"]) for c in claims}
    ranked = SAL.score_claims(claims)
    after = {(c["id"], c["metric"], c["value"]) for c in ranked}
    identity_preserved = before == after
    head = ranked[:head_k]
    head_ids = [c["id"] for c in head]
    n_headline = sum(1 for _id, hl in labels.items() if hl)
    tp = sum(1 for c in head if labels.get(c["id"]))
    head_precision = tp / len(head) if head else 0.0
    recall_at_head = tp / n_headline if n_headline else 0.0
    return {"identity_preserved": identity_preserved, "head_ids": head_ids,
            "head_precision": round(head_precision, 4), "recall_at_head": round(recall_at_head, 4),
            "n_headline": n_headline, "head_k": head_k}


def main():
    m = measure()
    with open(os.path.join(HERE, "claim_legibility_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== CLAIM LEGIBILITY (feature 4) ===")
    print("head=%s" % m["head_ids"])
    print("head-precision=%.2f  recall@head=%.2f  identity-preserved=%s (MUST be True)"
          % (m["head_precision"], m["recall_at_head"], m["identity_preserved"]))
    ok = m["identity_preserved"] and m["head_precision"] >= 0.6
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
