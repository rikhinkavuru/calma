"use client";

import { SectionHead } from "./chrome";

const ITEMS: [string, React.ReactNode][] = [
  [
    "Why not ask the agent to check its own work?",
    <>
      Asked to &quot;double-check,&quot; a model re-reads its reasoning and agrees with itself. Even
      when it re-runs the code it still judges the match — and nothing stops it from fixing the
      comparison instead of the code. Calma&apos;s diff happens in deterministic scripts under a
      calibrated tolerance, and the ledger re-derives every label byte-for-byte. On REPRO-Bench,
      agents judging reproducibility score ~21%. The producer is never the verifier.
    </>,
  ],
  [
    "What do people use for this today?",
    <>
      Mostly nothing — the printed number is trusted. Eval platforms score with model judges for the
      builder; data validators check schemas; CI tests what the author thought to test. In quant,
      independent validation is bespoke human consulting. None re-execute the work and recompute the
      claimed number.
    </>,
  ],
  [
    "Does code or data leave the machine?",
    <>
      No. Everything runs locally. On macOS the run sits inside a verified network-off sandbox
      proven by a self-test; elsewhere the verdict prints <code>host-not-isolated</code> instead of
      pretending.
    </>,
  ],
  [
    "What if there's no number to check?",
    <>
      It still verifies the result reproduces — including <code>--check-determinism</code>, which
      re-executes twice and refuses to confirm anything whose outputs differ across identical runs.
    </>,
  ],
  [
    "Won't better models make this unnecessary?",
    <>
      Better models mean more delegation and more money moving on AI-produced numbers — every dollar
      needing a referee the producer doesn&apos;t own. The failures Calma catches — overfitting,
      leakage, cherry-picking — are incentive problems, not capability problems. A stronger
      optimizer makes more convincing overfits. Humans are very capable; we still audit them.
    </>,
  ],
  [
    "Is it only for trading?",
    <>
      No. Fifteen recipes across ML, analytics, and trading; Python, R, Julia, C++, and Rust run as
      a black box. Quant is where independent verification is already bought, so the lab starts
      there.
    </>,
  ],
];

export function Faq() {
  return (
    <section className="section" id="faq">
      <div className="wrap">
        <SectionHead num="006 / Questions" title="Asked" note="Spec-sheet answers. No padding." />
        <div className="faq">
          {ITEMS.map(([q, a]) => (
            <details key={q as string}>
              <summary>{q}</summary>
              <div className="a">{a}</div>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
