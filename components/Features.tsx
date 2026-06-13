"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { CardArt } from "./CardArt";

/* Pinned horizontal scroll: each feature fills the screen; scrolling slides the
   current one out to the left and the next one in. The section is tall, so it
   takes deliberate scrolling to advance — it can't flip on a touch. Falls back
   to a vertical stack on small screens / reduced motion (handled in CSS). */
const FEATURES: { k: string; art: "rerun" | "verdict" | "claim" | "signed"; h: string; p: string }[] = [
  {
    k: "Re-execution",
    art: "rerun",
    h: "Nothing is taken on the AI’s word.",
    p: "Calma re-executes your code from scratch in a sandbox that proves its own isolation first: it plants a fake secret, tries to leak it and reach the network, and only calls the machine sealed once every attempt fails. The number is then rebuilt on bit-stable kernels — same inputs, same answer, on any machine. Python, R, Julia, C++, Rust and Node all run as a sealed black box, no SDK to add. Nothing is ever uploaded.",
  },
  {
    k: "Deterministic verdict",
    art: "verdict",
    h: "A pass no model can argue its way into.",
    p: "Every number and the verdict itself come from code, so a persuasive model — or a motivated author — can’t charm its way to a pass. A claim is refuted only when the gap clears a calibrated tolerance budget drawn from the claim’s own stated precision and the metric’s noise floor; when an input is ambiguous it degrades to can’t-confirm with the exact fix. A caveat over a false alarm, every time.",
  },
  {
    k: "Plain-English claims",
    art: "claim",
    h: "Say the claim like you’d say it out loud.",
    p: "Write it the way you’d say it — “p95 latency 120 ms,” “pass@5 0.62,” “monthly CAGR 23.9%.” Calma parses the number, the metric, and even the convention, then scans your output files to find the column that holds it and independently double-checks that guess before it’s allowed to matter. Pin everything explicitly with one small config when you’d rather not leave it to inference.",
  },
  {
    k: "Signed & portable",
    art: "signed",
    h: "Proof your counterparty can check alone.",
    p: "Every run emits a signed report the other side checks with tools already on their machine — stock OpenSSH, fully offline — plus an optional trusted timestamp that proves the date years later. It drops into agent loops and CI, cached by content hash so unchanged work answers instantly and gating only when a claim truly breaks, and each verification appends to a track record that can’t be retconned. (DSSE/in-toto, Sigstore-compatible, RFC 3161.)",
  },
];

export function Features() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const x = useTransform(scrollYProgress, [0, 1], ["0vw", `-${(FEATURES.length - 1) * 100}vw`]);

  return (
    <section ref={ref} className="fscroll" id="features" style={{ height: `${FEATURES.length * 100}vh` }}>
      <div className="fscroll__pin">
        <div className="fscroll__label">
          <span className="kicker">Features</span>
          <span className="fscroll__tag">Simple to use. Hard to fool.</span>
        </div>

        <motion.div className="fscroll__track" style={{ x }}>
          {FEATURES.map((f, i) => (
            <article className="fpanel" key={f.k}>
              <div className="fpanel__inner">
                <div className="fpanel__art">
                  <CardArt kind={f.art} />
                </div>
                <div className="fpanel__text">
                  <span className="fpanel__idx">
                    {String(i + 1).padStart(2, "0")} / {String(FEATURES.length).padStart(2, "0")}
                  </span>
                  <span className="frow__k">{f.k}</span>
                  <h3>{f.h}</h3>
                  <p>{f.p}</p>
                </div>
              </div>
            </article>
          ))}
        </motion.div>

        <motion.div className="fscroll__bar" style={{ scaleX: scrollYProgress }} />
      </div>
    </section>
  );
}
