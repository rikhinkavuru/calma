"use server";
// Server actions behind the redesigned login screen. Two real auth paths, both forcing a fresh WorkOS
// prompt (prompt:"login") so the user is NEVER silently single-signed-on:
//   - Google / hosted: getSignInUrl({ prompt:"login" }) -> redirect to WorkOS AuthKit.
//   - Inline email + password: authenticateWithPassword() -> saveSession() -> /dashboard (no redirect).
// AuthKit is imported DYNAMICALLY (as in lib/session.ts) so the @workos-inc/node worker chain stays out
// of the static page-data graph at build time.
import { redirect } from "next/navigation";
import { headers } from "next/headers";

const RETURN_TO = "/dashboard";

// The SDK type narrows `prompt` to 'consent', but AuthKit forwards any standard OIDC prompt value to the
// hosted page, and prompt=login is what disables silent SSO.
type AuthKit = typeof import("@workos-inc/authkit-nextjs");
const authkit = (): Promise<AuthKit> => import("@workos-inc/authkit-nextjs");

async function hostedUrl(kind: "in" | "up", opts: { loginHint?: string } = {}): Promise<string | null> {
  try {
    const { getSignInUrl, getSignUpUrl } = await authkit();
    const o = { ...opts, returnTo: RETURN_TO, prompt: "login" } as unknown as Parameters<typeof getSignInUrl>[0];
    return kind === "in" ? await getSignInUrl(o) : await getSignUpUrl(o);
  } catch (e) {
    console.error("[calma] login url error:", e instanceof Error ? e.message : e);
    return null;
  }
}

// "Continue with Google" (and the email "Sign in" when password isn't used) -> WorkOS hosted login.
export async function continueWithProvider(formData: FormData) {
  const email = String(formData.get("email") || "").trim();
  const url = await hostedUrl("in", email ? { loginHint: email } : {});
  if (url) redirect(url);
}

// "Create one"
export async function createAccount() {
  const url = await hostedUrl("up");
  if (url) redirect(url);
}

export type LoginState = { error?: string };

function errCode(e: unknown): string {
  if (e && typeof e === "object") {
    const o = e as Record<string, unknown>;
    if (typeof o.code === "string") return o.code;
    const rd = o.rawData as Record<string, unknown> | undefined;
    if (rd && typeof rd.code === "string") return rd.code;
  }
  return "";
}

// Inline email + password sign-in. Returns an inline error on failure; redirects on success.
export async function passwordSignIn(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") || "").trim();
  const password = String(formData.get("password") || "");

  // "Forgot password?" submits this same form with intent=reset -> hand off to WorkOS (which owns reset).
  if (formData.get("intent") === "reset") {
    const url = await hostedUrl("in", email ? { loginHint: email } : {});
    if (url) redirect(url);
    return { error: "Couldn’t open password reset — try again." };
  }

  if (!email || !password) return { error: "Enter your email and password." };

  let auth;
  let challenge = false;
  try {
    const { getWorkOS } = await authkit();
    auth = await getWorkOS().userManagement.authenticateWithPassword({
      clientId: process.env.WORKOS_CLIENT_ID || "",
      email,
      password,
    });
  } catch (e) {
    const code = errCode(e);
    // MFA / email-verification / SSO challenges can't be completed inline — hand off to the hosted page.
    if (/mfa|verification|sso_required|organization_selection/i.test(code)) challenge = true;
    else if (/password|credential|authentication_failed|user_not_found|invalid/i.test(code) || code === "")
      return { error: "Incorrect email or password." };
    else return { error: "Couldn’t sign in with email & password — try “Continue with Google”." };
  }

  if (challenge) {
    const url = await hostedUrl("in", { loginHint: email });
    if (url) redirect(url);
    return { error: "Extra verification needed — try “Continue with Google”." };
  }

  // Persist the WorkOS session into the AuthKit cookie, then land on the dashboard.
  const { saveSession } = await authkit();
  const h = await headers();
  const origin = `${h.get("x-forwarded-proto") || "https"}://${h.get("host") || "localhost:3000"}`;
  await saveSession(auth!, origin);
  redirect(RETURN_TO);
}
