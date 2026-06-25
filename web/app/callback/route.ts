// WorkOS AuthKit OAuth callback. The redirect URI (NEXT_PUBLIC_WORKOS_REDIRECT_URI) must point here and
// be registered in the WorkOS dashboard (Redirects). After a successful login the user lands on /dashboard.
import { handleAuth } from "@workos-inc/authkit-nextjs";

export const GET = handleAuth({ returnPathname: "/dashboard" });
