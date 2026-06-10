"use client";

import { Reveal, SectionHead } from "./chrome";

export function Access({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="section" id="get">
      <div className="wrap">
        <SectionHead idx="05" title="Get Calma" />
        <div className="access">
          <Reveal dir="left">
            <div className="card">
              <span className="who mono">For your agents — free, open source</span>
              <h3>The skill</h3>
              <p>
                Verifies any agent&apos;s result — metrics, backtests, totals — from a plain-language
                claim. Runs in Claude Code, Codex, or Cursor, or as a CLI. Nothing leaves your
                machine.
              </p>
              <pre className="cmd">/plugin install calma@calma</pre>
              <div className="cta">
                <a className="btn" href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
                  Read the source →
                </a>
              </div>
            </div>
          </Reveal>

          <Reveal dir="right" delay={140}>
            <div className="card card--dark">
              <span className="who mono">For capital — signed engagements</span>
              <h3>The verification lab</h3>
              <p>
                Independent re-execution of research before money moves: for managers raising and
                allocators deciding. A signed report your counterparty can re-check
                command-for-command.
              </p>
              <pre className="cmd">claimed +14,698% → re-executed −32.4%</pre>
              <div className="cta">
                <button className="btn btn--flare" onClick={onRequest}>
                  Request verification
                </button>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
