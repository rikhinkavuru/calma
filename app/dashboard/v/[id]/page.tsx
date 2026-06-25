import crypto from "crypto";
import Link from "next/link";
import { calma, type Verification } from "@/lib/calma";
import { getSession } from "@/lib/session";
import { StatusBadge, VerdictBadge } from "../../Badge";
import styles from "../../dashboard.module.css";

export const dynamic = "force-dynamic";

// Pinned control-plane proof-signing public key (source of truth: control_plane/signing_pubkey.json).
// Verifying here proves the proof was signed by Calma's key — not just that the envelope claims a signature.
const PINNED_PUBKEY_B64 = "TY0kvWBGY+henz1JF2OfnFhA/gDJDNLxsxwDNB4+z0U=";

type Dsse = { payloadType: string; payload: string; signatures: { keyid: string; sig: string }[] };

function isEnvelope(p: unknown): p is Dsse {
  const e = p as Dsse;
  return !!e && typeof e.payloadType === "string" && typeof e.payload === "string" && Array.isArray(e.signatures);
}

// DSSE PAE, byte-identical to control_plane/api/signing.py::_pae
function pae(payloadType: string, payload: Buffer): Buffer {
  const pt = Buffer.from(payloadType, "ascii");
  return Buffer.concat([
    Buffer.from(`DSSEv1 ${pt.length} `, "ascii"), pt,
    Buffer.from(` ${payload.length} `, "ascii"), payload,
  ]);
}

function verifyEnvelope(env: Dsse): boolean {
  try {
    const raw = Buffer.from(PINNED_PUBKEY_B64, "base64"); // 32-byte ed25519 key
    const der = Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), raw]); // SPKI wrapper
    const pub = crypto.createPublicKey({ key: der, format: "der", type: "spki" });
    const msg = pae(env.payloadType, Buffer.from(env.payload, "base64"));
    return (env.signatures || []).some((s) =>
      crypto.verify(null, msg, pub, Buffer.from(s.sig, "base64")));
  } catch {
    return false;
  }
}

export default async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const s = await getSession();
  if (!s) return null; // unauthenticated: the layout renders the sign-in gate
  let v: Verification | null = null;
  let proof: Record<string, unknown> | null = null;
  let error: string | null = null;
  try {
    v = await calma.getVerification(s.tenantId, id);
    try { proof = await calma.getProof(s.tenantId, id); } catch { /* proof may not exist yet */ }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error || !v) {
    return (
      <div className={styles.main}>
        <Link href="/dashboard" className={styles.back}>← Verifications</Link>
        <div className={`${styles.notice} ${styles.noticeErr}`} style={{ marginTop: 16 }}>{error || "Not found"}</div>
      </div>
    );
  }

  const r = v.recomputed || {};
  const ex = v.execution || {};
  // proof is a DSSE envelope: verify the signature against the pinned key, then show the decoded evidence.
  const env = isEnvelope(proof) ? proof : null;
  const sigVerified = env ? verifyEnvelope(env) : false;
  const sigKeyid = env?.signatures?.[0]?.keyid;
  const signed = !!env && env.signatures.length > 0;
  const evidence: unknown = env
    ? JSON.parse(Buffer.from(env.payload, "base64").toString("utf-8"))
    : proof;
  return (
    <div className={styles.main}>
      <Link href="/dashboard" className={styles.back}>← Verifications</Link>
      <div className={styles.row} style={{ marginTop: 14 }}>
        <div>
          <h1 className={styles.h1}>{v.recipe.id} <span className={styles.muted}>@{v.recipe.version}</span></h1>
          <p className={styles.sub}><span className={styles.mono}>{v.verification_id}</span></p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <VerdictBadge verdict={v.verdict} />
          <StatusBadge status={v.status} />
        </div>
      </div>

      <div className={styles.detailGrid}>
        <div className={styles.kv}>
          <div className={styles.kvLabel}>Claimed{v.claim?.metric ? ` · ${v.claim.metric}` : ""}</div>
          <div className={styles.kvValue}>{v.claim?.value ?? "—"}</div>
        </div>
        <div className={styles.kv}>
          <div className={styles.kvLabel}>Recomputed (ground truth)</div>
          <div className={styles.kvValue}>{r.value ?? "—"}</div>
        </div>
        <div className={styles.kv}>
          <div className={styles.kvLabel}>Absolute difference</div>
          <div className={styles.kvValue}>{r.abs_diff ?? "—"}</div>
        </div>
        <div className={styles.kv}>
          <div className={styles.kvLabel}>Within tolerance</div>
          <div className={styles.kvValue}>{r.within_tolerance === undefined ? "—" : r.within_tolerance ? "yes" : "no"}</div>
        </div>
      </div>

      {v.reason && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Reason</div>
          <div className={styles.pre}>{v.reason}</div>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionTitle}>Execution</div>
        <div className={styles.pre}>
          isolation_tier : {ex.isolation_tier || "—"}{"\n"}
          tier_verified  : {String(ex.tier_verified)}{"\n"}
          network_run    : {ex.network_run || "—"}{"\n"}
          determinism    : {ex.determinism_mode || "—"}
        </div>
      </div>

      {v.validity && Object.keys(v.validity).length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Validity</div>
          <div className={styles.pre}>{JSON.stringify(v.validity, null, 2)}</div>
        </div>
      )}

      {proof && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Proof signature</div>
          <div className={styles.pre}>
            {signed
              ? `${sigVerified ? "✓ VERIFIED" : "✗ SIGNATURE INVALID"} — ed25519 · keyid ${sigKeyid}\n` +
                `signed by the Calma control-plane; verify offline: python control_plane/verify_proof.py proof.json`
              : "unsigned — this deployment has no signing key configured"}
          </div>
        </div>
      )}

      {proof && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Evidence bundle</div>
          <details>
            <summary className={styles.mono} style={{ cursor: "pointer", color: "#77776e" }}>
              {v.proof?.uri || "view"}
            </summary>
            <div className={styles.pre} style={{ marginTop: 8 }}>{JSON.stringify(evidence, null, 2)}</div>
          </details>
        </div>
      )}
    </div>
  );
}
