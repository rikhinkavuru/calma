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
    p: "Every number and the verdict itself come from code, so a persuasive model — or a motivated author — can’t charm its way to a pass. A claim is refuted only when the gap clears a calibrated tolerance budget; when an input is ambiguous it degrades to can’t-confirm with the exact fix. A caveat over a false alarm, every time.",
  },
  {
    idx: "03",
    name: "Plain-English claims",
    art: "claim",
    p: "Write the claim the way you’d say it — “p95 latency 120 ms,” “pass@5 0.62,” “monthly CAGR 23.9%.” Calma parses the number, the metric, and the convention, scans your output files for the column that holds it, and independently double-checks that guess before it’s allowed to matter. Pin it with one small config when you’d rather not infer.",
  },
  {
    idx: "04",
    name: "Signed & portable",
    art: "signed",
    p: "Every run emits a signed report the other side checks with tools already on their machine — stock OpenSSH, fully offline — plus an optional trusted timestamp. It drops into agent loops and CI, cached by content hash, gating only when a claim truly breaks, and each verification appends to a track record that can’t be retconned. (DSSE/in-toto, Sigstore-compatible, RFC 3161.)",
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
