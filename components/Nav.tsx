"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { hoverLift } from "./motion";

export function Nav({ onRequest }: { onRequest: () => void }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const links: [string, string][] = [
    ["The problem", "#problem"],
    ["How it works", "#how"],
    ["Roadmap", "#roadmap"],
    ["Independence", "#independence"],
  ];
  return (
    <header className={"nav" + (scrolled ? " nav--scrolled" : "")}>
      <div className="wrap nav__inner">
        <a href="#top" className="brand" aria-label="Calma — home">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__word">
            calma<sub className="brand__beta mono">beta</sub>
          </span>
        </a>
        <nav className="nav__links">
          {links.map(([label, href]) => (
            <a key={href} href={href}>
              {label}
            </a>
          ))}
        </nav>
        <div className="nav__right">
          <motion.button className="btn btn-primary nav__cta" onClick={onRequest} {...hoverLift}>
            Request access
          </motion.button>
        </div>
      </div>
    </header>
  );
}
