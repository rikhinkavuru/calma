"""Regression suite for the zero-touch claim sniffer (sniff_claims.py).

The sniffer's contract is PRECISION: everything it emits is safe to auto-verify. So the
suite is dominated by the must-stay-SILENT corpus - ordinary agent chatter full of numbers
that are not checkable claims. A false fire here is a release blocker by design.

Also enforced:
  - round-trip: every emitted claim string re-parses (draft_contract.parse_claim) to the
    same value the sniffer extracted - so the hook can pass the string to `calma verify`
    without the value drifting;
  - vocabulary closure: every sniffer term maps into CLAIM_METRIC_HINTS (the engine's own
    table) - the sniffer can never name a metric the engine does not serve.

Pure stdlib. Run: python3 test_sniff.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import draft_contract as DC  # noqa: E402
import sniff_claims as SN  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def fires(text, metric=None, value=None):
    cs = SN.sniff(text)
    if not cs:
        return False
    if metric is not None and not any(c["metric"] == metric for c in cs):
        return False
    if value is not None and not any(abs(c["value"] - value) < 1e-9 for c in cs):
        return False
    return True


def silent(text):
    return not SN.sniff(text)


# ---------------------------------------------------------------------------
# MUST FIRE: real checkable claims in the shapes agents actually emit
# ---------------------------------------------------------------------------
fire_cases = [
    ("Final held-out accuracy is 0.91 on the test set.", "accuracy", 0.91),
    ("The model achieves an AUC of 0.94.", "auc", 0.94),
    ("Done! The backtest returned +19,971% over the period.", "total_return", 199.71),
    ("The strategy returned 23% annually.", "total_return", 0.23),
    ("RMSE: 12.4", "rmse", 12.4),
    ("MAE came out to 3.2", "mae", 3.2),
    ("Sharpe ratio came in at 1.84 on the held-out window.", "sharpe", 1.84),
    ("Max drawdown was -18%.", "max_drawdown", -0.18),
    ("F1 = 0.87", "f1", 0.87),
    ("macro F1 is 0.81 across the 12 classes", "macro_f1", 0.81),
    ("recall@10 = 0.84 on the eval set", "recall_at_k", 0.84),
    ("pass@5 hit 0.62 after the fix", "pass_at_k", 0.62),
    ("NDCG of 0.71", "ndcg_at_k", 0.71),
    ("The p95 latency is 120ms after the cache change.", "latency_p95", 120.0),
    ("latency p95 is 120ms now", "latency_p95", 120.0),
    ("It runs 2.3x faster than before.", "speedup_ratio", 2.3),
    ("Coverage is at 87% now.", "test_coverage", 0.87),
    ("Processed 10,000 rows and wrote the output.", "row_count", 10000.0),
    ("Cleaned 48,212 rows from the raw dump.", "row_count", 48212.0),
    ("The p-value is 0.03, so the effect is real.", "p_value", 0.03),
    ("Pearson correlation of 0.92 between the two series.", "correlation", 0.92),
    ("Log loss is 0.41 on validation.", "log_loss", 0.41),
    ("The Gini coefficient is 0.42 for this cohort.", "gini_norm", 0.42),
    ("CAGR works out to 14% over the decade.", "cagr", 0.14),
    ("Churn is 4.2% monthly.", "churn_rate", 0.042),
    ("MAPE is 8.3% on the holdout.", "mape", 0.083),
    ("Brier score of 0.09.", "brier", 0.09),
    ("R2 is 0.86 for the fitted model.", "r2", 0.86),
    ("Volatility is 18% annualized.", "volatility", 0.18),
    ("Uptime was 99.95% this quarter.", "uptime_pct", 0.9995),
    ("Win rate is 58% across 1,200 trades.", "win_rate", 0.58),
    ("Perplexity dropped to 12.7.", "perplexity", 12.7),
    ("precision 0.93 and recall 0.88 on the test split",
     "precision", 0.93),
    # boundaries of the stress-test guards: these shapes must KEEP firing
    ("Test set accuracy is 0.91.", "accuracy", 0.91),  # noun "set", not assignment
    ("Latency dropped to 80ms after the cache change.", "latency_p50",
     80.0),  # "to" in the gap without an assignment verb is still a result
    ("Exact match is 0.71 on the QA benchmark.", "exact_match",
     0.71),  # eval context, no byte/file vocabulary
]
for text, metric, value in fire_cases:
    truth(fires(text, metric, value), "fires: %r -> %s %s" % (text, metric, value))

# the second metric in a two-metric sentence also fires
truth(fires("precision 0.93 and recall 0.88 on the test split", "recall", 0.88),
      "fires: both metrics in one sentence")

# ---------------------------------------------------------------------------
# MUST STAY SILENT: ordinary agent chatter with numbers
# ---------------------------------------------------------------------------
silent_cases = [
    # engineering narration
    "I fixed the bug on line 42 and bumped the version to 1.2.3.",
    "Updated 12 files, 340 lines changed, all 58 tests pass.",
    "The server listens on port 8080 with pid 4112.",
    "Exit code 1 means the gate failed.",
    "See step 3 of the pipeline, then re-run with seed 42.",
    "Trained for 30 epochs with batch size 64.",
    "The function returns 3 results when given a list.",
    "Python 3.11 is required; node 18 also works.",
    "Released v2.4.0 this morning.",
    "I split it into 4 chunks of 250 tokens each.",
    # dates, times, years
    "The data runs from 2019 to 2024.",
    "Deployed on 2026-06-11 at 14:32.",
    "Q3 2025 numbers are in the second sheet.",
    # counts and sizes (not the rows template)
    "There are 1,204 files totaling 3.2GB.",
    "The CSV has 14 columns and the parquet has 9.",
    "It found 7 duplicates and 3 outliers in the sample.",
    "Downloaded 45MB in 12 seconds.",
    # hypothetical / planning / targets
    "We should target an accuracy of 0.95 next sprint.",
    "The goal is a Sharpe above 2.0.",
    "I expect coverage to reach 90% once the suite lands.",
    "If accuracy hits 0.97 we ship.",
    "Ideally the p-value would be under 0.01.",
    "Let's aim for RMSE around 10.",
    "An accuracy of 0.99 would be suspicious, e.g. leakage.",
    # questions
    "Is the accuracy 0.91?",
    "Did the backtest really return 23%?",
    # baselines / previous values
    "Baseline accuracy was 0.80.",
    "Previously the AUC was 0.90; see the old report.",
    # negation
    "Accuracy is not 0.95, despite the README.",
    # code, paths, urls, quotes
    "```\naccuracy = 0.99\n```",
    "Set `threshold = 0.91` in config.py.",
    "The file lives at data/processed/v2/train.csv.",
    "See https://example.com/report?accuracy=0.99 for details.",
    "> the backtest returned +500% (quoted from the README)",
    # percent-ambiguous bare values for [0,1] metrics
    "accuracy of 91 on the benchmark",
    # implausible values
    "accuracy 7.3 looks like a label mixup",
    "correlation of 14 between the columns",
    # generic words that are NOT in the vocabulary on purpose
    "The total is $4.2M across all accounts.",
    "The mean is 50.2 and the median is 48.",
    "We have 10,000 rows in the table.",
    "Peak memory was 1.2GB during the join.",
    "Alpha is 0.05 for the test.",
    "Beta exposure is 1.2 to the index.",
    "The CI is 0.4 to 0.6.",
    "Revenue grew 12% month over month.",
    "Dropped 132 rows with nulls.",
    # near-miss claim syntax (metric word present, no claim relationship)
    "accuracy improved while latency went from 12 to 9 seconds of total runtime",
    "The accuracy column has 3 nulls.",
    "I renamed accuracy_v2.csv to accuracy.csv.",
    "Precision matters more than recall for this use case.",
    "The recall implementation uses 4 threads.",
    "F1 cars hit 300 km/h.",
    # tool/skill output shapes
    "Ran calma verify and got exit code 0.",
    "The verdict was CONFIRMED with confidence 97/100.",
    # --- adversarial stress-test regressions (multi-agent attack round, 2026-06-11):
    # 12 confirmed false fires, each pinned forever ---
    # 'returned N%' with a non-finance subject (probes/checks/functions return things)
    "Cleaned up the self-hosted runner. The disk usage probe returned 92%, so I pruned "
    "the stale docker images and rotated the build logs.\n\nWe're back to 41 GB free on "
    "the volume. The nightly prune job will keep it that way.",
    # config assignment: a latency knob being set, not measured
    "Wired up the failure-injection suite. I set the toxiproxy latency to 500ms and the "
    "bandwidth cap to 1 mbps; both knobs are read from chaos.yaml now.\n\nThe whole "
    "suite runs in about 90 seconds on the shared runner.",
    # injected/fabricated latency in a test harness
    "Soak test harness is ready. For the soak runs I set the load generator's injected "
    "latency to 250ms and left the request rate at 40 per worker.\n\nResults land in "
    "artifacts/soak/ after each run.",
    # diff churn in code-review chatter, not customer churn
    "Heads up before you review: the diff is large but it's mostly churn — 80% of "
    "it is the directory rename from utils to lib.\n\nThe actual behavioral change is "
    "confined to retry.py (about 30 lines).",
    # Perplexity the search product, '5 results' is a counted unit
    "I searched for that stack trace first. Perplexity gave 5 results but none matched "
    "our glibc version, so I ended up bisecting instead.\n\nThe regression landed in "
    "commit 4f2a9c1; reverted it and the segfault is gone.",
    # CSS margin assignment, not profit margin
    "Polished the landing hero. I set the section margin to 4% so it scales properly on "
    "tablets, swapped in the variable font, and fixed the CLS from the unsized logo "
    "image.\n\nLighthouse no longer flags layout shift on mobile.",
    # byte-identical files, not the LLM-eval exact_match score
    "Verified the build is reproducible: the two artifacts are an exact match, 100% "
    "byte-identical, and the SBOM diff is empty.\n\nBoth were built from the same tag "
    "on independent runners.",
    # lost log lines during failover, not ML cross-entropy (never a percent)
    "Ran the failover drill. We saw about 0.4% log loss in the shipper during the "
    "cutover window, all within the documented buffer limits.\n\nIncreased the disk "
    "buffer to 512 MB anyway to be safe.",
    # rounding tolerance, not classifier precision (number-first path)
    "Fixed the flaky money test by rounding the displayed totals to 0.01 precision "
    "before comparison; the underlying decimal math is untouched.\n\nThe test has "
    "passed 50 consecutive local runs since.",
    # float-comparison tolerance, not classifier precision (term-first path)
    "The diff tool now compares floats with a precision of 0.001 instead of exact "
    "equality, which fixes the spurious failures on macOS.\n\nNo fixtures had to "
    "change.",
    # R2 the object store; '0.4 cents' is a money unit, not an R-squared value
    "Mirrored the build cache to R2 at roughly 0.4 cents per GB stored, which is far "
    "cheaper than what we pay on S3.\n\nEgress to the runners is free since they sit "
    "behind Cloudflare already.",
    # an analytics-tracking bug, not the portfolio tracking-error statistic
    "Found the analytics bug. The tracking error was 3 duplicate events per pageview, "
    "caused by the handler re-binding on every render; debounced it.\n\nDashboards "
    "should normalize within a day.",
]
for text in silent_cases:
    truth(silent(text), "silent: %r" % text)

# ---------------------------------------------------------------------------
# round-trip: emitted claim strings re-parse to the same value (+ metric when
# the hint table can see it) - the hook hands these to `calma verify` verbatim
# ---------------------------------------------------------------------------
for text, metric, value in fire_cases:
    for c in SN.sniff(text):
        v, h = DC.parse_claim(c["claim"])
        truth(v is not None and abs(v - c["value"]) < 1e-9,
              "round-trip value: %r -> %r" % (text, c["claim"]))
        if h is not None:
            truth(h == c["metric"],
                  "round-trip metric: %r -> %s (sniffed %s)" % (c["claim"], h, c["metric"]))

# ---------------------------------------------------------------------------
# vocabulary closure: every term resolves inside the engine's own hint table
# ---------------------------------------------------------------------------
for term in SN.STRONG_TERMS:
    truth(SN._hint_metric(term) is not None, "vocab closure (strong): %r" % term)
for term in SN.CONDITIONAL_TERMS:
    truth(SN._hint_metric(term) is not None, "vocab closure (conditional): %r" % term)
for term, (mid, canon, _kind) in SN._ALIASES.items():
    truth(DC.parse_claim("%s 1" % canon)[1] == mid, "alias canon maps: %r" % term)

# ---------------------------------------------------------------------------
# shape and ordering invariants
# ---------------------------------------------------------------------------
many = SN.sniff("accuracy 0.91. auc 0.92. f1 0.85. rmse 12. mae 3. sharpe 1.2. brier 0.1.")
truth(len(many) <= SN.MAX_CLAIMS, "MAX_CLAIMS cap respected")
truth(all(c["confidence"] == "high" for c in many), "all emitted candidates are high")
truth(SN.sniff("") == [] and SN.sniff("   \n  ") == [], "empty input -> empty list")
truth(SN.sniff(None if False else "no numbers here at all") == [], "no numbers -> empty")
# dedupe: the same metric+value mentioned twice emits once
dups = SN.sniff("accuracy 0.91 held; to repeat, accuracy 0.91 on test.")
truth(len([c for c in dups if c["metric"] == "accuracy"]) == 1, "dedupe same metric+value")
# debug mode returns rejection reasons
cands, rej = SN.sniff("We should target accuracy 0.95.", debug=True)
truth(cands == [] and any(r["reason"] == "hypothetical" for r in rej),
      "debug mode surfaces rejection reasons")

print("sniff: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
