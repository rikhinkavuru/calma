"use client";

import { Reveal } from "./chrome";

/* HOW IT WORKS — three steps, no jargon. */
export function Overview() {
  return (
    <section className="sec" id="overview">
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
              You give Calma two things — the work, and the claim. Four steps later you have a
              verdict you can hand to someone else. Everything runs on your machine, in one command,
              with no model anywhere in the decision.
            </p>
          </Reveal>
        </div>

        <Reveal delay={200}>
          <div className="steps steps--4">
            <div className="step">
              <span className="step__n">01</span>
              <h3>Point it at the work</h3>
              <p>Hand Calma the folder your AI produced and state the claim in plain English — &ldquo;Sharpe 2.1,&rdquo; &ldquo;94% accuracy,&rdquo; &ldquo;3.2&times; faster.&rdquo; That&apos;s the entire setup.</p>
            </div>
            <div className="step">
              <span className="step__n">02</span>
              <h3>Run it again</h3>
              <p>The work re-executes from scratch in a sandbox that proves its own isolation first. Your code and data never leave the machine; nothing in the report is taken on faith.</p>
            </div>
            <div className="step">
              <span className="step__n">03</span>
              <h3>Rebuild the number</h3>
              <p>From the raw output files alone, Calma recomputes the headline figure on deterministic kernels — the textbook formula, never the number the AI typed into its report.</p>
            </div>
            <div className="step step--out">
              <span className="step__n">04</span>
              <h3>Get the verdict</h3>
              <p>Code compares rebuilt against claimed within a calibrated tolerance and returns one word — confirmed, refuted, or can&apos;t-confirm — with the exact gap, the fix, and a one-command replay.</p>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
