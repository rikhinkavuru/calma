"use client";

import { useEffect, useRef, useState } from "react";
import { GITHUB_URL } from "../contact";

const WORDS = ["number", "backtest", "eval", "metric", "result"];
const TARGET = 239855; // 623 recipes × 385 reference vectors, re-derived each release

export function BpCounter({ onRequest }: { onRequest?: () => void }) {
  const [word, setWord] = useState(0);
  const [n, setN] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => {
    const id = setInterval(() => setWord((w) => (w + 1) % WORDS.length), 2000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !started.current) {
        started.current = true;
        const dur = 1800;
        const t0 = performance.now();
        const tick = (t: number) => {
          const p = Math.min(1, (t - t0) / dur);
          setN(Math.round(TARGET * (1 - Math.pow(1 - p, 3))));
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }
    }, { threshold: 0.4 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div className="bp-cta" ref={ref}>
      <h2 className="bp-cta__h">
        Catch the wrong <span className="am">{WORDS[word]}</span> before it ships.
      </h2>
      <div className="bp-cta__row">
        <div className="bp-cta__panel">
          <div className="lab">Reference assertions re-derived, byte-for-byte</div>
          <div className="bp-cta__num">{n.toLocaleString("en-US")}</div>
        </div>
        <div className="bp-cta__side">
          <a className="gh" href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub ↗</a>
          <b>Star the engine</b>
          <span>MIT · pure Python stdlib</span>
          {onRequest && (
            <button type="button" className="gh" style={{ marginTop: 18, background: "none", border: 0, cursor: "pointer", padding: 0, justifyContent: "flex-start", gap: 6 }} onClick={onRequest}>
              Request a verification →
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
