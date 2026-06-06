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
            <span className="closing__dot" /> before capital is committed
          </div>
          <h2 className="closing__title">
            Know your research is real
            <span className="closing__title-dim"> before you put money on it.</span>
          </h2>
          <p className="closing__sub">
            Calma works with systematic funds as an independent verification layer.
          </p>
          <div className="closing__actions">
            <motion.button className="btn btn-primary" onClick={onRequest} {...hoverLift}>
              Request access <Arrow />
            </motion.button>
            <motion.a className="btn btn-ghost" href="#roadmap" {...hoverLift}>
              See the roadmap
            </motion.a>
          </div>
        </Reveal>
      </div>

      <footer className="footer">
        <div className="wrap footer__inner">
          <div className="footer__brand">
            <span className="brand__mark" aria-hidden="true" />
            <span className="brand__word">calma</span>
          </div>
          <div className="footer__cols">
            <div className="footer__col">
              <div className="footer__h mono">Product</div>
              <a href="#how">The four checks</a>
              <a href="#roadmap">Roadmap</a>
              <a href="#independence">Why independent</a>
            </div>
            <div className="footer__col">
              <div className="footer__h mono">Company</div>
              <a href="#access">Request access</a>
              <a href="#top">Security</a>
              <a href="#top">Contact</a>
            </div>
            <div className="footer__col">
              <div className="footer__h mono">Legal</div>
              <a href="#top">Terms</a>
              <a href="#top">Privacy</a>
            </div>
          </div>
        </div>
        <div className="wrap footer__base mono">
          <span>© 2026 Calma Research, Inc.</span>
          <span className="footer__motto">the system that generates a strategy can't be trusted to verify it.</span>
        </div>
      </footer>
    </section>
  );
}
