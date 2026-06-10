import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

const basteleur = localFont({
  src: [
    { path: "./fonts/Basteleur-Moonlight.woff2", weight: "400", style: "normal" },
    { path: "./fonts/Basteleur-Bold.woff2", weight: "700", style: "normal" },
  ],
  variable: "--bast",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Calma — proof before the money moves",
  description:
    "AI does the work; money moves on the numbers it reports. Calma re-runs the work and recomputes the number — the verdict is computed by code, and nobody can talk it out of a fail.",
  openGraph: {
    title: "Calma — proof before the money moves",
    description:
      "Re-run the work. Recompute the number. Prove the claim — or break it.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={basteleur.variable}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;430;500;600&family=Space+Mono:wght@400;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
