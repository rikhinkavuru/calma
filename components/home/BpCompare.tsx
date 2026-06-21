import { Reveal } from "../chrome";

export function BpCompare() {
  return (
    <div className="bp-block" style={{ paddingTop: "clamp(8px, 2vw, 24px)" }}>
      <Reveal>
        <div className="bp-head bp-head--center">
          <span className="bp-kicker">Recompute vs. trust</span>
          <h2 className="bp-h2">Everyone else reads the diff or trusts the score. <span className="am">Calma re-runs the work and recomputes the number.</span></h2>
          <p className="bp-lead">A diff review and an LLM judge both reason <i>about</i> a result. Calma re-derives it from the raw outputs — so there&apos;s no score left to game.</p>
        </div>
      </Reveal>
      <Reveal>
        <div className="bp-cmp">
          <div className="bp-cmp__col bp-cmp__col--legacy">
            <span className="bp-cmp__tag">✕&nbsp; The default · read the diff or trust the score</span>
            <h3 className="bp-cmp__h">Reads the reported number. Believes it. Ships it.</h3>
            <div className="bp-cmp__list">
              <span className="bp-cmp__li"><span className="x">✕</span> Reviews the code, or takes the dashboard at face value</span>
              <span className="bp-cmp__li"><span className="x">✕</span> No isolation, no re-execution</span>
              <span className="bp-cmp__li"><span className="x">✕</span> A model grading its own homework</span>
            </div>
          </div>
          <div className="bp-cmp__col bp-cmp__col--calma">
            <span className="bp-cmp__tag am">✦&nbsp; Calma</span>
            <h3 className="bp-cmp__h">Re-derives the number from raw outputs. Proves it, or breaks it.</h3>
            <div className="bp-cmp__list">
              <span className="bp-cmp__li"><span className="sq" /> Recompute from raw files, never the claim</span>
              <span className="bp-cmp__li"><span className="sq" /> Network-off sandbox, self-tested every run</span>
              <span className="bp-cmp__li"><span className="sq" /> One deterministic verdict, re-derived at the gate</span>
            </div>
          </div>
        </div>
      </Reveal>
    </div>
  );
}
