"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./dashboard.module.css";

const LINKS = [
  { href: "/dashboard", label: "Verifications" },
  { href: "/dashboard/submit", label: "Submit" },
  { href: "/dashboard/keys", label: "API keys" },
];

export function Nav({ user }: { user: { name: string; email: string; mode: "workos" | "dev" } }) {
  const path = usePathname();
  const isActive = (href: string) => (href === "/dashboard" ? path === href : path.startsWith(href));
  return (
    <nav className={styles.nav}>
      <Link href="/dashboard" className={styles.brand}>calma<span> / console</span></Link>
      <div className={styles.navlinks}>
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href}
                className={`${styles.navlink} ${isActive(l.href) ? styles.navlinkActive : ""}`}>
            {l.label}
          </Link>
        ))}
      </div>
      <div className={styles.navright}>
        {user.mode === "dev" && <span className={styles.devpill}>DEV SESSION</span>}
        <span>{user.name}</span>
        {user.mode === "workos" && (
          // POST (not a <Link>): a prefetched GET to /dashboard/signout would silently log the user out.
          <form action="/dashboard/signout" method="post" style={{ margin: 0 }}>
            <button type="submit" className={styles.navlink}
                    style={{ background: "none", border: "none", padding: 0, cursor: "pointer", font: "inherit" }}>
              Sign out
            </button>
          </form>
        )}
      </div>
    </nav>
  );
}
