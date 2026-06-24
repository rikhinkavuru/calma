"use client";

import { useState } from "react";
import { MotionConfig } from "framer-motion";
import { SiteNav } from "./SiteNav";
import { Hero } from "./Hero";
import { RequestDialog } from "./RequestDialog";
import { BpProgress } from "./home/BpProgress";
import { BpCounter } from "./home/BpCounter";
import { BpFooter } from "./home/BpFooter";

// Landing stripped to hero + outro + footer; the full body is being rebuilt.
export default function App() {
  const [dlg, setDlg] = useState(false);

  return (
    <MotionConfig reducedMotion="user">
      <BpProgress />
      <div className="grain" aria-hidden="true"></div>
      <SiteNav />

      <main>
        <Hero />

        <div className="wrap" style={{ paddingBottom: "clamp(24px, 4vw, 48px)" }}>
          <BpCounter onRequest={() => setDlg(true)} />
        </div>
      </main>

      <BpFooter />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </MotionConfig>
  );
}
