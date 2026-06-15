"use client";

import { Cross, Reveal } from "./chrome";

const ITEMS: [string, React.ReactNode][] = [
  [
    "What is Calma, in one sentence?",
    <>
      A tool that re-runs work done by AI and checks the numbers it reported —{" "}
      <b>so you don&apos;t have to take its word for it.</b>
    </>,
  ],
  [
    "Why can't the AI just check its own work?",
    <>
      Because it grades its own homework. Even when it re-runs the code, it still decides whether
      the answer matches — and it tends to agree with itself. <b>Calma&apos;s decision is made by
      code the AI can&apos;t influence.</b>
    </>,
  ],
  [
    "What do I get back?",
    <>
      One of five answers: confirmed, refuted, invalidated (the number reproduces but the result
      isn&apos;t valid), can&apos;t confirm, or confirmed with caveats (checking several claims at once
      can come back mixed) — plus the reason, the fix when something&apos;s missing, and <b>a
      one-command replay anyone can run.</b>
    </>,
  ],
  [
    "Does my code or data leave my machine?",
    <>
      No. Everything runs locally, inside a sandbox that blocks the network.{" "}
      <b>Nothing is uploaded, ever.</b>
    </>,
  ],
  [
    "What does it cost?",
    <>
      The skill is free and open source — install it and your agents use it today. The lab&apos;s
      signed verification reports are paid engagements, <b>for when money is about to move on a
      number.</b>
    </>,
  ],
];

export function Faqs() {
  return (
    <section className="sec" id="faq">
      <div className="wrap">
        <div className="faqlay">
          <div className="faqlay__main">
            <div className="sec__head">
              <Reveal>
                <span className="kicker">Questions</span>
              </Reveal>
            </div>
            <div className="faq">
              {ITEMS.map(([q, a], i) => (
                <Reveal key={q as string} delay={i * 60}>
                  <details>
                    <summary>{q}</summary>
                    <div className="a">{a}</div>
                  </details>
                </Reveal>
              ))}
            </div>
          </div>

          <Reveal delay={150} className="faqlay__aside">
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
              <figcaption className="photo__cap">Whoever did the work never grades it.</figcaption>
            </figure>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
