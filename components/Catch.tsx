"use client";

import { Cross, Reveal, useInView } from "./chrome";

/* THE PROBLEM — one real story: a number that looked great and wasn't. */
export function Problem() {
  const [ref, seen] = useInView<HTMLDivElement>(0.3);

  return (
    <section className="sec sec--orbed" id="problem">
      <i className="orb orb--deep" aria-hidden="true"
         style={{ width: 620, height: 620, left: -200, bottom: -240 }} />
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">The problem</span>
          </Reveal>
          <Reveal delay={150}>
            <h2 className="h2">A wrong number looks exactly like a right one.</h2>
          </Reveal>
          <Reveal delay={250}>
            <p className="lead">
              An AI tested a trading strategy and reported a spectacular result. The report looked
              perfect. <b>Re-running the work on data the AI never saw</b> told a different story.
            </p>
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
                aria-label="Chart: the AI reported +14,698%; re-running the work on unseen data found −32.4%"
              >
                <line className="axis" x1="64" y1="22" x2="64" y2="288" />
                <line className="axis" x1="64" y1="288" x2="830" y2="288" />
                <line className="zero" x1="64" y1="254" x2="830" y2="254" />
                <line className="axis" x1="540" y1="22" x2="540" y2="288" />

                <text className="lbl lbl--amber" x="70" y="48">what the AI reported</text>
                <text className="lbl" x="70" y="249">0%</text>
                <text className="lbl" x="548" y="38">data the AI never saw →</text>
                <text className="lbl lbl--teal" x="668" y="240">the truth</text>

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
              <p className="lead">
                Nobody re-checks these numbers. <b>They get believed, shipped, and spent on.</b>
              </p>
              <div className="figs">
                <div className="fig">
                  <span className="k">What the AI reported</span>
                  <span className="v v--amber">+14,698%</span>
                </div>
                <div className="fig">
                  <span className="k">What was actually true</span>
                  <span className="v v--teal">−32.4%</span>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
