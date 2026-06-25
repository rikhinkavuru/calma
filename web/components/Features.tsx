"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { FeatureAscii, type AsciiVariant } from "./FeatureAscii";

/* Pinned horizontal scroll: each feature fills the screen — text on the left
   half, a live ASCII field on the right half. Scrolling slides the current
   feature out to the left and the next in. Deliberate (a screen of scroll per
   feature); vertical-stack fallback on small screens / reduced motion (CSS). */
const FEATURES: { idx: string; name: string; art: AsciiVariant; p: string }[] = [
  {
    idx: "01",
    name: "Re-execution",
    art: "rerun",
    p: "Calma re-executes your code from scratch in a sandbox that proves its own isolation first — it plants a fake secret, tries to leak it and reach the network, and only calls the machine sealed once every attempt fails. The number is rebuilt on bit-stable kernels: same inputs, same answer, on any machine. Python, R, Julia, C++, Rust and Node all run as a sealed black box. Nothing is ever uploaded.",
  },
  {
    idx: "02",
    name: "Deterministic verdict",
    art: "verdict",
    p: "Write the claim the way you’d say it — “p95 latency 120 ms,” “net Sharpe 2.4,” “monthly CAGR 23.9%.” Calma parses the number and metric, finds the output column that holds it, and independently double-checks that binding before it can matter. Then every number and the verdict come from code, not a model — so nothing, not even the agent that produced the number, can talk its way to a pass: a claim is refuted only when the gap clears a calibrated tolerance, and an ambiguous one degrades to can’t-confirm with the exact fix.",
  },
  {
    idx: "03",
    name: "Validity, not just arithmetic",
    art: "claim",
    p: "A number can recompute perfectly and still be wrong. Calma re-runs the result against four validity families — data leakage (train/test overlap), overfitting (the deflated Sharpe ratio and PBO across the declared trials), execution realism (cost, slippage and market impact on a “net” claim), and benchmark contamination — and stamps it INVALIDATED when the headline reproduces but the held-out claim doesn’t actually hold. These checks only ever make a verdict more cautious, never less.",
  },
  {
    idx: "04",
    name: "Signed, portable & autonomous",
    art: "signed",
    p: "Every run emits a signed report the other side checks with tools already on their machine — stock OpenSSH, fully offline — plus an optional trusted timestamp, and each verification appends to a public track record that can’t be retconned. It drops into agent loops and CI, cached by content hash, gating only when a claim truly breaks; choose how hands-off it runs with ask, suggest or auto modes. (DSSE/in-toto, Sigstore-compatible, RFC 3161.)",
  },
];

export function Features() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const x = useTransform(scrollYProgress, [0, 1], ["0vw", `-${(FEATURES.length - 1) * 100}vw`]);

  return (
    <section ref={ref} className="fscroll" id="features" style={{ height: `${FEATURES.length * 100}vh` }}>
      <div className="fscroll__pin">
        <motion.div className="fscroll__track" style={{ x }}>
          {FEATURES.map((f) => (
            <article className="fpanel" key={f.name}>
              <div className="fpanel__text">
                <span className="fpanel__idx">
                  {f.idx} / 0{FEATURES.length}
                </span>
                <h3 className="fpanel__title">
                  <span className="fpanel__arrow">→</span> {f.name}
                </h3>
                <p>{f.p}</p>
              </div>
              <div className="fpanel__ascii">
                <FeatureAscii variant={f.art} />
              </div>
            </article>
          ))}
        </motion.div>
        <motion.div className="fscroll__bar" style={{ scaleX: scrollYProgress }} />
      </div>
    </section>
  );
}
