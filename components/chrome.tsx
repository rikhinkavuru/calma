"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { motion } from "framer-motion";
import { GITHUB_URL } from "./contact";

const EASE = [0.22, 1, 0.36, 1] as const;

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
  return (
    <motion.div
      className={"rv" + (className ? " " + className : "")}
      style={style}
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -8% 0px" }}
      transition={{ duration: 0.7, ease: EASE, delay: delay / 1000 }}
    >
      {children}
    </motion.div>
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

function Burger({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      className="nav__burger"
      aria-label={open ? "Close menu" : "Open menu"}
      aria-expanded={open}
      onClick={onToggle}
    >
      <span aria-hidden="true">{open ? "✕" : "☰"}</span>
    </button>
  );
}

/* THE nav — one component, one set of links, one CTA, mounted on every page.
   Anchors are absolute so they resolve from any route; the background fades in
   on scroll identically everywhere. Any per-page nav variant is a bug. */
const NAV_LINKS: { href: string; label: string }[] = [
  { href: "/#problem", label: "The problem" },
  { href: "/#benchmarks", label: "Benchmarks" },
  { href: "/#features", label: "Features" },
  { href: "/recipes", label: "Recipes" },
  { href: "/registry", label: "Registry" },
  { href: "/lab", label: "The lab" },
];

export function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [menu, setMenu] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const close = () => setMenu(false);
  const cta = (
    <a
      className="nav__cta"
      href={GITHUB_URL}
      target="_blank"
      rel="noreferrer"
      onClick={close}
    >
      Get the free skill
    </a>
  );
  return (
    <header className={"nav" + (scrolled || menu ? " nav--bg" : "")}>
      <div className="wrap">
        <a className="nav__brand" href="/">
          CALMA
        </a>
        <nav className="nav__links">
          {NAV_LINKS.map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
          {cta}
        </nav>
        <Burger open={menu} onToggle={() => setMenu((m) => !m)} />
      </div>
      {menu && (
        <nav className="nav__menu">
          {NAV_LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={close}>
              {l.label}
            </a>
          ))}
          {cta}
        </nav>
      )}
    </header>
  );
}
