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

export function CountUp({ to, dur = 1100, decimals = 0 }: { to: number; dur?: number; decimals?: number }) {
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
      setN(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [seen, to, dur]);
  return <span ref={ref}>{n.toLocaleString(undefined, { maximumFractionDigits: decimals, minimumFractionDigits: decimals })}</span>;
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <span className="eyebrow">{children}</span>;
}

export function CropFrame({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={"cropframe " + className}>
      <i aria-hidden="true" />
      <i aria-hidden="true" />
      <i aria-hidden="true" />
      <i aria-hidden="true" />
      {children}
    </div>
  );
}

/* the + / ≡ corner ornaments 24labs hangs on section rails */
export function Orns({ top = "50%" }: { top?: string }) {
  return (
    <>
      <div className="orn" style={{ top }} aria-hidden="true">
        <span>+</span>
        <span>≡</span>
      </div>
      <div className="orn orn--r" style={{ top }} aria-hidden="true">
        <span>+</span>
        <span>≡</span>
      </div>
    </>
  );
}

export function Nav({ onRequest }: { onRequest: () => void }) {
  return (
    <header className="nav">
      <div className="wrap">
        <a className="nav__brand" href="#top">
          Calma
        </a>
        <nav className="nav__pill">
          <a href="#catch">The catch</a>
          <span className="x" aria-hidden="true">✕</span>
          <a href="#money">The stakes</a>
          <span className="x" aria-hidden="true">✕</span>
          <a href="#verdicts">Verdicts</a>
          <span className="x" aria-hidden="true">✕</span>
          <a href="#get">Get Calma</a>
          <button className="nav__cta" onClick={onRequest}>
            Request Verification
          </button>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap">
        <div className="footer__grid">
          <div className="footer__word">
            <span className="serif-acc">proof</span>@
            <br />
            before.money
            <small>
              Calma re-executes AI&apos;s work and recomputes the number — the verdict is computed by
              code.
            </small>
          </div>
          <div className="footer__nav">
            <span className="h mono">Navigate</span>
            <a href="#catch">The catch</a>
            <a href="#money">The stakes</a>
            <a href="#verdicts">Verdicts</a>
            <a href="#get">Get Calma</a>
          </div>
          <div className="footer__nav">
            <span className="h mono">Open source</span>
            <a href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
              GitHub
            </a>
            <a href="https://github.com/rikhinkavuru/calma/blob/main/README.md" target="_blank" rel="noreferrer">
              Docs
            </a>
            <a href="https://github.com/rikhinkavuru/calma/blob/main/LICENSE" target="_blank" rel="noreferrer">
              MIT License
            </a>
          </div>
        </div>
        <div className="footer__base">
          <span>© 2026 Calma</span>
          <span>/// the producer is never the verifier &gt;&gt;&gt;</span>
        </div>
      </div>
    </footer>
  );
}
