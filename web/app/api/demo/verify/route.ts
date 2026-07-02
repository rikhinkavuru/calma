// Public, unauthenticated proxy: POST /api/demo/verify → run the verifier against ONE fixed sample repo
// (demo-repo/ in this monorepo — see demo-repo/README.md). No signup, no repo input: this exists so a
// visitor can see the real engine catch a real wrong number before creating an account. The `demo` tier
// (spike/core/limits.py) caps this hard (3 scans/day, top-1 claim, 120s wall) and the identity is an IP
// hash, not a real tenant, so it can never become a free arbitrary-compute proxy — the repo/entry are not
// caller-controlled.
import { NextResponse } from "next/server";
import { verifyApi, VerifyApiError } from "@/lib/verify";
import { demoTenant, edgeGuard } from "@/lib/tier";

export const dynamic = "force-dynamic";

const DEMO_REPO = "rikhinkavuru/calma";
const DEMO_ENTRY = "demo-repo/eval.py";

export async function POST(req: Request) {
  const tenant = demoTenant(req);
  const guard = edgeGuard(tenant);
  if (!guard.ok) {
    return NextResponse.json(
      { error: "too many requests — slow down" },
      { status: 429, headers: { "Retry-After": String(guard.retryAfter) } },
    );
  }
  try {
    const out = await verifyApi.submit(
      {
        repo: DEMO_REPO,
        deep: true,
        runner: "e2b",
        entry: DEMO_ENTRY,
        discover: true,
        pip_install: ["scikit-learn"],
      },
      { tenant, tier: "demo" },
    );
    return NextResponse.json(out);
  } catch (e) {
    if (e instanceof VerifyApiError && [400, 402, 403, 429].includes(e.status)) {
      const headers = e.retryAfter ? { "Retry-After": String(e.retryAfter) } : undefined;
      return NextResponse.json({ error: e.message }, { status: e.status, headers });
    }
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "the verification API is unreachable" },
      { status: 502 },
    );
  }
}
