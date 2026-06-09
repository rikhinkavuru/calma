"use client";

import { Eyebrow } from "./primitives";
import { Reveal } from "./Reveal";

const MAP_ROWS = [
  { domain: "Net asset value", producer: "the fund", verifier: "fund administrator", hot: false },
  { domain: "The books", producer: "the company", verifier: "external auditor", hot: false },
  { domain: "Your agent's results", producer: "the model", verifier: "Calma", hot: true },
];

export function Independence() {
  return (
    <section id="independence" className="indep">
      <span className="sec__wm mono" aria-hidden="true">
        04
      </span>
      <div className="wrap sec__wrap">
        <Reveal className="indep__head">
          <Eyebrow num="04">Why independence</Eyebrow>
          <h2 className="indep__title">No one certifies their own number.</h2>
          <p className="indep__sub">
            The party that produces a result can&apos;t be the party trusted to verify it. Asking your
            agent to double-check its own number is the model grading its own homework — even when it
            re-runs the code, it still judges the match itself. Finance settled this everywhere except
            research: the verdict must come from an independent layer, computed by code.
          </p>
        </Reveal>

        <div className="map">
          <div className="map__cols mono">
            <span></span>
            <span className="map__h">produced by</span>
            <span></span>
            <span className="map__h">certified by</span>
          </div>
          {MAP_ROWS.map((r, i) => (
            <Reveal className={"map__row" + (r.hot ? " map__row--hot" : "")} key={r.domain} delay={i * 0.06}>
              <span className="map__domain">{r.domain}</span>
              <span className="map__node mono">{r.producer}</span>
              <span className="map__arrow mono" aria-hidden="true">
                →
              </span>
              <span className={"map__node map__node--v mono" + (r.hot ? " is-hot" : "")}>{r.verifier}</span>
            </Reveal>
          ))}
        </div>

        <p className="indep__kicker">
          <em>Calma is that independent layer for research</em> — applied before capital is committed, not after the drawdown explains why.
        </p>
      </div>
    </section>
  );
}
