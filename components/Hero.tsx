"use client";

import { Bench } from "./Bench";

export function Hero() {
  return (
    <header className="mast wrap" id="top">
      <div className="mast-top">
        <span>Verification by re-execution</span>
        <span>Open source · v0.3</span>
      </div>
      <div className="mast-grid">
        <h1 className="wordmark">
          calma<span className="dot">.</span>
        </h1>
        <p className="mast-meta">
          <strong>Your AI did the work. Calma re-runs it.</strong> The number is rebuilt from the
          raw outputs and the verdict is computed by code — the producer is never the verifier.
        </p>
      </div>
      <div className="mast-actions">
        <a className="explore solid" href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
          Get the skill
          <span className="nub" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          </span>
        </a>
        <span className="mast-claim">free · pure stdlib · MIT</span>
      </div>

      <div id="bench">
        <Bench />
      </div>
    </header>
  );
}
