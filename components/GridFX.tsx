"use client";

import { useEffect, useRef } from "react";

/* Lightweight canvas backdrop: a faint dot lattice with a slow signal sweep that briefly
   "verifies" dots (green flash) as it passes. ~2KB, no deps, pauses for reduced motion. */
export function GridFX() {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let w = 0;
    let h = 0;
    let raf = 0;
    const GAP = 36;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const resize = () => {
      const rect = canvas.parentElement?.getBoundingClientRect();
      w = rect?.width || window.innerWidth;
      h = rect?.height || 600;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      const sweep = reduced ? -1 : ((t * 0.05) % (w + 400)) - 200;
      for (let x = GAP / 2; x < w; x += GAP) {
        for (let y = GAP / 2; y < h; y += GAP) {
          const d = Math.abs(x - sweep);
          // fade the lattice toward the bottom so the terminal sits on clean black
          const fade = Math.max(0, 1 - y / (h * 0.85));
          if (d < 70 && !reduced) {
            const k = 1 - d / 70;
            ctx.fillStyle = `rgba(74, 222, 128, ${(0.05 + 0.3 * k) * fade})`;
            ctx.fillRect(x - 1, y - 1, 2, 2);
          } else {
            ctx.fillStyle = `rgba(250, 250, 250, ${0.05 * fade})`;
            ctx.fillRect(x - 0.5, y - 0.5, 1, 1);
          }
        }
      }
      if (!reduced) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={ref} className="hero__fx" aria-hidden="true" />;
}
