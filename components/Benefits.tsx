"use client";

import { Reveal } from "./chrome";

export function Benefits({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="sec" id="benefits">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Benefits — who this is for</span>
          </Reveal>
        </div>
        <div className="benefits">
          <Reveal>
            <div className="benefit">
              <hr className="hline" />
              <span className="who">For builders</span>
              <h3>Ship numbers you can stand behind</h3>
              <p>
                Your agent checks its own work before reporting it. <b>The mistake is caught in the
                loop</b> — not by your user.
              </p>
              <span className="codeline">/plugin install calma@calma</span>
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
              <span className="fine">Open source · MIT · zero dependencies</span>
            </div>
          </Reveal>

          <Reveal delay={130}>
            <div className="benefit">
              <hr className="hline" />
              <span className="who">For teams</span>
              <h3>Stop bad numbers at the gate</h3>
              <p>
                Run it in CI: <b>a result that doesn&apos;t reproduce never ships.</b> The proof
                travels with the work, and anyone can replay it later.
              </p>
              <span className="codeline">fail only on a real break</span>
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
              <hr className="hline" />
              <span className="who">For funds &amp; allocators</span>
              <h3>Proof before the money moves</h3>
              <p>
                An independent re-execution of the research, delivered as{" "}
                <b>a signed report your counterparty can re-check</b> command-for-command.
              </p>
              <span className="codeline">claimed +14,698% → found −32.4%</span>
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
