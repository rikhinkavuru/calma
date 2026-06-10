import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CALMA® — verification by re-execution",
  description:
    "Your AI did the work. Calma re-runs it: the number is rebuilt from the raw outputs and the verdict is computed by code. The producer is never the verifier.",
  openGraph: {
    title: "CALMA® — verification by re-execution",
    description:
      "Re-run the work. Recompute the number. Prove the claim — or break it.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62.5..125,100..900&family=Space+Mono:wght@400;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
