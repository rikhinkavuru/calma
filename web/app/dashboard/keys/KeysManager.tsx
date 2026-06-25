"use client";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ApiKey } from "@/lib/calma";
import { createKeyAction, revokeKeyAction } from "../actions";
import styles from "../dashboard.module.css";

export function KeysManager({ keys }: { keys: ApiKey[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [created, setCreated] = useState<{ token: string; prefix: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const create = () => {
    setError(null);
    start(async () => {
      try {
        const k = await createKeyAction("live");
        setCreated({ token: k.token, prefix: k.prefix });
        router.refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });
  };

  const revoke = (id: string) => {
    start(async () => {
      try { await revokeKeyAction(id); router.refresh(); }
      catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    });
  };

  return (
    <>
      <div className={styles.row}>
        <div>
          <h1 className={styles.h1}>API keys</h1>
          <p className={styles.sub}>Use a key to call the verifications API directly (CLI, CI, agents).</p>
        </div>
        <button className={styles.btn} onClick={create} disabled={pending}>+ Create key</button>
      </div>

      {error && <div className={`${styles.notice} ${styles.noticeErr}`}>{error}</div>}
      {created && (
        <div className={`${styles.notice} ${styles.noticeOk}`}>
          New key <strong>{created.prefix}</strong> — copy it now, it won’t be shown again:
          <div className={styles.keytoken} style={{ marginTop: 8 }}>{created.token}</div>
        </div>
      )}

      {keys.length === 0 ? (
        <div className={styles.card}><div className={styles.empty}><h3>No keys yet</h3><p>Create one to start calling the API.</p></div></div>
      ) : (
        <div className={styles.card}>
          <table className={styles.table}>
            <thead><tr><th>Key</th><th>Env</th><th>Last used</th><th>Created</th><th></th></tr></thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id}>
                  <td className={styles.mono}>{k.prefix}…{k.revoked && <span className={styles.muted}> (revoked)</span>}</td>
                  <td>{k.environment}</td>
                  <td className={styles.muted}>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
                  <td className={styles.muted}>{new Date(k.created_at).toLocaleDateString()}</td>
                  <td style={{ textAlign: "right" }}>
                    {!k.revoked && <button className={styles.btnDanger} onClick={() => revoke(k.id)} disabled={pending}>Revoke</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
