"use client";

export function Get({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="section wrap" id="get">
      <div className="sec-head">
        <div>
          <span className="eyebrow">Two instruments</span>
          <h2 className="sec-title">For your agents. For your capital.</h2>
        </div>
        <div className="index" aria-hidden="true"><span className="lead">0</span>04</div>
      </div>

      <div className="rails">
        <div className="rail">
          <div className="tagrow">
            <span className="u-label" style={{ color: "var(--ink-2)" }}>The skill — open source</span>
            <span className="u-label" style={{ color: "var(--ash)" }}>MIT</span>
          </div>
          <h3>Verification in the agent loop</h3>
          <div className="price">free · pure stdlib · zero dependencies</div>
          <ul>
            <li>Claims in plain language: &quot;accuracy 0.87&quot;, &quot;+14,698% backtest&quot;, &quot;$4.2M revenue&quot;</li>
            <li>Works in Claude Code, Codex, Cursor — anything that reads SKILL.md — or as a plain CLI</li>
            <li>Machine verdicts (--json), millisecond cached re-checks, a CI gate that fails only on a real break</li>
            <li>Teardown cards (--svg) when something breaks</li>
          </ul>
          <div className="cmd">{`/plugin marketplace add rikhinkavuru/calma
/plugin install calma@calma`}</div>
          <div className="cta">
            <a className="explore solid" href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
              View on GitHub
              <span className="nub" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </span>
            </a>
          </div>
        </div>

        <div className="rail rail--lab">
          <div className="tagrow">
            <span className="u-label">The lab — engagements</span>
            <span className="u-label" style={{ color: "var(--ash)" }}>Signed</span>
          </div>
          <h3>Independent verification reports</h3>
          <div className="price">per engagement · managers raising · allocators deciding</div>
          <ul>
            <li>Independent re-execution of the research, in isolation, on your data snapshot</li>
            <li>The overfitting battery — deflated Sharpe, PBO, baseline edge — over disclosed trials</li>
            <li>Leakage re-run that quantifies the drop, not a static opinion</li>
            <li>A signed, content-addressed attestation your counterparty can re-check command-for-command</li>
          </ul>
          <div className="cmd">{`claimed +14,698%  →  recomputed −32.4%
caught before capital was committed`}</div>
          <div className="cta">
            <button className="explore" onClick={onRequest}>
              Request verification
              <span className="nub" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </span>
            </button>
            <span className="u-label" style={{ color: "var(--ash)" }}>No self-serve · a person replies</span>
          </div>
        </div>
      </div>
    </section>
  );
}
