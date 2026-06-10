"use client";

import { Cross, Reveal, useInView } from "./chrome";

export function Catch() {
  const [ref, seen] = useInView<HTMLDivElement>(0.3);

  return (
    <section className="sec" id="catch">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Field report — 001</span>
          </Reveal>
          <Reveal delay={150}>
            <div className="cascade" style={{ marginTop: 8 }}>
              <span>The number looked great.</span>
              <span>Re-running it didn&apos;t.</span>
            </div>
          </Reveal>
        </div>

        <div className="catch" ref={ref}>
          <Reveal>
            <div className="panel">
              <Cross className="tl" />
              <Cross className="br" />
              <svg
                className={"chart" + (seen ? " draw" : "")}
                viewBox="0 0 860 330"
                role="img"
                aria-label="Chart: an AI reported +14,698% in-sample; re-execution on unseen data found −32.4%"
              >
                <line className="axis" x1="64" y1="22" x2="64" y2="288" />
                <line className="axis" x1="64" y1="288" x2="830" y2="288" />
                <line className="zero" x1="64" y1="254" x2="830" y2="254" />
                <line className="axis" x1="540" y1="22" x2="540" y2="288" />

                <text className="lbl lbl--amber" x="70" y="48">+14,698% — as reported</text>
                <text className="lbl" x="70" y="249">0%</text>
                <text className="lbl" x="548" y="36">data the AI never saw →</text>
                <text className="lbl lbl--teal" x="650" y="242">−32.4% — re-executed</text>

                <polyline
                  className="claimline"
                  style={{ ["--len" as string]: 700 }}
                  points="64,254 120,250 176,244 232,235 288,221 340,203 392,179 444,144 496,100 540,56"
                />
                <polyline
                  points="540,56 640,42 740,32 830,26"
                  fill="none"
                  stroke="rgba(233,221,196,.22)"
                  strokeWidth="1.4"
                  strokeDasharray="3 7"
                />
                <polyline
                  className="realline"
                  style={{ ["--len" as string]: 340 }}
                  points="540,254 580,259 620,253 660,264 700,268 740,263 780,272 830,275"
                />
              </svg>
            </div>
          </Reveal>

          <Reveal delay={200}>
            <div>
              <p className="col" style={{ marginBottom: 26 }}>
                An agent backtested a trading strategy and reported{" "}
                <b>the best of one hundred attempts</b>. Calma re-ran the code on data it had never
                seen.
              </p>
              <div className="figs">
                <div className="fig">
                  <span className="k">As reported</span>
                  <span className="v v--amber">+14,698%</span>
                </div>
                <div className="fig">
                  <span className="k">Re-executed</span>
                  <span className="v v--teal">−32.4%</span>
                </div>
                <div className="fig">
                  <span className="k">Verdict</span>
                  <span className="v">Refuted</span>
                </div>
              </div>
              <p className="replay">
                Rebuilt from the run&apos;s own output files — never the report. Replay it:{" "}
                <b>calma replay ./.calma/run</b>
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
