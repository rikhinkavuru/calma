"use client";

import { Reveal } from "./chrome";

/* The two differentiators get the marquee; the grid is the actual machinery. */
const MARQUEE: [string, string, string][] = [
  [
    "Adversarial by design",
    "A verdict nobody can argue with — including the AI that did the work",
    "Every number and the verdict itself come from deterministic code, and the ledger re-derives each verdict byte-for-byte from its recorded inputs. A persuasive model — or a motivated author — cannot argue, edit, or charm their way to a pass.",
  ],
  [
    "Self-proving isolation",
    "It proves its own sandbox before trusting it",
    "Before any run, Calma plants a fake secret and tries to steal it — and tries to reach the network — under its own sandbox. Only when every attempt fails does it claim isolation; a machine that can't provide it is stamped honestly. Nothing is uploaded: your code and data never leave the machine.",
  ],
];

const FEATS: [string, string][] = [
  [
    "Deterministic to the bit",
    "Same inputs, same number, on any machine. The recompute runs on correctly-rounded kernels with Calma's own deterministic math — no GPU noise, no platform library drift, anywhere in the path.",
  ],
  [
    "Calibrated tolerance budgets",
    "A claim is only refuted when the gap is statistically distinguishable: the budget comes from the claim's own reported precision — “$4.2M” is a ±$50k claim — plus the metric's sampling error and a measured noise floor.",
  ],
  [
    "Honesty guards",
    "REFUTED is structurally blocked on an ambiguous column binding, a failed re-run, flaky outputs, or uncontrolled randomness. It degrades to can't-confirm with a fix: line naming the exact unblock — a caveat over a false alarm, every time.",
  ],
  [
    "Plain-English claims",
    "“p95 latency 120ms.” “pass@5 0.62.” “monthly CAGR 23.9%.” The number, the metric, and even the convention — which k, which period, Welch or pooled — are parsed straight from the words.",
  ],
  [
    "Auto-drafted, graded contracts",
    "Calma scans the output files, infers which column is the metric, and grades each binding by an independent sanity check. Only an independently-verified binding can ever refute. Pin everything with one small verify.yaml.",
  ],
  [
    "Forensic replay & attestation",
    "Every run leaves a content-addressed manifest (in-toto/SLSA, CycloneDX ML-BOM) and one command that re-runs the whole check. The proof is built for the counterparty, not the author.",
  ],
  [
    "Built for agent loops & CI",
    "Verifications are cached by the content hash of code, data, and claim — unchanged work answers instantly. Agents branch on --json verdicts mid-task; the GitHub Action gates CI only when a claim actually breaks.",
  ],
  [
    "Any language, black box",
    "Python, R, Julia, C++, Rust — the program runs as a sealed box and Calma rebuilds the number in its own layer. No instrumentation, no SDK, no changes to the code under test.",
  ],
  [
    "Every catch leaves a record",
    "A break produces a shareable teardown — claimed X, recomputed Y, here's the reproduction — and every verification appends to a per-project history. The track record compounds; it can't be retconned.",
  ],
];

export function Features() {
  return (
    <section className="sec" id="features">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Features</span>
          </Reveal>
          <Reveal delay={150}>
            <h2 className="h2">Simple to use. Hard to fool.</h2>
          </Reveal>
        </div>

        <Reveal delay={200}>
          <div className="marquee">
            {MARQUEE.map(([k, t, d]) => (
              <div className="mq" key={k}>
                <span className="mq__k">{k}</span>
                <h3>{t}</h3>
                <p>{d}</p>
              </div>
            ))}
          </div>
        </Reveal>

        <Reveal delay={250}>
          <div className="features features--3">
            {FEATS.map(([t, d]) => (
              <div className="feat" key={t}>
                <h3>{t}</h3>
                <p>{d}</p>
              </div>
            ))}
          </div>
        </Reveal>

        <Reveal delay={300}>
          <div className="rband">
            <div className="rband__n">
              <span className="rband__num">59</span>
              <span className="rband__sub">SOTA recipes</span>
            </div>
            <p className="rband__copy">
              A recipe is how Calma rebuilds one kind of number — a Sharpe ratio, a p95 latency, a
              pass@1, a p-value — from the raw output files. <b>Every one is validated against the
              published reference implementation</b> (scikit-learn, SciPy, NumPy) before it ships,
              and runs deterministically: same inputs, same number, to the bit.
            </p>
            <a className="pbtn pbtn--amber" href="/recipes">
              Browse all 59
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
