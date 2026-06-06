"use client";

import { useEffect, useState } from "react";
import { MotionConfig } from "framer-motion";
import { Announce } from "./Announce";
import { Nav } from "./Nav";
import { Hero } from "./Hero";
import { Problem } from "./Problem";
import { ImageBand } from "./ImageBand";
import { HowItWorks } from "./HowItWorks";
import { Roadmap } from "./Roadmap";
import { Independence } from "./Independence";
import { Closing } from "./Closing";
import { RequestDialog } from "./RequestDialog";
import { TweaksPanel } from "./TweaksPanel";

export type Tweaks = {
  theme: "paper" | "ink";
  accent: "ochre" | "graphite" | "evergreen" | "slate";
  headline: "blunt" | "earned" | "quiet";
  serifMoment: boolean;
};

const TWEAK_DEFAULTS: Tweaks = {
  theme: "paper",
  accent: "ochre",
  headline: "blunt",
  serifMoment: true,
};

const HEADLINES: Record<Tweaks["headline"], { text: string; dim?: boolean }[]> = {
  blunt: [{ text: "Your backtest looks" }, { text: "profitable. That's the problem." }],
  earned: [{ text: "A profitable backtest" }, { text: "is a claim, not a result.", dim: true }],
  quiet: [{ text: "Calm is knowing your" }, { text: "research is real first.", dim: true }],
};

export default function App() {
  const [t, setT] = useState<Tweaks>(TWEAK_DEFAULTS);
  const [dlg, setDlg] = useState(false);
  const openDlg = () => setDlg(true);

  function setTweak<K extends keyof Tweaks>(k: K, v: Tweaks[K]) {
    setT((prev) => ({ ...prev, [k]: v }));
  }

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", t.theme);
    root.setAttribute("data-accent", t.accent);
    root.setAttribute("data-serif", t.serifMoment ? "on" : "off");
  }, [t.theme, t.accent, t.serifMoment]);

  const headline = HEADLINES[t.headline] || HEADLINES.blunt;

  return (
    <MotionConfig reducedMotion="user">
      <Announce />
      <Nav onRequest={openDlg} />
      <main>
        <Hero headline={headline} onRequest={openDlg} />
        <Problem />
        <ImageBand
          label="// research desk"
          caption="where the number gets made"
          src="https://images.unsplash.com/photo-1754548930550-be9fa88874f4?w=1900&q=80&auto=format&fit=crop"
        />
        <HowItWorks />
        <Roadmap />
        <Independence />
        <Closing onRequest={openDlg} />
      </main>

      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
      <TweaksPanel t={t} setTweak={setTweak} />
    </MotionConfig>
  );
}
