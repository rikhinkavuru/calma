"use client";

import { MotionConfig } from "framer-motion";
import { SiteNav } from "./SiteNav";
import { Hero } from "./Hero";
import { BpProgress } from "./home/BpProgress";
import { BpFlow } from "./home/BpFlow";
import { BpFeatures } from "./home/BpFeatures";
import { BpFooter } from "./home/BpFooter";

// Landing: hero + convergence section + footer; the full body is being rebuilt.
export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <BpProgress />
      <div className="grain" aria-hidden="true"></div>
      <SiteNav />

      <main>
        <Hero />
        <BpFlow />
        <BpFeatures />
      </main>

      <BpFooter />
    </MotionConfig>
  );
}
