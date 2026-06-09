"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform, useReducedMotion } from "framer-motion";
import { Arrow } from "./primitives";
import { Reveal } from "./Reveal";
import { hoverLift } from "./motion";
import { HeroConsole } from "./HeroConsole";
import { StackMarquee } from "./StackMarquee";

type Line = { text: string; dim?: boolean };

export function Hero({ headline, onRequest }: { headline: Line[]; onRequest: () => void }) {
  const ref = useRef<HTMLElement | null>(null);
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const yRaw = useTransform(scrollYProgress, [0, 1], [0, 48]);
  const y = reduced ? 0 : yRaw;

  return (
    <section id="top" className="hero" ref={ref}>
      <motion.div className="hero__bg" aria-hidden="true" style={{ y }}>
        <div className="hero__grid" />
        <svg className="hero__curve" viewBox="0 0 200 60" preserveAspectRatio="none">
          <path className="cl" d="M0,54 L30,48 L60,40 L100,28 L140,16 L175,8 L200,4" vectorEffect="non-scaling-stroke" />
          <path className="vf" d="M0,54 L30,51 L60,49 L100,47 L140,49 L175,52 L200,53" vectorEffect="non-scaling-stroke" />
        </svg>
      </motion.div>
      <div className="wrap hero__inner">
        <Reveal as="h1" className="hero__title">
          {headline.map((line, i) => (
            <span key={i} className={"hero__line" + (line.dim ? " hero__line--dim" : "")}>
              {line.text}
            </span>
          ))}
        </Reveal>

        <Reveal as="p" className="hero__sub" delay={0.08}>
          Calma re-runs the work on your own machine and recomputes the number from the raw outputs —
          proving the claim, or breaking it, before capital is committed. The open-source skill is free
          today; the quant CLI adds the deep statistics.
        </Reveal>

        <Reveal className="hero__actions" delay={0.16}>
          <motion.a
            className="btn btn-primary btn-lg"
            href="https://github.com/rikhinkavuru/calma"
            target="_blank"
            rel="noreferrer"
            {...hoverLift}
          >
            Install the free skill <Arrow />
          </motion.a>
          <motion.button className="btn btn-ghost btn-lg" onClick={onRequest} {...hoverLift}>
            Request CLI access
          </motion.button>
        </Reveal>

        <Reveal className="hero__demo" delay={0.24}>
          <HeroConsole />
        </Reveal>
      </div>

      <div className="hero__stack">
        <span className="hero__stack-lbl mono">reads your existing pipeline</span>
        <StackMarquee />
      </div>
    </section>
  );
}
