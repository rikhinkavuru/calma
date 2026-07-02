import type { MetadataRoute } from "next";

const SITE_URL = "https://calma1.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { path: "", priority: 1 },
    { path: "/demo", priority: 0.8 },
    { path: "/pricing", priority: 0.9 },
  ].map(({ path, priority }) => ({
    url: `${SITE_URL}${path}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority,
  }));
}
