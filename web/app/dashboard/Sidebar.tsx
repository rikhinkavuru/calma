"use client";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { FiFileText, FiLogOut, FiExternalLink, FiCheckCircle } from "react-icons/fi";
import { GITHUB_URL } from "../../components/contact";
import styles from "./dashboard.module.css";

type NavItem = { href: string; label: string; icon: React.ReactNode; external?: boolean };
type NavGroup = { head?: string; items: NavItem[] };

const GROUPS: NavGroup[] = [
  {
    items: [{ href: "/dashboard", label: "Verify a repo", icon: <FiCheckCircle /> }],
  },
  {
    head: "Resources",
    items: [{ href: GITHUB_URL, label: "Docs", icon: <FiFileText />, external: true }],
  },
];

export function Sidebar({ user }: { user: { name: string; email: string; mode: "workos" | "dev" } }) {
  const path = usePathname();
  const isActive = (href: string) => (href === "/dashboard" ? path === href : path.startsWith(href));
  const initial = (user.name || user.email || "?").trim().charAt(0).toUpperCase();

  return (
    <aside className={styles.sidebar}>
      <Link href="/dashboard" className={styles.brand}>
        <Image src="/img/calma-lotus.png" alt="" width={26} height={26} className={styles.brandMark} />
        <span className={styles.brandName}>calma<span> / console</span></span>
      </Link>

      <nav className={styles.navgroups}>
        {GROUPS.map((g, gi) => (
          <div key={g.head ?? gi} className={styles.navgroup}>
            {g.head && <div className={styles.navhead}>{g.head}</div>}
            {g.items.map((it) => (
              <Link
                key={it.href}
                href={it.href}
                className={`${styles.navlink} ${!it.external && isActive(it.href) ? styles.navlinkActive : ""}`}
              >
                {it.icon}
                {it.label}
                {it.external && <FiExternalLink className={styles.navext} size={13} />}
              </Link>
            ))}
          </div>
        ))}
      </nav>

      <div className={styles.sidefoot}>
        <div className={styles.account}>
          <span className={styles.avatar}>{initial}</span>
          <div style={{ minWidth: 0 }}>
            <div className={styles.acctName}>{user.name}</div>
            <div className={styles.acctMeta}>{user.mode === "dev" ? "Dev session" : user.email}</div>
          </div>
          {user.mode === "workos" && (
            // POST (not a <Link>): a prefetched GET to /signout would silently log the user out.
            <form action="/dashboard/signout" method="post" style={{ margin: 0, marginLeft: "auto" }}>
              <button type="submit" className={styles.signout} title="Sign out" aria-label="Sign out">
                <FiLogOut />
              </button>
            </form>
          )}
        </div>
      </div>
    </aside>
  );
}
