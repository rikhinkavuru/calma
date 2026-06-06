"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/* Section eyebrow: 01 / PROVENANCE */
export function Eyebrow({ num, children }: { num?: string; children: ReactNode }) {
  return (
    <div className="eyebrow">
      {num && <span className="num">{num}</span>}
      <span>{children}</span>
    </div>
  );
}

/* A full-bleed hairline that respects the wrap gutters */
export function Rule({ inset }: { inset?: boolean }) {
  return <hr className="rule" style={inset ? {} : { marginInline: 0 }} />;
}

type SectionProps = {
  id?: string;
  label?: string;
  num?: string;
  title?: ReactNode;
  intro?: ReactNode;
  children?: ReactNode;
  tight?: boolean;
  bg?: "tint" | "deep";
  watermark?: string;
};

/* Section scaffold with consistent vertical rhythm + top hairline */
export function Section({ id, label, num, title, intro, children, tight, bg, watermark }: SectionProps) {
  return (
    <section id={id} className={"sec " + (bg ? "sec--" + bg : "")}>
      {watermark && (
        <span className="sec__wm mono" aria-hidden="true">
          {watermark}
        </span>
      )}
      <div className="wrap sec__wrap" style={{ paddingBlock: tight ? "76px" : "112px" }}>
        {(label || title) && (
          <div className="sec-head">
            {label && <Eyebrow num={num}>{label}</Eyebrow>}
            {title && <h2 className="sec-title">{title}</h2>}
            {intro && <p className="sec-intro">{intro}</p>}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}

/* Small monospace status pill */
export function Pill({ tone, children }: { tone?: "pass" | "fail" | "neutral"; children: ReactNode }) {
  const map = {
    pass: { color: "var(--pass)", bg: "var(--pass-bg)" },
    fail: { color: "var(--fail)", bg: "var(--fail-bg)" },
    neutral: { color: "var(--ink-2)", bg: "var(--paper-3)" },
  };
  const s = map[tone || "neutral"];
  return (
    <span className="pill mono" style={{ color: s.color, background: s.bg }}>
      {children}
    </span>
  );
}

/* Animated count-up trigger when scrolled into view */
export function useInView<T extends Element = HTMLElement>(opts?: IntersectionObserverInit) {
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
      opts || { threshold: 0.35 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [opts]);
  return [ref, seen] as const;
}

/* Inline arrow glyph */
export function Arrow() {
  return (
    <span className="arrow" aria-hidden="true">
      →
    </span>
  );
}
