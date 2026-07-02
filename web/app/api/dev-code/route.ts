// Dev / promo-code unlock. A signed-in user submits a code (POST), it's validated against CALMA_DEV_CODES,
// and on a hit it's persisted as an httpOnly cookie so every subsequent /api/verify resolves to the unlocked
// tier (see lib/tier.ts resolveTier + devCodeTierFromCookie). This is the pre-billing "dev mode": the founder
// unlocks everything for themselves, and hand-picked beta testers self-unlock without touching env allowlists.
//
// The code IS the secret and can only ELEVATE a tier — a forged or stale cookie resolves to null, leaving the
// user's real (identity/allowlist) tier untouched. Fail closed on an unknown code.
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { DEV_CODE_COOKIE, tierForDevCode, devCodeTierFromCookie } from "@/lib/tier";

export const dynamic = "force-dynamic";

// GET → the tier currently unlocked by a stored code (or null), so the UI can reflect dev-mode state.
export async function GET() {
  return NextResponse.json({ tier: await devCodeTierFromCookie() });
}

// POST { code } → validate + persist. Requires a session: a code elevates *your* identity's tier, so there's
// nothing to elevate for an anonymous caller.
export async function POST(req: Request) {
  const { user } = await withAuth().catch(() => ({ user: null }));
  if (!user) return NextResponse.json({ error: "sign in first" }, { status: 401 });

  const body = await req.json().catch(() => null);
  const code = body?.code && String(body.code).trim();
  if (!code) return NextResponse.json({ error: "a code is required" }, { status: 400 });

  const tier = tierForDevCode(code);
  if (!tier) return NextResponse.json({ error: "that code isn't valid" }, { status: 404 });

  const store = await cookies();
  store.set(DEV_CODE_COOKIE, code, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30, // 30 days
  });
  return NextResponse.json({ ok: true, tier });
}

// DELETE → drop dev mode, revert to the real tier.
export async function DELETE() {
  const store = await cookies();
  store.delete(DEV_CODE_COOKIE);
  return NextResponse.json({ ok: true });
}
