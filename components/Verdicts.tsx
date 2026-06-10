"use client";

import { SectionHead } from "./chrome";

const VERDICTS = [
  {
    chip: "is-ink",
    glyph: "=",
    name: "Confirmed",
    hex: "exit 0",
    p: "Re-runs, and the rebuilt number matches the claim within the calibrated budget.",
  },
  {
    chip: "is-flare",
    glyph: "≠",
    name: "Refuted",
    hex: "exit 1 · repro attached",
    p: "The recomputed number contradicts the claim. Ships a teardown card and a one-command replay.",
  },
  {
    chip: "is-bone2",
    glyph: "?",
    name: "Can't confirm",
    hex: "exit 1 · fix named",
    p: "Not verifiable yet — the report names the exact change. Never a shrug, never a guess.",
  },
  {
    chip: "is-chalk",
    glyph: "≈",
    name: "With caveats",
    hex: "exit 0 · scope stamped",
    p: "Holds, but narrower than claimed — and the caveat is printed on the verdict.",
  },
];

export function Verdicts() {
  return (
    <section className="section" id="verdicts">
      <div className="wrap">
        <SectionHead
          num="004 / Vocabulary"
          title="Verdicts"
          note="Fixed vocabulary, machine-consumable, biased toward a caveat over a false alarm."
        />
        <div className="verdicts">
          {VERDICTS.map((v) => (
            <div className="verdict" key={v.name}>
              <div className={"verdict__chip " + v.chip} aria-hidden="true">
                {v.glyph}
              </div>
              <div className="verdict__meta">
                <b>{v.name}</b>
                <span className="hx">{v.hex}</span>
                <p>{v.p}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
