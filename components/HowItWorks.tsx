"use client";

import { Section } from "./primitives";
import { Reveal } from "./Reveal";

const STEPS = [
  {
    num: "01 / RE-EXECUTE",
    h: "Run the work again, in a verified sandbox",
    p: "Network off, secrets unreadable — and a built-in doctor self-test proves the sandbox actually blocks both before the tier is claimed. A crashed re-run can never confirm: stale output files don't count.",
    code: (
      <>
        <span className="c-d">$</span> run_hermetic.py doctor{"\n"}
        <span className="c-g">✓</span> secret_read_blocked: true{"\n"}
        <span className="c-g">✓</span> egress_blocked: true <span className="c-d">— tier: seatbelt-verified</span>
      </>
    ),
  },
  {
    num: "02 / RECOMPUTE",
    h: "Rebuild the number from the raw outputs",
    p: "The headline metric is recomputed from the output files the run just produced — never the reported value, never a notebook cell. Reference-deterministic kernels: no floating-point surprises, no numpy, no transcendentals.",
    code: (
      <>
        <span className="c-d"># 15 recipes: sharpe, return, drawdown, accuracy,</span>{"\n"}
        <span className="c-d"># auc, f1, rmse, r², sums, means, row counts…</span>{"\n"}
        recompute(predictions.csv) <span className="c-d">→</span> accuracy = 0.87
      </>
    ),
  },
  {
    num: "03 / DIFF",
    h: "Compare against the claim, under a calibrated tolerance",
    p: "The gap is judged against a calibrated budget that includes the claim's own sampling noise — so normal hardware and threading variation never causes a false alarm. Zero false-REFUTED on the calibration corpus.",
    code: (
      <>
        claimed 0.99 <span className="c-d">vs</span> recomputed 0.87{"\n"}
        gap 0.12 <span className="c-d">&gt;&gt;</span> budget 0.005 <span className="c-d">→</span>{" "}
        <span className="c-r">statistically distinguishable</span>
      </>
    ),
  },
  {
    num: "04 / DECIDE",
    h: "A deterministic verdict no model can author",
    p: "One pure verdict() function computes the label; the ledger re-derives every stored verdict byte-for-byte and rejects mismatches. Then it's attested: a content-addressed manifest (in-toto + CycloneDX ML-BOM) for the audit trail.",
    code: (
      <>
        verdict(inputs) <span className="c-d">→</span> <span className="c-r">REFUTED</span>{"\n"}
        ledger: re-derived byte-for-byte <span className="c-g">✓</span>{"\n"}
        <span className="c-d">calma replay → exit 0 iff it reproduces</span>
      </>
    ),
  },
];

export function HowItWorks() {
  return (
    <Section
      id="how"
      num="02"
      label="the method"
      bg="tint"
      watermark="02 / EXECUTE"
      title={
        <>
          Re-run it. Recompute it. <span className="dim">Decide with code.</span>
        </>
      }
      intro={
        <>
          One command — <code className="mono">calma verify &lt;folder&gt; &quot;accuracy 0.87&quot;</code> —
          runs a four-step pipeline, one auditable script per step. Re-verifying anything unchanged
          returns the cached verdict in milliseconds, so agents can call it after every result.
        </>
      }
    >
      <div className="how">
        {STEPS.map((s, i) => (
          <Reveal className="how__card" key={i} delay={i * 0.06}>
            <div className="how__num">{s.num}</div>
            <h3 className="how__h">{s.h}</h3>
            <p className="how__p">{s.p}</p>
            <div className="how__code">{s.code}</div>
          </Reveal>
        ))}
      </div>
    </Section>
  );
}
