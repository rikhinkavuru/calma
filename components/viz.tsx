/* viz.tsx — small SVG data diagrams (charts, not illustrations).
   All schematic line/grid work, themed via CSS vars. */
import type { ComponentType } from "react";

/* generic polyline sparkline */
export function Spark({
  d,
  area,
  w = 120,
  h = 44,
  stroke = "var(--ink)",
  fill,
  sw = 1.5,
  dash,
}: {
  d: string;
  area?: string;
  w?: number;
  h?: number;
  stroke?: string;
  fill?: string;
  sw?: number;
  dash?: string;
}) {
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none" aria-hidden="true">
      {area && <path d={area} style={{ fill: fill || stroke, opacity: 0.1 }} />}
      <path
        d={d}
        style={{ stroke, fill: "none", strokeWidth: sw, strokeLinejoin: "round", strokeLinecap: "round", strokeDasharray: dash || "none" }}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/* claimed (rising, ink) vs verified (flat/declining, red) equity curves */
export function EquityDiverge({ h = 56 }: { h?: number }) {
  const claimed = "M0,52 L18,46 L36,42 L54,31 L72,26 L90,15 L108,9 L126,3";
  const verified = "M0,52 L18,50 L36,52 L54,47 L72,50 L90,46 L108,49 L126,45";
  const area = claimed + " L126,56 L0,56 Z";
  return (
    <svg className="spark" viewBox="0 0 126 56" width="100%" height={h} preserveAspectRatio="none" aria-hidden="true">
      <path d={area} style={{ fill: "var(--ink)", opacity: 0.07 }} />
      <path d={claimed} style={{ stroke: "var(--ink-3)", fill: "none", strokeWidth: 1.5, strokeDasharray: "3 3" }} vectorEffect="non-scaling-stroke" />
      <path d={verified} style={{ stroke: "var(--fail)", fill: "none", strokeWidth: 2 }} vectorEffect="non-scaling-stroke" strokeLinecap="round" />
    </svg>
  );
}

/* leakage scan: grid of cells, one flagged red */
export function Heatmap({ cols = 9, rows = 5, hot = [6, 1] }: { cols?: number; rows?: number; hot?: [number, number] }) {
  const cells = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const isHot = c === hot[0] && r === hot[1];
      const v = (Math.sin(c * 1.7 + r * 2.3) + 1) / 2;
      cells.push(
        <rect
          key={r + "-" + c}
          x={c * 12 + 1}
          y={r * 12 + 1}
          width="10"
          height="10"
          rx="1.5"
          style={{ fill: isHot ? "var(--fail)" : "var(--ink)", opacity: isHot ? 1 : 0.08 + v * 0.3 }}
        />
      );
    }
  }
  return (
    <svg className="spark" viewBox={`0 0 ${cols * 12} ${rows * 12}`} width="100%" height={rows * 12} aria-hidden="true">
      {cells}
    </svg>
  );
}

/* before → after big metric */
export function BeforeAfter({ from, to, label }: { from: string; to: string; label?: string }) {
  return (
    <div className="ba mono">
      <span className="ba__from">{from}</span>
      <span className="ba__arr">→</span>
      <span className="ba__to">{to}</span>
      {label && <span className="ba__lbl">{label}</span>}
    </div>
  );
}

/* ---- problem-card schematic diagrams (78px tall band) ---- */

export function DiagLookahead() {
  return (
    <svg className="diag" viewBox="0 0 240 78" width="100%" height="78" aria-hidden="true">
      <line x1="14" y1="50" x2="226" y2="50" style={{ stroke: "var(--line-2)", strokeWidth: 1 }} />
      {[40, 90, 140, 190].map((x, i) => (
        <g key={x}>
          <circle cx={x} cy="50" r="3.5" style={{ fill: i === 2 ? "var(--ink)" : "var(--ink-3)" }} />
          <text x={x} y="68" className="diag__t" textAnchor="middle">
            {["t-2", "t-1", "t", "t+1"][i]}
          </text>
        </g>
      ))}
      <path d="M190,38 C190,20 140,20 140,36" style={{ stroke: "var(--fail)", fill: "none", strokeWidth: 1.6 }} />
      <path d="M140,36 l-4,-6 l8,0 z" style={{ fill: "var(--fail)" }} />
      <text x="165" y="14" className="diag__lbl" textAnchor="middle" style={{ fill: "var(--fail)" }}>
        reads future
      </text>
    </svg>
  );
}

