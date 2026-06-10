"use client";

import { Reveal } from "./chrome";

/* The two actual differentiators get the marquee; everything else consolidates. */
const MARQUEE: [string, string, string][] = [
  [
    "Tamper-proof",
    "A verdict nobody can argue with — including the AI that did the work",
    "Every number and the verdict itself come from deterministic code, and the ledger re-derives each verdict byte-for-byte from its recorded inputs. A persuasive model — or a motivated human — cannot author a pass.",
  ],
  [
    "Self-proving",
    "It proves its own sandbox before trusting it",
    "Before any run, Calma plants a fake secret and tries to steal it — and tries to reach the network — under its own sandbox. Only when every attempt fails does it claim isolation. If your machine can't provide that, the verdict says so instead of pretending.",
  ],
];

const FEATS: [string, string][] = [
  [
    "Plain English in, plain English out",
    "“p95 latency 120ms.” “pass@5 0.62.” The number, the metric, even the convention are parsed from the words. Back comes one of four answers — confirmed, refuted, can't confirm, or confirmed with caveats.",
  ],
  [
    "It never cries wolf",
    "Tolerances are calibrated to the claim's own precision — “$4.2M” is a ±$50k claim. And when something can't be verified, you get a fix: line naming the exact change, never a guess or a false alarm.",
  ],
  [
    "Anyone can replay it",
    "Every verdict ships with one command that re-runs the entire check, on their machine. You never have to take Calma's word for it either.",
  ],
  [
    "Cheap enough to run in a loop",
    "Verifications are cached by the content hash of code, data, and claim — unchanged work answers instantly. Agents verify their own results mid-task, so the mistake dies before anyone sees it.",
  ],
  [
    "Any language, zero config",
    "Python, R, Julia, C++, Rust — your program runs as a black box and Calma rebuilds the number itself. The contract is auto-drafted from your files; pin it with one small verify.yaml when you want control.",
  ],
  [
    "Nothing leaves your machine",
    "The work runs locally, in a sandbox with no network access. Your code and data are never uploaded, anywhere.",
  ],
];

const ALSO = [
  "flaky-result detection (runs twice, diffs the bytes)",
  "stale-output guard — a crashed re-run can never confirm",
  "bit-identical recompute kernels",
  "in-toto/SLSA attestation manifests",
  "CycloneDX ML-BOM",
  "GitHub Action CI gate",
  "--json verdicts for agents",
  "shareable teardown cards",
  "verification history per project",
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
          <div className="alsobox">
            <span className="alsobox__k">Also in the box</span>
            <p className="alsobox__items">
              {ALSO.map((item, i) => (
                <span key={item}>
                  {item}
                  {i < ALSO.length - 1 ? <i aria-hidden="true"> · </i> : null}
                </span>
              ))}
            </p>
          </div>
        </Reveal>

        <Reveal delay={350}>
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
