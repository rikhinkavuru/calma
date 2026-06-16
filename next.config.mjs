/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin the workspace root to this repo so a stray package-lock.json one level
  // up doesn't make Next infer the wrong root (multiple-lockfile warning).
  outputFileTracingRoot: import.meta.dirname,
};

export default nextConfig;
