"use client";

import { Atmo, Cross, Dots, Glyph, Reveal } from "./chrome";

export function Hero({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="hero" id="top">
      <Atmo />
      <Dots style={{ top: 84, left: "6%" }} />
      <Dots style={{ top: 110, right: "8%" }} />
      <Cross style={{ top: "38%", left: "4%" }} />
      <Cross style={{ bottom: "12%", right: "5%" }} />
      <span className="coord" style={{ top: "30%" }}>
        +14,698.0° claimed
      </span>
      <span className="coord" style={{ top: "58%" }}>
        −32.4° found
      </span>

      <div className="wrap hero__inner">
        <Reveal>
          <div className="cascade" aria-label="In the race to hand real work to AI,">
            <span>In the race</span>
            <span>to hand</span>
            <span>real work</span>
            <span>to AI,</span>
          </div>
        </Reveal>

        <Reveal delay={350}>
          <div className="hero__mid">
            <div className="cascade" aria-label="whoever trusts the number loses.">
              <span>whoever trusts</span>
              <span>the number</span>
              <span>loses.</span>
            </div>
          </div>
        </Reveal>

        <Reveal delay={600}>
          <p className="col" style={{ marginTop: "clamp(40px, 7vh, 80px)" }}>
            Money moves on figures an agent printed, and nobody re-computes them.{" "}
            <b>Calma re-runs the work, rebuilds the number from the raw outputs, and decides with
            code</b> — before the money moves.
          </p>
        </Reveal>

        <Reveal delay={750}>
          <div className="hero__cta">
            <a
              className="pbtn pbtn--amber"
              href="https://github.com/rikhinkavuru/calma"
              target="_blank"
              rel="noreferrer"
            >
              Get the free skill
            </a>
            <button className="pbtn" onClick={onRequest}>
              Request verification
            </button>
          </div>
        </Reveal>
      </div>

      <div className="hero__specs" aria-hidden="true">
        <div className="spec">
          <span className="spec__box"><Glyph kind="rerun" /></span>
          <span className="spec__t">
            Re-run
            <small>sandboxed</small>
          </span>
        </div>
        <div className="spec">
          <span className="spec__box"><Glyph kind="recompute" /></span>
          <span className="spec__t">
            Recompute
            <small>raw outputs</small>
          </span>
        </div>
        <div className="spec">
          <span className="spec__box"><Glyph kind="decide" /></span>
          <span className="spec__t">
            Decide
            <small>by code</small>
          </span>
        </div>
      </div>
    </section>
  );
}
