"use client";

/* Show, don't tell: a real attestation excerpt and the field notes that motivate the
   whole instrument. The sheet is verbatim-shaped engine output. */

export function Evidence() {
  return (
    <section className="section wrap" id="evidence">
      <div className="sec-head">
        <div>
          <span className="eyebrow">The paper trail</span>
          <h2 className="sec-title">Every verdict leaves evidence.</h2>
          <p className="sec-lead">
            Each run writes a ledger, a content-addressed manifest, and an in-toto attestation.
            Anyone can re-check the verdict command-for-command — including the person who
            doesn&apos;t trust you.
          </p>
        </div>
        <div className="index" aria-hidden="true"><span className="lead">0</span>03</div>
      </div>

      <div className="sheets">
        <div className="sheet sheet--framed">
          <div className="cap">
            <span>attestation.json — btc-backtest</span>
            <span>sha256 · in-toto v1</span>
          </div>
          <pre>{`{
  "_type": "https://in-toto.io/Statement/v1",
  "predicate": {
    "verdict": `}<span className="vm">&quot;REFUTED&quot;</span>{`,
    "isolation_tier": "seatbelt-verified",
    "determinism_mode": "controlled-to-bit",
    "materials": [
      { "uri": "runs/oos/returns.csv",
        "digest": { "sha256": "1f0c…9aa2" } }
    ]
  }
}`}</pre>
          <div className="note">
            Re-derived byte-for-byte by <span className="mono">ledger.py</span> — a hand-edited or
            model-authored label cannot validate. Reproduce it yourself:{" "}
            <span className="mono">calma replay ./.calma/run</span> · exit 0 iff the verdict holds.
          </div>
        </div>

        <div className="fieldnotes">
          <div className="fn">
            <div className="n">~35%</div>
            <p>of 12,720 studied notebooks reproduce at all.</p>
            <div className="src">Pimentel et al.</div>
          </div>
          <div className="fn">
            <div className="n">0.97 <em>→ 0.91</em></div>
            <p>a published AUC once data leakage was removed.</p>
            <div className="src">Kapoor &amp; Narayanan</div>
          </div>
          <div className="fn">
            <div className="n">~21%</div>
            <p>accuracy of LLM agents judging reproducibility. Judgment fails where re-execution works.</p>
            <div className="src">REPRO-Bench</div>
          </div>
          <div className="fn">
            <div className="n">251</div>
            <p>deterministic checks behind the engine. Zero model opinions in any verdict.</p>
            <div className="src">test suite · CI</div>
          </div>
        </div>
      </div>
    </section>
  );
}
