"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { Reveal } from "./chrome";

const MoneyStack = dynamic(() => import("./MoneyStack").then((m) => m.MoneyStack), {
  ssr: false,
});

/* True one-liners, typed in the stage corner. Every line is sourced. */
const FACTS = [
  "claimed +14,698% → re-executed −32.4%. caught before the money moved.",
  "deloitte refunded AU$440K after unverified AI work shipped to a client.",
  "two-thirds of enterprises say trust is the #1 blocker to scaling agents.",
  "the verdict is computed by code. there is nothing to argue with.",
];

function Typewriter() {
  const [line, setLine] = useState(0);
  const [chars, setChars] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setChars(FACTS[0].length);
      return;
    }
    const full = FACTS[line];
    if (chars < full.length) {
      const t = setTimeout(() => setChars((c) => c + 1), 26);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => {
      setLine((l) => (l + 1) % FACTS.length);
      setChars(0);
    }, 3200);
    return () => clearTimeout(t);
  }, [chars, line]);

  return (
    <div className="stage__type" aria-live="polite">
      {FACTS[line].slice(0, chars)}
      <span className="caret" aria-hidden="true" />
    </div>
  );
}

export function Hero({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="hero" id="top">
      <div className="wrap hero__grid">
        <div>
          <Reveal>
            <h1>
              Money moves on AI&apos;s numbers. Calma checks them <em>first</em>.
            </h1>
          </Reveal>
          <Reveal delay={120}>
            <p className="hero__sub">
              Calma re-runs the work and rebuilds the number from the raw outputs — never from the
              claim. The verdict is computed by code, so even the agent that wrote the code
              can&apos;t talk it out of a fail.
            </p>
          </Reveal>
          <Reveal delay={220}>
            <div className="hero__cta">
              <a
                className="btn btn--solid"
                href="https://github.com/rikhinkavuru/calma"
                target="_blank"
                rel="noreferrer"
              >
                Get the free skill →
              </a>
              <button className="btn" onClick={onRequest}>
                Request verification
              </button>
            </div>
          </Reveal>
          <Reveal delay={300}>
            <div className="hero__foot">open source · pure stdlib · nothing leaves your machine</div>
          </Reveal>
        </div>

        <Reveal dir="pop" delay={150}>
          <div className="stage">
            <MoneyStack />
            <span className="stage__hint">hover · click</span>
            <Typewriter />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
