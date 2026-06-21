import { Reveal } from "../chrome";
import { CapIllo, type IlloKind } from "./CapIllo";

const STEPS: { kind: IlloKind; tag: string; h: string; p: string }[] = [
  { kind: "rerun", tag: "01 · Re-execution", h: "Re-run from scratch, in a sealed sandbox.", p: "Calma re-executes your code in a sandbox that proves its own isolation first — a planted secret and a network call must both fail." },
  { kind: "determinism", tag: "02 · Deterministic verdict", h: "The label comes from code, not a model.", p: "Every number and the verdict come from one pure function — nothing, not even the agent that produced it, can talk its way to a pass." },
  { kind: "validity", tag: "03 · Validity, not just arithmetic", h: "Catches what reproduces but isn't valid.", p: "Re-runs the result against the validity families — leakage, overfitting, execution realism, contamination — and stamps INVALIDATED." },
  { kind: "attestation", tag: "04 · Signed & portable", h: "A proof the other side can replay.", p: "A signed report checked with stock OpenSSH, fully offline, plus a public track record that can't be retconned." },
];

export function BpHow() {
  return (
    <div className="bp-block" id="how-it-works">
      <Reveal>
        <div className="bp-head">
          <span className="bp-kicker">How it works</span>
          <h2 className="bp-h2">Four moves, one <span className="am">non-gameable</span> verdict.</h2>
        </div>
      </Reveal>
      <div className="bp-how">
        {STEPS.map((s, i) => (
          <Reveal key={s.tag} delay={i * 80}>
            <article className="bp-howcard">
              <div className="bp-howcard__viz"><CapIllo kind={s.kind} /></div>
              <div className="bp-howcard__body">
                <span className="bp-howcard__tag">{s.tag}</span>
                <h3 className="bp-howcard__h">{s.h}</h3>
                <p className="bp-howcard__p">{s.p}</p>
              </div>
            </article>
          </Reveal>
        ))}
      </div>
    </div>
  );
}
