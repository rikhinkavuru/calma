"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

export function useInView<T extends Element = HTMLDivElement>(threshold = 0.2) {
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

export function Reveal({
  children,
  dir = "up",
  delay = 0,
  className = "",
  style,
}: {
  children: ReactNode;
  dir?: "up" | "left" | "right" | "pop";
  delay?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const [ref, seen] = useInView<HTMLDivElement>(0.15);
  const dirClass = dir === "up" ? "" : dir === "left" ? " rv--l" : dir === "right" ? " rv--r" : " rv--pop";
  return (
    <div
      ref={ref}
      className={"rv" + dirClass + (seen ? " in" : "") + (className ? " " + className : "")}
      style={{ ...style, ["--d" as string]: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

export function Nav({ onRequest }: { onRequest: () => void }) {
  return (
    <header className="nav">
      <div className="wrap">
        <a className="nav__brand" href="#top">
          Calma
        </a>
        <nav className="nav__links">
          <a href="#catch">The catch</a>
          <a href="#how">How it works</a>
          <a href="#get">Get Calma</a>
          <button className="btn btn--blue btn--sm" onClick={onRequest}>
            Request verification
          </button>
        </nav>
      </div>
    </header>
  );
}

export function Footer({ onRequest }: { onRequest: () => void }) {
  return (
    <footer className="footer">
      <div className="wrap">
        <div className="footer__word">
          Proof, <span className="serif">before</span> the money moves.
        </div>
        <div className="footer__cta">
          <a
            className="btn btn--blue"
            href="https://github.com/rikhinkavuru/calma"
            target="_blank"
            rel="noreferrer"
          >
            Get the free skill →
          </a>
          <button className="btn btn--ghostwhite" onClick={onRequest}>
            Request verification
          </button>
        </div>
        <div className="footer__grid">
          <span className="footer__brand">Calma</span>
          <div className="footer__links">
            <a href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
              GitHub
            </a>
            <a
              href="https://github.com/rikhinkavuru/calma/blob/main/README.md"
              target="_blank"
              rel="noreferrer"
            >
              Docs
            </a>
            <a
              href="https://github.com/rikhinkavuru/calma/blob/main/LICENSE"
              target="_blank"
              rel="noreferrer"
            >
              MIT License
            </a>
          </div>
        </div>
        <div className="footer__base">
          <span>© 2026 Calma</span>
          <span>The producer is never the verifier.</span>
        </div>
      </div>
    </footer>
  );
}
