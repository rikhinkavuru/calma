"use server";
// Server actions behind the sign-in screen. Every path forces a fresh WorkOS prompt so the user is never
// silently single-signed-on. Methods:
//   - Direct OAuth (Google / GitHub / Microsoft): userManagement.getAuthorizationUrl({ provider }) ->
//     WorkOS -> /auth/callback (confidential-client code exchange). No AuthKit PKCE, so it needs its own route.
//   - SSO + Sign up: AuthKit hosted (getSignInUrl / getSignUpUrl) -> /callback. Hosted routes SSO by domain.
//   - Magic Auth (email): createMagicAuth sends a 6-digit code -> authenticateWithMagicAuth verifies it.
//     Passwordless, so there is no password to reset.
import { redirect } from "next/navigation";
import { headers, cookies } from "next/headers";

const RETURN_TO = "/dashboard";
const OAUTH_STATE_COOKIE = "calma_oauth_state";
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

type AuthKit = typeof import("@workos-inc/authkit-nextjs");
const authkit = (): Promise<AuthKit> => import("@workos-inc/authkit-nextjs");

async function origin(): Promise<string> {
  const h = await headers();
  return `${h.get("x-forwarded-proto") || "https"}://${h.get("host") || "localhost:3000"}`;
}

// ── Direct OAuth (Google / GitHub / Microsoft) ────────────────────────────────────────────────────────────
type OAuthProvider = "GoogleOAuth" | "GitHubOAuth" | "MicrosoftOAuth";

async function startOAuth(provider: OAuthProvider) {
  const { getWorkOS } = await authkit();
  const state = crypto.randomUUID();
  (await cookies()).set(OAUTH_STATE_COOKIE, state, {
    httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 600,
  });
  const url = getWorkOS().userManagement.getAuthorizationUrl({
    provider,
    clientId: process.env.WORKOS_CLIENT_ID || "",
    redirectUri: `${await origin()}/auth/callback`,
    state,
  });
  redirect(url);
}

export async function continueWithGoogle() { await startOAuth("GoogleOAuth"); }
export async function continueWithGithub() { await startOAuth("GitHubOAuth"); }
export async function continueWithMicrosoft() { await startOAuth("MicrosoftOAuth"); }

// ── SSO + Sign up via AuthKit hosted (existing /callback) ──────────────────────────────────────────────────
async function hostedUrl(kind: "in" | "up"): Promise<string | null> {
  try {
    const { getSignInUrl, getSignUpUrl } = await authkit();
    const o = { returnTo: RETURN_TO, prompt: "login" } as unknown as Parameters<typeof getSignInUrl>[0];
    return kind === "in" ? await getSignInUrl(o) : await getSignUpUrl(o);
  } catch (e) {
    console.error("[calma] hosted url error:", e instanceof Error ? e.message : e);
    return null;
  }
}

// Enterprise SSO — the hosted page routes the user to their org's IdP by email domain.
export async function continueWithSSO() {
  const url = await hostedUrl("in");
  if (url) redirect(url);
}

export async function signUp() {
  const url = await hostedUrl("up");
  if (url) redirect(url);
}

// ── Magic Auth (email code) ───────────────────────────────────────────────────────────────────────────────
export type LoginState = { error?: string; notice?: string; sent?: boolean; email?: string };

// Step 1: send the code.
export async function startMagicAuth(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") || "").trim();
  if (!EMAIL_RE.test(email)) return { error: "Enter a valid email address." };
  try {
    const { getWorkOS } = await authkit();
    await getWorkOS().userManagement.createMagicAuth({ email });
  } catch (e) {
    console.error("[calma] magic auth send error:", e instanceof Error ? e.message : e);
    return { error: "Couldn’t send a code to that address — try again." };
  }
  return { sent: true, email };
}

// Step 2: verify the code and open a session.
export async function verifyMagicAuth(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") || "").trim();
  const code = String(formData.get("code") || "").replace(/\s+/g, "");
  if (!code) return { sent: true, email, error: "Enter the code we emailed you." };

  let auth;
  try {
    const { getWorkOS } = await authkit();
    auth = await getWorkOS().userManagement.authenticateWithMagicAuth({
      clientId: process.env.WORKOS_CLIENT_ID || "",
      email,
      code,
    });
  } catch (e) {
    console.error("[calma] magic auth verify error:", e instanceof Error ? e.message : e);
    return { sent: true, email, error: "That code didn’t match. Check it and try again." };
  }

  const { saveSession } = await authkit();
  await saveSession(auth!, await origin());
  redirect(RETURN_TO);
}

// Resend the code.
export async function resendMagicAuth(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") || "").trim();
  if (!EMAIL_RE.test(email)) return { error: "Enter a valid email address." };
  try {
    const { getWorkOS } = await authkit();
    await getWorkOS().userManagement.createMagicAuth({ email });
  } catch (e) {
    console.error("[calma] magic auth resend error:", e instanceof Error ? e.message : e);
    return { sent: true, email, error: "Couldn’t resend the code — try again." };
  }
  return { sent: true, email, notice: `New code sent to ${email}.` };
}
