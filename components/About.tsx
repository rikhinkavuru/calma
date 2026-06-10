"use client";

import { Cross, Reveal } from "./chrome";

export function About() {
  return (
    <section className="sec" id="about">
      <div className="wrap">
        <div className="sec__head">
          <Reveal>
            <span className="kicker">About</span>
          </Reveal>
        </div>
        <div className="about">
          <Reveal delay={100}>
            <div>
              <h2 className="h2">Whoever did the work never gets to grade it.</h2>
              <p className="lead">
                That&apos;s the whole idea. Funds have administrators. Companies have auditors.{" "}
                <b>Work done by AI gets Calma.</b> The engine is open source so anyone can check
                the checker — and the lab signs its name to every report.
              </p>
            </div>
          </Reveal>
          <Reveal delay={220}>
            <figure className="photo">
              <Cross className="tl" />
              <Cross className="br" />
              <img
                src="/img/lab.webp"
                alt="A desk lamp examining a stack of printed pages in a dark room"
                width={1200}
                height={896}
                loading="lazy"
              />
              <figcaption className="photo__cap">The lab — every claim under the lamp</figcaption>
            </figure>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
