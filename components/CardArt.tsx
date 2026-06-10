"use client";

/* Simple line-drawn pictures for the benefit cards — hairline strokes,
   one amber accent each, same palette as everything else. */

export function CardArt({ kind }: { kind: "builder" | "team" | "fund" }) {
  if (kind === "builder")
    return (
      <svg className="cart" viewBox="0 0 400 250" aria-hidden="true">
        {/* a terminal window with a verified result */}
        <rect x="60" y="40" width="280" height="170" />
        <line x1="60" y1="72" x2="340" y2="72" />
        <circle cx="78" cy="56" r="4" className="dim" />
        <circle cx="94" cy="56" r="4" className="dim" />
        <circle cx="110" cy="56" r="4" className="dim" />
        <line x1="84" y1="100" x2="250" y2="100" className="dim" />
        <line x1="84" y1="124" x2="290" y2="124" className="dim" />
        <line x1="84" y1="148" x2="210" y2="148" className="dim" />
        <circle cx="104" cy="180" r="14" className="amber" />
        <path d="M97 180 l5 5 l9 -10" className="amber" />
        <text x="130" y="185">checked</text>
      </svg>
    );
  if (kind === "team")
    return (
      <svg className="cart" viewBox="0 0 400 250" aria-hidden="true">
        {/* results queue up to a gate; only what reproduces passes */}
        <circle cx="70" cy="125" r="13" className="dim" />
        <circle cx="120" cy="125" r="13" className="dim" />
        <circle cx="170" cy="125" r="13" />
        <line x1="83" y1="125" x2="107" y2="125" className="dim" />
        <line x1="133" y1="125" x2="157" y2="125" className="dim" />
        <line x1="183" y1="125" x2="207" y2="125" className="dim" />
        <rect x="210" y="65" width="34" height="120" className="amber" />
        <path d="M220 125 l5 5 l9 -10" className="amber" />
        <line x1="244" y1="125" x2="285" y2="125" className="dim" />
        <circle cx="300" cy="125" r="13" />
        <path d="M294 125 l4 4 l8 -9" />
        <text x="200" y="220" textAnchor="middle">the gate</text>
      </svg>
    );
  return (
    <svg className="cart" viewBox="0 0 400 250" aria-hidden="true">
      {/* a signed report with a seal */}
      <rect x="120" y="30" width="160" height="190" />
      <line x1="145" y1="62" x2="255" y2="62" className="dim" />
      <line x1="145" y1="86" x2="235" y2="86" className="dim" />
      <line x1="145" y1="110" x2="255" y2="110" className="dim" />
      <line x1="145" y1="134" x2="215" y2="134" className="dim" />
      <circle cx="232" cy="180" r="20" className="amber" />
      <path d="M224 180 l6 6 l10 -12" className="amber" />
      <line x1="145" y1="188" x2="200" y2="188" />
      <text x="200" y="244" textAnchor="middle">signed &amp; replayable</text>
    </svg>
  );
}
