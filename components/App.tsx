"use client";

import { useState } from "react";
import { MotionConfig } from "framer-motion";
import { Nav } from "./chrome";
import { Hero } from "./Hero";
import { Problem } from "./Catch";
import { Benchmarks } from "./Benchmarks";
import { RecipeTicker } from "./RecipeTicker";
import { Features } from "./Features";
import { Benefits } from "./Benefits";
import { Faqs } from "./Faqs";
import { Outro } from "./Outro";
import { RequestDialog } from "./RequestDialog";

export default function App() {
  const [dlg, setDlg] = useState(false);
  const openDlg = () => setDlg(true);

  return (
    <MotionConfig reducedMotion="user">
      <div className="grain" aria-hidden="true"></div>
      <Nav />
      <main>
        <Hero />
        <div className="texture">
          <Problem />
          <Benchmarks />
          <Features />
          <Benefits onRequest={openDlg} />
          <RecipeTicker />
          <Faqs />
        </div>
      </main>
      <Outro />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </MotionConfig>
  );
}
