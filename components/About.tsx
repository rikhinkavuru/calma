"use client";

import { Reveal } from "./chrome";

export function About() {
  return (
    <section className="sec" id="about">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">About — the lab</span>
          </Reveal>
        </div>
        <div className="about">
          <Reveal delay={100}>
            <div>
              <div className="cascade">
                <span>One principle:</span>
                <span>the producer</span>
                <span>is never</span>
                <span>the verifier.</span>
              </div>
              <p className="col" style={{ marginTop: 32 }}>
                Calma is an independent verification lab. Finance settled this long ago — funds have
                administrators, companies have auditors. <b>Work done by AI gets Calma.</b> The
                engine is open source so anyone can check the checker; the lab signs its name to
                reports.
              </p>
            </div>
          </Reveal>
          <Reveal delay={220}>
            <div className="about__facts">
              <div className="fig">
                <span className="k">Founded</span>
                <span className="v">2026</span>
              </div>
              <div className="fig">
                <span className="k">Principle</span>
                <span className="v">Producer ≠ verifier</span>
              </div>
              <div className="fig">
                <span className="k">Engine</span>
                <span className="v">Open source · MIT</span>
              </div>
              <div className="fig">
                <span className="k">Dependencies</span>
                <span className="v">Zero</span>
              </div>
              <div className="fig">
                <span className="k">Verdicts</span>
                <span className="v">Computed by code</span>
              </div>
              <div className="fig">
                <span className="k">Built</span>
                <span className="v">In the open</span>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
