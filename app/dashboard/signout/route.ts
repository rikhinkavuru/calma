// WorkOS sign-out (clears the session cookie + redirects). Only reachable in WorkOS mode (the nav hides
// it in dev). Falls back to a plain redirect if AuthKit isn't available.
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  try {
    const mod = await import("@workos-inc/authkit-nextjs");
    return await mod.signOut({ returnTo: "/dashboard" });
  } catch {
    return NextResponse.redirect(new URL("/dashboard", req.url));
  }
}
