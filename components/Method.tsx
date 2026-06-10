"use client";

import { Reveal, SectionHead } from "./chrome";

const STEPS = [
  ["Re-run", "The work executes again in a sandbox that proves itself before it's trusted."],
  ["Recompute", "The headline number is rebuilt from the raw output files — never read from the claim."],
  ["Diff", "Recomputed against claimed, under a tolerance calibrated so noise never raises a false alarm."],
  ["Decide", "One pure function returns the verdict. A crashed, flaky, or gamed run can never confirm."],
] as const;

export function Method() {
  return (
    <section className="section section--tint" id="how">
      <div className="wrap">
        <SectionHead idx="02" title="How it works" sub="One command. Four steps. Cached re-checks answer in milliseconds, so agents run it after every result." />
        <div className="method">
          {STEPS.map(([t, d], i) => (
            <Reveal key={t} delay={i * 110} dir={i % 2 ? "up" : "pop"}>
              <div className={"step" + (i === 3 ? " step--last" : "")}>
                <span className="step__n mono">0{i + 1}</span>
                <div className="step__t">{t}</div>
                <p className="step__d">{d}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
