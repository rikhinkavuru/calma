// WorkOS AuthKit middleware — REQUIRED for withAuth()/getSignInUrl() to work (they read the session the
// middleware populates from the cookie). Scoped to the dashboard + the OAuth callback so the marketing site
// is untouched. middlewareAuth stays disabled: we gate in app/dashboard/layout.tsx (it renders a sign-in
// card for an anonymous session) rather than hard-redirecting at the edge.
import { authkitMiddleware } from "@workos-inc/authkit-nextjs";

export default authkitMiddleware();

export const config = {
  matcher: ["/dashboard", "/dashboard/:path*", "/callback"],
};
