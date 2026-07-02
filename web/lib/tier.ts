// Tier resolution + a cheap edge burst guard for the verification proxy. The backend (spike/core/limits.py)
// is the AUTHORITATIVE meter (daily scans, sandbox-minutes, concurrency); this layer resolves *who* the user
// is and *what plan* they're on from the WorkOS identity, and adds a first-line-of-defense per-user burst
// limit so a flood is shed at the edge before it ever reaches the backend or spends a Vercel function.
//
// Billing isn't wired yet, so tier assignment is an env allowlist (emails or WorkOS user ids). Anyone not
// listed is `free` — fail closed on entitlement. Set CALMA_PRO_USERS / CALMA_ENTERPRISE_USERS (comma-sep),
// or CALMA_TIER_DEFAULT to grant a blanket tier during a launch.

import { createHash } from "node:crypto";
import { cookies } from "next/headers";

export type Tier = "free" | "pro" | "enterprise";

// Ordering so a dev/promo code (or any override) can only ever ELEVATE a tier, never silently downgrade one.
const TIER_RANK: Record<Tier, number> = { free: 0, pro: 1, enterprise: 2 };

type Userish = { id?: string | null; email?: string | null } | null | undefined;

function allowlist(env: string | undefined): Set<string> {
  return new Set(
    (env || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function resolveTier(user: Userish, override?: Tier | null): Tier {
  const id = (user?.id || "").toLowerCase();
  const email = (user?.email || "").toLowerCase();
  const ent = allowlist(process.env.CALMA_ENTERPRISE_USERS);
  const pro = allowlist(process.env.CALMA_PRO_USERS);
  let base: Tier;
  if ((id && ent.has(id)) || (email && ent.has(email))) base = "enterprise";
  else if ((id && pro.has(id)) || (email && pro.has(email))) base = "pro";
  else {
    const dflt = (process.env.CALMA_TIER_DEFAULT || "free").toLowerCase();
    base = dflt === "pro" || dflt === "enterprise" ? (dflt as Tier) : "free";
  }
  // A valid dev/promo code elevates but never downgrades: a Pro user typing a Pro code stays Pro, and an
  // unknown/forged cookie (override=null) leaves the identity tier untouched. Fail closed on entitlement.
  if (override && TIER_RANK[override] > TIER_RANK[base]) return override;
  return base;
}

// ── dev / promo codes ──────────────────────────────────────────────────────────────────────────────────
// A reusable, env-configured code a signed-in user types once to self-unlock a tier — the founder's own dev
// mode, and hand-picked beta testers, before billing exists. Format:
//   CALMA_DEV_CODES="CALMA-DEV-2026:enterprise,BETA-2026:pro"   (a bare "CODE" grants enterprise)
// The code itself IS the secret. A forged cookie carrying an unknown code resolves to null (no elevation), so
// a code can only ever unlock a tier the operator explicitly minted. Codes are case-sensitive.
export const DEV_CODE_COOKIE = "calma_dev";

function devCodeMap(): Map<string, Tier> {
  const m = new Map<string, Tier>();
  for (const pair of (process.env.CALMA_DEV_CODES || "").split(",")) {
    const t = pair.trim();
    if (!t) continue;
    const [codeRaw, tierRaw] = t.split(":");
    const code = (codeRaw || "").trim();
    if (!code) continue;
    const tier = (tierRaw || "enterprise").trim().toLowerCase();
    m.set(code, tier === "pro" || tier === "free" ? (tier as Tier) : "enterprise");
  }
  return m;
}

// The tier a submitted code unlocks, or null if it isn't a live code.
export function tierForDevCode(code: string | null | undefined): Tier | null {
  const c = (code || "").trim();
  return c ? devCodeMap().get(c) || null : null;
}

// Resolve the dev-code cookie (set by POST /api/dev-code) to a tier. Returns null outside a request scope or
// when no valid code is present — safe to `await` in any authed route and pass straight to resolveTier().
export async function devCodeTierFromCookie(): Promise<Tier | null> {
  try {
    const store = await cookies();
    return tierForDevCode(store.get(DEV_CODE_COOKIE)?.value);
  } catch {
    return null;
  }
}

// A stable tenant id for metering: the WorkOS user id (falls back to the dev tenant, then "anon").
export function tenantOf(user: Userish, devTenant?: string | false | null): string {
  return user?.id || (devTenant || undefined) || "anon";
}

// The public, unauthenticated demo's identity: an IP hash, not a real tenant. Shared by the submit route
// (app/api/demo/verify) and the poll route (app/api/demo/verify/[id]) — they MUST resolve to the same string
// for the same visitor, or the backend's per-tenant job-ownership check (server.py _job_or_404) will 404 the
// visitor's own demo job on poll.
export function demoTenant(req: Request): string {
  const ip = (req.headers.get("x-forwarded-for") || "").split(",")[0].trim() || "unknown";
  return "demo:" + createHash("sha256").update(ip).digest("hex").slice(0, 16);
}

// ── edge burst guard ────────────────────────────────────────────────────────────────────────────────────
// A fixed 60s window per tenant. In-memory, per-instance — deliberately coarse (defense in depth, not the
// authoritative meter). Fluid Compute reuses instances so this catches the common single-instance flood; the
// backend's per-tenant limiter is the real ceiling across instances.
const EDGE_RPM = Number(process.env.CALMA_EDGE_RPM || "60") || 60;
const _win = new Map<string, { minute: number; count: number }>();

export function edgeGuard(tenant: string): { ok: boolean; retryAfter: number } {
  const now = Date.now();
  const minute = Math.floor(now / 60000);
  const cur = _win.get(tenant);
  if (!cur || cur.minute !== minute) {
    _win.set(tenant, { minute, count: 1 });
    // opportunistic cleanup so the map can't grow unbounded across many tenants
    if (_win.size > 5000) for (const [k, v] of _win) if (v.minute !== minute) _win.delete(k);
    return { ok: true, retryAfter: 0 };
  }
  cur.count += 1;
  if (cur.count > EDGE_RPM) return { ok: false, retryAfter: 60 - Math.floor((now % 60000) / 1000) };
  return { ok: true, retryAfter: 0 };
}
