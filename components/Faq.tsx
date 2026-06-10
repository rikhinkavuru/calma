"use client";

import { Reveal } from "./chrome";

const ITEMS: [string, React.ReactNode][] = [
  [
    "Why can't I just ask the AI to check its own work?",
    <>
      Even when an agent re-runs its code, it still judges the match itself — and nothing stops it
      from fixing the comparison instead of the code. Calma&apos;s comparison happens in
      deterministic scripts, and every stored verdict is re-derived byte-for-byte. The producer is
      never the verifier.
    </>,
  ],
  [
    "Does my code or data leave my machine?",
    <>
      No. Everything runs locally, in a network-off sandbox that proves itself with a self-test
      before it&apos;s trusted. Where no verified sandbox exists, the verdict says so instead of
      pretending.
    </>,
  ],
  [
    "Won't better models make this unnecessary?",
    <>
      Better models mean more delegation — and more money moving on AI-produced numbers. The
      failures Calma catches (overfitting, leakage, cherry-picking) are incentive problems, not
      capability problems. Humans are very capable; we still audit them.
    </>,
  ],
  [
    "Is it only for trading?",
    <>
      No. It verifies any computational claim — model accuracy, data totals, row counts — across
      Python, R, Julia, C++, and Rust. Trading is simply where independent verification is already
      bought, so the lab starts there.
    </>,
  ],
];

export function Faq() {
  return (
    <section className="sec" id="faq">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Questions</span>
          </Reveal>
          <Reveal delay={90}>
            <h2>
              Fair questions. <span className="serif">Straight answers.</span>
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
