"use client";

import { Reveal } from "./chrome";

const FEATS: [string, string][] = [
  [
    "Plain English in, plain English out",
    "Describe the claim the way you'd say it out loud. Get back one of four answers: confirmed, refuted, can't confirm, or confirmed with caveats.",
  ],
  [
    "Anyone can replay it",
    "Every verdict ships with one command that re-runs the entire check. You never have to take Calma's word for it either.",
  ],
  [
    "Nothing leaves your machine",
    "The work runs locally, in a sandbox with no network access. Your code and data are never uploaded, anywhere.",
  ],
  [
    "Your agents can use it",
    "AI agents call Calma to check their own results mid-task — so the mistake is caught before anyone sees it.",
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
          <div className="features">
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
