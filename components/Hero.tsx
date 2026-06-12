"use client";

import { Atmo, Reveal } from "./chrome";

export function Hero({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="hero" id="top">
      <Atmo />
      <div className="wrap hero__inner">
        <Reveal>
          <span className="kicker">Independent verification lab</span>
          <h1 className="h1">AI did the work. Calma checks it.</h1>
        </Reveal>

        <Reveal delay={250}>
          <p className="lead hero__lead">
            Calma re-runs your AI&apos;s work, rebuilds the numbers it reported, and tells you —
            in one word — <b>whether to trust them.</b>
          </p>
        </Reveal>

        <Reveal delay={450}>
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
          <p className="hero__split">
            The engine is free and open source — builders and their agents use it today. The lab
            runs <a href="/lab">signed verification engagements</a> for allocators and funds.
          </p>
        </Reveal>

        <Reveal delay={650}>
          <div className="hero__demo">
            <figure className="term hero__movie">
              <div className="term__bar">
                <div className="term__dots" aria-hidden="true">
                  <i></i>
                  <i></i>
                  <i></i>
                </div>
                <span className="term__title">Live recording — the zero-touch catch</span>
                <span className="term__title" aria-hidden="true">87s</span>
              </div>
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
              <figcaption className="hero__movie-cap micro">
                Unscripted session — the agent reports +19,971%, calma re-executes the work
                and blocks the turn: the real number is +168%.
              </figcaption>
            </figure>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
