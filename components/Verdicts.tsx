"use client";

import { Section } from "./primitives";
import { Reveal } from "./Reveal";

export function Verdicts() {
  return (
    <Section
      id="verdicts"
      num="03"
      label="the verdict"
      watermark="03 / DECIDE"
      title={
        <>
          Four answers. <span className="dim">Never a shrug.</span>
        </>
      }
      intro={
        <>
          Every outcome is actionable: a break ships a one-command reproduction, and anything
          unverifiable ships the exact fix to make it verifiable. Calma biases toward a caveat over
          a false alarm — it never cries wolf.
        </>
      }
    >
      <div className="verdicts">
        <Reveal className="verdict verdict--pass">
          <span className="verdict__tag">CONFIRMED</span>
          <p className="verdict__p">
            It re-runs, and the number rebuilt from the raw outputs matches the claim within the
            calibrated budget. A deterministic confidence score says how strong the evidence is.
          </p>
          <div className="verdict__mono">
            <b>CONFIRMED</b> (confidence 95/100){"\n"}reproduces and recomputes to the claim
          </div>
        </Reveal>

        <Reveal className="verdict verdict--fail" delay={0.05}>
          <span className="verdict__tag">REFUTED</span>
          <p className="verdict__p">
            The recomputed number contradicts the claim — with a shareable teardown card and a
            reproduction you can run yourself. The producer can&apos;t steer it: refutations require an
            independently sanity-checked binding and an unambiguous claim.
          </p>
          <div className="verdict__mono">
            CLAIMED: <b>+14,698%</b>{"\n"}RECOMPUTED: <b>−32.4%</b>{"\n"}reproduce: calma replay
            ./.calma/run
          </div>
        </Reveal>

        <Reveal className="verdict verdict--warn" delay={0.1}>
          <span className="verdict__tag">CAN&apos;T-CONFIRM</span>
          <p className="verdict__p">
            Not verifiable yet — and the report names the one change that makes it verifiable, with
            who can act on it. Unseeded randomness, missing output files, ambiguous bindings: each
            gets its exact fix line.
          </p>
          <div className="verdict__mono">
            <b>fix:</b> set a fixed seed and write outputs{"\n"}deterministically, then re-run calma
            verify
          </div>
        </Reveal>

        <Reveal className="verdict verdict--pass" delay={0.15}>
          <span className="verdict__tag">CONFIRMED-WITH-CAVEATS</span>
          <p className="verdict__p">
            It holds, but narrower than claimed — and the caveat is named: an unisolated host, a
            cross-stack numeric difference, a plausible-but-unpinned binding. Honest scope is what
            makes a verifier credible.
          </p>
          <div className="verdict__mono">
            holds, but narrows: <b>host tier not isolated</b>{"\n"}scope stamped on every verdict
          </div>
        </Reveal>
      </div>
    </Section>
  );
}
