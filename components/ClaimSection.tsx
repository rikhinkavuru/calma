"use client";

import { CropFrame, Eyebrow, Reveal, useInView } from "./chrome";

/* The drift chart, deep-space edition: metallic claim line vs accent re-execution line. */
export function ClaimSection() {
  const [ref, seen] = useInView<HTMLDivElement>(0.3);

  return (
    <section className="sec" id="chart">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <Eyebrow>in-sample vs unseen data</Eyebrow>
          </Reveal>
          <Reveal delay={100}>
            <h2>
              The mountain was <span className="serif-acc">fitted.</span>
              <br />
              The cliff was <span className="serif-acc">real.</span>
            </h2>
          </Reveal>
        </div>
        <Reveal dir="pop" delay={150}>
          <div ref={ref}>
            <CropFrame className="chartwrap">
              <svg
                className={"chart" + (seen ? " draw" : "")}
                viewBox="0 0 920 340"
                role="img"
                aria-label="Chart: the claimed +14,698% in-sample equity curve versus the recomputed −32.4% on held-out data"
              >
                <defs>
                  <linearGradient id="metalStroke" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor="#ffffff" />
                    <stop offset="1" stopColor="#6f6f7c" />
                  </linearGradient>
                </defs>
                <line className="axis" x1="70" y1="24" x2="70" y2="296" />
                <line className="axis" x1="70" y1="296" x2="890" y2="296" />
                <line className="zero" x1="70" y1="262" x2="890" y2="262" />
                <line className="axis" x1="580" y1="24" x2="580" y2="296" />

                <text className="lbl" x="76" y="52">+14,698% claimed</text>
                <text className="lbl" x="76" y="257">0%</text>
                <text className="lbl" x="588" y="38">unseen data →</text>
                <text className="lbl lbl--acc" x="704" y="250">−32.4% re-executed</text>

                <polyline
                  className="claimline"
                  style={{ ["--len" as string]: 760 }}
                  points="70,262 130,258 190,251 250,242 310,228 360,210 410,186 460,150 510,106 545,80 580,56"
                />
                <polyline
                  points="580,56 680,40 790,30 890,24"
                  fill="none"
                  stroke="#6f6f7c"
                  strokeWidth="1.5"
                  strokeDasharray="3 7"
                  opacity="0.5"
                />
                <polyline
                  className="realline"
                  style={{ ["--len" as string]: 360 }}
                  points="580,262 620,267 660,261 700,272 740,276 780,271 820,280 855,277 890,283"
                />
              </svg>
            </CropFrame>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
