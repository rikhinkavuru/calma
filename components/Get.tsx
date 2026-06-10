"use client";

import { Reveal } from "./chrome";

export function Get({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="sec" id="get">
      <div className="wrap access">
        <Reveal>
          <div className="offer">
            <hr className="hline" />
            <span className="micro">For developers &amp; their agents</span>
            <h3>The open-source skill</h3>
            <p className="col">
              Install once and your agent verifies its own results before reporting them — in
              Claude Code, Codex, Cursor, or as a CLI. <b>Runs locally. Nothing leaves your
              machine.</b>
            </p>
            <span className="codeline">/plugin install calma@calma</span>
            <div className="cta">
              <a
                className="pbtn"
                href="https://github.com/rikhinkavuru/calma"
                target="_blank"
                rel="noreferrer"
              >
                Read the source
              </a>
              <span className="fine">MIT · zero dependencies</span>
            </div>
          </div>
        </Reveal>
        <Reveal delay={160}>
          <div className="offer">
            <hr className="hline" />
            <span className="micro">For funds &amp; allocators</span>
            <h3>The verification lab</h3>
            <p className="col">
              An independent re-execution of research before money moves — delivered as{" "}
              <b>a signed report your counterparty can re-check command-for-command.</b>
            </p>
            <span className="codeline">claimed +14,698% → re-executed −32.4%</span>
            <div className="cta">
              <button className="pbtn pbtn--amber" onClick={onRequest}>
                Request verification
              </button>
              <span className="fine">Engagements are limited — a person replies</span>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
