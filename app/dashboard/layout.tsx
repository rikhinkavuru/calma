import { getSession, getSignInUrl } from "@/lib/session";
import styles from "./dashboard.module.css";
import { Nav } from "./Nav";

export const dynamic = "force-dynamic";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();

  if (!session) {
    const url = await getSignInUrl();
    return (
      <div className={styles.signin}>
        <div className={styles.signinCard}>
          <h1>Calma console</h1>
          <p>Verify your AI-generated results — re-executed to ground truth.</p>
          {url ? (
            <a href={url} className={styles.btn}>Sign in with WorkOS</a>
          ) : (
            <p className={styles.hint}>
              Auth isn’t configured yet. Register the redirect URI in WorkOS and set
              <code> WORKOS_*</code> in <code>.env</code>, or set <code>DASHBOARD_DEV_TENANT_ID</code> for
              local dev.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.shell}>
      <Nav user={session.user} />
      {children}
    </div>
  );
}
