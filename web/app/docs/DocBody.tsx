"use client";

// Renders a doc page's Markdown (GFM: tables, code, lists) into the editorial docs styling. Code blocks get a
// copy button; ## headings get anchor ids matching the right-rail "On this page" links.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useState } from "react";
import { FiCopy, FiCheck } from "react-icons/fi";
import { slugify } from "./content";
import s from "./docs.module.css";

function textOf(node: unknown): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in (node as any)) return textOf((node as any).props.children);
  return "";
}

function CodeBlock({ children }: { children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = textOf(children).replace(/\n$/, "");
  const copy = () => navigator.clipboard?.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); });
  return (
    <div className={s.codewrap}>
      <button className={s.codecopy} onClick={copy} aria-label="Copy code">
        {copied ? <FiCheck /> : <FiCopy />}
      </button>
      <pre className={s.pre}>{children}</pre>
    </div>
  );
}

export function DocBody({ markdown }: { markdown: string }) {
  return (
    <div className={s.prose}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h2: ({ children }) => <h2 id={slugify(textOf(children))}>{children}</h2>,
          h3: ({ children }) => <h3 id={slugify(textOf(children))}>{children}</h3>,
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          a: ({ href, children }) => {
            const external = !!href && /^https?:\/\//.test(href) && !href.includes("calma1.vercel.app");
            return <a href={href} {...(external ? { target: "_blank", rel: "noreferrer" } : {})}>{children}</a>;
          },
          table: ({ children }) => <div className={s.tablewrap}><table>{children}</table></div>,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
