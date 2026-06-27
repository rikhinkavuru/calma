"use server";
import { createHash } from "crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { calma } from "@/lib/calma";
import { getSession } from "@/lib/session";

// Upload bundle bytes to R2 (server-side presigned PUT, no browser CORS) and submit a verification.
// Shared by the real upload form and the one-click demo so both travel the exact same proven path.
async function uploadAndSubmit(
  tenantId: string,
  bytes: Buffer,
  opts: { recipeId: string; recipeVersion: string; entrypoint: string; trust: string;
    claim?: { metric: string; value: number } },
) {
  const sha = createHash("sha256").update(bytes).digest("hex");
  const up = await calma.uploadUrl(tenantId, "bundle", sha);
  // Uint8Array (not Buffer) is the portable BodyInit across the fetch typings.
  const put = await fetch(up.url, { method: "PUT", body: new Uint8Array(bytes) });
  if (!put.ok) throw new Error(`storage upload failed (${put.status})`);
  const body: Record<string, unknown> = {
    recipe_id: opts.recipeId,
    recipe_version: opts.recipeVersion,
    template_id: "python-3.11",
    trust: opts.trust,
    bundle: { uri: up.uri, sha256: sha, entrypoint: opts.entrypoint, language: "python" },
  };
  if (opts.claim) body.claim = opts.claim;
  return calma.submit(tenantId, body);
}

// Submit a verification: the bundle .tar.gz is uploaded to R2 SERVER-SIDE via a presigned PUT (no browser
// CORS), then submitted to the engine. Redirects to the new verification's detail page.
export async function submitAction(formData: FormData) {
  const s = await getSession();
  if (!s) throw new Error("no session");

  const file = formData.get("bundle") as File | null;
  if (!file || file.size === 0) throw new Error("a bundle .tar.gz is required");
  const bytes = Buffer.from(await file.arrayBuffer());

  const metric = String(formData.get("metric") || "").trim();
  const valueRaw = String(formData.get("value") || "").trim();
  const v = await uploadAndSubmit(s.tenantId, bytes, {
    recipeId: String(formData.get("recipe_id") || "trading.total_return"),
    recipeVersion: String(formData.get("recipe_version") || "1.0.0"),
    entrypoint: String(formData.get("entrypoint") || "gen.py"),
    // Tenant uploads default to UNTRUSTED: the server must never execute submitted bytes as own-code
    // (which can degrade to an unisolated host run). Untrusted requires a verified container/microVM
    // tier and is refused otherwise. The form only offers own-code as an explicit opt-in.
    trust: String(formData.get("trust") || "untrusted-third-party"),
    claim: metric && valueRaw ? { metric, value: Number(valueRaw) } : undefined,
  });
  redirect(`/dashboard/v/${v.verification_id}`);
}

// One-click demo: replay a PRE-RECORDED real verification of the sample backtest instead of re-booting a
// ~50s e2b microVM on every click. The demo bundle is fixed and its result is deterministic, so the baked-in
// fixture (web/app/dashboard/v/[id]/demoFixture.ts — a genuine past e2b run + its signed proof) shows the
// exact same re-execute → recompute → signed-proof loop, instantly. The real form below still runs live.
export async function submitDemoAction() {
  const s = await getSession();
  if (!s) throw new Error("no session");
  redirect("/dashboard/v/demo");
}

export async function createKeyAction(environment: string) {
  const s = await getSession();
  if (!s) throw new Error("no session");
  const created = await calma.createKey(s.tenantId, environment);
  revalidatePath("/dashboard/keys");
  return created as { id: string; prefix: string; environment: string; token: string };
}

export async function revokeKeyAction(id: string) {
  const s = await getSession();
  if (!s) throw new Error("no session");
  await calma.revokeKey(s.tenantId, id);
  revalidatePath("/dashboard/keys");
}
