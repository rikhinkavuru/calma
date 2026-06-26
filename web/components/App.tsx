"use client";

import { MotionConfig } from "framer-motion";
import { SiteNav } from "./SiteNav";
import { Hero } from "./Hero";
import { BpProgress } from "./home/BpProgress";
import { BpFlow } from "./home/BpFlow";
import { BpMoats } from "./home/BpMoats";
import { BpFaq } from "./home/BpFaq";
import { BpFooter } from "./home/BpFooter";

// Landing: hero → convergence (flow) → features (moats) → FAQ → footer.
export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <BpProgress />
      <div className="grain" aria-hidden="true"></div>
      <SiteNav />

      <main>
        <Hero />
        <BpFlow />
        <BpMoats />
        <section className="flowsec faqsec">
          <div className="wrap">
            <BpFaq />
          </div>
        </section>
      </main>

      <BpFooter />
    </MotionConfig>
  );
}
