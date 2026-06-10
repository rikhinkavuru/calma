"use client";

const STEPS = [
  {
    n: "01",
    ttl: "Re-execute",
    desc: "The work runs again in a sandbox — network off, secrets unreadable, proven by a self-test before the tier is claimed. A crashed re-run can never confirm.",
    spec: "doctor: secret_read_blocked ✓\negress_blocked ✓",
  },
  {
    n: "02",
    ttl: "Recompute",
    desc: "The headline number is rebuilt from the output files the run just produced. Never the reported value. Fifteen recipes, reference-deterministic, no numpy.",
    spec: "recompute(predictions.csv)\n→ accuracy = 0.87",
  },
  {
    n: "03",
    ttl: "Diff",
    desc: "Recomputed against claimed, under a calibrated tolerance that includes the claim's own noise. Hardware variation never raises a false alarm.",
    spec: "gap 0.12 » budget 0.005\nstatistically distinguishable",
  },
  {
    n: "04",
    ttl: "Decide",
    desc: "One pure verdict() function computes the label; the ledger re-derives every stored verdict byte-for-byte. Then it's attested — a content-addressed manifest per run.",
    spec: "verdict(inputs) → REFUTED\nre-derived ✓ · calma replay",
  },
];

export function Method() {
  return (
    <section className="section wrap" id="method">
      <div className="sec-head">
        <div>
          <span className="eyebrow">The method</span>
          <h2 className="sec-title">One command. Four checks.</h2>
          <p className="sec-lead">
            <strong>calma verify &lt;folder&gt; &quot;accuracy 0.87&quot;</strong> — claims in plain
            language, one auditable script per step. Unchanged work answers from cache in
            milliseconds, so agents call it after every result.
          </p>
        </div>
        <div className="index" aria-hidden="true"><span className="lead">0</span>01</div>
      </div>
      <div className="exhibits">
        {STEPS.map((s) => (
          <div className="exhibit" key={s.n}>
            <span className="thumb">{s.n}</span>
            <div className="ttl">{s.ttl}</div>
            <div className="desc">{s.desc}</div>
            <div className="spec">{s.spec}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
