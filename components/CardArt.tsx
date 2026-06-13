"use client";

/* Simple line-drawn pictures for the benefit cards — hairline strokes,
   one amber accent each, same palette as everything else. */

type Kind =
  | "builder" | "team" | "fund"
  | "rerun" | "verdict" | "claim" | "signed";

export function CardArt({ kind }: { kind: Kind }) {
  if (kind === "rerun")
    return (
      <svg className="cart" viewBox="0 0 400 250" aria-hidden="true">
        {/* the work re-runs from scratch inside a sealed sandbox */}
        <rect x="64" y="44" width="272" height="162" rx="2" />
        <line x1="64" y1="78" x2="336" y2="78" />
        <circle cx="84" cy="61" r="3.5" className="dim" />
        <circle cx="98" cy="61" r="3.5" className="dim" />
        <circle cx="112" cy="61" r="3.5" className="dim" />
        <line x1="92" y1="104" x2="248" y2="104" className="dim" />
        <line x1="92" y1="128" x2="288" y2="128" className="dim" />
        <line x1="92" y1="152" x2="214" y2="152" className="dim" />
        <path d="M232 176 a30 30 0 1 1 -10 -22" className="amber" />
        <path d="M218 148 l5 10 l10 -3" className="amber" />
        <text x="200" y="232" textAnchor="middle">re-run, sealed</text>
      </svg>
    );
  if (kind === "verdict")
    return (
      <svg className="cart" viewBox="0 0 400 250" aria-hidden="true">
        {/* claimed vs rebuilt — code decides, not a model */}
        <text x="58" y="86">claimed</text>
        <line x1="56" y1="100" x2="150" y2="100" className="dim" />
        <text x="58" y="150">rebuilt</text>
        <line x1="56" y1="164" x2="116" y2="164" className="dim" />
        <line x1="206" y1="116" x2="246" y2="116" className="amber" />
        <line x1="206" y1="134" x2="246" y2="134" className="amber" />
        <line x1="240" y1="104" x2="212" y2="146" className="amber" />
        <rect x="280" y="100" width="74" height="50" className="amber" />
        <path d="M298 126 l8 8 l16 -18" className="amber" />
        <text x="200" y="216" textAnchor="middle">deterministic</text>
      </svg>
    );
  if (kind === "claim")
    return (
      <svg className="cart" viewBox="0 0 400 250" aria-hidden="true">
        {/* plain words → the exact column in the output file */}
        <rect x="40" y="44" width="150" height="34" />
        <text x="54" y="66">Sharpe 2.1</text>
        <path d="M150 92 q44 26 66 44" className="amber" />
        <path d="M210 124 l8 12 l9 -7" className="amber" />
        <rect x="222" y="96" width="146" height="110" />
        <line x1="271" y1="96" x2="271" y2="206" className="dim" />
        <line x1="320" y1="96" x2="320" y2="206" className="dim" />
        <line x1="222" y1="124" x2="368" y2="124" className="dim" />
        <line x1="222" y1="152" x2="368" y2="152" className="dim" />
        <line x1="222" y1="180" x2="368" y2="180" className="dim" />
        <rect x="320" y="96" width="48" height="110" className="amber" />
        <text x="204" y="234" textAnchor="middle">found, not guessed</text>
      </svg>
    );
  if (kind === "signed")
    return (
      <svg className="cart" viewBox="0 0 400 250" aria-hidden="true">
        {/* a signed report, and a chain that compounds */}
        <rect x="128" y="28" width="144" height="138" />
        <line x1="150" y1="58" x2="250" y2="58" className="dim" />
        <line x1="150" y1="80" x2="232" y2="80" className="dim" />
        <line x1="150" y1="102" x2="250" y2="102" className="dim" />
        <circle cx="222" cy="136" r="17" className="amber" />
        <path d="M214 136 l6 6 l12 -13" className="amber" />
        <circle cx="150" cy="206" r="9" className="dim" />
        <circle cx="178" cy="206" r="9" className="dim" />
        <circle cx="206" cy="206" r="9" className="dim" />
        <circle cx="234" cy="206" r="9" className="amber" />
        <line x1="159" y1="206" x2="169" y2="206" className="dim" />
        <line x1="187" y1="206" x2="197" y2="206" className="dim" />
        <line x1="215" y1="206" x2="225" y2="206" className="dim" />
        <text x="200" y="240" textAnchor="middle">signed · logged</text>
      </svg>
    );
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
