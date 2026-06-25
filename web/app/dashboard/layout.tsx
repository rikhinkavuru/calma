import { redirect } from "next/navigation";
import { getSession, getSignInUrl } from "@/lib/session";
import styles from "./dashboard.module.css";
import { Nav } from "./Nav";

export const dynamic = "force-dynamic";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();

  if (!session) {
    // getSignInUrl() sets a PKCE/state cookie, which is only allowed in a Server Action / Route Handler —
    // NOT during a Server Component render. So the sign-in runs as a form Server Action that redirects.
    async function signIn() {
      "use server";
      const url = await getSignInUrl();
      if (url) redirect(url);
    }
    return (
      <div className={styles.signin}>
        <div className={styles.signinCard}>
          <h1>Calma console</h1>
          <p>Verify your AI-generated results — re-executed to ground truth.</p>
          <form action={signIn}>
            <button type="submit" className={styles.btn}>Sign in with WorkOS</button>
          </form>
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
