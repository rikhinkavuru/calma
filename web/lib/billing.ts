// Stripe billing — the entitlement source of truth once a user actually pays. No local subscription DB:
// the tier is resolved live from Stripe ("does this email have an active subscription?") and cached per
// warm instance, so a paid user is Pro on every device with zero webhook plumbing. The env allowlist and
// dev codes in lib/tier.ts still work and compose via resolveTier's elevate-only override rule.
//
// Requires STRIPE_SECRET_KEY (+ STRIPE_PRO_PRICE_ID for checkout). Absent keys → billing is simply off:
// stripeTierFor() returns null and the tier system behaves exactly as before billing existed.
import "server-only";
import Stripe from "stripe";
import type { Tier } from "./tier";

let _stripe: Stripe | null = null;

export function stripeClient(): Stripe | null {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) return null;
  if (!_stripe) _stripe = new Stripe(key);
  return _stripe;
}

// Warm-instance cache: email -> resolved tier. Positive hits live 5 min (a cancelled sub downgrades within
// that window); misses live 60s so a fresh checkout unlocks Pro within a minute of paying.
const HIT_TTL_MS = 5 * 60_000;
const MISS_TTL_MS = 60_000;
const _cache = new Map<string, { tier: Tier | null; exp: number }>();

export async function stripeTierFor(
  user: { email?: string | null } | null | undefined,
): Promise<Tier | null> {
  const email = (user?.email || "").trim().toLowerCase();
  const stripe = stripeClient();
  if (!stripe || !email) return null;

  const hit = _cache.get(email);
  if (hit && hit.exp > Date.now()) return hit.tier;

  let tier: Tier | null = null;
  try {
    const customers = await stripe.customers.list({ email, limit: 5 });
    for (const customer of customers.data) {
      const subs = await stripe.subscriptions.list({ customer: customer.id, status: "active", limit: 5 });
      if (subs.data.length > 0) {
        tier = "pro";
        break;
      }
    }
  } catch (e) {
    // Fail closed on entitlement (no elevation) but do NOT cache the error — a transient Stripe outage
    // shouldn't lock a paid user out of Pro for a full TTL.
    console.error("[calma] stripeTierFor error:", e instanceof Error ? e.message : e);
    return null;
  }

  if (_cache.size > 5000) _cache.clear(); // crude bound; entries are tiny and re-resolve on demand
  _cache.set(email, { tier, exp: Date.now() + (tier ? HIT_TTL_MS : MISS_TTL_MS) });
  return tier;
}
