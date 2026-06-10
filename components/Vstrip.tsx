"use client";

import { Reveal } from "./chrome";

const CELLS = [
  ["=", "", "Confirmed", "exit 0", "Re-runs, and the rebuilt number matches the report."],
  ["≠", "g--amber", "Refuted", "exit 1 · replay attached", "The rebuilt number contradicts the report."],
  ["?", "", "Can't confirm", "fix named", "Not verifiable yet — the exact fix is printed."],
  ["≈", "", "With caveats", "scope printed", "Holds, narrower than reported. The caveat is stated."],
] as const;

export function Vstrip() {
  return (
    <section className="sec" id="verdicts">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Possible verdicts — four</span>
          </Reveal>
        </div>
        <Reveal delay={120}>
          <div className="vstrip">
            {CELLS.map(([g, cls, name, x, p]) => (
              <div className="vcell" key={name}>
                <span className={"g " + cls}>{g}</span>
                <b>{name}</b>
                <span className="x">{x}</span>
                <p>{p}</p>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
