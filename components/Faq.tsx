"use client";

import { Section } from "./primitives";
import { Reveal } from "./Reveal";

const ITEMS: [string, React.ReactNode][] = [
  [
    "Can't I just ask my agent to verify it — or to re-run the code itself?",
    <>
      Asked to &quot;double-check,&quot; a model usually re-reads its reasoning and says it looks
      right. Even when an agent does re-run the code, it still <em>judges the match itself</em>,
      nothing stops it from fixing the comparison instead of the code, and there&apos;s no audit
      trail. Calma closes all three: a calibrated tolerance diff in deterministic scripts, a ledger
      that re-derives every label byte-for-byte, and a content-addressed manifest per run. On
      REPRO-Bench, agents judging reproducibility score ~21% — judgment fails where re-execution
      works.
    </>,
  ],
  [
    "What do people use for this problem today?",
    <>
      Mostly nothing — they trust the printed number. The adjacent tools solve different problems:
      eval platforms (LangSmith, Braintrust) score with LLM judges for the builder; data validators
      (Great Expectations) check schemas; CI tests check code paths the author thought to test. In
      quant, independent validation exists as bespoke human consulting. None re-execute the work and
      recompute the claimed number from raw outputs.
    </>,
  ],
  [
    "Does my code or data leave my machine?",
    <>
      No. Everything runs locally; nothing is uploaded. On macOS the run is inside a verified
      network-off sandbox proven by a self-test; on hosts without one, the verdict says so
      explicitly (<code>host-not-isolated</code>) instead of pretending.
    </>,
  ],
  [
    "What if there's no specific number to check?",
    <>
      It still verifies that the result reproduces — including <code>--check-determinism</code>,
      which re-executes twice and refuses to confirm anything whose outputs differ across identical
      runs (FLAKY).
    </>,
  ],
  [
    "Won't this stop mattering as models get better?",
    <>
      The opposite. Better models → more delegation → more money moving on AI-produced numbers →
      more demand for a referee the producer doesn&apos;t own. And the failures Calma catches —
      overfitting, leakage, cherry-picking — are incentive problems, not capability problems: a
      stronger optimizer produces <em>more</em> convincing overfits. Humans are very capable; we
      still audit them.
    </>,
  ],
  [
    "Is it only for trading and quant?",
    <>
      No. The engine is domain-agnostic — 15 recipes across ML (accuracy, AUC, F1, RMSE, R²),
      analytics (sums, means, row counts), and trading (Sharpe, return, drawdown) — and it runs
      Python, R, Julia, C++, and Rust as a black box. Quant is where independent verification is
      already bought, so it&apos;s where the paid lab starts.
    </>,
  ],
];

export function Faq() {
  return (
    <Section id="faq" num="06" label="questions" bg="tint" watermark="06 / FAQ"
      title={<>Asked immediately, <span className="dim">answered honestly.</span></>}>
      <div className="faq">
        {ITEMS.map(([q, a], i) => (
          <Reveal as="div" key={i} delay={i * 0.04}>
            <details className="faq__item">
              <summary>{q}</summary>
              <div className="faq__a">{a}</div>
            </details>
          </Reveal>
        ))}
      </div>
    </Section>
  );
}
