"use client";

import { motion } from "framer-motion";
import { Section, Arrow } from "./primitives";
import { Reveal } from "./Reveal";
import { hoverLift } from "./motion";

export function Layers({ onRequest }: { onRequest: () => void }) {
  return (
    <Section
      id="get"
      num="05"
      label="get it"
      watermark="05 / TWO LAYERS"
      title={
        <>
          Free for your agents. <span className="dim">Independent for your capital.</span>
        </>
      }
    >
      <div className="layers">
        <Reveal className="layer">
          <span className="layer__tag">open source · mit</span>
          <h3 className="layer__h">The skill + CLI</h3>
          <div className="layer__price">free, forever — pure stdlib, zero dependencies</div>
          <ul className="layer__list">
            <li><span>Verify any agent&apos;s result: metrics, backtests, datasets, aggregates — claims in plain language</span></li>
            <li><span>Works in Claude Code, Codex, Cursor — anything that reads SKILL.md — or as a plain CLI</span></li>
            <li><span>Agent-grade: <code className="mono">--json</code> verdicts, millisecond cached re-checks, a CI gate that fails only on a real break</span></li>
            <li><span>Shareable teardown cards (<code className="mono">--svg</code>) when something breaks</span></li>
          </ul>
          <div className="layer__cmd">
            <span className="c-g">$</span> /plugin marketplace add rikhinkavuru/calma{"\n"}
            <span className="c-g">$</span> /plugin install calma@calma
          </div>
          <div className="layer__cta">
            <motion.a
              className="btn btn-primary"
              href="https://github.com/rikhinkavuru/calma"
              target="_blank"
              rel="noreferrer"
              {...hoverLift}
            >
              GitHub <Arrow />
            </motion.a>
          </div>
        </Reveal>

        <Reveal className="layer layer--lab" delay={0.07}>
          <span className="layer__tag">the verification lab</span>
          <h3 className="layer__h">Signed verification reports</h3>
          <div className="layer__price">per engagement — for managers raising, and allocators deciding</div>
          <ul className="layer__list">
            <li><span>Independent re-execution of the research, in isolation, on your data snapshot</span></li>
            <li><span>The overfitting battery: deflated Sharpe, PBO, baseline edge — over disclosed trials</span></li>
            <li><span>Leakage re-run that quantifies the drop, not a static opinion</span></li>
            <li><span>A signed, content-addressed attestation your counterparty can re-check command-for-command</span></li>
          </ul>
          <div className="layer__cmd">
            claimed +14,698% <span className="c-g">→</span> recomputed −32.4%{"\n"}
            <span className="c-g">caught before capital was committed</span>
          </div>
          <div className="layer__cta">
            <motion.button className="btn btn-primary" onClick={onRequest} {...hoverLift}>
              Request verification <Arrow />
            </motion.button>
          </div>
        </Reveal>
      </div>
    </Section>
  );
}
