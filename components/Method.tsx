"use client";

import { Glyph, Reveal } from "./chrome";

const STEPS = [
  ["rerun", "Re-run", "The work executes again in a sandbox that proves itself first."],
  ["recompute", "Recompute", "The number is rebuilt from the raw output files. Never the report."],
  ["diff", "Compare", "Rebuilt vs reported, under a calibrated tolerance. Noise never false-alarms."],
  ["decide", "Decide", "One deterministic function. Crashed, flaky, or gamed runs can never confirm."],
] as const;

export function Method() {
  return (
    <section className="sec" id="method">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Method</span>
          </Reveal>
        </div>
        <div className="method">
          {STEPS.map(([kind, t, d], i) => (
            <Reveal key={t} delay={i * 140}>
              <div className="spec">
                <span className="spec__box">
                  <Glyph kind={kind as "rerun"} />
                </span>
                <span className="spec__t">
                  {t}
                  <small>/0{i + 1}</small>
                </span>
                <p className="spec__d">{d}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
