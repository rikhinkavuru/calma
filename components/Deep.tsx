"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { Reveal } from "./chrome";

const MoneyStack = dynamic(() => import("./MoneyStack").then((m) => m.MoneyStack), {
  ssr: false,
});

const FACTS = [
  "an agent claimed +14,698%. re-execution found −32.4%.",
  "deloitte refunded AU$440K after unverified AI work shipped.",
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
      const t = setTimeout(() => setChars((c) => c + 1), 24);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => {
      setLine((l) => (l + 1) % FACTS.length);
      setChars(0);
    }, 3400);
    return () => clearTimeout(t);
  }, [chars, line]);
  return (
    <div className="stage__type" aria-live="polite">
      {FACTS[line].slice(0, chars)}
      <span className="caret" aria-hidden="true" />
    </div>
  );
}

/* The one deep, mystical band: what's actually at stake. */
export function Deep() {
  return (
    <section className="deep" id="stakes">
      <div className="wrap">
        <div>
          <Reveal>
            <span className="kicker">Why it matters</span>
          </Reveal>
          <Reveal delay={90}>
            <h2>
              Money moves on
              <br />
              <span className="serif">unchecked</span> numbers.
            </h2>
          </Reveal>
          <Reveal delay={180}>
            <p className="lead">
              Allocations, payouts, budgets — capital settles on figures an agent printed, and
              nobody re-computes them. Calma is the referee the producer can&apos;t own:{" "}
              <b>it re-runs the work and rebuilds the number itself.</b>
            </p>
          </Reveal>
        </div>
        <Reveal dir="right" delay={140}>
          <div className="stage">
            <MoneyStack />
            <span className="stage__hint">hover</span>
            <Typewriter />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
