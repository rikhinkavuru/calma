// Callback for the DIRECT OAuth providers (Google / GitHub / Microsoft) started in login-actions.startOAuth.
// Confidential-client exchange: verify the CSRF state cookie, swap the code for a session with the WorkOS
// secret, persist it via AuthKit's saveSession, then land on /dashboard (which provisions the tenant lazily
// on first render). The AuthKit `/callback` route can't be reused here because it requires the PKCE cookie
// that only AuthKit's own getSignInUrl sets.
import { NextResponse, type NextRequest } from "next/server";
import { cookies } from "next/headers";

const STATE_COOKIE = "calma_oauth_state";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const origin = url.origin;
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");

  const jar = await cookies();
  const expected = jar.get(STATE_COOKIE)?.value;
  jar.delete(STATE_COOKIE);

  if (url.searchParams.get("error")) {
    console.error("[calma] oauth provider error:", url.searchParams.get("error_description") || url.searchParams.get("error"));
    return NextResponse.redirect(`${origin}/dashboard?auth_error=provider`);
  }
  if (!code || !state || !expected || state !== expected) {
    return NextResponse.redirect(`${origin}/dashboard?auth_error=state`);
  }

  try {
    const { getWorkOS, saveSession } = await import("@workos-inc/authkit-nextjs");
    const auth = await getWorkOS().userManagement.authenticateWithCode({
      clientId: process.env.WORKOS_CLIENT_ID || "",
      code,
    });
    await saveSession(auth, origin);
  } catch (e) {
    console.error("[calma] oauth callback error:", e instanceof Error ? e.message : e);
    return NextResponse.redirect(`${origin}/dashboard?auth_error=oauth`);
  }

  return NextResponse.redirect(`${origin}/dashboard`);
}
