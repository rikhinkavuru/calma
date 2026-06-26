// WS5 — the embeddable "Verified by Calma" badge. Drop it in a README, a PR comment, a model card,
// or a fund's IC memo:
//   ![verified by calma](https://trycalma.ai/badge?outcome=Confirmed&label=sharpe%201.42)
//
// Self-contained: it renders straight from query params (no auth, no DB), shields "for-the-badge"
// style, verdict-coloured. Pair it with a link to /proof for the deep-link to the evidence.
import type { NextRequest } from "next/server";

// the three user-facing outcomes -> colour (Confirmed green, Caught red, Can't-tell / Pending grey).
const COLOR: Record<string, string> = {
  Confirmed: "#1f9d55",
  Caught: "#c5302a",
  "Can't tell": "#8a8f98",
  "Can't-tell": "#8a8f98",
  Pending: "#8a8f98",
};

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// approximate advance width for uppercase bold ~11px text with the for-the-badge letter-spacing,
// plus symmetric horizontal padding. Good enough for a crisp two-segment badge.
function seg(text: string): number {
  return Math.ceil(text.length * 8.2) + 22;
}

export function GET(req: NextRequest): Response {
  const sp = req.nextUrl.searchParams;
  const outcome = (sp.get("outcome") || sp.get("verdict") || "Pending").trim();
  const left = (sp.get("left") || "verified by calma").trim();
  const right = (sp.get("label") || outcome).trim().slice(0, 64);
  const color = COLOR[outcome] || COLOR.Pending;

  const lt = left.toUpperCase();
  const rt = right.toUpperCase();
  const lw = seg(lt);
  const rw = seg(rt);
  const h = 28;
  const total = lw + rw;

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${total}" height="${h}" role="img" ` +
    `aria-label="${esc(left)}: ${esc(right)}">` +
    `<rect width="${lw}" height="${h}" fill="#161616"/>` +
    `<rect x="${lw}" width="${rw}" height="${h}" fill="${color}"/>` +
    `<g fill="#ffffff" font-family="Verdana,DejaVu Sans,Geneva,sans-serif" font-size="11" ` +
    `font-weight="bold" letter-spacing="1" text-anchor="middle">` +
    `<text x="${lw / 2}" y="18">${esc(lt)}</text>` +
    `<text x="${lw + rw / 2}" y="18">${esc(rt)}</text>` +
    `</g></svg>`;

  return new Response(svg, {
    headers: {
      "content-type": "image/svg+xml; charset=utf-8",
      // short cache so a re-verified verdict updates promptly, long enough to absorb README traffic.
      "cache-control": "public, max-age=300, s-maxage=300",
    },
  });
}
