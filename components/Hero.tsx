"use client";

import { motion } from "framer-motion";
import { Arrow } from "./primitives";
import { Reveal } from "./Reveal";
import { hoverLift } from "./motion";
import { GridFX } from "./GridFX";
import { Terminal } from "./Terminal";

export function Hero({ onRequest }: { onRequest: () => void }) {
  return (
    <section id="top" className="hero">
      <GridFX />
      <div className="wrap hero__inner">
        <Reveal as="h1" className="hero__title">
          Your AI did the work. <span className="dim">Calma checks it.</span>
        </Reveal>

        <Reveal as="p" className="hero__sub" delay={0.08}>
          Calma <strong>re-runs the work in a sandbox and recomputes the number from the raw
          outputs</strong> — never the number that was reported. The verdict comes from
          deterministic code, not a model&apos;s opinion. Even the agent that wrote the code
          can&apos;t talk it out of a FAIL.
        </Reveal>

        <Reveal className="hero__actions" delay={0.16}>
          <motion.a
            className="btn btn-primary btn-lg"
            href="https://github.com/rikhinkavuru/calma"
            target="_blank"
            rel="noreferrer"
            {...hoverLift}
          >
            Get the free skill <Arrow />
          </motion.a>
          <motion.button className="btn btn-ghost btn-lg" onClick={onRequest} {...hoverLift}>
            Request verification
          </motion.button>
        </Reveal>

        <Reveal className="hero__hint" delay={0.22}>
          <code>/plugin install calma@calma</code> · pure stdlib · zero dependencies · MIT
        </Reveal>

        <Reveal delay={0.3} style={{ width: "100%", display: "flex", justifyContent: "center" }}>
          <Terminal />
        </Reveal>
      </div>
    </section>
  );
}
