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
          Calma's first verification checks are open source.
          <a href="#roadmap" className="announce__link">
            See the roadmap <span aria-hidden="true">→</span>
          </a>
        </span>
        <button className="announce__x mono" aria-label="Dismiss" onClick={() => setShow(false)}>
          ×
        </button>
      </div>
    </div>
  );
}
