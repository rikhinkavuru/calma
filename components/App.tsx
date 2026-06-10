"use client";

import { useState } from "react";
import { Atmos } from "./Atmos";
import { Nav } from "./Nav";
import { Hero } from "./Hero";
import { Method } from "./Method";
import { Palette } from "./Palette";
import { Evidence } from "./Evidence";
import { Get } from "./Get";
import { Faq } from "./Faq";
import { Footer } from "./Footer";
import { RequestDialog } from "./RequestDialog";

export default function App() {
  const [dlg, setDlg] = useState(false);
  const openDlg = () => setDlg(true);

  return (
    <>
      <Atmos />
      <Nav onRequest={openDlg} />
      <main>
        <Hero />
        <Method />
        <Palette />
        <Evidence />
        <Get onRequest={openDlg} />
        <Faq />
      </main>
      <Footer />
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </>
  );
}
