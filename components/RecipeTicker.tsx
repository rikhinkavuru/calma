"use client";

/* A kinetic coverage strip: each segment is one recipe family — a category
   glyph (its mark), the family name, and a few of its metrics. Differentiated
   by glyph + grouping, not a flat word stream. Pauses on hover. */

type Fam = { fam: string; glyph: GlyphKind; metrics: string[] };
type GlyphKind =
  | "trading" | "class" | "reg" | "analytics" | "eng"
  | "retrieval" | "stats" | "risk" | "finance" | "forecast";

const FAMILIES: Fam[] = [
  { fam: "Trading", glyph: "trading", metrics: ["Sharpe", "Sortino", "Calmar", "max drawdown"] },
  { fam: "Classification", glyph: "class", metrics: ["AUC", "F1", "MCC", "log-loss"] },
  { fam: "Regression", glyph: "reg", metrics: ["RMSE", "MAE", "R²"] },
  { fam: "Analytics", glyph: "analytics", metrics: ["median", "p95", "growth", "join-loss"] },
  { fam: "Engineering", glyph: "eng", metrics: ["p99 latency", "throughput", "peak memory"] },
  { fam: "Retrieval & LLM", glyph: "retrieval", metrics: ["recall@k", "NDCG", "pass@k", "MRR"] },
  { fam: "Statistics", glyph: "stats", metrics: ["p-value", "chi-square", "Cohen's d"] },
  { fam: "Quant risk", glyph: "risk", metrics: ["VaR", "CVaR", "beta"] },
  { fam: "Finance", glyph: "finance", metrics: ["CAGR", "IRR", "churn"] },
  { fam: "Forecasting", glyph: "forecast", metrics: ["MAPE", "WAPE", "MASE"] },
];

function Glyph({ kind }: { kind: GlyphKind }) {
  const p = { className: "rtick__glyph", viewBox: "0 0 18 18", "aria-hidden": true } as const;
  switch (kind) {
    case "trading":
      return (
        <svg {...p}>
          <line x1="6" y1="2" x2="6" y2="16" />
          <rect x="3.5" y="6" width="5" height="6" />
          <line x1="13" y1="4" x2="13" y2="15" />
          <rect x="10.5" y="8" width="5" height="4" />
        </svg>
      );
    case "class":
      return (
        <svg {...p}>
          <circle cx="9" cy="9" r="7" />
          <circle cx="9" cy="9" r="2.6" />
        </svg>
      );
    case "reg":
      return (
        <svg {...p}>
          <polyline points="2 15 7 10 11 12 16 4" />
        </svg>
      );
    case "analytics":
      return (
        <svg {...p}>
          <line x1="4" y1="16" x2="4" y2="9" />
          <line x1="9" y1="16" x2="9" y2="3" />
          <line x1="14" y1="16" x2="14" y2="11" />
        </svg>
      );
    case "eng":
      return (
        <svg {...p}>
          <path d="M3 13 a6 6 0 0 1 12 0" />
          <line x1="9" y1="13" x2="12.5" y2="8" />
        </svg>
      );
    case "retrieval":
      return (
        <svg {...p}>
          <circle cx="7.5" cy="7.5" r="4.8" />
          <line x1="11.4" y1="11.4" x2="16" y2="16" />
        </svg>
      );
    case "stats":
      return (
        <svg {...p}>
          <path d="M2 15 C 6 15, 6 4, 9 4 C 12 4, 12 15, 16 15" />
        </svg>
      );
    case "risk":
      return (
        <svg {...p}>
          <path d="M9 2 L15 5 V9 C15 13 12 15 9 16 C6 15 3 13 3 9 V5 Z" />
        </svg>
      );
    case "finance":
      return (
        <svg {...p}>
          <circle cx="9" cy="9" r="7" />
          <line x1="9" y1="4.5" x2="9" y2="13.5" />
        </svg>
      );
    case "forecast":
      return (
        <svg {...p}>
          <line x1="2" y1="9" x2="9" y2="9" />
          <line x1="9" y1="9" x2="13" y2="9" strokeDasharray="2 2.4" />
          <polyline points="11.5 6 14.5 9 11.5 12" />
        </svg>
      );
  }
}

export function RecipeTicker() {
  const segs = [...FAMILIES, ...FAMILIES];
  return (
    <div className="rtick" aria-label="Recipe families Calma verifies">
      <div className="rtick__track">
        {segs.map((f, i) => (
          <span className="rtick__seg" key={i}>
            <Glyph kind={f.glyph} />
            <span className="rtick__fam">{f.fam}</span>
            <span className="rtick__metrics">{f.metrics.join(" · ")}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
