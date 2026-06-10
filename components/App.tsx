"use client";

import { useState } from "react";
import { Nav } from "./chrome";
import { Hero } from "./Hero";
import { Catch } from "./Catch";
import { Specimen } from "./Specimen";
import { Method } from "./Method";
import { Vstrip } from "./Vstrip";
import { Get } from "./Get";
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
        <Catch />
        <Specimen />
        <Method />
        <Vstrip />
        <Get onRequest={openDlg} />
      </main>
      <Outro />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </>
  );
}
