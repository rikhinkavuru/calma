"use client";

import { Section } from "./primitives";
import { Reveal } from "./Reveal";

const STATS = [
  {
    n: <>~35%</>,
    t: "of 12,720 studied notebooks reproduce at all. Re-running the same code on the same data can still give different results.",
    s: "Pimentel et al., notebook reproducibility",
  },
  {
    n: (
      <>
        0.97 <em>→ 0.91</em>
      </>
    ),
    t: "a published model's AUC once data leakage was removed. Leakage is documented across 17+ fields and hundreds of papers.",
    s: "Kapoor & Narayanan, leakage survey",
  },
  {
    n: <em>+14,698%</em>,
    t: "a real backtest's claimed return. Re-executed on held-out data it recomputes to −32.4% — best of 100 in-sample tries.",
    s: "Calma flagship fixture, vendored BTC data",
  },
  {
    n: <>~21%</>,
    t: "accuracy of LLM agents asked to judge reproducibility. Judgment fails where re-execution works.",
    s: "REPRO-Bench, 2025",
  },
];

export function Problem() {
  return (
    <Section
      id="problem"
      num="01"
      label="the failure mode"
      watermark="01 / SILENT"
      title={
        <>
          Plausible numbers <span className="dim">fail silently.</span>
        </>
      }
      intro={
        <>
          Agents and pipelines produce numbers all day — accuracy, returns, row counts, totals.
          When one is wrong, nothing looks wrong: the failure is a plausible number that doesn&apos;t
          survive re-execution. You can&apos;t catch that by asking a model if it looks right.
        </>
      }
    >
      <Reveal className="stats">
        {STATS.map((s, i) => (
          <article className="stat" key={i}>
            <div className="stat__n">{s.n}</div>
            <p className="stat__t">{s.t}</p>
            <div className="stat__s mono">{s.s}</div>
          </article>
        ))}
      </Reveal>
    </Section>
  );
}
