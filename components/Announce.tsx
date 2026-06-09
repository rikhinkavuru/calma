"use client";

import { useState } from "react";

export function Announce() {
  const [show, setShow] = useState(true);
  if (!show) return null;
  return (
    <div className="announce">
      <div className="wrap announce__inner">
        <span className="announce__txt">
          <span className="announce__badge mono">new</span>
          The Calma skill is open source and free — verify any agent's results today.
          <a href="https://github.com/rikhinkavuru/calma" className="announce__link" target="_blank" rel="noreferrer">
            Get it on GitHub <span aria-hidden="true">→</span>
          </a>
        </span>
        <button className="announce__x mono" aria-label="Dismiss" onClick={() => setShow(false)}>
          ×
        </button>
      </div>
    </div>
  );
}
