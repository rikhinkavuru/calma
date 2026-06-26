/** @type {import('next').NextConfig} */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// Local-dev convenience: the secrets `.env` lives at the repo root, but Next only
// loads `.env*` from this `web/` project dir — so `npm run dev` from here would
// otherwise start with NO env (WorkOS/API keys missing) and the dashboard 500s.
// Load the repo-root `.env` into process.env for any UNSET keys, DEV ONLY. In
// production (`next build`/`start` force NODE_ENV=production) this is a no-op, and
// any key already set (real env / CI / web/.env.local) always wins.
if (process.env.NODE_ENV !== "production") {
  // fileURLToPath (not URL.pathname) so a repo path with spaces / URL-special
  // chars resolves correctly instead of silently not loading.
  const rootEnv = join(dirname(fileURLToPath(import.meta.url)), "..", ".env");
  if (existsSync(rootEnv)) {
    for (let line of readFileSync(rootEnv, "utf8").split("\n")) {
      let t = line.trim();
      if (!t || t.startsWith("#")) continue;
      if (t.startsWith("export ")) t = t.slice(7).trim();
      const eq = t.indexOf("=");
      if (eq < 1) continue;
      const key = t.slice(0, eq).trim();
      if (key in process.env) continue; // real env / CI / web/.env.local always wins
      let val = t.slice(eq + 1).trim();
      const q = val[0];
      if (val.length > 1 && (q === '"' || q === "'") && val.at(-1) === q) {
        val = val.slice(1, -1); // quoted: literal contents
      } else {
        const h = val.indexOf(" #"); // unquoted: strip an inline comment
        if (h >= 0) val = val.slice(0, h).trim();
      }
      process.env[key] = val;
    }
  }
}

// Baseline security headers on every route. A strict Content-Security-Policy is intentionally NOT set
// here: it must be authored + tested against the actual app (inline styles / framer-motion) to avoid
// breaking rendering - tracked as a follow-up. These headers are safe for a static marketing site.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig = {
  reactStrictMode: true,
  // Pin the workspace root to this repo so a stray package-lock.json one level
  // up doesn't make Next infer the wrong root (multiple-lockfile warning).
  outputFileTracingRoot: import.meta.dirname,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
