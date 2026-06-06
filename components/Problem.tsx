"use client";

import { Section } from "./primitives";
import { Reveal } from "./Reveal";
import { DIAGS } from "./viz";

const FAILURES = [
  {
    id: "look-ahead",
    name: "Look-ahead bias",
    glyph: "t+1",
    desc: "It survives every unit test you wrote. The leak is in a join you trusted, not in the signal logic.",
    tell: "Returns inflate smoothly. No exception is raised.",
  },
  {
    id: "survivorship",
    name: "Survivorship bias",
    glyph: "Σ",
    desc: "The universe quietly drops names that delisted or defaulted — a set only knowable in hindsight.",
    tell: "The dead names leave no error. Just the dataset.",
  },
  {
    id: "leakage",
    name: "Target leakage",
    glyph: "y→x",
    desc: "It hides one fold deep — the kind you only notice after the strategy is already live.",
    tell: "Cross-validation looks immaculate. Production doesn't.",
  },
  {
    id: "repro",
    name: "Non-reproducibility",
    glyph: "≠",
    desc: "Re-run the same code and the number moves — an unset seed, a silent revision. If it doesn't reproduce, it isn't a result.",
    tell: "It passed once. That was enough to get funded.",
  },
];

export function Problem() {
  return (
    <Section
      id="problem"
      num="01"
      label="The problem"
      bg="tint"
      watermark="01"
      title="Your backtest doesn't throw an error when it's wrong."
      intro="The failures that cost money are silent. Four account for almost everything."
    >
      <div className="pgrid">
        {FAILURES.map((f, i) => {
          const Diag = DIAGS[f.id];
          return (
            <Reveal as="article" className="pcell" key={f.id} delay={(i % 2) * 0.08}>
              <div className="pcell__top">
                <span className="pcell__idx mono">{String(i + 1).padStart(2, "0")}</span>
                <span className="pcell__glyph mono">{f.glyph}</span>
              </div>
              <h3 className="pcell__name">{f.name}</h3>
              <div className="pcell__diag">{Diag && <Diag />}</div>
              <p className="pcell__desc">{f.desc}</p>
              <p className="pcell__tell mono">
                <span className="pcell__tell-mark">↳</span>
                {f.tell}
              </p>
            </Reveal>
          );
        })}
      </div>

      <div className="prob-thesis">
        <div className="prob-thesis__rule" />
        <p className="prob-thesis__text">
          None of these raise an exception — which is why a model asked
          <em> “does this look right?”</em> can't catch them. Eval tools interrogate judgment. Calma interrogates reality: the data, the trades, the timestamps.
        </p>
      </div>
    </Section>
  );
}
