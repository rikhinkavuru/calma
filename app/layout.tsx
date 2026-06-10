import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CALMA — proof is here",
  description:
    "AI did the work. Calma checks it. Calma re-runs your AI's work, rebuilds the numbers it reported, and tells you whether to trust them.",
  openGraph: {
    title: "CALMA — proof is here",
    description: "AI did the work. Calma checks it.",
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
      <body>
        <div className="paper" aria-hidden="true"></div>
        {children}
      </body>
    </html>
  );
}
