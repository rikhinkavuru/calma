"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { RequestDialog } from "./RequestDialog";

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

export function Nav({ onRequest }: { onRequest: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  const [menu, setMenu] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const close = () => setMenu(false);
  return (
    <header className={"nav" + (scrolled || menu ? " nav--bg" : "")}>
      <div className="wrap">
        <a className="nav__brand" href="#top">
          CALMA
        </a>
        <nav className="nav__links">
          <a href="#problem">The problem</a>
          <a href="#overview">How it works</a>
          <a href="#features">Features</a>
          <a href="/recipes">Recipes</a>
          <a href="/registry">Registry</a>
          <a href="/lab">The lab</a>
          <button className="nav__cta" onClick={onRequest}>
            Request verification
          </button>
        </nav>
        <Burger open={menu} onToggle={() => setMenu((m) => !m)} />
      </div>
      {menu && (
        <nav className="nav__menu">
          <a href="#problem" onClick={close}>The problem</a>
          <a href="#overview" onClick={close}>How it works</a>
          <a href="#features" onClick={close}>Features</a>
          <a href="/recipes" onClick={close}>Recipes</a>
          <a href="/registry" onClick={close}>Registry</a>
          <a href="/lab" onClick={close}>The lab</a>
          <button
            className="nav__cta"
            onClick={() => {
              close();
              onRequest();
            }}
          >
            Request verification
          </button>
        </nav>
      )}
    </header>
  );
}

/* Every page shows the same quick links — a missing nav item on a sub-page reads
   as a bug. Anchors are absolute so they work from any route. */
export const NAV_LINKS: { href: string; label: string }[] = [
  { href: "/#problem", label: "The problem" },
  { href: "/#overview", label: "How it works" },
  { href: "/#features", label: "Features" },
  { href: "/recipes", label: "Recipes" },
  { href: "/registry", label: "Registry" },
  { href: "/lab", label: "The lab" },
];

/* Shared sub-page header: same chrome, takes plain links (server-page safe).
   CTA: pass onCta (client pages with their own dialog), or set requestDialog
   to let SubNav own a RequestDialog itself (server pages). */
export function SubNav({
  links = NAV_LINKS,
  onCta,
  requestDialog = false,
  ctaLabel = "Request verification",
}: {
  links?: { href: string; label: string }[];
  onCta?: () => void;
  requestDialog?: boolean;
  ctaLabel?: string;
}) {
  const [menu, setMenu] = useState(false);
  const [dlg, setDlg] = useState(false);
  const close = () => setMenu(false);
  const handleCta = onCta ?? (requestDialog ? () => setDlg(true) : undefined);
  const cta = handleCta ? (
    <button className="nav__cta" onClick={() => { close(); handleCta(); }}>
      {ctaLabel}
    </button>
  ) : null;
  return (
    <header className="nav nav--bg">
      <div className="wrap">
        <a className="nav__brand" href="/">
          CALMA
        </a>
        <nav className="nav__links">
          {links.map((l) => (
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
          {links.map((l) => (
            <a key={l.href} href={l.href} onClick={close}>
              {l.label}
            </a>
          ))}
          {cta}
        </nav>
      )}
      {requestDialog && <RequestDialog open={dlg} onClose={() => setDlg(false)} />}
    </header>
  );
}
