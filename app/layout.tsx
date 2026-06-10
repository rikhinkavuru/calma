import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CALMA — proof is here",
  description:
    "In the race to hand real work to AI, whoever trusted the number loses. Calma re-runs the work, recomputes the result, and decides with code — before the money moves.",
  openGraph: {
    title: "CALMA — proof is here",
    description:
      "Re-run the work. Recompute the number. Decide with code.",
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
