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
      { label: "The problem", href: "/#problem", ariaLabel: "The problem" },
      { label: "Features", href: "/#features", ariaLabel: "Features" },
      { label: "Benchmarks", href: "/#benchmarks", ariaLabel: "Benchmarks" },
    ],
  },
  {
    label: "Resources",
    bgColor: "#1a1610",
    textColor: "#e9ddc4",
    links: [
      { label: "Recipes", href: "/recipes", ariaLabel: "Recipes" },
      { label: "Registry", href: "/registry", ariaLabel: "Registry" },
      { label: "The lab", href: "/lab", ariaLabel: "The lab" },
    ],
  },
  {
    label: "Docs",
    bgColor: "#16130d",
    textColor: "#e9ddc4",
    links: [
      { label: "Docs", href: "/install", ariaLabel: "Docs" },
      { label: "GitHub", href: GITHUB_URL, ariaLabel: "Calma on GitHub" },
    ],
  },
];

export function SiteNav() {
  return (
    <CardNav
      logo="/img/calma-mark.svg"
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
