"use client";

import { CardArt } from "./CardArt";
import { Reveal } from "./chrome";

export function Benefits({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="sec" id="benefits">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Who it&apos;s for</span>
          </Reveal>
          <Reveal delay={150}>
            <h2 className="h2">Three ways people use Calma.</h2>
          </Reveal>
        </div>
        <div className="benefits">
          <Reveal>
            <div className="benefit">
              <div className="benefit__art"><CardArt kind="builder" /></div>
              <span className="who">Builders</span>
              <h3>Catch the mistake before your users do</h3>
              <p>
                Your agent checks its own work as it goes — so the wrong number dies in the loop,
                not in production.
              </p>
              <div className="cta">
                <a
                  className="pbtn"
                  href="https://github.com/rikhinkavuru/calma"
                  target="_blank"
                  rel="noreferrer"
                >
                  Get the free skill
                </a>
              </div>
              <span className="fine">Free · open source · MIT</span>
            </div>
          </Reveal>

          <Reveal delay={130}>
            <div className="benefit">
              <div className="benefit__art"><CardArt kind="team" /></div>
              <span className="who">Teams</span>
              <h3>A result that doesn&apos;t reproduce never ships</h3>
              <p>
                Run Calma in CI as a gate. The proof travels with the work, and anyone can replay
                it later.
              </p>
              <div className="cta">
                <a
                  className="pbtn"
                  href="https://github.com/rikhinkavuru/calma/blob/main/README.md"
                  target="_blank"
                  rel="noreferrer"
                >
                  Read the docs
                </a>
              </div>
              <span className="fine">GitHub Action included</span>
            </div>
          </Reveal>

          <Reveal delay={260}>
            <div className="benefit">
              <div className="benefit__art"><CardArt kind="fund" /></div>
              <span className="who">Investors &amp; funds</span>
              <h3>Proof before the money moves</h3>
              <p>
                Before you act on a number, the lab independently re-runs the research and signs a
                report your counterparty can re-check.
              </p>
              <div className="cta">
                <button className="pbtn pbtn--amber" onClick={onRequest}>
                  Request verification
                </button>
              </div>
              <span className="fine">Engagements are limited — a person replies</span>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
