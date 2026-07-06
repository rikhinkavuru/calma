// WorkOS AuthKit middleware — REQUIRED for withAuth()/getSignInUrl() to work (they read the session the
// middleware populates from the cookie). Scoped to the dashboard + the OAuth callback so the marketing site
// is untouched. middlewareAuth stays disabled: we gate in app/dashboard/layout.tsx (it renders a sign-in
// card for an anonymous session) rather than hard-redirecting at the edge.
import { authkitMiddleware } from "@workos-inc/authkit-nextjs";

export default authkitMiddleware();

export const config = {
  // EVERY route that calls withAuth() must be matched here, or the session cookie isn't populated and
  // withAuth() returns no user → the route 401s even for a signed-in user. This bit the API-keys page (added
  // after the original matcher) and the client-side job polling: /api/keys, /api/jobs and /api/dev-code were
  // missing, so key generation and live metric updates both 401'd. Keep this list in sync with
  // `grep -rl withAuth app/api`.
  matcher: [
    "/dashboard", "/dashboard/:path*", "/callback",
    "/api/verify", "/api/verify/:path*",
    "/api/github", "/api/github/:path*",
    "/api/keys", "/api/keys/:path*",
    "/api/jobs", "/api/jobs/:path*",
    "/api/dev-code",
    "/api/billing/:path*",
  ],
};
