"use client";

import { Reveal } from "./chrome";

export function Get({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="sec" id="get">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Get Calma</span>
          </Reveal>
          <Reveal delay={90}>
            <h2>
              Free for agents.
              <br />
              <span className="serif">Signed</span> for capital.
            </h2>
          </Reveal>
        </div>
        <div className="get">
          <Reveal dir="left">
            <div className="offer">
              <span className="who">For developers &amp; their agents</span>
              <h3>
                The open-source <span className="serif">skill</span>
              </h3>
              <p>
                Install once and your agent verifies its own results before reporting them — in
                Claude Code, Codex, Cursor, or as a plain CLI. Plain-language claims, machine-readable
                verdicts.
              </p>
              <div className="codeline">/plugin install calma@calma</div>
              <div className="cta">
                <a
                  className="btn btn--ink"
                  href="https://github.com/rikhinkavuru/calma"
                  target="_blank"
                  rel="noreferrer"
                >
                  Read the source →
                </a>
                <span className="fine">MIT · zero dependencies</span>
              </div>
            </div>
          </Reveal>
          <Reveal dir="right" delay={130}>
            <div className="offer offer--lab">
              <span className="who">For funds &amp; allocators</span>
              <h3>
                The verification <span className="serif">lab</span>
              </h3>
              <p>
                An independent re-execution of research before money moves — delivered as a signed
                report your counterparty can re-check command-for-command.
              </p>
              <div className="codeline">claimed +14,698% → re-executed −32.4%</div>
              <div className="cta">
                <button className="btn btn--blue" onClick={onRequest}>
                  Request verification
                </button>
                <span className="fine">Engagements are limited — a person replies.</span>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
