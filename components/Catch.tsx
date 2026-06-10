"use client";

import { Cross, Reveal, useInView } from "./chrome";

/* THE PROBLEM — shown, not told: a real number that looked great and wasn't. */
export function Problem() {
  const [ref, seen] = useInView<HTMLDivElement>(0.3);

  return (
    <section className="sec" id="problem">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">The problem — 001</span>
          </Reveal>
          <Reveal delay={150}>
            <div className="cascade" style={{ marginTop: 8 }}>
              <span>AI gives you a number.</span>
              <span>Sometimes it&apos;s wrong.</span>
              <span>Nothing looks wrong.</span>
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
                aria-label="Chart: an AI reported +14,698%; re-running the work on unseen data found −32.4%"
              >
                <line className="axis" x1="64" y1="22" x2="64" y2="288" />
                <line className="axis" x1="64" y1="288" x2="830" y2="288" />
                <line className="zero" x1="64" y1="254" x2="830" y2="254" />
                <line className="axis" x1="540" y1="22" x2="540" y2="288" />

                <text className="lbl lbl--amber" x="70" y="48">+14,698% — what the AI reported</text>
                <text className="lbl" x="70" y="249">0%</text>
                <text className="lbl" x="548" y="36">data the AI never saw →</text>
                <text className="lbl lbl--teal" x="660" y="242">−32.4% — the truth</text>

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
                An AI agent tested a trading strategy and reported its best result. The report
                looked perfect. <b>Nobody re-checks these numbers</b> — they get believed, shipped,
                and spent on.
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
              <p className="fieldnote">
                Field note: Deloitte refunded AU$440K after unverified AI work shipped to a client.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
