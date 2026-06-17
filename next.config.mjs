/** @type {import('next').NextConfig} */

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
