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

export function Cross({ style, className = "" }: { style?: CSSProperties; className?: string }) {
  return <span className={"cross " + className} style={style} aria-hidden="true" />;
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
          <a href="#problem">The problem</a>
          <a href="#overview">How it works</a>
          <a href="#features">Features</a>
          <a href="#benefits">Who it&apos;s for</a>
          <a href="#about">About</a>
          <button className="nav__cta" onClick={onRequest}>
            Request verification
          </button>
        </nav>
      </div>
    </header>
  );
}
