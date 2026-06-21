"use client";

import dynamic from "next/dynamic";
import { Reveal } from "./chrome";

/* FlowingMenu (gsap + window) — client-only. */
const FlowingMenu = dynamic(() => import("./FlowingMenu"), { ssr: false });

const WHO = [
  {
    link: "https://github.com/rikhinkavuru/calma",
    text: "Builders",
    description: "Your agent checks its own work — the wrong number dies in the loop, not in production.",
    image: "/img/who-builders.svg",
  },
  {
    link: "https://github.com/rikhinkavuru/calma/blob/main/README.md",
    text: "Teams",
    description: "Run Calma in CI as a gate — the proof travels with the work, and anyone can replay it.",
    image: "/img/who-teams.svg",
  },
  {
    link: "/lab",
    text: "Investors & funds",
    description: "The lab independently re-executes the research before the money moves.",
    image: "/img/who-fund.svg",
  },
];

export function Benefits(_props: { onRequest: () => void }) {
  return (
    <section className="sec" id="benefits">
      <div className="wrap">
        <Reveal>
          <div className="sec__head">
            <span className="kicker">Who it&apos;s for</span>
            <h2 className="h2">Three ways people use Calma.</h2>
            <p className="lead whoflow__lead">
              Builders catch the mistake in the agent loop. Teams gate it in CI. Funds get proof
              before the money moves.
            </p>
          </div>

          <div className="whoflow">
            <FlowingMenu
              items={WHO}
              speed={18}
              textColor="#e9ddc4"
              bgColor="transparent"
              marqueeBgColor="#e89a5d"
              marqueeTextColor="#0d0b08"
              borderColor="rgba(233,221,196,0.16)"
            />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
