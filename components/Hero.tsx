"use client";

import { Eyebrow, Reveal } from "./chrome";

export function Hero({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="hero" id="top">
      <div className="hero__moon" aria-hidden="true" />
      <div className="wrap hero__inner">
        <Reveal>
          <Eyebrow>built for the agent economy</Eyebrow>
        </Reveal>
        <Reveal delay={100}>
          <h1 style={{ marginTop: 22 }}>
            We re-run, recompute
            <br />
            <span className="dim2">&amp; </span>
            <span className="serif-acc">verify</span>
            <span className="dim2"> AI&apos;s </span>
            <span className="serif-acc">numbers.</span>
          </h1>
        </Reveal>
        <Reveal delay={200}>
          <p className="hero__sub">
            Money moves on what AI reports. Calma re-executes the work, rebuilds the number from the
            raw outputs, and returns a verdict computed by code — before the money moves.
          </p>
        </Reveal>
        <Reveal delay={300}>
          <div className="hero__cta">
            <a
              className="pillbtn pillbtn--solid"
              href="https://github.com/rikhinkavuru/calma"
              target="_blank"
              rel="noreferrer"
            >
              Get the free skill →
            </a>
            <button className="pillbtn" onClick={onRequest}>
              Request verification
            </button>
          </div>
        </Reveal>
        <Reveal delay={420}>
          <div className="hero__scroll">scroll ↓</div>
        </Reveal>
      </div>
    </section>
  );
}
