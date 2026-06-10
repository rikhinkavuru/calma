import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "calma. — verification by re-execution",
  description:
    "Your AI did the work. Calma re-runs it: recomputes the number from the raw outputs and proves the claim — or breaks it. The verdict is computed by code.",
  openGraph: {
    title: "calma. — verification by re-execution",
    description:
      "Re-run the work. Recompute the number. Prove the claim — or break it. Free open-source skill; independent verification lab.",
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
          href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Archivo:wght@400;500;600;700&family=Fredoka:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
