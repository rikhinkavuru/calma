"use client";

import { CountUp, Reveal, SectionHead } from "./chrome";

export function Evidence() {
  return (
    <section className="section" id="evidence">
      <div className="wrap">
        <SectionHead
          idx="03"
          title="Verdicts you can re-check"
          sub="Every run leaves a signed-shape paper trail. Agents read the machine verdict and branch; people replay it with one command."
        />

        <div className="evidence">
          <Reveal dir="left">
            <div className="counters">
              <div className="counter">
                <div className="n"><CountUp to={251} /></div>
                <div className="k">deterministic checks behind the engine</div>
              </div>
              <div className="counter">
                <div className="n"><em>0</em></div>
                <div className="k">model opinions in any verdict</div>
              </div>
              <div className="counter">
                <div className="n"><CountUp to={15} /></div>
                <div className="k">metrics, from Sharpe to AUC to row counts</div>
              </div>
              <div className="counter">
                <div className="n"><CountUp to={6} /></div>
                <div className="k">languages, run as a black box</div>
              </div>
            </div>
          </Reveal>

          <Reveal dir="right" delay={150}>
            <div className="proof">
              <pre className="cmd">{`$ calma verify . "accuracy 0.87" --json
{
  "verdict": `}<span className="g">&quot;CONFIRMED&quot;</span>{`,
  "claimed": 0.87, "recomputed": 0.87,
  "confidence": 0.95
}`}</pre>
              <p>
                The same engine that confirmed this refuted the backtest above — and printed{" "}
                <span className="mono">REFUTED</span> with a replay command attached.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
