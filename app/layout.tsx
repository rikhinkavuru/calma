import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

const zarathustra = localFont({
  src: "./fonts/Zarathustra.otf",
  variable: "--zara",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Calma — we re-run, recompute & verify AI's numbers",
  description:
    "Money moves on AI-produced numbers. Calma re-executes the work, rebuilds the number from raw outputs, and returns a verdict computed by code — before the money moves.",
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
    <html lang="en" className={zarathustra.variable}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
