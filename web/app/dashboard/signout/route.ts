// WorkOS sign-out. MUST be POST-only: a GET would be PREFETCHED by Next's <Link> (the nav link entering
// the viewport silently logs the user out -> every page then renders blank). The nav posts a form here.
// A GET is kept as a harmless no-op redirect so any stray/prefetched GET never clears the session.
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  return NextResponse.redirect(new URL("/dashboard", req.url));
}

export async function POST(req: Request) {
  try {
    const mod = await import("@workos-inc/authkit-nextjs");
    return await mod.signOut({ returnTo: "/dashboard" });
  } catch {
    return NextResponse.redirect(new URL("/dashboard", req.url));
  }
}
