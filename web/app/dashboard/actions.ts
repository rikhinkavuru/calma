"use server";
import { createHash } from "crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { calma } from "@/lib/calma";
import { getSession } from "@/lib/session";
import { DEMO_BUNDLE } from "./submit/demoBundle";

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
    trust: String(formData.get("trust") || "own-code"),
    claim: metric && valueRaw ? { metric, value: Number(valueRaw) } : undefined,
  });
  redirect(`/dashboard/v/${v.verification_id}`);
}

// One-click demo: run a REAL verification on a bundled sample backtest, so a first-time user sees the
// whole loop (re-execute offline → recompute from raw outputs → verdict + signed proof) without first
// authoring a verify.yaml or building a tar.gz. Reuses the exact upload+submit path as the real form.
export async function submitDemoAction() {
  const s = await getSession();
  if (!s) throw new Error("no session");
  const bytes = Buffer.from(DEMO_BUNDLE.base64, "base64");
  const v = await uploadAndSubmit(s.tenantId, bytes, {
    recipeId: DEMO_BUNDLE.recipeId,
    recipeVersion: DEMO_BUNDLE.recipeVersion,
    entrypoint: DEMO_BUNDLE.entrypoint,
    trust: "own-code",
    claim: { metric: DEMO_BUNDLE.metric, value: DEMO_BUNDLE.claimedValue },
  });
  redirect(`/dashboard/v/${v.verification_id}`);
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
