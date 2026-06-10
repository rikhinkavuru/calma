"use client";

import { Reveal } from "./chrome";

export function Outro() {
  return (
    <section className="outro">
      <div className="wrap">
        <Reveal>
          <div className="outro__grid">
            <div className="outro__brand">
              <div className="lockup">CALMA</div>
              <div className="micro">Independent verification lab</div>
            </div>
            <div className="outro__camp">
              <div className="lockup">
                Proof
                <br />
                <em>is here.</em>
              </div>
            </div>
          </div>
        </Reveal>
        <Reveal delay={200}>
          <p className="outro__line">Catch the bad number before the money moves.</p>
        </Reveal>
        <Reveal delay={300}>
          <p className="outro__cta">
            Read more at{" "}
            <a href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
              github.com/rikhinkavuru/calma
            </a>
          </p>
        </Reveal>
        <div className="barcode" aria-hidden="true" />
        <div className="outro__base">
          <span>© 2026 Calma</span>
          <span>The producer is never the verifier</span>
        </div>
      </div>
    </section>
  );
}
