"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
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
  // Replaces the old global <MotionConfig reducedMotion="user">: when the user prefers reduced motion,
  // render the content in its final visible state with no entrance animation.
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={"rv" + (className ? " " + className : "")}
      style={style}
      initial={reduce ? false : { opacity: 0, y: 18 }}
      whileInView={reduce ? undefined : { opacity: 1, y: 0 }}
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
type NavLink = { href: string; label: string };
const PRIMARY_LINKS: NavLink[] = [
  { href: "/#problem", label: "The problem" },
  { href: "/#features", label: "Features" },
];
const RESOURCE_LINKS: NavLink[] = [
  { href: "/recipes", label: "Recipes" },
  { href: "/registry", label: "Registry" },
  { href: "/lab", label: "The lab" },
];
const DOCS_LINK: NavLink = { href: "/install", label: "Docs" };

function Caret() {
  return (
    <svg className="nav__caret" viewBox="0 0 10 6" aria-hidden="true">
      <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

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
      Star the repo
    </a>
  );
  return (
    <header className={"nav" + (scrolled || menu ? " nav--bg" : "")}>
      <div className="wrap">
        <Link className="nav__brand" href="/">
          CALMA
        </Link>
        <nav className="nav__links">
          {PRIMARY_LINKS.map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
          <div className="nav__drop">
            <button type="button" className="nav__droptrigger" aria-haspopup="true">
              Resources <Caret />
            </button>
            <div className="nav__dropmenu" role="menu">
              {RESOURCE_LINKS.map((l) => (
                <a key={l.href} href={l.href} role="menuitem">
                  {l.label}
                </a>
              ))}
            </div>
          </div>
          <a href={DOCS_LINK.href}>{DOCS_LINK.label}</a>
        </nav>
        <div className="nav__right">
          {cta}
          <Burger open={menu} onToggle={() => setMenu((m) => !m)} />
        </div>
      </div>
      {menu && (
        <nav className="nav__menu">
          {PRIMARY_LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={close}>
              {l.label}
            </a>
          ))}
          <span className="nav__menugroup">Resources</span>
          {RESOURCE_LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={close} className="nav__menusub">
              {l.label}
            </a>
          ))}
          <a href={DOCS_LINK.href} onClick={close}>
            {DOCS_LINK.label}
          </a>
          {cta}
        </nav>
      )}
    </header>
  );
}
