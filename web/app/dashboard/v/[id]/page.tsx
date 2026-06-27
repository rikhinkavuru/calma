import crypto from "crypto";
import Link from "next/link";
import { calma, type Verification } from "@/lib/calma";
import { getSession } from "@/lib/session";
import { StatusBadge, VerdictBadge } from "../../Badge";
import { DEMO_VERIFICATION, DEMO_PROOF } from "./demoFixture";
import styles from "../../dashboard.module.css";

export const dynamic = "force-dynamic";

// Pinned control-plane proof-signing public keys (source of truth: control_plane/signing_pubkey.json).
// `current` = KMS ECDSA-P256 (non-exportable); the ed25519 one stays for proofs issued before the cutover.
// Verifying here proves the proof was signed by Calma's key — not just that the envelope claims a signature.
const TRUSTED_KEYS = [
  { keyid: "3d48e4df88f77082", algorithm: "ecdsa-p256-sha256",
    pub_b64: "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEHxlPj9KVKXNv8pP3HRCBg073f1f1Dedm9kcJd+bzQUGvRN9bPuelllETYZoBpJN1lNj9VffAPeD3PTMaHyeseQ==" },
  { keyid: "6828f0ad98306a21", algorithm: "ed25519",
    pub_b64: "TY0kvWBGY+henz1JF2OfnFhA/gDJDNLxsxwDNB4+z0U=" },
];

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
  const msg = pae(env.payloadType, Buffer.from(env.payload, "base64"));
  return (env.signatures || []).some((s) => {
    const k = TRUSTED_KEYS.find((t) => t.keyid === s.keyid);
    if (!k) return false;
    try {
      const sig = Buffer.from(s.sig, "base64");
      if (k.algorithm === "ed25519") {
        const der = Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), Buffer.from(k.pub_b64, "base64")]);
        const pub = crypto.createPublicKey({ key: der, format: "der", type: "spki" });
        return crypto.verify(null, msg, pub, sig);
      }
      // ecdsa-p256-sha256: KMS returns a DER-encoded ECDSA signature; the pub is already DER SPKI
      const pub = crypto.createPublicKey({ key: Buffer.from(k.pub_b64, "base64"), format: "der", type: "spki" });
      return crypto.verify("sha256", msg, { key: pub, dsaEncoding: "der" }, sig);
    } catch {
      return false;
    }
  });
}

// Plain-language gloss for the verdict word — so a first-time reader knows what it MEANS, not just
// the label. Keyed by the verdict the API returns (CAN'T-CONFIRM is the display form of INCONCLUSIVE).
const VERDICT_GLOSS: Record<string, string> = {
  CONFIRMED: "The claimed number holds. Calma re-executed the code and recomputed the same value from the raw outputs.",
  "CONFIRMED-WITH-CAVEATS": "The number holds, but with caveats worth reading below.",
  REFUTED: "The claimed number does not hold. Recomputing it from the raw outputs gives a materially different value.",
  INVALIDATED: "The number reproduces, but the result itself is invalid (e.g. leakage or look-ahead) — the value is real but it doesn't mean what was claimed.",
  FLAG_FOR_DECLARATION: "The number reproduces, but undeclared structure could invalidate it. Declare the relevant block to resolve.",
  "CAN'T-CONFIRM": "Not enough was declared to verify this yet — see what to provide below.",
  INCONCLUSIVE: "Not enough was declared to verify this yet — see what to provide below.",
};

// One-line plain-English captions for the execution metadata jargon.
const EXEC_GLOSS: Record<string, string> = {
  isolation_tier: "the sandbox the code ran in (seatbelt / bubblewrap / docker / firecracker)",
  tier_verified: "whether Calma confirmed that sandbox actually isolated on this host",
  network_run: "network during the run — off means the result can't phone home for its number",
  determinism: "how reproducible the run was — controlled-to-bit means byte-identical across re-runs",
};

export default async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const s = await getSession();
  if (!s) return null; // unauthenticated: the layout renders the sign-in gate
  const isDemo = id === "demo";
  let v: Verification | null = null;
  let proof: Record<string, unknown> | null = null;
  let error: string | null = null;
  if (isDemo) {
    // Pre-recorded sample: a REAL past e2b run + its signed proof, baked in and replayed instantly so the
    // one-click demo never re-boots a ~50s microVM. No API call, no per-tenant data; the proof still verifies.
    v = DEMO_VERIFICATION;
    proof = DEMO_PROOF;
  } else {
    try {
      v = await calma.getVerification(s.tenantId, id);
      try { proof = await calma.getProof(s.tenantId, id); } catch { /* proof may not exist yet */ }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
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
  const sigAlgo = TRUSTED_KEYS.find((t) => t.keyid === sigKeyid)?.algorithm || "unknown";
  const signed = !!env && env.signatures.length > 0;
  // decode the signed payload defensively: a malformed envelope must not escalate one bad row to a
  // full-page error boundary — show the rest of the verdict (sig status etc.) instead.
  let evidence: unknown = proof;
  if (env) {
    try {
      evidence = JSON.parse(Buffer.from(env.payload, "base64").toString("utf-8"));
    } catch {
      evidence = null;
    }
  }
  return (
    <div className={styles.main}>
      <Link href="/dashboard" className={styles.back}>← Verifications</Link>
      {isDemo && (
        <div className={`${styles.notice} ${styles.noticeOk}`} style={{ marginTop: 12 }}>
          <strong>Pre-recorded sample.</strong> A real past verification of the demo backtest — re-executed in
          the e2b microVM, recomputed host-side, and signed — replayed here instantly. The proof below still
          verifies in your browser. <Link href="/dashboard/submit">Run your own →</Link>
        </div>
      )}
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

      {v.verdict && VERDICT_GLOSS[v.verdict] && (
        <p className={styles.sub} style={{ marginTop: 10, maxWidth: 720 }}>{VERDICT_GLOSS[v.verdict]}</p>
      )}

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
      <p className={styles.hint} style={{ marginTop: -6 }}>
        Calma diffs the recomputed value against the claim under the recipe&apos;s calibrated tolerance —
        a pass means they agree within that band, not that they&apos;re bit-identical.
      </p>

      {v.reason && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Reason</div>
          <div className={styles.pre}>{v.reason}</div>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionTitle}>Execution</div>
        <div className={styles.detailGrid}>
          {([
            ["isolation_tier", ex.isolation_tier || "—"],
            ["tier_verified", String(ex.tier_verified)],
            ["network_run", ex.network_run || "—"],
            ["determinism", ex.determinism_mode || "—"],
          ] as const).map(([key, val]) => (
            <div className={styles.kv} key={key}>
              <div className={styles.kvLabel} title={EXEC_GLOSS[key]}>{key}</div>
              <div className={styles.kvValue} style={{ fontSize: 15 }}>{val}</div>
              <div className={styles.hint} style={{ marginTop: 4 }}>{EXEC_GLOSS[key]}</div>
            </div>
          ))}
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
              ? (sigVerified
                  ? `✓ Verified in your browser against Calma's published signing key (${sigAlgo} · keyid ${sigKeyid}).\n` +
                    `That proves this proof was signed by Calma's key — not just that the envelope claims a signature.\n` +
                    `It's a self-contained DSSE envelope: anyone can re-verify it offline with the open-source verifier (control_plane/verify_proof.py).`
                  : `✗ Signature did NOT verify against Calma's published keys (keyid ${sigKeyid}) — do not trust this proof.`)
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
