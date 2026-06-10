"use client";

import { Eyebrow, Reveal } from "./chrome";

const ITEMS: [string, React.ReactNode][] = [
  [
    "Why not ask the agent to check its own work?",
    <>
      Even when an agent re-runs its code, it still judges the match itself — and nothing stops it
      from fixing the comparison instead of the code. Calma&apos;s diff happens in deterministic
      scripts, and every stored verdict is re-derived byte-for-byte. The producer is never the
      verifier.
    </>,
  ],
  [
    "What do people use for this today?",
    <>
      Mostly nothing — the printed number is trusted. Eval platforms score with model judges; data
      validators check schemas; CI tests what the author thought to test. None re-execute the work
      and recompute the claimed number.
    </>,
  ],
  [
    "Does code or data leave the machine?",
    <>
      No. Everything runs locally, in a network-off sandbox that proves itself with a self-test.
      Where no verified sandbox exists, the verdict says so instead of pretending.
    </>,
  ],
  [
    "Won't better models make this unnecessary?",
    <>
      Better models mean more delegation and more money moving on AI-produced numbers. The failures
      Calma catches — overfitting, leakage, cherry-picking — are incentive problems, not capability
      problems. Humans are very capable; we still audit them.
    </>,
  ],
  [
    "Is it only for trading?",
    <>
      No. Fifteen metrics across ML, analytics, and trading; five languages run as a black box.
      Quant is simply where independent verification is already bought, so the lab starts there.
    </>,
  ],
];

export function Faq() {
  return (
    <section className="sec" id="faq">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <Eyebrow>questions</Eyebrow>
          </Reveal>
          <Reveal delay={100}>
            <h2>
              Asked. <span className="serif-acc">Answered.</span>
            </h2>
          </Reveal>
        </div>
        <div className="faq">
          {ITEMS.map(([q, a], i) => (
            <Reveal key={q as string} delay={i * 60}>
              <details>
                <summary>{q}</summary>
                <div className="a">{a}</div>
              </details>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
