"use client";

import { Section } from "./primitives";
import { Reveal } from "./Reveal";
import { CHECK_DIAGS } from "./viz";

const CHECKS = [
  {
    id: "provenance",
    num: "01",
    name: "Point-in-time provenance",
    one: "Every signal traced back to data knowable at decision time. Forward leaks are flagged to the field.",
    spec: [
      ["asserts", "knowable_at(x) ≤ t"],
      ["flags", "forward leaks · restatements"],
    ],
  },
  {
    id: "recompute",
    num: "02",
    name: "Independent recomputation",
    one: "Returns rebuilt from the raw fills — never the reported curve — and reconciled basis point by basis point.",
    spec: [
      ["rebuilds", "equity from fills + costs"],
      ["attributes", "every Δ to its cause"],
    ],
  },
  {
    id: "holdout",
    num: "03",
    name: "Unseen-data re-run",
    one: "The frozen strategy is re-executed on a window withheld from research. Signal survives; overfitting collapses.",
    spec: [
      ["quarantines", "out-of-sample window"],
      ["measures", "in-sample → holdout decay"],
    ],
  },
  {
    id: "invariants",
    num: "04",
    name: "Invariant assertion",
    one: "The identities that must hold for any honest backtest, checked on every bar, with the first violation surfaced.",
    spec: [
      ["enforces", "causality: signal ≺ fill"],
      ["surfaces", "first violation + row"],
    ],
  },
];

export function HowItWorks() {
  return (
    <Section
      id="how"
      num="02"
      label="How it works"
      watermark="02"
      title="Four checks. Each re-derives a claim from ground truth."
      intro="Calma doesn't read your code and form an opinion — it re-executes the strategy against the data and proves, or breaks, every assumption the result depends on."
    >
      <div className="spine">
        <div className="cap cap--in">
          <span className="cap__node" />
          <span className="cap__txt mono">
            <b>input</b> — strategy + raw trade log
          </span>
        </div>

        {CHECKS.map((c, i) => {
          const Diag = CHECK_DIAGS[c.id];
          return (
            <Reveal className="fstep" key={c.id} delay={(i % 2) * 0.06}>
              <div className="fstep__rail">
                <span className="fstep__node mono">{c.num}</span>
              </div>
              <div className="fstep__body">
                <h3 className="fstep__name">{c.name}</h3>
                <p className="fstep__one">{c.one}</p>
                <dl className="fstep__spec mono">
                  {c.spec.map(([k, v]) => (
                    <div className="cspec" key={k}>
                      <dt>{k}</dt>
                      <dd>{v}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <div className="fstep__diag">{Diag && <Diag />}</div>
            </Reveal>
          );
        })}

        <div className="cap cap--out">
          <span className="cap__node cap__node--out" />
          <span className="cap__txt mono">
            <b>output</b> — signed, reproducible verdict
          </span>
        </div>
      </div>
    </Section>
  );
}
