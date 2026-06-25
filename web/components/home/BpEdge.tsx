import { Reveal } from "../chrome";

/* A2 — two engine checks that are real but under-marketed: the trivial-baseline edge and
   eval-contamination. Both catch a number that recomputes perfectly, passes every other gate,
   and is still wrong — the failures no dbt test / schema / snapshot / LLM-eval looks for. */
export function BpEdge() {
  return (
    <div className="bp-block" style={{ paddingTop: 0 }}>
      <Reveal>
        <div className="bp-head">
          <span className="bp-kicker">What slips past every other gate</span>
          <h2 className="bp-h2">A number can pass every check you have <span className="am">and still be wrong.</span></h2>
          <p className="bp-lead">
            dbt tests, Pandera schemas, snapshot diffs, an LLM-eval harness — they all confirm a number is
            <i> internally consistent</i>. Two failures stay invisible to every one of them, because the number
            recomputes perfectly. Calma catches both.
          </p>
        </div>
      </Reveal>

      <Reveal delay={120}>
        <div className="bp-bcards">
          <div className="bp-bcard">
            <span className="bp-bcard__tag">Trivial-baseline edge</span>
            <div className="bp-bcard__big">Beaten by a coin flip</div>
            <p className="bp-bcard__p">
              A model card reports 92% accuracy. It recomputes to 92% — but 92% of the rows are one class,
              so predicting the majority every time scores the same. The number is real and reproducible;
              the result is worthless. Calma recomputes the <b>trivial baseline</b> next to the claim and flags
              a headline that doesn&apos;t beat it.
            </p>
          </div>
          <div className="bp-bcard">
            <span className="bp-bcard__tag">Eval contamination</span>
            <div className="bp-bcard__big">Your held-out set isn&apos;t held out</div>
            <p className="bp-bcard__p">
              A &ldquo;zero-shot held-out&rdquo; benchmark scores 92% — and recomputes to 92%. But Calma hashes the
              eval items against the declared corpus (exact sha256 <i>and</i> near-duplicate MinHash/LSH) and finds
              40% already in pretraining. The number reproduces; the held-out claim is <b>INVALIDATED</b>. The
              entire eval-tooling category checks for none of this.
            </p>
          </div>
        </div>
      </Reveal>
    </div>
  );
}
