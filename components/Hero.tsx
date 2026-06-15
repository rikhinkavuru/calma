"use client";

import { Atmo, Reveal } from "./chrome";
import { HeroDemo } from "./HeroDemo";

export function Hero() {
  return (
    <section className="hero" id="top">
      <Atmo />
      <div className="wrap hero__inner hero__inner--center">
        <Reveal>
          <h1 className="h1">AI did the work. Calma checks it.</h1>
        </Reveal>

        <Reveal delay={200}>
          <p className="lead hero__lead">
            Your AI reports a number and calls the work done. Calma re-runs the work, rebuilds that
            number from the raw outputs, and tells you in one word <b>whether to trust it.</b>
          </p>
        </Reveal>

        <Reveal delay={400} className="hero__fill">
          <div className="hero__demo">
            <HeroDemo />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
