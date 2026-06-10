"use client";

import { Reveal, SectionHead, useInView } from "./chrome";

export function ClaimSection() {
  const [ref, seen] = useInView<HTMLDivElement>(0.3);

  return (
    <section className="section" id="catch">
      <div className="wrap">
        <SectionHead
          idx="01"
          title="A real catch"
          sub="An agent backtested a trading strategy and reported the best of a hundred tries. Calma re-ran it on the data it never saw."
        />

        <div className="claimgrid" ref={ref}>
          <Reveal dir="left">
            <div className="chartpanel">
              <svg
                className={"chart" + (seen ? " draw" : "")}
                viewBox="0 0 720 320"
                role="img"
                aria-label="Chart: the claimed +14,698% in-sample equity curve versus the recomputed −32.4% on held-out data"
              >
                <line className="axis" x1="60" y1="20" x2="60" y2="280" />
                <line className="axis" x1="60" y1="280" x2="700" y2="280" />
                <line className="zero" x1="60" y1="250" x2="700" y2="250" />
                <line className="axis" x1="460" y1="20" x2="460" y2="280" />

                <text className="lbl" x="64" y="54">+14,698% claimed</text>
                <text className="lbl" x="64" y="245">0%</text>
                <text className="lbl" x="466" y="30">unseen data →</text>
                <text className="lbl lbl--flare" x="560" y="240">−32.4% re-executed</text>

                <polyline
                  className="claimline"
                  style={{ ["--len" as string]: 560 }}
                  points="60,250 100,247 140,241 180,236 220,224 260,210 290,196 320,178 350,152 390,118 420,92 460,60"
                />
                <polyline
                  points="460,60 540,46 620,36 700,30"
                  fill="none"
                  stroke="var(--ink)"
                  strokeWidth="1.5"
                  strokeDasharray="3 6"
                  opacity="0.3"
                />
                <polyline
                  className="realline"
                  style={{ ["--len" as string]: 300 }}
                  points="460,250 490,254 520,248 550,258 580,262 610,257 640,266 670,263 700,268"
                />
              </svg>
            </div>
          </Reveal>

          <Reveal dir="right" delay={150}>
            <div className="claimmeta">
              <div className="big">
                +14,698% claimed.
                <br />
                <em>−32.4%</em> when re-run.
              </div>
              <p>
                The number was rebuilt from the run&apos;s own output files, inside a sandbox, under
                a calibrated tolerance. The claim collapsed — before any capital moved. Anyone can
                replay the verdict:
              </p>
              <pre className="repro">$ calma replay ./btc-backtest/.calma/run</pre>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