export function DiagSurvivorship() {
  const bars = [22, 40, 14, 34, 9, 30, 18];
  return (
    <svg className="diag" viewBox="0 0 240 78" width="100%" height="78" aria-hidden="true">
      <line x1="14" y1="60" x2="226" y2="60" style={{ stroke: "var(--line-2)", strokeWidth: 1 }} />
      {bars.map((bh, i) => {
        const dead = i === 2 || i === 4;
        const x = 28 + i * 28;
        return (
          <g key={i}>
            <rect
              x={x}
              y={60 - bh}
              width="16"
              height={bh}
              rx="1.5"
              style={{ fill: dead ? "transparent" : "var(--ink)", opacity: dead ? 1 : 0.85, stroke: dead ? "var(--line-2)" : "none", strokeWidth: 1, strokeDasharray: "2 2" }}
            />
            {dead && <line x1={x - 2} y1={60 - bh - 4} x2={x + 18} y2="64" style={{ stroke: "var(--fail)", strokeWidth: 1.4 }} />}
          </g>
        );
      })}
      <text x="120" y="14" className="diag__lbl" textAnchor="middle">
        delisted names dropped
      </text>
    </svg>
  );
}

export function DiagLeakage() {
  return (
    <svg className="diag" viewBox="0 0 240 78" width="100%" height="78" aria-hidden="true">
      <rect x="36" y="22" width="62" height="34" rx="4" style={{ fill: "none", stroke: "var(--line-2)", strokeWidth: 1 }} />
      <text x="67" y="43" className="diag__big" textAnchor="middle">
        X
      </text>
      <text x="67" y="14" className="diag__t" textAnchor="middle">
        features
      </text>
      <rect x="142" y="22" width="62" height="34" rx="4" style={{ fill: "var(--fail-bg)", stroke: "var(--fail)", strokeWidth: 1 }} />
      <text x="173" y="43" className="diag__big" textAnchor="middle" style={{ fill: "var(--fail)" }}>
        y
      </text>
      <text x="173" y="14" className="diag__t" textAnchor="middle">
        target
      </text>
      <path d="M142,39 L104,39" style={{ stroke: "var(--fail)", fill: "none", strokeWidth: 1.6 }} />
      <path d="M104,39 l6,-4 l0,8 z" style={{ fill: "var(--fail)" }} />
      <text x="120" y="70" className="diag__lbl" textAnchor="middle" style={{ fill: "var(--fail)" }}>
        bleeds in
      </text>
    </svg>
  );
}

export function DiagRepro() {
  return (
    <svg className="diag" viewBox="0 0 240 78" width="100%" height="78" aria-hidden="true">
      <circle cx="30" cy="40" r="3.5" style={{ fill: "var(--ink)" }} />
      <path d="M30,40 C90,38 140,20 214,14" style={{ stroke: "var(--ink)", fill: "none", strokeWidth: 1.6 }} />
      <path d="M30,40 C90,42 140,58 214,64" style={{ stroke: "var(--fail)", fill: "none", strokeWidth: 1.6, strokeDasharray: "3 3" }} />
      <text x="222" y="14" className="diag__t" textAnchor="end" dx="-6">
        run A
      </text>
      <text x="222" y="72" className="diag__t" textAnchor="end" dx="-6" style={{ fill: "var(--fail)" }}>
        run B
      </text>
      <text x="78" y="34" className="diag__lbl" textAnchor="middle">
        same code
      </text>
    </svg>
  );
}

export const DIAGS: Record<string, ComponentType> = {
  "look-ahead": DiagLookahead,
  survivorship: DiagSurvivorship,
  leakage: DiagLeakage,
  repro: DiagRepro,
};

/* ---- how-it-works per-check diagrams (wide band, ~108 tall) ---- */

export function CheckLineage() {
  const inputs: [string, boolean][] = [
    ["close[t]", false],
    ["vol[t]", false],
    ["close[t+1]", true],
  ];
  return (
    <svg className="diag" viewBox="0 0 280 108" width="100%" height="108" aria-hidden="true">
      {inputs.map(([lbl, bad], i) => {
        const y = 20 + i * 32;
        return (
          <g key={i}>
            <line x1="92" y1={y + 9} x2="184" y2="63" style={{ stroke: bad ? "var(--fail)" : "var(--line-2)", strokeWidth: bad ? 1.6 : 1 }} />
            <rect x="6" y={y} width="86" height="18" rx="3" style={{ fill: bad ? "var(--fail-bg)" : "var(--paper)", stroke: bad ? "var(--fail)" : "var(--line-2)", strokeWidth: 1 }} />
            <text x="49" y={y + 12.5} className="diag__c" textAnchor="middle" style={{ fill: bad ? "var(--fail)" : "var(--ink-2)" }}>
              {lbl}
            </text>
          </g>
        );
      })}
      <rect x="184" y="50" width="90" height="28" rx="4" style={{ fill: "var(--ink)" }} />
      <text x="229" y="68" className="diag__c" textAnchor="middle" style={{ fill: "var(--paper)" }}>
        signal[t]
      </text>
      <text x="229" y="20" className="diag__lbl" textAnchor="middle" style={{ fill: "var(--fail)" }}>
        1 input from t+1
      </text>
    </svg>
  );
}

