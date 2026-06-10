"use client";

import { Reveal, SectionHead } from "./chrome";

const VERDICTS = [
  ["is-ink", "=", "Confirmed", "It re-runs, and the rebuilt number matches the claim."],
  ["is-flare", "≠", "Refuted", "The recomputed number contradicts the claim — replay attached."],
  ["is-bone", "?", "Can't confirm", "Not verifiable yet. The report names the exact fix."],
  ["", "≈", "With caveats", "Holds, but narrower than claimed — the caveat is printed."],
] as const;

export function Verdicts() {
  return (
    <section className="section section--tint" id="verdicts">
      <div className="wrap">
        <SectionHead
          idx="04"
          title="Four possible answers"
          sub="Fixed vocabulary, biased toward a caveat over a false alarm. It never cries wolf."
        />
        <div className="verdicts">
          {VERDICTS.map(([chip, glyph, name, p], i) => (
            <Reveal key={name} delay={i * 110} dir={i < 2 ? "left" : "right"}>
              <div className="verdict">
                <div className={"verdict__chip " + chip} aria-hidden="true">
                  {glyph}
                </div>
                <div className="verdict__meta">
                  <b>{name}</b>
                  <p>{p}</p>
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
