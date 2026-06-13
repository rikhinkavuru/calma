"use client";

import { Reveal } from "./chrome";
import { CardArt } from "./CardArt";

/* Four features, each an alternating row. Every line of the old grid is folded
   into one of these — re-execution, isolation, determinism, languages →
   row 1; adversarial verdict, tolerances, honesty guards → row 2; plain-English
   claims, graded contracts → row 3; attestation, CI/agent loops, the record →
   row 4. Direct, because four rows have to carry everything. */
const FEATURES: {
  k: string;
  art: "rerun" | "verdict" | "claim" | "signed";
  h: string;
  p: string;
}[] = [
  {
    k: "Re-execution",
    art: "rerun",
    h: "Nothing is taken on the AI’s word.",
    p: "Calma re-executes your code from scratch in a sandbox that proves its own isolation first: it plants a fake secret, tries to leak it and reach the network, and only calls the machine sealed once every attempt fails. The number is then rebuilt on bit-stable kernels — same inputs, same answer, on any machine. Python, R, Julia, C++, Rust and Node all run as a sealed black box, no SDK to add. Nothing is ever uploaded.",
  },
  {
    k: "Deterministic verdict",
    art: "verdict",
    h: "A pass no model can argue its way into.",
    p: "Every number and the verdict itself come from code, so a persuasive model — or a motivated author — can’t charm its way to a pass. A claim is refuted only when the gap clears a calibrated tolerance budget drawn from the claim’s own stated precision and the metric’s noise floor; when an input is ambiguous it degrades to can’t-confirm with the exact fix. A caveat over a false alarm, every time.",
  },
  {
    k: "Plain-English claims",
    art: "claim",
    h: "Say the claim like you’d say it out loud.",
    p: "Write it the way you’d say it — “p95 latency 120 ms,” “pass@5 0.62,” “monthly CAGR 23.9%.” Calma parses the number, the metric, and even the convention, then scans your output files to find the column that holds it and independently double-checks that guess before it’s allowed to matter. Pin everything explicitly with one small config when you’d rather not leave it to inference.",
  },
  {
    k: "Signed & portable",
    art: "signed",
    h: "Proof your counterparty can check alone.",
    p: "Every run emits a signed report the other side checks with tools already on their machine — stock OpenSSH, fully offline — plus an optional trusted timestamp that proves the date years later. It drops into agent loops and CI, cached by content hash so unchanged work answers instantly and gating only when a claim truly breaks, and each verification appends to a track record that can’t be retconned. (DSSE/in-toto, Sigstore-compatible, RFC 3161.)",
  },
];

export function Features() {
  return (
    <section className="sec" id="features">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">Features</span>
          </Reveal>
          <Reveal delay={150}>
            <h2 className="h2">Simple to use. Hard to fool.</h2>
          </Reveal>
          <Reveal delay={250}>
            <p className="lead">
              The properties that separate a Calma verdict from a second opinion — under the hood of
              every check.
            </p>
          </Reveal>
        </div>

        <div className="frows">
          {FEATURES.map((f, i) => (
            <Reveal key={f.k} delay={i === 0 ? 0 : 100}>
              <div className="frow">
                <div className="frow__art">
                  <CardArt kind={f.art} />
                </div>
                <div className="frow__text">
                  <span className="frow__k">{f.k}</span>
                  <h3>{f.h}</h3>
                  <p>{f.p}</p>
                </div>
              </div>
            </Reveal>
          ))}
        </div>

        <Reveal delay={150} style={{ marginTop: "clamp(40px, 5vw, 68px)" }}>
          <div className="rband">
            <div className="rband__n">
              <span className="rband__num">100+</span>
              <span className="rband__sub">validated recipes</span>
            </div>
            <p className="rband__copy">
              A recipe is how Calma rebuilds one kind of number — a Sortino ratio, a p95 latency, a
              pass@1, a Fisher exact p, a WER — from the raw output files. <b>Every one is validated
              against the published reference implementation</b> (scikit-learn, SciPy, NumPy,
              numpy-financial, statsmodels) across 385 pinned reference vectors before it ships,
              and runs deterministically: same inputs, same number, to the bit. New recipes are
              compiled, not improvised: drafted offline, admitted by a deterministic gate, frozen
              under a content hash.
            </p>
            <a className="pbtn pbtn--amber" href="/recipes">
              Browse the library
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
