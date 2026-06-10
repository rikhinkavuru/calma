"use client";

import { SectionHead, useInView } from "./chrome";

/* 001 — the claim. The chart IS the argument: the in-sample mountain an agent reported,
   and what re-execution found on the data it never saw. Real numbers from the flagship
   fixture (vendored BTC data, best-of-100 in-sample tries). */

export function ClaimSection() {
  const [ref, seen] = useInView<HTMLDivElement>(0.3);

  return (
    <section className="section" id="claim">
      <div className="wrap">
        <SectionHead
          num="001 / Exhibit"
          title="The claim"
          note="A real backtest, submitted by an agent. Re-executed on held-out data."
        />

        <div className="claimgrid" ref={ref}>
          <div className="chartpanel">
            <svg
              className={"chart" + (seen ? " draw" : "")}
              viewBox="0 0 720 320"
              role="img"
              aria-label="Chart: the claimed +14,698% in-sample equity curve versus the recomputed −32.4% on held-out data"
            >
              {/* frame + grid */}
              <line className="axis" x1="60" y1="20" x2="60" y2="280" />
              <line className="axis" x1="60" y1="280" x2="700" y2="280" />
              <line className="gridline" x1="60" y1="60" x2="700" y2="60" />
              <line className="gridline" x1="60" y1="155" x2="700" y2="155" />
              <line className="zero" x1="60" y1="250" x2="700" y2="250" />
              <line className="axis" x1="460" y1="20" x2="460" y2="280" />

              {/* labels */}
              <text className="lbl" x="64" y="54">+14,698% — claimed</text>
              <text className="lbl" x="64" y="149">+7,000%</text>
              <text className="lbl" x="64" y="245">0%</text>
              <text className="lbl" x="466" y="30">holdout →</text>
              <text className="lbl" x="64" y="296">2018 — in-sample fit (best of 100 tries)</text>
              <text className="lbl" x="552" y="296">2024 — never seen</text>
              <text className="lbl lbl--flare" x="560" y="240">−32.4% — re-executed</text>

              {/* the in-sample mountain (ink) */}
              <polyline
                className="claimline"
                style={{ ["--len" as string]: 560 }}
                points="60,250 100,247 140,241 180,236 220,224 260,210 290,196 320,178 350,152 390,118 420,92 460,60"
              />
              {/* its projection, had you believed it */}
              <polyline
                points="460,60 540,46 620,36 700,30"
                fill="none"
                stroke="var(--ink)"
                strokeWidth="1.5"
                strokeDasharray="3 6"
                opacity="0.35"
              />
              {/* what re-execution found (flare) */}
              <polyline
                className="realline"
                style={{ ["--len" as string]: 300 }}
                points="460,250 490,254 520,248 550,258 580,262 610,257 640,266 670,263 700,268"
              />
            </svg>
          </div>

          <div className="claimmeta">
            <div className="row">
              <span className="k">Claimed — annual return</span>
              <span className="v">+14,698%</span>
            </div>
            <div className="row">
              <span className="k">Recomputed — held-out</span>
              <span className="v v--flare">−32.4%</span>
            </div>
            <div className="row">
              <span className="k">vs buy-and-hold</span>
              <span className="v">loses</span>
            </div>
            <p>
              The agent reported the survivor of one hundred in-sample fits. Calma re-ran the code
              on the data it never saw, rebuilt the return from{" "}
              <span className="mono">runs/oos/returns.csv</span>, and the claim collapsed. Verdict
              and reproduction below — run it yourself.
            </p>
            <div className="repro">$ calma replay ./btc-backtest/.calma/run{"\n"}REFUTED · exit 0 iff the verdict holds</div>
          </div>
        </div>
      </div>
    </section>
  );
}
