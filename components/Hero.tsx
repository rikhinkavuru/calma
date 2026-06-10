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
            <a
              className="pbtn pbtn--amber"
              href="https://github.com/rikhinkavuru/calma"
              target="_blank"
              rel="noreferrer"
            >
              Get the free skill
            </a>
            <button className="pbtn" onClick={onRequest}>
              Request verification
            </button>
          </div>
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
