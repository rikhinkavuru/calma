"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { CountUp, CropFrame, Eyebrow, Reveal } from "./chrome";

const MoneyStack = dynamic(() => import("./MoneyStack").then((m) => m.MoneyStack), {
  ssr: false,
});

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

export function Money() {
  return (
    <section className="money" id="money">
      <div className="wrap money__grid">
        <div>
          <Reveal>
            <Eyebrow>the stakes</Eyebrow>
          </Reveal>
          <Reveal delay={100}>
            <h2 style={{ marginTop: 18 }}>
              This is what moves on an{" "}
              <span className="serif-acc">unchecked</span> number.
            </h2>
          </Reveal>
          <Reveal delay={200}>
            <p className="lead">
              Allocations, payouts, budgets — capital settles on figures an agent printed. Nobody
              independently re-computes them. Calma is the referee the producer can&apos;t own: it
              re-runs the work in a sandbox and rebuilds the number itself.
            </p>
          </Reveal>
          <Reveal delay={300}>
            <div className="money__stats">
              <div className="mstat">
                <div className="n"><CountUp to={251} /></div>
                <div className="k">deterministic checks</div>
              </div>
              <div className="mstat">
                <div className="n">0</div>
                <div className="k">model opinions</div>
              </div>
              <div className="mstat">
                <div className="n"><CountUp to={15} /></div>
                <div className="k">metrics covered</div>
              </div>
            </div>
          </Reveal>
        </div>
        <Reveal dir="right" delay={150}>
          <CropFrame>
            <div className="stage">
              <MoneyStack />
              <span className="stage__hint">hover</span>
              <Typewriter />
            </div>
          </CropFrame>
        </Reveal>
      </div>
    </section>
  );
}
