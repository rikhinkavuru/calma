// A WorkOS user's Calma tenant is stable but resolving it (provision()) is a cold cross-service call.
// We provision ONCE at login (app/callback/route.ts) and stash the tenant id here in a sealed,
// tamper-proof cookie bound to the WorkOS user id — so getSession() reads it locally on every
// subsequent render instead of paying the round-trip. Sealed with the same secret AuthKit already
// uses for its session cookie (guaranteed present wherever WorkOS auth runs).
//
// NOT marked `server-only`: writeTenantCookie is imported by the /callback ROUTE HANDLER, which lives
// outside the React Server Components graph where the `server-only` guard would throw. next/headers
// already makes this module unusable from the client, so the guard is redundant here anyway.
import { cookies } from "next/headers";
import { sealData, unsealData } from "iron-session";

const COOKIE = "calma_tid";
const PASSWORD = process.env.WORKOS_COOKIE_PASSWORD || "";
const TTL = 60 * 60 * 24 * 30; // 30 days, in seconds

type Sealed = { uid: string; tid: string };

// Read the tenant id IFF the cookie is present, unseals, and is bound to THIS user. Render-safe.
export async function readTenantCookie(uid: string): Promise<string | null> {
  if (!PASSWORD) return null;
  const raw = (await cookies()).get(COOKIE)?.value;
  if (!raw) return null;
  try {
    const data = await unsealData<Sealed>(raw, { password: PASSWORD, ttl: TTL });
    return data?.uid === uid && data.tid ? data.tid : null;
  } catch {
    return null; // tampered / expired / wrong secret -> treat as absent
  }
}

// Settable only from a Route Handler / Server Action (the login callback). Best-effort: any failure
// just means getSession() provisions lazily next render.
export async function writeTenantCookie(uid: string, tid: string): Promise<void> {
  if (!PASSWORD) return;
  const sealed = await sealData({ uid, tid } satisfies Sealed, { password: PASSWORD, ttl: TTL });
  (await cookies()).set(COOKIE, sealed, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: TTL,
  });
}
