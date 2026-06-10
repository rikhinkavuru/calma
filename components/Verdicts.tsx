"use client";

import { Reveal } from "./chrome";

const CARDS = [
  ["g-pass", "=", "Confirmed", "exit 0", "It re-runs, and the rebuilt number matches the report."],
  ["g-fail", "≠", "Refuted", "exit 1", "The rebuilt number contradicts the report — a one-command replay is attached."],
  ["g-warn", "?", "Can't confirm", "fix named", "Not verifiable yet. The report names the exact change that would make it verifiable."],
  ["g-cav", "≈", "With caveats", "scope printed", "Holds, but narrower than reported — and the caveat is printed on the verdict."],
] as const;

export function Verdicts() {
  return (
    <section className="sec sec--card" id="verdicts">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">What you get back</span>
          </Reveal>
          <Reveal delay={90}>
            <h2>
              Four answers. <span className="serif">Never a shrug.</span>
            </h2>
          </Reveal>
          <Reveal delay={170}>
            <p>
              A fixed vocabulary, biased toward a caveat over a false alarm — so when Calma does say
              a result is broken, it means it.
            </p>
          </Reveal>
        </div>
        <div className="verdicts">
          {CARDS.map(([cls, glyph, name, x, p], i) => (
            <Reveal key={name} delay={i * 90} dir={i % 2 ? "pop" : "up"}>
              <div className="verdict">
                <div className={"verdict__glyph " + cls} aria-hidden="true">
                  {glyph}
                </div>
                <b>{name}</b>
                <span className="x mono">{x}</span>
                <p>{p}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
