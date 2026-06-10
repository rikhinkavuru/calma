"use client";

import dynamic from "next/dynamic";
import { GlobeEye } from "./chrome";

const StarSpinner = dynamic(() => import("./StarSpinner").then((m) => m.StarSpinner), {
  ssr: false,
});

export function Hero({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="hero">
      <div className="wrap">
        <div className="hero__grid">
          <div className="stage">
            <StarSpinner />
            <span className="stage__corner tl" aria-hidden="true"></span>
            <span className="stage__corner tr" aria-hidden="true"></span>
            <span className="stage__corner br" aria-hidden="true"></span>
            <span className="stage__reg">CALMA//RE-EXECUTION</span>
            <span className="stage__hud" aria-hidden="true">
              spin 1.5 rad/s
              <br />
              precession ±0.09
            </span>
          </div>
          <div className="panel thesis">
            <span className="eyebrow">The mark — verdicts computed by code</span>
            <h2>Your AI did the work. Calma re-runs it.</h2>
            <p>
              The number is rebuilt from the raw outputs — never read from the claim — inside a
              sandbox that proves itself before it&apos;s trusted. One pure function decides; even
              the agent that wrote the code can&apos;t talk it out of a fail.
            </p>
            <div className="thesis__cta">
              <a
                className="btn btn--solid"
                href="https://github.com/rikhinkavuru/calma"
                target="_blank"
                rel="noreferrer"
              >
                Get the skill →
              </a>
              <button className="btn" onClick={onRequest}>
                Request verification
              </button>
            </div>
            <div className="eye" aria-hidden="true">
              <GlobeEye />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
