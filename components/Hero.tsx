"use client";

import { Atmo, Reveal } from "./chrome";
import { Demo } from "./Demo";

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
            <Demo />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
