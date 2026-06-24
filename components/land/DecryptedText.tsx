"use client";

import { useEffect, useRef, useState } from "react";

/* React Bits-style "decrypt" text: scrambles glyphs, then resolves to the target left-to-right.
   Re-runs whenever `text` (or `runKey`) changes — used for the recomputed number re-deriving. */
const GLYPHS = "0123456789ABCDEFXYZ$%+-.";

export function DecryptedText({
  text,
  className = "",
  duration = 850,
  runKey,
}: {
  text: string;
  className?: string;
  duration?: number;
  runKey?: string | number;
}) {
  const [display, setDisplay] = useState(text);
  const reduce = useRef(false);

  useEffect(() => {
    reduce.current =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce.current) {
      setDisplay(text);
      return;
    }
    let raf = 0;
    let start: number | null = null;
    const tick = (t: number) => {
      if (start === null) start = t;
      const p = Math.min(1, (t - start) / duration);
      const reveal = Math.floor(p * text.length);
      let out = "";
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        out += i < reveal || ch === " " ? ch : GLYPHS[(Math.random() * GLYPHS.length) | 0];
      }
      setDisplay(out);
      if (p < 1) raf = requestAnimationFrame(tick);
      else setDisplay(text);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [text, duration, runKey]);

  return (
    <span className={className} aria-label={text}>
      {display}
    </span>
  );
}
