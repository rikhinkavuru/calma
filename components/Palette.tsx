"use client";

/* The verdicts presented as the system's palette — swatch cards, exactly like a
   design-system color page. REFUTED is the only vermilion on the page section. */

const VERDICTS = [
  {
    nm: "Confirmed",
    hex: "exit 0",
    use: "Re-runs, and the rebuilt number matches the claim within the calibrated budget.",
    chip: { background: "var(--ink)", color: "var(--on-ink)" },
    glyph: "=",
  },
  {
    nm: "Refuted",
    hex: "exit 1 · reproduction attached",
    use: "The recomputed number contradicts the claim. Ships a teardown card and a one-command replay.",
    chip: { background: "var(--vermilion)", color: "var(--on-accent)" },
    glyph: "≠",
  },
  {
    nm: "Can't confirm",
    hex: "exit 1 · fix named",
    use: "Not verifiable yet — and the report says exactly what to change. Never a shrug, never a guess.",
    chip: { background: "var(--paper-deep)", color: "var(--ink)" },
    glyph: "?",
  },
  {
    nm: "Confirmed, with caveats",
    hex: "exit 0 · scope stamped",
    use: "Holds, but narrower than claimed — and the caveat is named on the verdict.",
    chip: { background: "var(--surface)", color: "var(--ink)", borderBottom: "var(--bd-hair)" },
    glyph: "≈",
  },
];

export function Palette() {
  return (
    <section className="section wrap" id="verdicts">
      <div className="sec-head">
        <div>
          <span className="eyebrow">The vocabulary</span>
          <h2 className="sec-title">Four verdicts.</h2>
          <p className="sec-lead">
            Fixed vocabulary, machine-consumable, biased toward a caveat over a false alarm.
            A model can&apos;t author any of them — the ledger re-derives every label and rejects
            mismatches.
          </p>
        </div>
        <div className="index" aria-hidden="true"><span className="lead">0</span>02</div>
      </div>
      <div className="swatches">
        {VERDICTS.map((v) => (
          <div className="swatch" key={v.nm}>
            <div className="chip" style={v.chip}>
              <span className="glyph" aria-hidden="true">{v.glyph}</span>
            </div>
            <div className="meta">
              <div className="nm">{v.nm}</div>
              <div className="hex">{v.hex}</div>
              <div className="use">{v.use}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
