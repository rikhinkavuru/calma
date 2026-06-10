"use client";

import { useState } from "react";
import { Nav, Footer } from "./chrome";
import { Hero } from "./Hero";
import { Giant } from "./Giant";
import { Money } from "./Money";
import { ClaimSection } from "./ClaimSection";
import { Banner } from "./Banner";
import { Verdicts } from "./Verdicts";
import { Method } from "./Method";
import { Access } from "./Access";
import { CircleCta } from "./CircleCta";
import { Faq } from "./Faq";
import { RequestDialog } from "./RequestDialog";

export default function App() {
  const [dlg, setDlg] = useState(false);
  const openDlg = () => setDlg(true);

  return (
    <>
      <div className="stars" aria-hidden="true"></div>
      <Nav onRequest={openDlg} />
      <main>
        <Hero onRequest={openDlg} />
        <Giant />
        <Money />
        <ClaimSection />
        <Banner />
        <Verdicts />
        <Method />
        <Access onRequest={openDlg} />
        <CircleCta onRequest={openDlg} />
        <Faq />
      </main>
      <Footer />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </>
  );
}
