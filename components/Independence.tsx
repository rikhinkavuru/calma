"use client";

import { Section } from "./primitives";
import { Reveal } from "./Reveal";

const MAP_ROWS = [
  { domain: "Net asset value", producer: "the fund", verifier: "fund administrator", hot: false },
  { domain: "The books", producer: "the company", verifier: "external auditor", hot: false },
  { domain: "Your agent's results", producer: "the model", verifier: "Calma", hot: true },
];

export function Independence() {
  return (
    <Section
      id="independence"
      num="04"
      label="why independent"
      bg="deep"
      watermark="04 / REFEREE"
      title={
        <>
          The auditor can&apos;t be <span className="dim">the auditee.</span>
        </>
      }
      intro={
        <>
          Asking your agent to double-check its own number is the model grading its own homework —
          even when it re-runs the code, it still judges the match itself, and nothing stops it from
          &quot;fixing&quot; the comparison instead of the code. Every other domain where money moves
          settled this long ago: the verdict comes from an independent layer, computed by code.
        </>
      }
    >
      <Reveal className="map">
        <div className="map__cols mono">
          <span></span>
          <span>produced by</span>
          <span></span>
          <span>certified by</span>
        </div>
        {MAP_ROWS.map((r) => (
          <div className={"map__row" + (r.hot ? " map__row--hot" : "")} key={r.domain}>
            <span className="map__domain">{r.domain}</span>
            <span className="map__node mono">{r.producer}</span>
            <span className="map__arrow mono" aria-hidden="true">
              →
            </span>
            <span className={"map__node map__node--v mono" + (r.hot ? " is-hot" : "")}>
              {r.verifier}
            </span>
          </div>
        ))}
      </Reveal>
      <Reveal as="p" className="indep__kicker" delay={0.1}>
        <em>The verdict, every statistic, and the confidence score come from deterministic,
        unit-tested scripts</em> — and the ledger re-derives every label byte-for-byte, so a model
        can&apos;t author a passing verdict. Eval and observability tools score outputs with
        model-as-judge; data validators check schemas. None re-execute the work and recompute the
        claimed number. That empty cell is what Calma fills.
      </Reveal>
    </Section>
  );
}
