"use client";

import { useState } from "react";
import { Topbar, Footer } from "./chrome";
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
      <Topbar onRequest={openDlg} />
      <main>
        <Hero onRequest={openDlg} />
        <ClaimSection />
        <Method />
        <Evidence />
        <Verdicts />
        <Access onRequest={openDlg} />
        <Faq />
      </main>
      <Footer />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </>
  );
}
