// Shared verdict grouping for the dashboard + demo results tables (VerifyClient.tsx, DemoClient.tsx). The
// engine's 7 verdicts (spike/core/verdict.py) are each precise on purpose, but shown flat they read as noise
// — and worse, everything that wasn't a bare CONFIRMED/REFUTED/INVALIDATED used to render as the SAME grey
// pill, so "we tried hard and genuinely can't tell" (REPRODUCED-ONLY, INCONCLUSIVE) looked identical to "we
// haven't checked yet" (DISCOVERED). This maps each verdict to one of 6 visual tiers, reusing the palette
// dashboard.module.css already defines (ok/bad/warn/inv/neu/idle) but that was never fully wired up.
export type PillTier = "ok" | "bad" | "warn" | "inv" | "neu" | "idle";

// CONFIRMED + CONFIRMED-STOCHASTIC are BOTH the engine's affirmative verdicts (core/verdict.py's own
// AFFIRMATIVE tuple) — CONFIRMED-STOCHASTIC used to fall through to the neutral grey pill despite being a
// real, positive result (a statistically-confirmed claim on a non-deterministic run).
const OK = new Set(["CONFIRMED", "CONFIRMED-STOCHASTIC"]);
const BAD = new Set(["REFUTED"]);                       // a plain misreport: the claimed number is just wrong
const INVALID = new Set(["INVALIDATED"]);                // a deeper catch: the repo's own formula is wrong/cheating
const NEUTRAL = new Set(["NON-DETERMINISTIC"]);          // not a lie — the number just isn't stable enough to trust
const UNVERIFIABLE = new Set(["REPRODUCED-ONLY", "INCONCLUSIVE"]);  // tried hard, genuinely can't confirm or deny

export function pillTier(verdict: string): PillTier {
  if (OK.has(verdict)) return "ok";
  if (BAD.has(verdict)) return "bad";
  if (INVALID.has(verdict)) return "inv";
  if (NEUTRAL.has(verdict)) return "neu";
  if (UNVERIFIABLE.has(verdict)) return "warn";
  return "idle";                                          // DISCOVERED (and anything unrecognized) — not yet checked
}

// A short, human label for the pill/summary — the raw verdict string doubles as this for most cases, but a
// couple read better paraphrased for a first-time viewer.
export function verdictLabel(verdict: string): string {
  if (verdict === "REPRODUCED-ONLY") return "REPRODUCED, UNVERIFIED";
  return verdict;
}

// Needs-a-human's-attention filter (the dashboard's "Problems" quick-filter) — broader than just BAD/INVALID:
// a non-deterministic number is just as worth a second look as a caught misreport, even though it isn't a
// "gotcha" in the same sense.
export const PROBLEMS = ["REFUTED", "INVALIDATED", "NON-DETERMINISTIC"];

// display order: catches first (most actionable), then confirms, then the honest-uncertainty tiers, then
// not-yet-checked last.
export const ORDER = [
  "REFUTED", "INVALIDATED",
  "CONFIRMED", "CONFIRMED-STOCHASTIC",
  "NON-DETERMINISTIC", "REPRODUCED-ONLY", "INCONCLUSIVE",
  "DISCOVERED",
];

// Tier-level summary for the results view: a big claim list is noise until it's grouped. Order matches
// ORDER's priority — issues first, confirms next, the honest-uncertainty tiers, not-yet-checked last.
export const TIER_META: { tier: PillTier; label: string; issue: boolean }[] = [
  { tier: "bad", label: "caught", issue: true },              // REFUTED — a plain misreport
  { tier: "inv", label: "invalidated", issue: true },         // INVALIDATED — the repo's own formula is wrong
  { tier: "neu", label: "unstable", issue: true },            // NON-DETERMINISTIC — can't be trusted as-is
  { tier: "ok", label: "confirmed", issue: false },
  { tier: "warn", label: "unverifiable", issue: false },      // REPRODUCED-ONLY / INCONCLUSIVE
  { tier: "idle", label: "not checked yet", issue: false },   // DISCOVERED
];

// "Issues" = the tiers worth a human's attention by default (mirrors PROBLEMS, but at tier granularity).
export const ISSUE_TIERS: PillTier[] = TIER_META.filter((t) => t.issue).map((t) => t.tier);

// Roll a per-verdict counts map (job.counts, e.g. {"REFUTED": 2, "CONFIRMED": 5}) up into per-tier totals.
export function tierCounts(counts: Record<string, number>): Record<PillTier, number> {
  const out: Record<PillTier, number> = { ok: 0, bad: 0, warn: 0, inv: 0, neu: 0, idle: 0 };
  for (const [verdict, n] of Object.entries(counts || {})) out[pillTier(verdict)] += n;
  return out;
}
