import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Calma — your AI did the work. Calma checks it.",
  description:
    "Independent verification for AI-produced results: Calma re-runs the work in a sandbox and recomputes the number from the raw outputs. The verdict comes from deterministic code, not a model's opinion.",
  openGraph: {
    title: "Calma — verification by re-execution",
    description:
      "Re-run the work. Recompute the number. Prove the claim — or break it. Free open-source skill; independent verification lab for funds and allocators.",
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
          href="https://fonts.googleapis.com/css2?family=Archivo:ital,wght@0,300..900;1,300..700&family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;1,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
