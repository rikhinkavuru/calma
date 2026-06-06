"use client";

import { motion } from "framer-motion";
import type { ComponentProps } from "react";

type MotionTag = "div" | "section" | "article" | "h1" | "h2" | "h3" | "p" | "li";

const MOTION = {
  div: motion.div,
  section: motion.section,
  article: motion.article,
  h1: motion.h1,
  h2: motion.h2,
  h3: motion.h3,
  p: motion.p,
  li: motion.li,
} as const;

type RevealProps = ComponentProps<typeof motion.div> & { delay?: number; as?: MotionTag };

/* Scroll-triggered reveal with stagger — the Framer Motion equivalent of the
   prototype's IntersectionObserver reveal layer (opacity + 20px rise, once).
   Polymorphic via `as` so headlines stay real <h1>/<h2> elements. */
export function Reveal({ delay = 0, as = "div", children, ...rest }: RevealProps) {
  const M = MOTION[as] as typeof motion.div;
  return (
    <M
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -7% 0px" }}
      transition={{ duration: 0.8, ease: [0.2, 0.7, 0.2, 1], delay }}
      {...rest}
    >
      {children}
    </M>
  );
}
