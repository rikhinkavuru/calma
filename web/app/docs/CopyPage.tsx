"use client";

// The OpenRouter-style "Copy page" control. Copies the page as Markdown for LLMs, opens the plain-markdown
// view, or opens ChatGPT / Claude / Perplexity with a prompt already typed — pointing the model at this
// page's .md so it can answer questions about it. URL schemes are the ones OpenRouter/Mintlify ship in prod.
import { useEffect, useRef, useState } from "react";
import { FiCopy, FiCheck, FiChevronDown, FiFileText, FiArrowUpRight } from "react-icons/fi";
import s from "./docs.module.css";

// prompt "Read from <url> so I can ask questions about it." — ChatGPT gets the page URL (+ search hint),
// the others get the .md (they fetch it directly).
function llmLinks(pageUrl: string, mdUrl: string) {
  const q = (t: string) => encodeURIComponent(`Read from ${t} so I can ask questions about it.`);
  return [
    { key: "chatgpt", label: "Open in ChatGPT", href: `https://chat.openai.com/?hints=search&q=${q(pageUrl)}` },
    { key: "claude", label: "Open in Claude", href: `https://claude.ai/new?q=${q(mdUrl)}` },
    { key: "perplexity", label: "Open in Perplexity", href: `https://www.perplexity.ai/search?q=${q(mdUrl)}` },
  ];
}

const LOGO: Record<string, React.ReactNode> = {
  chatgpt: <span className={`${s.llmDot} ${s.llmGpt}`} aria-hidden />,
  claude: <span className={`${s.llmDot} ${s.llmClaude}`} aria-hidden />,
  perplexity: <span className={`${s.llmDot} ${s.llmpplx}`} aria-hidden />,
};

export function CopyPage({ slug, markdown }: { slug: string; markdown: string }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onEsc); };
  }, [open]);

  const copy = async () => {
    try { await navigator.clipboard.writeText(markdown); setCopied(true); setTimeout(() => setCopied(false), 1800); }
    catch { /* clipboard blocked */ }
  };

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const pageUrl = `${origin}/docs/${slug}`;
  const mdUrl = `${pageUrl}.md`;
  const links = llmLinks(pageUrl, mdUrl);

  return (
    <div className={s.copywrap} ref={ref}>
      <button className={s.copybtn} onClick={copy} title="Copy this page as Markdown for an LLM">
        {copied ? <FiCheck /> : <FiCopy />} {copied ? "Copied" : "Copy page"}
      </button>
      <button
        className={s.copycaret}
        aria-label="More copy options"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <FiChevronDown style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .15s" }} />
      </button>

      {open && (
        <div className={s.copymenu} role="menu">
          <button className={s.copyitem} role="menuitem" onClick={() => { copy(); setOpen(false); }}>
            <FiCopy className={s.copyitemIcon} />
            <span><b>Copy page</b><small>Copy this page as Markdown for LLMs</small></span>
          </button>
          <a className={s.copyitem} role="menuitem" href={mdUrl} target="_blank" rel="noreferrer" onClick={() => setOpen(false)}>
            <FiFileText className={s.copyitemIcon} />
            <span><b>View as Markdown <FiArrowUpRight className={s.ext} /></b><small>Open this page as plain text</small></span>
          </a>
          <div className={s.copydiv} />
          {links.map((l) => (
            <a key={l.key} className={s.copyitem} role="menuitem" href={l.href} target="_blank" rel="noreferrer" onClick={() => setOpen(false)}>
              {LOGO[l.key]}
              <span><b>{l.label} <FiArrowUpRight className={s.ext} /></b><small>Ask questions about this page</small></span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
