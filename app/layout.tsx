import type { Metadata } from "next";
import { Archivo, Space_Mono } from "next/font/google";
import "./globals.css";

/* Archivo variable: wdth 62..125, wght 100..900 — the same axes the old
   Google Fonts CDN link loaded (wdth,wght@62.5..125,100..900). */
const archivo = Archivo({
  subsets: ["latin"],
  weight: "variable",
  axes: ["wdth"],
  display: "swap",
  variable: "--font-archivo",
});

const spaceMono = Space_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
  variable: "--font-space-mono",
});

/* globals.css declares --disp: "Archivo", ... and --mono: "Space Mono", ...
   next/font registers the fonts under hashed family names, so the literal
   names in globals.css would no longer resolve. globals.css is owned by
   another workstream, so instead of editing it we re-point --disp/--mono
   at the next/font variables via an inline style on <html> — inline style
   on the root element wins over the :root rule, and every
   font-family: var(--disp|--mono) in globals.css keeps resolving. */
const fontVarOverrides = {
  "--disp": "var(--font-archivo), system-ui, sans-serif",
  "--mono": "var(--font-space-mono), ui-monospace, Menlo, monospace",
} as React.CSSProperties;

const SITE_URL = "https://calma1.vercel.app";
const TITLE = "Calma — independent verification of AI-produced results";
const DESCRIPTION =
  "AI did the work. Calma checks it. Calma independently re-executes AI-produced " +
  "work, rebuilds the headline number from raw outputs, and tells you whether to " +
  "trust the claim.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: "%s — Calma",
  },
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "Calma",
    title: TITLE,
    description: "AI did the work. Calma checks it.",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: "AI did the work. Calma checks it.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${spaceMono.variable}`}
      style={fontVarOverrides}
    >
      <body>
        <div className="paper" aria-hidden="true"></div>
        {children}
      </body>
    </html>
  );
}
