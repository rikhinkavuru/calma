"use client";

import { Reveal } from "./chrome";

const FEATS: [string, string, React.ReactNode][] = [
  [
    "Plain-language claims",
    "Say what was claimed the way you'd say it out loud. Calma finds the number and the metric.",
    <>verify . &quot;+14,698% backtest&quot;</>,
  ],
  [
    "Four fixed verdicts",
    "Confirmed, refuted, can't confirm, or confirmed with caveats. JSON for machines, words for people.",
    <>= &nbsp;≠&nbsp; ? &nbsp;≈ <span className="dim">· {`{"verdict": "REFUTED"}`}</span></>,
  ],
  [
    "Replayable proof",
    "Every verdict can be re-run by anyone, with one command. Trust nothing — replay it.",
    <>calma replay ./.calma/run <span className="dim">· exit 0 if it holds</span></>,
  ],
  [
    "Private by design",
    "Runs on your machine, in a sandbox that proves itself before it's trusted. Nothing is uploaded.",
    <>secret read — blocked <span className="dim">·</span> network — blocked</>,
  ],
  [
    "Any stack",
    "Fifteen metrics across trading, machine learning, and analytics. Five languages, run as a black box.",
    <>python · r · julia · c++ · rust</>,
  ],
  [
    "Fast enough for loops",
    "Agents call it after every result. Anything unchanged answers from cache instantly.",
    <>re-check 0.08s <span className="dim">· first run 2.2s</span></>,
  ],
];

export function Features() {
  return (
    <section className="sec" id="features">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Features — the instrument</span>
          </Reveal>
        </div>
        <Reveal delay={120}>
          <div className="features">
            {FEATS.map(([t, d, art]) => (
              <div className="feat" key={t}>
                <b>{t}</b>
                <p>{d}</p>
                <span className="art">{art}</span>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
