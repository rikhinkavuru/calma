"use client";

import { SectionHead, useInView } from "./chrome";

const STEPS = [
  {
    n: "M-01",
    t: "Re-execute",
    d: "The work runs again in a sandbox that proves itself first — a planted secret-read and a network call must both fail before the tier is claimed.",
    spec: "doctor: secret_read blocked\negress blocked · tier verified\ncrashed re-run ⇒ never confirms",
  },
  {
    n: "M-02",
    t: "Recompute",
    d: "The headline number is rebuilt from the output files the run just produced. Never the reported value. Fifteen recipes, deterministic kernels.",
    spec: "recompute(predictions.csv)\n→ accuracy 0.87\nno numpy · no transcendentals",
  },
  {
    n: "M-03",
    t: "Diff",
    d: "Recomputed against claimed, under a calibrated tolerance that includes the claim's own noise. Hardware variation never raises a false alarm.",
    spec: "gap 147.30 » budget 1e-9\nzero false-refuted, n=16 corpus\nclaim SE in the budget",
  },
  {
    n: "M-04",
    t: "Decide",
    d: "One pure function computes the verdict; the ledger re-derives every label byte-for-byte and rejects mismatches. Each run is attested.",
    spec: "verdict(inputs) → REFUTED\nin-toto + ML-BOM manifest\ncalma replay · exit 0 iff holds",
  },
];

export function Method() {
  const [ref, seen] = useInView<HTMLDivElement>(0.3);
  return (
    <section className="section" id="method">
      <div className="wrap">
        <SectionHead
          num="002 / Instrument"
          title="Method"
          note="One command. Four checks. Cached re-checks answer in milliseconds."
        />
        <div className={"method" + (seen ? " run" : "")} ref={ref}>
          {STEPS.map((s) => (
            <div className="step" key={s.n}>
              <div className="step__hd">
                <span>{s.n}</span>
                <span>seq</span>
              </div>
              <div className="step__t">{s.t}</div>
              <p className="step__d">{s.d}</p>
              <div className="step__spec">{s.spec}</div>
              <div className="step__pulse" aria-hidden="true">
                <i></i>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
