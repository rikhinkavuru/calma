"use client";

import { useState } from "react";
import { Nav } from "./chrome";
import { Hero } from "./Hero";
import { Problem } from "./Catch";
import { Overview } from "./Overview";
import { Features } from "./Features";
import { Benefits } from "./Benefits";
import { About } from "./About";
import { Faqs } from "./Faqs";
import { Outro } from "./Outro";
import { RequestDialog } from "./RequestDialog";

export default function App() {
  const [dlg, setDlg] = useState(false);
  const openDlg = () => setDlg(true);

  return (
    <>
      <div className="grain" aria-hidden="true"></div>
      <Nav onRequest={openDlg} />
      <main>
        <Hero onRequest={openDlg} />
        <div className="nebula-host">
          <div className="nebula nebula--band nebula--home" aria-hidden="true">
            <i />
          </div>
          <Problem />
          <Overview />
          <Features />
          <Benefits onRequest={openDlg} />
          <About />
          <Faqs />
        </div>
      </main>
      <Outro />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </>
  );
}
