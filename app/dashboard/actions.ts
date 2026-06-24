"use server";
import { createHash } from "crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { calma } from "@/lib/calma";
import { getSession } from "@/lib/session";

// Submit a verification: the bundle .tar.gz is uploaded to R2 SERVER-SIDE via a presigned PUT (no browser
// CORS), then submitted to the engine. Redirects to the new verification's detail page.
export async function submitAction(formData: FormData) {
  const s = await getSession();
  if (!s) throw new Error("no session");

  const file = formData.get("bundle") as File | null;
  if (!file || file.size === 0) throw new Error("a bundle .tar.gz is required");
  const bytes = Buffer.from(await file.arrayBuffer());
  const sha = createHash("sha256").update(bytes).digest("hex");

  const up = await calma.uploadUrl(s.tenantId, "bundle", sha);
  const put = await fetch(up.url, { method: "PUT", body: bytes });
  if (!put.ok) throw new Error(`storage upload failed (${put.status})`);

  const metric = String(formData.get("metric") || "").trim();
  const valueRaw = String(formData.get("value") || "").trim();
  const body: Record<string, unknown> = {
    recipe_id: String(formData.get("recipe_id") || "trading.total_return"),
    recipe_version: String(formData.get("recipe_version") || "1.0.0"),
    template_id: "python-3.11",
    trust: String(formData.get("trust") || "own-code"),
    bundle: {
      uri: up.uri, sha256: sha,
      entrypoint: String(formData.get("entrypoint") || "gen.py"), language: "python",
    },
  };
  if (metric && valueRaw) body.claim = { metric, value: Number(valueRaw) };

  const v = await calma.submit(s.tenantId, body);
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
