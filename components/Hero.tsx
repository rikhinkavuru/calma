"use client";

import { Reveal } from "./chrome";

export function Hero({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="hero" id="top">
      <div className="hero__moon" aria-hidden="true" />
      <div className="wrap hero__inner">
        <Reveal>
          <span className="hero__kicker">Independent verification for AI-produced results</span>
        </Reveal>
        <Reveal delay={100}>
          <h1>
            AI did the work.
            <br />
            <span className="serif">Who checked it?</span>
          </h1>
        </Reveal>
        <Reveal delay={200}>
          <p className="hero__sub">
            Calma re-runs your AI&apos;s code and recomputes the result it reported — an accuracy, a
            return, a total. The verdict comes from code, not opinion, so the bad number is caught{" "}
            <b>before anyone acts on it</b>.
          </p>
        </Reveal>
        <Reveal delay={300}>
          <div className="hero__cta">
            <a
              className="btn btn--blue"
              href="https://github.com/rikhinkavuru/calma"
              target="_blank"
              rel="noreferrer"
            >
              Get the free skill →
            </a>
            <button className="btn btn--line" onClick={onRequest}>
              Request verification
            </button>
          </div>
        </Reveal>
        <Reveal delay={380}>
          <p className="hero__note">Open source · runs locally · nothing leaves your machine</p>
        </Reveal>
      </div>
    </section>
  );
}
