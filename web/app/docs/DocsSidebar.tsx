"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { FiMenu, FiX } from "react-icons/fi";
import { docsByGroup } from "./content";
import s from "./docs.module.css";

export function DocsSidebar() {
  const path = usePathname();
  const groups = docsByGroup();
  const [open, setOpen] = useState(false);

  const nav = (
    <nav className={s.navgroups}>
      {groups.map(({ group, pages }) => (
        <div key={group} className={s.navgroup}>
          <div className={s.navhead}>{group}</div>
          {pages.map((p) => {
            const href = `/docs/${p.slug}`;
            const active = path === href;
            return (
              <Link key={p.slug} href={href} className={`${s.navlink} ${active ? s.navlinkActive : ""}`}
                onClick={() => setOpen(false)}>
                {p.title}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );

  return (
    <>
      {/* mobile toggle */}
      <button className={s.navToggle} onClick={() => setOpen((v) => !v)} aria-label="Toggle docs navigation">
        {open ? <FiX /> : <FiMenu />} Docs menu
      </button>
      <aside className={`${s.sidebar} ${open ? s.sidebarOpen : ""}`}>
        <Link href="/" className={s.brand}>
          <Image src="/img/calma-lotus.png" alt="" width={24} height={24} className={s.brandMark} />
          <span className={s.brandName}>calma<span> / docs</span></span>
        </Link>
        {nav}
      </aside>
    </>
  );
}
