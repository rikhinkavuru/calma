import styles from "./dashboard.module.css";

export type Outcome = { name: string; glyph: string; cls: string; key: "ok" | "bad" | "idle" | "pending" };

// The deterministic 6 -> 3 roll-up, mirrored from the engine's verdict.outcome()
// (kept in sync by the reference docs). Anything unknown degrades to Can't-tell
// (fail-closed, never a green pass).
export function outcome(verdict?: string): Outcome {
  const v = (verdict || "").toUpperCase();
  if (v === "CONFIRMED" || v === "CONFIRMED-WITH-CAVEATS")
    return { name: "Confirmed", glyph: "✓", cls: styles.bConfirmed, key: "ok" };
  if (["REFUTED", "INVALIDATED", "FLAG_FOR_DECLARATION", "MIXED"].includes(v))
    return { name: "Caught", glyph: "✗", cls: styles.bRefuted, key: "bad" };
  if (v === "INCONCLUSIVE" || v === "CAN'T-CONFIRM")
    return { name: "Can't tell", glyph: "?", cls: styles.bInconcl, key: "idle" };
  return { name: verdict || "pending", glyph: "·", cls: styles.bInconcl, key: "pending" };
}
