"use client";

import { Reveal } from "./chrome";
import { FAMILIES, RECIPE_COUNT } from "@/app/recipes/data";

/* The recipe coverage band: a heading, a kinetic strip of every family, and a
   browse CTA. Each segment carries a category glyph + tone; each metric is a
   live link that lights up and jumps to its entry on the recipes page. */

type GlyphKind =
  | "trading" | "class" | "reg" | "analytics" | "eng"
  | "retrieval" | "stats" | "finance" | "compiled";
type Tone = "amber" | "teal" | "sky";

const META: Record<string, { glyph: GlyphKind; tone: Tone }> = {
  trading: { glyph: "trading", tone: "amber" },
  classification: { glyph: "class", tone: "teal" },
  regression: { glyph: "reg", tone: "sky" },
  analytics: { glyph: "analytics", tone: "amber" },
  engineering: { glyph: "eng", tone: "sky" },
  retrieval: { glyph: "retrieval", tone: "teal" },
  stats: { glyph: "stats", tone: "sky" },
  finance: { glyph: "finance", tone: "amber" },
  compiled: { glyph: "compiled", tone: "teal" },
};

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
    case "finance":
      return (
        <svg {...p}>
          <circle cx="9" cy="9" r="7" />
          <line x1="9" y1="4.5" x2="9" y2="13.5" />
        </svg>
      );
    case "compiled":
      return (
        <svg {...p}>
          <path d="M6 3 C 3 3, 3 9, 1.5 9 C 3 9, 3 15, 6 15" />
          <path d="M12 3 C 15 3, 15 9, 16.5 9 C 15 9, 15 15, 12 15" />
        </svg>
      );
  }
}

function Segment({ famKey, title, recipes }: { famKey: string; title: string; recipes: { id: string; name: string }[] }) {
  const meta = META[famKey] ?? { glyph: "compiled" as GlyphKind, tone: "teal" as Tone };
  return (
    <span className={`rtick__seg rtick__seg--${meta.tone}`}>
      <Glyph kind={meta.glyph} />
      <span className="rtick__fam">{title}</span>
      <span className="rtick__metrics">
        {recipes.map((r) => (
          <a className="rtick__metric" href={`/recipes#${r.id}`} key={r.id}>
            {r.name}
          </a>
        ))}
      </span>
    </span>
  );
}

export function RecipeTicker() {
  const segs = FAMILIES.map((f) => ({
    famKey: f.key,
    title: f.title,
    recipes: f.recipes.slice(0, 4).map((r) => ({ id: r.id, name: r.name })),
  }));
  const loop = [...segs, ...segs];

  return (
    <section className="sec recsec" id="recipes">
      <div className="wrap recsec__head">
        <Reveal>
          <span className="kicker">The recipe library</span>
        </Reveal>
        <Reveal delay={120}>
          <h2 className="h2 recsec__h2">
            <span className="recsec__num">{RECIPE_COUNT}</span> validated recipes
          </h2>
        </Reveal>
        <Reveal delay={200}>
          <p className="lead recsec__lead">
            One deterministic procedure per number, each validated against its published reference.
            Hover to light one up — click to jump straight to how it&apos;s rebuilt.
          </p>
        </Reveal>
      </div>

      <Reveal delay={150} className="recsec__rail">
        <div className="rtick" aria-label="Recipe families Calma verifies">
          <div className="rtick__track">
            {loop.map((s, i) => (
              <Segment key={`${s.famKey}-${i}`} famKey={s.famKey} title={s.title} recipes={s.recipes} />
            ))}
          </div>
        </div>
      </Reveal>

      <div className="wrap recsec__foot">
        <Reveal>
          <a className="pbtn pbtn--amber" href="/recipes">
            Browse the library →
          </a>
        </Reveal>
      </div>
    </section>
  );
}
