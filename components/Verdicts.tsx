"use client";

import { Eyebrow, Reveal } from "./chrome";

const CARDS = [
  ["card--pass", "=", "Confirmed", "EXIT 0", "It re-runs, and the rebuilt number matches the claim within a calibrated tolerance."],
  ["card--fail", "≠", "Refuted", "EXIT 1", "The recomputed number contradicts the claim — with a one-command replay attached."],
  ["card--warn", "?", "Can't confirm", "FIX NAMED", "Not verifiable yet. The report names the exact change that makes it verifiable."],
  ["card--cav", "≈", "With caveats", "SCOPED", "Holds, but narrower than claimed — and the caveat is printed on the verdict."],
] as const;

export function Verdicts() {
  return (
    <section className="sec" id="verdicts">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <Eyebrow>the vocabulary</Eyebrow>
          </Reveal>
          <Reveal delay={100}>
            <h2>
              Four answers. <span className="serif-acc">Never a shrug.</span>
            </h2>
          </Reveal>
          <Reveal delay={180}>
            <p className="lead">
              Fixed vocabulary, machine-consumable, biased toward a caveat over a false alarm. Agents
              read the JSON verdict and branch.
            </p>
          </Reveal>
        </div>
        <div className="cards">
          {CARDS.map(([cls, glyph, name, tag, p], i) => (
            <Reveal key={name} delay={i * 110} dir={i % 2 ? "pop" : "up"}>
              <div className={"card " + cls}>
                <div className="card__thumb">
                  <span className="card__tag mono">{tag}</span>
                  <span className="glyph serif-acc">{glyph}</span>
                </div>
                <div className="card__body">
                  <b>{name}</b>
                  <p>{p}</p>
                </div>
                <div className="card__foot">how it decides &gt;&gt;&gt;</div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
