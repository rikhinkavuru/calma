import { getUser } from "@/lib/session";
import { resolveTier, devCodeTierFromCookie } from "@/lib/tier";
import styles from "./dashboard.module.css";
import { LoginScreen } from "./LoginScreen";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export const dynamic = "force-dynamic";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  // getUser() is withAuth()-only (no tenant provision) so the shell paints instantly; the cold,
  // cross-service tenant resolution happens inside the page's Suspense boundary via getSession().
  const user = await getUser();

  if (!user) return <LoginScreen />;

  // resolve the display tier (respecting a dev-code elevation) so the console can show it + tier-aware UI.
  const tier = resolveTier(user, await devCodeTierFromCookie().catch(() => null));

  return (
    <div className={styles.shell}>
      <Sidebar user={user} />
      <div className={styles.content}>
        <Topbar user={user} tier={tier} />
        {children}
      </div>
    </div>
  );
}
