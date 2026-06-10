"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

export function useInView<T extends Element = HTMLDivElement>(threshold = 0.18) {
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
      { threshold, rootMargin: "0px 0px -5% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return [ref, seen] as const;
}

export function Reveal({
  children,
  delay = 0,
  className = "",
  style,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const [ref, seen] = useInView<HTMLDivElement>(0.15);
  return (
    <div
      ref={ref}
      className={"rv" + (seen ? " in" : "") + (className ? " " + className : "")}
      style={{ ...style, ["--d" as string]: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

/* the vast planet atmosphere — composed of blurred bands hugging one limb */
export function Atmo() {
  return (
    <div className="atmo" aria-hidden="true">
      <i className="glow-blue" />
      <i className="glow-teal" />
      <i className="glow-amber" />
      <i className="limb" />
      <i className="sun" />
    </div>
  );
}

export function Dots({ style }: { style?: CSSProperties }) {
  return <span className="dots" style={style} aria-hidden="true" />;
}

export function Cross({ style, className = "" }: { style?: CSSProperties; className?: string }) {
  return <span className={"cross " + className} style={style} aria-hidden="true" />;
}

/* thin line-icon glyphs for the specimen boxes */
export function Glyph({ kind }: { kind: "rerun" | "recompute" | "diff" | "decide" }) {
  if (kind === "rerun")
    return (
      <svg viewBox="0 0 16 16"><path d="M13 8a5 5 0 1 1-1.5-3.5M13 1.5V5h-3.5" /></svg>
    );
  if (kind === "recompute")
    return (
      <svg viewBox="0 0 16 16"><path d="M2 2h12M2 2l6 6-6 6M2 14h12" /></svg>
    );
  if (kind === "diff")
    return (
      <svg viewBox="0 0 16 16"><path d="M3 6h10M3 10h10M12 2 4 14" /></svg>
    );
  return (
    <svg viewBox="0 0 16 16"><path d="M1.5 1.5h13v13h-13zM4.5 8l2.5 2.5L11.5 5" /></svg>
  );
}

export function Nav({ onRequest }: { onRequest: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header className={"nav" + (scrolled ? " nav--bg" : "")}>
      <div className="wrap">
        <a className="nav__brand" href="#top">
          CALMA
        </a>
        <nav className="nav__links">
          <a href="#catch">The catch</a>
          <a href="#method">Method</a>
          <a href="#get">Get it</a>
          <button className="nav__cta" onClick={onRequest}>
            Request verification
          </button>
        </nav>
      </div>
    </header>
  );
}
