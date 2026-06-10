"use client";

import { Eyebrow, Reveal } from "./chrome";

export function Access({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="sec" id="get">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <Eyebrow>two ways in</Eyebrow>
          </Reveal>
          <Reveal delay={100}>
            <h2>
              Free for your <span className="serif-acc">agents.</span>
              <br />
              Signed for your <span className="serif-acc">capital.</span>
            </h2>
          </Reveal>
        </div>
        <div className="access">
          <Reveal dir="left">
            <div className="acc-card">
              <span className="who mono">/// the skill — open source &gt;&gt;&gt;</span>
              <h3>
                Verification in the <span className="serif-acc">agent loop</span>
              </h3>
              <p>
                Verifies any agent&apos;s result from a plain-language claim — metrics, backtests,
                totals. Runs in Claude Code, Codex, or Cursor, or as a CLI. Nothing leaves your
                machine.
              </p>
              <pre className="cmd"><span className="g">$</span> /plugin install calma@calma</pre>
              <div className="cta">
                <a className="pillbtn" href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
                  Read the source →
                </a>
              </div>
            </div>
          </Reveal>
          <Reveal dir="right" delay={140}>
            <div className="acc-card acc-card--lab">
              <span className="who mono">/// the lab — engagements &gt;&gt;&gt;</span>
              <h3>
                Independent <span className="serif-acc">verification reports</span>
              </h3>
              <p>
                Re-execution of research before money moves — for managers raising and allocators
                deciding. A signed report your counterparty can re-check command-for-command.
              </p>
              <pre className="cmd">claimed +14,698% → re-executed −32.4%</pre>
              <div className="cta">
                <button className="pillbtn pillbtn--solid" onClick={onRequest}>
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
