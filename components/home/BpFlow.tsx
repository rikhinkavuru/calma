import type { ComponentType } from "react";
import { FaArrowTrendUp, FaBitcoin, FaGaugeHigh, FaDatabase, FaTableCells } from "react-icons/fa6";
import { SiJupyter, SiScikitlearn, SiGithub } from "react-icons/si";
import { Reveal } from "../chrome";

/* The convergence section under the hero — a light band. Every kind of number an
   agent reports flows down the wires (slow pulses on the converging lines) into
   the engine (the lotus), which emits a single verdict. */

type Row = { Icon: ComponentType<{ size?: number }>; claim: string };
type Source = { name: string; tone: string; rows: Row[] };

const SOURCES: Source[] = [
  { name: "Trading", tone: "var(--teal)", rows: [
    { Icon: FaArrowTrendUp, claim: "Sharpe 2.61" },
    { Icon: FaBitcoin, claim: "+14,698%" },
  ] },
  { name: "ML & evals", tone: "var(--sky)", rows: [
    { Icon: SiJupyter, claim: "accuracy 0.94" },
    { Icon: SiScikitlearn, claim: "AUC 0.91" },
  ] },
  { name: "Engineering", tone: "var(--amber)", rows: [
    { Icon: SiGithub, claim: "2.3× faster" },
    { Icon: FaGaugeHigh, claim: "p99 142 ms" },
  ] },
  { name: "Analytics", tone: "var(--sun)", rows: [
    { Icon: FaDatabase, claim: "$4.2M total" },
    { Icon: FaTableCells, claim: "10,482 rows" },
  ] },
];

const VERDICTS: { label: string; cls: string }[] = [
  { label: "CONFIRMED", cls: "ok" },
  { label: "REFUTED", cls: "no" },
  { label: "INVALIDATED", cls: "inv" },
];

// converging wires: from each card column (top) down to the engine (bottom-center).
// viewBox aspect (~10:1) is kept close to the rendered aspect so the SVG's
// non-uniform stretch barely distorts the traveling pulses (they stay circular).
const IN_WIRES = [125, 375, 625, 875].map((sx, i) => ({
  d: `M ${sx} 0 C ${sx} 56, 500 50, 500 107`,
  begin: `${-i * 1.1}s`,
}));
// diverging wires: engine (top-center) → the three verdict columns. Drawn in a
// 600-wide box matched to the verdict grid so the line ends sit under each chip.
const OUT_WIRES = [100, 300, 500].map((ex) => `M 300 0 C 300 50, ${ex} 46, ${ex} 90`);

export function BpFlow() {
  return (
    <section className="flowsec">
      <div className="wrap">
        <div className="bp-block flow" id="flow">
          <Reveal>
            <div className="bp-head bp-head--center">
              <h2 className="bp-h2">
                Whatever your agent computes, <span className="am">one engine has the final say.</span>
              </h2>
              <p className="bp-lead">
                Backtests, model evals, benchmarks, datasets — every number flows into one engine,
                recomputed from the raw outputs and proven or broken.
              </p>
            </div>
          </Reveal>

          {/* source cards */}
          <div className="flow__cards">
            {SOURCES.map((s, i) => (
              <Reveal key={s.name} delay={i * 70}>
                <article className="flowcard" style={{ ["--tone" as string]: s.tone }}>
                  <header className="flowcard__h">
                    <span className="flowcard__name">{s.name}</span>
                  </header>
                  <ul className="flowcard__rows">
                    {s.rows.map((r) => (
                      <li key={r.claim} className="flowcard__row">
                        <span className="flowcard__ic"><r.Icon size={15} /></span>
                        <span className="flowcard__claim">{r.claim}</span>
                      </li>
                    ))}
                  </ul>
                </article>
              </Reveal>
            ))}
          </div>

          {/* converging wires + slow traveling data pulses (desktop) */}
          <svg className="flow__wires" viewBox="0 0 1000 107" preserveAspectRatio="none" aria-hidden="true">
            {IN_WIRES.map((w) => (
              <path key={w.d} className="flow__wire" d={w.d} fill="none" vectorEffect="non-scaling-stroke" />
            ))}
            {IN_WIRES.map((w) => (
              <circle key={`p${w.d}`} className="flow__pulse" r="2.1" vectorEffect="non-scaling-stroke">
                <animateMotion dur="5.4s" repeatCount="indefinite" path={w.d} begin={w.begin} calcMode="linear" />
              </circle>
            ))}
          </svg>

          {/* mobile connector */}
          <div className="flow__drop" aria-hidden="true" />

          {/* the engine — the lotus as the convergence point */}
          <Reveal>
            <div className="flow__node">
              <span className="flow__logo">
                <img src="/img/calma-lotus.png" alt="Calma" width={116} height={74} />
              </span>
            </div>
          </Reveal>

          {/* diverging wires down to the verdicts (no pulses), aligned to the chips */}
          <svg className="flow__wires flow__wires--out" viewBox="0 0 600 90" preserveAspectRatio="none" aria-hidden="true">
            {OUT_WIRES.map((d) => (
              <path key={d} className="flow__wire" d={d} fill="none" vectorEffect="non-scaling-stroke" />
            ))}
          </svg>

          {/* output */}
          <div className="flow__verdicts">
            {VERDICTS.map((v) => (
              <span key={v.label} className={`flow__verdict flow__verdict--${v.cls}`}>
                {v.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
