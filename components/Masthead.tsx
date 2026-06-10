"use client";

import { PixelBlock, StarGlyph } from "./chrome";

export function Masthead() {
  return (
    <section className="masthead">
      <div className="wrap">
        <h1 className="wordmark">
          CALMA<sup>®</sup>
        </h1>

        <div className="specbar">
          <div className="specbar__glyph" aria-hidden="true">
            <PixelBlock />
          </div>
          <div className="specbar__title">
            Proof through re-execution
            <StarGlyph className="spk" />
            Verdicts by code
          </div>
          <div className="specbar__labels" aria-hidden="true">
            <span>
              Re-run /<br />
              Recompute
            </span>
            <span>
              Diff /<br />
              Decide
            </span>
          </div>
        </div>

        <div className="codestrip">
          <span className="descend" aria-hidden="true">
            <svg viewBox="0 0 40 40">
              <path d="M20 2 V30 M10 22 L20 32 L30 22" fill="none" stroke="#141310" strokeWidth="2.5" />
            </svg>
          </span>
          <span className="code-id mono">0001 — CALMA / 2026 · 251 CHECKS · 0 OPINIONS</span>
          <span className="barcode" aria-hidden="true"></span>
        </div>
      </div>
    </section>
  );
}
