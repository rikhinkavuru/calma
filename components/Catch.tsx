"use client";

import { Reveal, useInView } from "./chrome";

/* One concrete story carries the whole pitch. Real numbers from a real run. */
export function Catch() {
  const [ref, seen] = useInView<HTMLDivElement>(0.3);

  return (
    <section className="sec sec--card" id="catch">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">A real catch</span>
          </Reveal>
          <Reveal delay={90}>
            <h2>
              The number looked great.
              <br />
              <span className="serif">Re-running it didn&apos;t.</span>
            </h2>
          </Reveal>
          <Reveal delay={170}>
            <p>
              An AI agent backtested a trading strategy and reported the best of a hundred attempts.
              Calma re-ran the code on data it had never seen.
            </p>
          </Reveal>
        </div>

        <div className="catchgrid" ref={ref}>
          <Reveal dir="left">
            <div className="chartcard">
              <svg
                className={"chart" + (seen ? " draw" : "")}
                viewBox="0 0 860 330"
                role="img"
                aria-label="Chart: the claimed +14,698% in-sample curve versus the −32.4% found by re-execution on unseen data"
              >
                <line className="axis" x1="64" y1="22" x2="64" y2="288" />
                <line className="axis" x1="64" y1="288" x2="830" y2="288" />
                <line className="zero" x1="64" y1="254" x2="830" y2="254" />
                <line className="axis" x1="540" y1="22" x2="540" y2="288" />

                <text className="lbl" x="70" y="48">+14,698% — as reported</text>
                <text className="lbl" x="70" y="249">0%</text>
                <text className="lbl" x="548" y="36">data the AI never saw →</text>
                <text className="lbl lbl--blue" x="650" y="242">−32.4% — re-executed</text>

                <polyline
                  className="claimline"
                  style={{ ["--len" as string]: 700 }}
                  points="64,254 120,250 176,244 232,235 288,221 340,203 392,179 444,144 496,100 540,56"
                />
                <polyline
                  points="540,56 640,42 740,32 830,26"
                  fill="none"
                  stroke="rgba(16,20,27,.3)"
                  strokeWidth="1.5"
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

          <Reveal dir="right" delay={140}>
            <div className="catchmeta">
              <div className="figures">
                <div className="fig">
                  <span className="k">As reported</span>
                  <span className="v">+14,698%</span>
                </div>
                <div className="fig">
                  <span className="k">Re-executed on unseen data</span>
                  <span className="v blue">−32.4%</span>
                </div>
                <div className="fig">
                  <span className="k">Verdict</span>
                  <span className="v blue">Refuted</span>
                </div>
              </div>
              <p>
                The result was rebuilt from the run&apos;s own output files — <b>never taken from
                the report</b>. Anyone can replay the verdict:
              </p>
              <div className="codeline">$ calma replay ./btc-backtest/.calma/run</div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
