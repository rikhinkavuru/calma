"use client";

import { motion, useScroll } from "framer-motion";

/* thin amber scroll-progress bar pinned to the top */
export function BpProgress() {
  const { scrollYProgress } = useScroll();
  return <motion.div className="bp-progress" style={{ scaleX: scrollYProgress }} aria-hidden="true" />;
}
