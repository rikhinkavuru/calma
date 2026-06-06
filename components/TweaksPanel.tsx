"use client";

/* Self-contained Tweaks panel — the standalone-site equivalent of the
   prototype's host-driven panel. A launcher pill opens a glass panel that
   live-controls theme / accent / headline / the editorial serif moment. */
import { useState } from "react";
import type { Tweaks } from "./App";

const ACCENTS: { name: string; hex: string }[] = [
  { name: "ochre", hex: "#a8763c" },
  { name: "graphite", hex: "#6c6760" },
  { name: "evergreen", hex: "#3f7a5f" },
  { name: "slate", hex: "#5f7393" },
];

function Check() {
  return (
    <svg viewBox="0 0 14 14" aria-hidden="true">
      <path d="M3 7.2 5.8 10 11 4.2" fill="none" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" stroke="#fff" />
    </svg>
  );
}

export function TweaksPanel({ t, setTweak }: { t: Tweaks; setTweak: <K extends keyof Tweaks>(k: K, v: Tweaks[K]) => void }) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button className="twk-launch" onClick={() => setOpen(true)} aria-label="Open tweaks">
        <span className="twk-launch__glyph" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        tweaks
      </button>
    );
  }

  const themes: Tweaks["theme"][] = ["paper", "ink"];
  const themeIdx = themes.indexOf(t.theme);

  return (
    <div className="twk-panel" role="dialog" aria-label="Tweaks">
      <div className="twk-hd">
        <b>Tweaks</b>
        <button className="twk-x" aria-label="Close tweaks" onClick={() => setOpen(false)}>
          ✕
        </button>
      </div>
      <div className="twk-body">
        <div className="twk-sect">Surface</div>

        <div className="twk-row">
          <div className="twk-lbl">
            <span>Theme</span>
          </div>
          <div className="twk-seg" role="radiogroup">
            <div
              className="twk-seg-thumb"
              style={{ left: `calc(2px + ${themeIdx} * (100% - 4px) / ${themes.length})`, width: `calc((100% - 4px) / ${themes.length})` }}
            />
            {themes.map((th) => (
              <button key={th} type="button" role="radio" aria-checked={t.theme === th} onClick={() => setTweak("theme", th)}>
                {th}
              </button>
            ))}
          </div>
        </div>

        <div className="twk-row">
          <div className="twk-lbl">
            <span>Accent</span>
          </div>
          <div className="twk-chips">
            {ACCENTS.map((a) => (
              <button
                key={a.name}
                type="button"
                className="twk-chip"
                data-on={t.accent === a.name ? "1" : "0"}
                style={{ background: a.hex }}
                aria-label={a.name}
                onClick={() => setTweak("accent", a.name as Tweaks["accent"])}
              >
                {t.accent === a.name && <Check />}
              </button>
            ))}
          </div>
        </div>

        <div className="twk-sect">Hero</div>

        <div className="twk-row">
          <div className="twk-lbl">
            <span>Headline</span>
          </div>
          <select className="twk-field" value={t.headline} onChange={(e) => setTweak("headline", e.target.value as Tweaks["headline"])}>
            <option value="blunt">blunt</option>
            <option value="earned">earned</option>
            <option value="quiet">quiet</option>
          </select>
        </div>

        <div className="twk-row twk-row-h">
          <div className="twk-lbl">
            <span>Editorial serif moment</span>
          </div>
          <button
            type="button"
            className="twk-toggle"
            data-on={t.serifMoment ? "1" : "0"}
            role="switch"
            aria-checked={t.serifMoment}
            onClick={() => setTweak("serifMoment", !t.serifMoment)}
          >
            <i />
          </button>
        </div>
      </div>
    </div>
  );
}
