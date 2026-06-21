"use client";

import { useId } from "react";

export type IlloKind =
  | "rerun" | "recompute" | "validity" | "determinism" | "isolation" | "attestation" | "plausibility";

/* warm faces for the isometric blocks */
const TOP = "#f1e7cd", LEFT = "#cdbf9c", RIGHT = "#9b8a69";
const AMBER = "#e89a5d", SUN = "#ffb36b", TEAL = "#7fb89e", CREAM = "#e9ddc4", INK = "#0d0b08";

function Cube({ cx, cy, w, h, top = TOP, left = LEFT, right = RIGHT, o = 1 }: { cx: number; cy: number; w: number; h: number; top?: string; left?: string; right?: string; o?: number }) {
  const t = `${cx},${cy - w / 2}`, r = `${cx + w},${cy}`, b = `${cx},${cy + w / 2}`, l = `${cx - w},${cy}`;
  return (
    <g opacity={o} stroke={INK} strokeOpacity={0.28} strokeWidth={1} strokeLinejoin="round">
      <polygon points={`${l} ${b} ${cx},${cy + w / 2 + h} ${cx - w},${cy + h}`} fill={left} />
      <polygon points={`${b} ${r} ${cx + w},${cy + h} ${cx},${cy + w / 2 + h}`} fill={right} />
      <polygon points={`${t} ${r} ${b} ${l}`} fill={top} />
    </g>
  );
}

function Plate({ cx, cy, w, fill, o = 1 }: { cx: number; cy: number; w: number; fill: string; o?: number }) {
  return <polygon opacity={o} points={`${cx},${cy - w / 2} ${cx + w},${cy} ${cx},${cy + w / 2} ${cx - w},${cy}`} fill={fill} stroke={INK} strokeOpacity={0.25} />;
}

