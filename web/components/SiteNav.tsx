"use client";

import dynamic from "next/dynamic";
import type { CardNavItem } from "./CardNav";
import { GITHUB_URL } from "./contact";

/* CardNav (gsap + window) — client-only. One shared nav across every page so
   the landing and all subpages carry the same chrome. */
const CardNav = dynamic(() => import("./CardNav"), { ssr: false });

const NAV_ITEMS: CardNavItem[] = [
  {
    label: "Explore",
    bgColor: "#16130d",
    textColor: "#e9ddc4",
    links: [
      { label: "How it works", href: "/#flow", ariaLabel: "How it works" },
      { label: "Features", href: "/#features", ariaLabel: "Features" },
      { label: "FAQ", href: "/#faq", ariaLabel: "Frequently asked questions" },
    ],
  },
  {
    label: "Product",
    bgColor: "#1a1610",
    textColor: "#e9ddc4",
    links: [
      { label: "Verify a repo", href: "/dashboard", ariaLabel: "Open the verify dashboard" },
      { label: "Pricing", href: "/pricing", ariaLabel: "Pricing" },
    ],
  },
  {
    label: "Docs",
    bgColor: "#16130d",
    textColor: "#e9ddc4",
    links: [
      { label: "Docs", href: GITHUB_URL, ariaLabel: "Docs (GitHub README)" },
      { label: "Try the demo", href: "/demo", ariaLabel: "Try the live demo, no signup" },
      { label: "GitHub", href: GITHUB_URL, ariaLabel: "Calma on GitHub" },
    ],
  },
];

export function SiteNav() {
  return (
    <CardNav
      logo="/img/calma-lotus.png"
      logoAlt="Calma"
      items={NAV_ITEMS}
      baseColor="rgba(13,11,8,0.9)"
      menuColor="#e9ddc4"
      buttonBgColor="#e89a5d"
      buttonTextColor="#0d0b08"
    />
  );
}

export default SiteNav;
