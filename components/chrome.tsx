"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/* Shared chrome: the star glyph, section scaffolding, in-view hook. */

export function StarGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 240 240" aria-hidden="true" className={className}>
      <path
        d="M120 8 C128 92 148 112 232 120 C148 128 128 148 120 232 C112 148 92 128 8 120 C92 112 112 92 120 8 Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function PixelBlock() {
  return (
    <svg viewBox="0 0 160 44" aria-hidden="true">
      <g fill="#141310">
        <rect x="0" y="6" width="14" height="14" /><rect x="18" y="0" width="10" height="10" />
        <rect x="14" y="24" width="20" height="10" /><rect x="38" y="10" width="10" height="20" />
        <rect x="52" y="2" width="14" height="14" /><rect x="58" y="22" width="10" height="14" />
        <rect x="74" y="8" width="22" height="10" /><rect x="80" y="24" width="10" height="12" />
        <rect x="102" y="0" width="10" height="22" /><rect x="100" y="28" width="20" height="8" />
        <rect x="124" y="6" width="14" height="14" /><rect x="130" y="26" width="10" height="10" />
        <rect x="146" y="2" width="10" height="32" />
      </g>
    </svg>
  );
}

export function GlobeEye({ width = 130 }: { width?: number }) {
  return (
    <svg viewBox="0 0 240 120" aria-hidden="true" style={{ width }}>
      <ellipse cx="120" cy="60" rx="112" ry="44" fill="none" stroke="#141310" strokeWidth="1.5" />
      <circle cx="120" cy="60" r="34" fill="none" stroke="#141310" strokeWidth="1.5" />
      <ellipse cx="120" cy="60" rx="13" ry="34" fill="none" stroke="#141310" strokeWidth="1.5" />
      <ellipse cx="120" cy="60" rx="26" ry="34" fill="none" stroke="#141310" strokeWidth="1.5" />
      <line x1="86" y1="60" x2="154" y2="60" stroke="#141310" strokeWidth="1.5" />
    </svg>
  );
}

export function SectionHead({
  num,
  title,
  note,
}: {
  num: string;
  title: string;
  note: string;
}) {
  return (
    <div className="section__head">
      <div>
        <div className="section__num">{num}</div>
        <h2 className="section__title">{title}</h2>
      </div>
      <p className="section__note">{note}</p>
    </div>
  );
}

export function useInView<T extends Element = HTMLDivElement>(threshold = 0.35) {
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
      { threshold }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return [ref, seen] as const;
}

export function CountUp({ to, dur = 1100, suffix = "" }: { to: number; dur?: number; suffix?: string }) {
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
  return (
    <span ref={ref}>
      {n.toLocaleString()}
      {suffix}
    </span>
  );
}

export function Topbar() {
  return (
    <div className="topbar">
      <div className="wrap">
        <div className="topbar__id">
          <span className="mark-mini">
            <StarGlyph />
            CALMA<sup>®</sup>
          </span>
          <span className="dim">Verification Lab / V0.3</span>
        </div>
        <div className="topbar__meta">
          <a href="#claim">The claim</a>
          <a href="#method">Method</a>
          <a href="#evidence">Evidence</a>
          <a href="#access">Access</a>
          <span className="ticks" aria-hidden="true">
            <i></i><i></i><i></i><i></i><i></i><i></i>
          </span>
        </div>
      </div>
    </div>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap">
        <span className="mark-mini">
          <StarGlyph />
          CALMA<sup>®</sup>
        </span>
        <span className="barcode" style={{ maxWidth: 220, height: 40 }} aria-hidden="true"></span>
        <span className="footer__end">
          <a href="https://github.com/rikhinkavuru/calma" target="_blank" rel="noreferrer">
            GitHub
          </a>
          {"  ·  MIT  ·  the producer is never the verifier"}
        </span>
      </div>
    </footer>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <span className="eyebrow">{children}</span>;
}
