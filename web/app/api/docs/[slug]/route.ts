// Plain-markdown version of a docs page, served at /docs/<slug>.md (via the next.config rewrite) and used by
// the "Copy page", "View as Markdown", and "Open in ChatGPT/Claude/Perplexity" actions. Public + cacheable.
import { DOCS, docBySlug } from "@/app/docs/content";

export const dynamic = "force-static";

export function generateStaticParams() {
  return DOCS.map((d) => ({ slug: d.slug }));
}

export async function GET(_req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = docBySlug(slug);
  if (!doc) return new Response("Not found", { status: 404 });
  const body = `# ${doc.title}\n\n_${doc.description}_\n\n${doc.markdown}`;
  return new Response(body, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=86400",
    },
  });
}
