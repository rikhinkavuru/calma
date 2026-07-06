import type { Metadata } from "next";
import { SiteNav } from "@/components/SiteNav";
import { DocsSidebar } from "./DocsSidebar";
import s from "./docs.module.css";

export const metadata: Metadata = {
  title: "Docs — Calma",
  description: "Verify the numbers a repository reports. API, CLI, MCP, and CI docs for Calma.",
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <SiteNav />
      <div className={s.docs}>
        <DocsSidebar />
        <main className={s.main}>{children}</main>
      </div>
    </>
  );
}
