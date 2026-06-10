"use client";

import { useState } from "react";
import { Topbar, Footer } from "./chrome";
import { Masthead } from "./Masthead";
import { Hero } from "./Hero";
import { ClaimSection } from "./ClaimSection";
import { Method } from "./Method";
import { Evidence } from "./Evidence";
import { Verdicts } from "./Verdicts";
import { Access } from "./Access";
import { Faq } from "./Faq";
import { RequestDialog } from "./RequestDialog";

export default function App() {
  const [dlg, setDlg] = useState(false);
  const openDlg = () => setDlg(true);

  return (
    <>
      <div className="grain" aria-hidden="true"></div>
      <Topbar />
      <main>
        <Masthead />
        <Hero onRequest={openDlg} />
        <ClaimSection />
        <hr className="rule" />
        <Method />
        <hr className="rule" />
        <Evidence />
        <hr className="rule" />
        <Verdicts />
        <hr className="rule" />
        <Access onRequest={openDlg} />
        <hr className="rule" />
        <Faq />
      </main>
      <Footer />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </>
  );
}