export function CapIllo({ kind }: { kind: IlloKind }) {
  const id = useId().replace(/:/g, "");
  const glow = `g-${id}`;

  return (
    <div className="bp-illo">
      <div className="bp-illo__floor" />
      <svg viewBox="0 0 240 200" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-hidden="true">
        <defs>
          <radialGradient id={glow} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={SUN} stopOpacity="0.55" />
            <stop offset="100%" stopColor={SUN} stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* shared pedestal + glow */}
        <ellipse cx="120" cy="150" rx="92" ry="30" fill={`url(#${glow})`} opacity="0.5" />
        <Cube cx={120} cy={138} w={66} h={12} top="#1a160f" left="#120f0a" right="#0d0b08" />
        <Cube cx={120} cy={120} w={50} h={11} />

        {kind === "rerun" && (
          <>
            <g className="bp-illo__float">
              <Cube cx={120} cy={74} w={26} h={20} />
              {/* re-run orbit ring */}
              <g transform="translate(120 80)">
                <ellipse cx="0" cy="0" rx="46" ry="22" stroke={AMBER} strokeWidth="2.4" fill="none" strokeDasharray="64 18">
                  <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="6s" repeatCount="indefinite" />
                </ellipse>
                <polygon points="46,-2 40,-9 40,5" fill={SUN}>
                  <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="6s" repeatCount="indefinite" />
                </polygon>
              </g>
            </g>
            {/* blocked secret + network */}
            <g transform="translate(44 120)"><rect x="-9" y="-7" width="18" height="14" rx="2" fill={LEFT} stroke={INK} strokeOpacity={0.3} /><path d="M-5 -7v-4a5 5 0 0 1 10 0v4" stroke={INK} strokeOpacity="0.5" fill="none" /><path d="M-11 9 11 -11" stroke="#c34" strokeWidth="2.4" /></g>
            <g transform="translate(196 120)"><circle r="8" fill={TEAL} opacity="0.7" /><path d="M-11 9 11 -11" stroke="#c34" strokeWidth="2.4" /></g>
          </>
        )}

        {kind === "recompute" && (
          <>
            {/* fanned raw-data sheets feeding a processor */}
            <Plate cx={58} cy={92} w={20} fill={CREAM} o={0.5} />
            <Plate cx={62} cy={84} w={20} fill={CREAM} o={0.7} />
            <Plate cx={66} cy={76} w={20} fill="#fff" o={0.92} />
            <path d="M86 80 L108 92" stroke={AMBER} strokeWidth="2" strokeDasharray="3 4" />
            <Cube cx={132} cy={96} w={24} h={16} />
            {/* glowing recomputed output */}
            <g className="bp-illo__float">
              <Cube cx={132} cy={58} w={16} h={13} top={SUN} left={AMBER} right="#b5702f" />
              <circle cx="132" cy="52" r="3" fill={CREAM} />
            </g>
          </>
        )}

        {kind === "validity" && (
          <>
            {/* layered validity planes, one flagged */}
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <Plate key={i} cx={120} cy={106 - i * 11} w={44 - i * 1.5} fill={i === 4 ? AMBER : "rgba(233,221,196,0.5)"} o={i === 4 ? 0.95 : 0.5} />
            ))}
            <g className="bp-illo__float" transform="translate(150 52)">
              <path d="M0 0 v-24" stroke={CREAM} strokeWidth="2" />
              <polygon points="0,-24 22,-19 0,-13" fill="#c34" />
            </g>
          </>
        )}

        {kind === "determinism" && (
          <>
            {/* input vector -> function block (locked) -> one output */}
            {[0, 1, 2].map((i) => <Cube key={i} cx={58} cy={108 - i * 13} w={11} h={8} top={CREAM} left="#c3b58f" right="#9b8a69" />)}
            <path d="M76 96 L100 96" stroke={AMBER} strokeWidth="2" strokeDasharray="3 4" />
            <Cube cx={124} cy={92} w={26} h={18} />
            <g transform="translate(124 84)"><rect x="-7" y="-5" width="14" height="11" rx="2" fill="#1a160f" stroke={SUN} strokeOpacity="0.8" /><path d="M-4 -5v-3a4 4 0 0 1 8 0v3" stroke={SUN} fill="none" /></g>
            <path d="M150 92 L172 92" stroke={AMBER} strokeWidth="2" strokeDasharray="3 4" />
            <g className="bp-illo__float"><Cube cx={188} cy={84} w={13} h={10} top={SUN} left={AMBER} right="#b5702f" /></g>
          </>
        )}

        {kind === "isolation" && (
          <>
            {/* vault walls around a sealed cube */}
            <polygon points="120,52 178,86 178,128 120,94" fill="#171309" stroke={INK} strokeOpacity={0.4} />
            <polygon points="120,52 62,86 62,128 120,94" fill="#1d1810" stroke={INK} strokeOpacity={0.4} />
            <g className="bp-illo__float"><Cube cx={120} cy={86} w={20} h={15} top={SUN} left={AMBER} right="#b5702f" /></g>
            {/* bouncing blocked probes */}
            <g><circle cx="44" cy="92" r="6" fill={TEAL} opacity="0.7" /><path d="M40 96 56 80" stroke="#c34" strokeWidth="2.2" /></g>
            <g><rect x="186" y="98" width="14" height="11" rx="2" fill={LEFT} /><path d="M184 111 202 95" stroke="#c34" strokeWidth="2.2" /></g>
            <path d="M52 90 Q96 70 112 84" stroke={CREAM} strokeOpacity="0.4" strokeWidth="1.4" strokeDasharray="3 5" fill="none" />
          </>
        )}

        {kind === "attestation" && (
          <>
            {/* hash chain of linked blocks ending in a signed seal */}
            {[0, 1, 2].map((i) => <Cube key={i} cx={70 + i * 26} cy={108 - i * 14} w={13} h={10} />)}
            <path d="M83 102 L96 95 M109 88 L122 81" stroke={AMBER} strokeWidth="2.5" />
            <g className="bp-illo__float" transform="translate(150 64)">
              <circle r="17" fill={AMBER} stroke={SUN} strokeWidth="2" />
              <circle r="11" fill="none" stroke="#fff6e6" strokeWidth="1" strokeDasharray="2 3" />
              <path d="M-6 0 l4 5 8 -10" stroke={INK} strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M-6 15 l-3 14 9 -6 9 6 -3 -14" fill={AMBER} stroke={SUN} />
            </g>
          </>
        )}

        {kind === "plausibility" && (
          <>
            {/* histogram + a floating equity ribbon with a flagged smooth run */}
            {[10, 18, 30, 22, 14, 8].map((h, i) => <rect key={i} x={62 + i * 17} y={114 - h} width="11" height={h} fill="rgba(233,221,196,0.4)" />)}
            <g className="bp-illo__float">
              <path d="M58 78 Q92 70 110 60 T168 40" stroke={AMBER} strokeWidth="3" fill="none" strokeLinecap="round" />
              <path d="M110 60 Q140 50 168 40" stroke={SUN} strokeWidth="3" fill="none" strokeLinecap="round" />
              <g transform="translate(150 40)"><path d="M0 0v-20" stroke={CREAM} strokeWidth="1.8" /><polygon points="0,-20 18,-16 0,-11" fill="#c34" /></g>
            </g>
          </>
        )}
      </svg>
    </div>
  );
}
