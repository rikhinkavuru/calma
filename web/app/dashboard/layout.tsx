import { getUser } from "@/lib/session";
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

  return (
    <div className={styles.shell}>
      <Sidebar user={user} />
      <div className={styles.content}>
        <Topbar user={user} />
        {children}
      </div>
    </div>
  );
}
