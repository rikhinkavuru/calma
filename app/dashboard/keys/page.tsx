import { calma, type ApiKey } from "@/lib/calma";
import { getSession } from "@/lib/session";
import styles from "../dashboard.module.css";
import { KeysManager } from "./KeysManager";

export const dynamic = "force-dynamic";

export default async function KeysPage() {
  const s = await getSession();
  if (!s) return null; // unauthenticated: the layout renders the sign-in gate
  let keys: ApiKey[] = [];
  let error: string | null = null;
  try {
    keys = (await calma.listKeys(s.tenantId)).data;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className={styles.main}>
      {error ? (
        <>
          <h1 className={styles.h1}>API keys</h1>
          <div className={`${styles.notice} ${styles.noticeErr}`}>{error}</div>
        </>
      ) : (
        <KeysManager keys={keys} />
      )}
    </div>
  );
}
