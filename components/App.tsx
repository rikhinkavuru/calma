"use client";

import { useState } from "react";
import { Nav, Footer } from "./chrome";
import { Hero } from "./Hero";
import { Catch } from "./Catch";
import { Deep } from "./Deep";
import { How } from "./How";
import { Verdicts } from "./Verdicts";
import { Get } from "./Get";
import { Faq } from "./Faq";
import { RequestDialog } from "./RequestDialog";

export default function App() {
  const [dlg, setDlg] = useState(false);
  const openDlg = () => setDlg(true);

  return (
    <>
      <Nav onRequest={openDlg} />
      <main>
        <Hero onRequest={openDlg} />
        <Catch />
        <Deep />
        <How />
        <Verdicts />
        <Get onRequest={openDlg} />
        <Faq />
      </main>
      <Footer onRequest={openDlg} />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </>
  );
}
