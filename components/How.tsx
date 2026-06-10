"use client";

import { Reveal } from "./chrome";

const STEPS = [
  ["1.", "Re-run", "The work executes again in a sandbox that proves itself first — secret reads and network access must fail before anything is trusted."],
  ["2.", "Recompute", "The headline number is rebuilt from the raw output files. Never read from the report."],
  ["3.", "Compare", "Rebuilt against reported, under a tolerance calibrated so hardware noise never raises a false alarm."],
  ["4.", "Decide", "One deterministic function returns the verdict. A crashed, flaky, or gamed run can never confirm."],
] as const;

export function How() {
  return (
    <section className="sec" id="how">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">How it works</span>
          </Reveal>
          <Reveal delay={90}>
            <h2>
              Re-run. Recompute. <span className="serif">Decide.</span>
            </h2>
          </Reveal>
        </div>
        <div className="howgrid">
          <div className="steps">
            {STEPS.map(([n, t, d], i) => (
              <Reveal key={t} delay={i * 80} dir="left">
                <div className="step">
                  <span className="step__n">{n}</span>
                  <div>
                    <b>{t}</b>
                    <p>{d}</p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal dir="right" delay={160}>
            <div>
              <div className="jsoncard">
                <span className="cm">$ calma verify . &quot;accuracy 0.87&quot; --json</span>
                {"\n"}
                {"{"}
                {"\n"}
                {"  "}&quot;verdict&quot;: <span className="b">&quot;CONFIRMED&quot;</span>,{"\n"}
                {"  "}&quot;claimed&quot;: 0.87,{"\n"}
                {"  "}&quot;recomputed&quot;: 0.87{"\n"}
                {"}"}
              </div>
              <p className="jsoncard__cap">
                Agents call it after every result and branch on the answer. Anything unchanged
                answers from cache in milliseconds.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
