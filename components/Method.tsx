"use client";

import { Eyebrow, Reveal } from "./chrome";

const ROWS = [
  ["/01", "Re-run", "The work executes again in a sandbox that proves itself — secret reads and network egress must fail before the tier is trusted."],
  ["/02", "Recompute", "The headline number is rebuilt from the raw output files. Never read from the claim."],
  ["/03", "Diff", "Recomputed against claimed, under a tolerance calibrated so hardware noise never raises a false alarm."],
  ["/04", "Decide", "One pure function returns the verdict. Crashed, flaky, or gamed runs can never confirm."],
] as const;

export function Method() {
  return (
    <section className="sec" id="how">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <Eyebrow>methodology</Eyebrow>
          </Reveal>
          <Reveal delay={100}>
            <h2>
              One command. <span className="serif-acc">Four moves.</span>
            </h2>
          </Reveal>
        </div>
        <div className="rows">
          {ROWS.map(([n, t, d], i) => (
            <Reveal key={n} delay={i * 90} dir={i % 2 ? "right" : "left"}>
              <div className="row">
                <span className="row__n">{n}</span>
                <span className="row__t">{t}</span>
                <span className="row__d">{d}</span>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
