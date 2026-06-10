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
  "the verdict is computed by code. nothing to argue with.",
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

export function Specimen() {
  return (
    <section className="sec" id="stakes">
      <div className="wrap specimen">
        <Reveal>
          <div>
            <span className="kicker">Specimen — capital at stake</span>
            <p className="col" style={{ marginTop: 22 }}>
              Allocations, payouts, budgets — <b>this is what settles on an unchecked figure</b>.
              Calma is the referee the producer can&apos;t own.
            </p>
          </div>
        </Reveal>
        <Reveal delay={180}>
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
