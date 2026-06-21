"use client";

import { useState } from "react";
import { MotionConfig } from "framer-motion";
import { SiteNav } from "./SiteNav";
import { Hero } from "./Hero";
import { RequestDialog } from "./RequestDialog";
import { BpProgress } from "./home/BpProgress";
import { BpTag } from "./home/BpTag";
import { BpProblem } from "./home/BpProblem";
import { BpCompare } from "./home/BpCompare";
import { BpHow } from "./home/BpHow";
import { BpFeatures } from "./home/BpFeatures";
import { BpEdge } from "./home/BpEdge";
import { BpBench } from "./home/BpBench";
import { BpWho } from "./home/BpWho";
import { BpFaq } from "./home/BpFaq";
import { BpCounter } from "./home/BpCounter";
import { BpFooter } from "./home/BpFooter";

export default function App() {
  const [dlg, setDlg] = useState(false);

  return (
    <MotionConfig reducedMotion="user">
      <BpProgress />
      <div className="grain" aria-hidden="true"></div>
      <SiteNav />

      <main>
        <Hero />

        {/* continuous, bordered, tag-divided body (supermemory-style, warm) */}
        <div className="bp">
          <BpTag label="The problem" n={1} />
          <BpProblem />
          <BpCompare />
          <BpTag label="How it works" n={2} />
          <BpHow />
          <BpTag label="Capabilities" n={3} />
          <BpFeatures />
          <BpEdge />
          <BpTag label="Benchmarks" n={4} />
          <BpBench />
          <BpTag label="Who it's for" n={5} />
          <BpWho />
          <BpTag label="FAQ" n={6} />
          <BpFaq />
        </div>

        <div className="wrap" style={{ paddingBottom: "clamp(24px, 4vw, 48px)" }}>
          <BpCounter onRequest={() => setDlg(true)} />
        </div>
      </main>

      <BpFooter />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </MotionConfig>
  );
}
