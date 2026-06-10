"use client";

import { motion } from "framer-motion";
import { Arrow } from "./primitives";
import { Reveal } from "./Reveal";
import { hoverLift } from "./motion";

export function Closing({ onRequest }: { onRequest: () => void }) {
  return (
    <section id="access" className="closing">
      <div className="wrap">
        <Reveal className="closing__inner">
          <div className="closing__lead mono">
            <span className="closing__dot" /> before the number ships
          </div>
          <h2 className="closing__title">
            Trust is earned
            <span className="closing__title-dim"> by re-execution.</span>
          </h2>
          <p className="closing__sub">
            Install the skill and your agents check their own homework against ground truth.
            Engage the lab and your counterparties get a verdict the producer can&apos;t touch.
          </p>
          <div className="closing__actions">
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
          </div>
        </Reveal>
      </div>

      <footer className="footer">
        <div className="wrap footer__inner">
          <div className="footer__brand">
            <span className="brand__word mono">calma</span>
            <span className="brand__cursor" aria-hidden="true" />
          </div>
          <div className="footer__cols">
            <div className="footer__col">
              <div className="footer__h mono">Product</div>
              <a href="#how">How it works</a>
              <a href="#verdicts">Verdicts</a>
              <a href="#get">Get the skill</a>
            </div>
            <div className="footer__col">
              <div className="footer__h mono">Open source</div>
              <a href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
                GitHub
              </a>
              <a
                href="https://github.com/rikhinkavuru/calma/blob/main/README.md"
                target="_blank"
                rel="noreferrer"
              >
                Docs
              </a>
              <a
                href="https://github.com/rikhinkavuru/calma/blob/main/LICENSE"
                target="_blank"
                rel="noreferrer"
              >
                MIT license
              </a>
            </div>
            <div className="footer__col">
              <div className="footer__h mono">The lab</div>
              <a href="#access">Request verification</a>
              <a href="#independence">Why independent</a>
              <a href="#faq">FAQ</a>
            </div>
          </div>
        </div>
        <div className="wrap footer__base mono">
          <span>© 2026 Calma</span>
          <span className="footer__motto">the system that produced a result can&apos;t be trusted to verify it.</span>
        </div>
      </footer>
    </section>
  );
}
