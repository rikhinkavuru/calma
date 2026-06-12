"use client";

import { Atmo, Reveal } from "./chrome";

export function Hero({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="hero" id="top">
      <Atmo />
      <div className="wrap hero__inner hero__inner--center">
        <Reveal>
          <h1 className="h1">AI did the work. Calma checks it.</h1>
        </Reveal>

        <Reveal delay={200}>
          <p className="lead hero__lead">
            Calma re-runs your AI&apos;s work, rebuilds the numbers it reported, and tells you —
            in one word — <b>whether to trust them.</b>
          </p>
        </Reveal>

        <Reveal delay={350}>
          <div className="hero__cta">
            <button className="pbtn pbtn--amber" onClick={onRequest}>
              Request verification
            </button>
            <a
              className="pbtn"
              href="https://github.com/rikhinkavuru/calma"
              target="_blank"
              rel="noreferrer"
            >
              Get the free skill
            </a>
          </div>
        </Reveal>

        <Reveal delay={500}>
          <div className="hero__demo">
            <figure className="term hero__movie">
              <video
                src="/video/hero-demo.mp4"
                autoPlay
                muted
                loop
                playsInline
                controls
                preload="metadata"
                aria-label="Screen recording: an AI agent reports an inflated backtest return; calma blocks the turn, refutes the number, and the agent corrects itself"
              />
            </figure>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
