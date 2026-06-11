"use client";

import { Cross, Reveal } from "./chrome";
import { CONTACT_EMAIL, FOUNDER, GITHUB_URL } from "./contact";

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
              <p className="about__founder">
                Calma is built and run by {FOUNDER}. Every line of the verification engine is
                public at{" "}
                <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                  github.com/rikhinkavuru/calma
                </a>
                , and a person answers <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
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