export function CheckReconcile() {
  const claimed = "M6,86 L52,74 L98,66 L144,44 L190,34 L236,16 L274,8";
  const recomp = "M6,86 L52,82 L98,80 L144,70 L190,72 L236,64 L274,60";
  return (
    <svg className="diag" viewBox="0 0 280 108" width="100%" height="108" aria-hidden="true">
      <path d={claimed + " L274,60 L236,64 L190,72 L144,70 L98,80 L52,82 L6,86 Z"} style={{ fill: "var(--fail)", opacity: 0.07 }} />
      <path d={claimed} style={{ stroke: "var(--ink-3)", fill: "none", strokeWidth: 1.4, strokeDasharray: "3 3" }} vectorEffect="non-scaling-stroke" />
      <path d={recomp} style={{ stroke: "var(--ink)", fill: "none", strokeWidth: 2 }} vectorEffect="non-scaling-stroke" />
      <text x="274" y="10" className="diag__c" textAnchor="end" style={{ fill: "var(--ink-3)" }}>
        claimed
      </text>
      <text x="274" y="74" className="diag__c" textAnchor="end" style={{ fill: "var(--ink)" }}>
        recomputed
      </text>
      <text x="150" y="56" className="diag__lbl" style={{ fill: "var(--fail)" }}>
        Δ unexplained
      </text>
    </svg>
  );
}

export function CheckHoldout() {
  return (
    <svg className="diag" viewBox="0 0 280 108" width="100%" height="108" aria-hidden="true">
      <rect x="6" y="18" width="178" height="22" rx="3" style={{ fill: "var(--ink)", opacity: 0.85 }} />
      <rect x="190" y="18" width="84" height="22" rx="3" style={{ fill: "var(--paper)", stroke: "var(--accent)", strokeWidth: 1.2 }} />
      <text x="95" y="33" className="diag__c" textAnchor="middle" style={{ fill: "var(--paper)" }}>
        in-sample
      </text>
      <text x="232" y="33" className="diag__c" textAnchor="middle" style={{ fill: "var(--accent-ink)" }}>
        holdout
      </text>
      <rect x="6" y="62" width="178" height="30" rx="3" style={{ fill: "var(--ink)", opacity: 0.06 }} />
      <text x="14" y="82" className="diag__big" style={{ fill: "var(--ink)" }}>
        2.81
      </text>
      <text x="120" y="82" className="diag__c" style={{ fill: "var(--ink-3)" }}>
        sharpe
      </text>
      <rect x="190" y="62" width="84" height="30" rx="3" style={{ fill: "var(--fail-bg)" }} />
      <text x="200" y="82" className="diag__big" style={{ fill: "var(--fail)" }}>
        0.2
      </text>
    </svg>
  );
}

export function CheckInvariants() {
  const rows: [string, boolean][] = [
    ["Σ weights = 1", true],
    ["cash ⟺ positions", true],
    ["signal ≺ fill", false],
    ["exposure ≤ mandate", true],
  ];
  return (
    <svg className="diag" viewBox="0 0 280 108" width="100%" height="108" aria-hidden="true">
      {rows.map(([lbl, ok], i) => {
        const y = 12 + i * 24;
        return (
          <g key={i}>
            <text x="8" y={y + 12} className="diag__c" style={{ fill: ok ? "var(--ink-2)" : "var(--fail)" }}>
              {lbl}
            </text>
            <text x="272" y={y + 12} className="diag__c" textAnchor="end" style={{ fill: ok ? "var(--pass)" : "var(--fail)", fontWeight: 600 }}>
              {ok ? "hold ✓" : "violated ✕"}
            </text>
            {i < 3 && <line x1="8" y1={y + 21} x2="272" y2={y + 21} style={{ stroke: "var(--line)", strokeWidth: 1 }} />}
          </g>
        );
      })}
    </svg>
  );
}

export const CHECK_DIAGS: Record<string, ComponentType> = {
  provenance: CheckLineage,
  recompute: CheckReconcile,
  holdout: CheckHoldout,
  invariants: CheckInvariants,
};

/* ---- how-it-works pipeline flow ---- */
export function FlowDiagram() {
  const steps = ["provenance", "recompute", "holdout", "invariants"];
  return (
    <div className="flow">
      <div className="flow__node flow__in mono">
        <span className="flow__cap">input</span>
        <span className="flow__val">strategy + raw trades</span>
      </div>
      <span className="flow__edge" aria-hidden="true" />
      <div className="flow__checks">
        {steps.map((s, i) => (
          <div className="flow__check mono" key={s}>
            <span className="flow__num">{String(i + 1).padStart(2, "0")}</span>
            <span>{s}</span>
          </div>
        ))}
      </div>
      <span className="flow__edge" aria-hidden="true" />
      <div className="flow__node flow__out mono">
        <span className="flow__cap">output</span>
        <span className="flow__val">signed verdict</span>
      </div>
    </div>
  );
}
