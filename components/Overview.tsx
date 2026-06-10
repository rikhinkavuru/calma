"use client";

import { Reveal } from "./chrome";

/* HOW IT WORKS — three steps, no jargon. */
export function Overview() {
  return (
    <section className="sec sec--orbed" id="overview">
      <i className="orb orb--amber" aria-hidden="true"
         style={{ width: 460, height: 460, right: -160, top: -120, opacity: 0.55 }} />
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">How it works</span>
          </Reveal>
          <Reveal delay={150}>
            <h2 className="h2">It doesn&apos;t read the work. It runs it.</h2>
          </Reveal>
          <Reveal delay={250}>
            <p className="lead">
              Point Calma at the work and say what was claimed. Everything happens on your machine,
              in one command.
            </p>
          </Reveal>
        </div>

        <Reveal delay={200}>
          <div className="steps">
            <div className="step">
              <span className="step__n">01</span>
              <h3>Run it again</h3>
              <p>Your AI&apos;s work re-executes in a sandbox, from scratch, with nothing taken on faith.</p>
            </div>
            <div className="step">
              <span className="step__n">02</span>
              <h3>Rebuild the number</h3>
              <p>The result is recomputed from the raw output files — never copied from the AI&apos;s report.</p>
            </div>
            <div className="step step--out">
              <span className="step__n">03</span>
              <h3>Get the verdict</h3>
              <p>Code compares rebuilt against reported and gives one clear answer. Nobody — including the AI — can argue it into passing.</p>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
