"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

/* Shared chrome: scroll-reveal choreography, counters, topbar, footer, section head. */

export function useInView<T extends Element = HTMLDivElement>(threshold = 0.25) {
  const ref = useRef<T | null>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold, rootMargin: "0px 0px -6% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return [ref, seen] as const;
}

/* Reveal: drop-in on scroll. dir = up | left | right | pop, delay staggers patterns. */
export function Reveal({
  children,
  dir = "up",
  delay = 0,
  as: Tag = "div",
  className = "",
  style,
}: {
  children: ReactNode;
  dir?: "up" | "left" | "right" | "pop";
  delay?: number;
  as?: "div" | "section" | "article" | "li";
  className?: string;
  style?: CSSProperties;
}) {
  const [ref, seen] = useInView<HTMLDivElement>(0.18);
  const dirClass = dir === "up" ? "" : dir === "left" ? " rv--l" : dir === "right" ? " rv--r" : " rv--pop";
  return (
    <Tag
      ref={ref as never}
      className={"rv" + dirClass + (seen ? " in" : "") + (className ? " " + className : "")}
      style={{ ...style, ["--d" as string]: `${delay}ms` }}
    >
      {children}
    </Tag>
  );
}

export function CountUp({ to, dur = 1100 }: { to: number; dur?: number }) {
  const [ref, seen] = useInView<HTMLSpanElement>(0.6);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!seen) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setN(to);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / dur);
      setN(Math.round(to * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [seen, to, dur]);
  return <span ref={ref}>{n.toLocaleString()}</span>;
}

export function Topbar({ onRequest }: { onRequest: () => void }) {
  return (
    <div className="topbar">
      <div className="wrap">
        <a className="brand" href="#top">
          Calma<span className="tm">.</span>
        </a>
        <nav className="topnav">
          <a href="#catch">The catch</a>
          <a href="#how">How it works</a>
          <a href="#verdicts">Verdicts</a>
          <a href="#get">Get Calma</a>
          <button className="btn btn--solid" onClick={onRequest}>
            Request verification
          </button>
        </nav>
      </div>
    </div>
  );
}

export function SectionHead({
  idx,
  title,
  sub,
}: {
  idx: string;
  title: ReactNode;
  sub?: ReactNode;
}) {
  return (
    <Reveal className="sec-head">
      <span className="idx mono">{idx}</span>
      <h2>{title}</h2>
      {sub && <p>{sub}</p>}
    </Reveal>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap">
        <a className="brand" href="#top">
          Calma<span className="tm">.</span>
        </a>
        <div className="footer__links">
          <a href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
            GitHub
          </a>
          <a href="https://github.com/rikhinkavuru/calma/blob/main/README.md" target="_blank" rel="noreferrer">
            Docs
          </a>
          <a href="https://github.com/rikhinkavuru/calma/blob/main/LICENSE" target="_blank" rel="noreferrer">
            MIT
          </a>
        </div>
        <span className="footer__motto">the producer is never the verifier</span>
      </div>
    </footer>
  );
}
