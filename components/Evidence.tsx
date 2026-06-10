"use client";

import { CountUp, SectionHead, useInView } from "./chrome";

/* 003 — evidence. The instrumentation is real: live counters from the test suite,
   the actual attestation shape, and the gap meter from the flagship refutation. */

export function Evidence() {
  const [gapRef, gapSeen] = useInView<HTMLDivElement>(0.5);

  return (
    <section className="section" id="evidence">
      <div className="wrap">
        <SectionHead
          num="003 / Ledger"
          title="Evidence"
          note="Every verdict leaves a paper trail anyone can re-check — including the person who doesn't trust you."
        />

        <div className="counters" style={{ marginBottom: "var(--hair)" }}>
          <div className="counter">
            <div className="n"><CountUp to={251} /></div>
            <div className="k">Deterministic checks behind the engine</div>
          </div>
          <div className="counter">
            <div className="n"><em>0</em></div>
            <div className="k">Model opinions in any verdict</div>
          </div>
          <div className="counter">
            <div className="n"><CountUp to={15} /></div>
            <div className="k">Metric recipes · quant / ML / analytics</div>
          </div>
          <div className="counter">
            <div className="n"><CountUp to={6} /></div>
            <div className="k">Languages run as a black box</div>
          </div>
        </div>

        <div className="bench">
          <div className="bench__cell">
            <div className="bench__hd">
              <span>attestation — btc-backtest</span>
              <span>in-toto v1</span>
            </div>
            <pre className="cmd">{`{
  "predicate": {
    "verdict": `}<span className="f">&quot;REFUTED&quot;</span>{`,
    "isolation_tier": "seatbelt-verified",
    "determinism_mode": "controlled-to-bit",
    "materials": [{ "uri": "runs/oos/returns.csv",
      "digest": { "sha256": "1f0c…9aa2" } }]
  }
}`}</pre>
            <p style={{ margin: 0, fontSize: ".88rem", maxWidth: "52ch" }}>
              Re-derived byte-for-byte by <span className="mono">ledger.py</span>. A hand-edited or
              model-authored label cannot validate.
            </p>
          </div>

          <div className="bench__cell">
            <div className="bench__hd">
              <span>the diff — claimed vs budget</span>
              <span>log scale</span>
            </div>
            <div className={"gap" + (gapSeen ? " run" : "")} ref={gapRef}>
              <div className="gap__track">
                <span className="gap__budget" aria-hidden="true"></span>
                <span className="gap__fill" aria-hidden="true"></span>
              </div>
              <div className="gap__lbls">
                <span>budget 1e-9</span>
                <span>gap 147.30 — eleven orders over</span>
              </div>
            </div>
            <pre className="cmd">{`$ calma verify . "accuracy 0.87" --json
{ "verdict": `}<span className="g">&quot;CONFIRMED&quot;</span>{`, "clean": true,
  "claimed": 0.87, "recomputed": 0.87,
  "cached": false, "confidence": 0.95 }`}</pre>
            <p style={{ margin: 0, fontSize: ".88rem", maxWidth: "52ch" }}>
              Agents read the machine verdict and branch. Unchanged work answers from cache in
              milliseconds; flaky work can never confirm.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
