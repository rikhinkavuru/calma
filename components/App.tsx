"use client";

import { useState } from "react";
import { MotionConfig } from "framer-motion";
import { Announce } from "./Announce";
import { Nav } from "./Nav";
import { Hero } from "./Hero";
import { Marquee } from "./Marquee";
import { Problem } from "./Problem";
import { HowItWorks } from "./HowItWorks";
import { Verdicts } from "./Verdicts";
import { Independence } from "./Independence";
import { Layers } from "./Layers";
import { Faq } from "./Faq";
import { Closing } from "./Closing";
import { RequestDialog } from "./RequestDialog";

export default function App() {
  const [dlg, setDlg] = useState(false);
  const openDlg = () => setDlg(true);

  return (
    <MotionConfig reducedMotion="user">
      <Announce />
      <Nav onRequest={openDlg} />
      <main>
        <Hero onRequest={openDlg} />
        <Marquee />
        <Problem />
        <HowItWorks />
        <Verdicts />
        <Independence />
        <Layers onRequest={openDlg} />
        <Faq />
        <Closing onRequest={openDlg} />
      </main>
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </MotionConfig>
  );
}
