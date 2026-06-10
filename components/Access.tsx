"use client";

export function Access({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="section" id="access">
      <div className="wrap">
        <div className="section__head">
          <div>
            <div className="section__num">005 / Access</div>
            <h2 className="section__title">Two instruments</h2>
          </div>
          <p className="section__note">The skill is free and runs where your agents run. The lab signs its name.</p>
        </div>

        <div className="access">
          <div className="access__card">
            <div className="access__hd">
              <span>The skill — open source</span>
              <span className="tag">MIT</span>
            </div>
            <div className="access__t">
              Verification in
              <br />
              the agent loop
            </div>
            <ul className="access__list">
              <li>Claims in plain language: &quot;accuracy 0.87&quot;, &quot;+14,698% backtest&quot;, &quot;$4.2M revenue&quot;.</li>
              <li>Runs in Claude Code, Codex, Cursor — anything that reads SKILL.md — or as a plain CLI.</li>
              <li>Machine verdicts, cached re-checks, a CI gate that fails only on a real break.</li>
              <li>Pure stdlib. Zero dependencies. Nothing leaves your machine.</li>
            </ul>
            <pre className="cmd">{`/plugin marketplace add rikhinkavuru/calma
/plugin install calma@calma`}</pre>
            <div className="access__cta">
              <a className="btn btn--solid" href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
                Read the source →
              </a>
            </div>
          </div>

          <div className="access__card">
            <div className="access__hd">
              <span>The lab — engagements</span>
              <span className="tag tag--flare">Signed</span>
            </div>
            <div className="access__t">
              Independent
              <br />
              verification reports
            </div>
            <ul className="access__list">
              <li>For managers raising and allocators deciding. Per engagement.</li>
              <li>Independent re-execution of the research, in isolation, on your data snapshot.</li>
              <li>The overfitting battery — deflated Sharpe, PBO, baseline edge — over disclosed trials.</li>
              <li>A signed, content-addressed attestation your counterparty re-checks command-for-command.</li>
            </ul>
            <pre className="cmd">claimed +14,698% → recomputed −32.4%{"\n"}caught before capital was committed</pre>
            <div className="access__cta">
              <button className="btn btn--flare" onClick={onRequest}>
                Request verification
              </button>
              <span className="eyebrow dim">No self-serve · a person replies</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
