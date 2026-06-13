"use client";

import { useEffect, useRef } from "react";

/* A live ASCII field rendered to <canvas>. Each variant is a distinct
   procedural motif (no source images): brightness per cell -> a character from
   a density ramp, tinted cream with amber highlights. Automated (time) and
   interactive (brightens under the cursor). Only animates while on screen;
   draws a single static frame under reduced-motion. */

export type AsciiVariant = "rerun" | "verdict" | "claim" | "signed";

const RAMP = " .,:;-~+=icoxsXZO0Qmw*#MW8%B@$";
const MONO = "'Space Mono', ui-monospace, Menlo, monospace";

function smooth(e0: number, e1: number, x: number) {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
}

export function FeatureAscii({ variant }: { variant: AsciiVariant }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const mouse = useRef({ x: 0.6, y: 0.5, on: false });

  useEffect(() => {
    const cvRaw = ref.current;
    if (!cvRaw) return;
    const cxRaw = cvRaw.getContext("2d", { alpha: true });
    if (!cxRaw) return;
    const cv = cvRaw; // narrowed non-null aliases usable inside closures
    const cx = cxRaw;

    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let raf = 0;
    let running = false;
    let t0 = 0;
    let last = 0;
    let cols = 0;
    let rows = 0;
    let cw = 7;
    let ch = 13;
    let W = 0;
    let H = 0;

    const colors: string[] = [];
    for (let i = 0; i < RAMP.length; i++) {
      const f = i / (RAMP.length - 1);
      const a = 0.18 + 0.82 * f;
      colors[i] =
        f > 0.78
          ? `rgba(232,154,93,${Math.min(1, a + 0.08).toFixed(3)})`
          : `rgba(233,221,196,${a.toFixed(3)})`;
    }

    function resize() {
      const r = cv.getBoundingClientRect();
      W = Math.max(1, r.width);
      H = Math.max(1, r.height);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = Math.floor(W * dpr);
      cv.height = Math.floor(H * dpr);
      cx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cw = Math.max(6, Math.round(W / 104));
      ch = Math.round(cw * 1.85);
      cols = Math.ceil(W / cw);
      rows = Math.ceil(H / ch);
      cx.font = `${Math.round(ch * 0.9)}px ${MONO}`;
      cx.textBaseline = "top";
      if (!running) draw(2200);
    }

    function noiseAt(x: number, y: number, t: number) {
      let s = Math.sin(x * 1.7 + t * 0.9) * Math.cos(y * 1.3 - t * 0.5);
      s += 0.5 * Math.sin(x * 3.9 - t * 0.6) * Math.cos(y * 3.1 + t * 0.7);
      return 0.5 + 0.32 * s;
    }

    function field(u: number, v: number, t: number, no: number) {
      const dx = u - 0.5;
      const dy = v - 0.5;
      const r = Math.hypot(dx, dy) * 2;
      const ang = Math.atan2(dy, dx);
      let b = 0;
      if (variant === "rerun") {
        const ring = Math.exp(-Math.pow((r - 0.55) / 0.24, 2));
        const swirl = 0.5 + 0.5 * Math.sin(ang * 4 + t * 1.4 - r * 6);
        b = ring * (0.42 + 0.58 * swirl) + 0.12 * no;
      } else if (variant === "verdict") {
        const band =
          Math.exp(-Math.pow((v - 0.4) / 0.07, 2)) + Math.exp(-Math.pow((v - 0.6) / 0.07, 2));
        const focal = Math.exp(-(Math.pow((u - 0.62) / 0.14, 2) + Math.pow((v - 0.5) / 0.2, 2)));
        b = band * (0.5 + 0.5 * no) + focal * 0.85;
      } else if (variant === "claim") {
        const col = Math.floor(u * cols);
        const h = Math.sin(col * 12.9898) * 43758.5453;
        const cp = h - Math.floor(h);
        let drop = v + t * 0.16 + cp;
        drop = drop - Math.floor(drop);
        const head = Math.pow(1 - drop, 6);
        const colmask = 0.55 + 0.45 * Math.sin(col * 0.7);
        b = head * colmask + 0.08 * no;
      } else {
        const rings = 0.5 + 0.5 * Math.sin(r * 18 - t * 2.2);
        b = rings * smooth(0, 0.85, 1 - r) * 0.85 + Math.exp(-Math.pow(r / 0.4, 2)) * 0.32;
      }
      b *= smooth(0.03, 0.5, u);
      const m = mouse.current;
      if (m.on) {
        const md = Math.exp(-((u - m.x) * (u - m.x) + (v - m.y) * (v - m.y)) / 0.012);
        b = Math.min(1, b + md * 0.55);
      }
      return b < 0 ? 0 : b > 1 ? 1 : b;
    }

    function draw(ts: number) {
      if (!t0) t0 = ts;
      const t = (ts - t0) / 1000;
      cx.clearRect(0, 0, W, H);
      const len = RAMP.length;
      let lastC = -1;
      for (let ry = 0; ry < rows; ry++) {
        const v = (ry + 0.5) / rows;
        const py = ry * ch;
        for (let rx = 0; rx < cols; rx++) {
          const u = (rx + 0.5) / cols;
          const b = field(u, v, t, noiseAt(u * 6, v * 6, t));
          if (b <= 0.05) continue;
          const idx = Math.min(len - 1, Math.floor(b * len));
          const c = RAMP[idx];
          if (c === " ") continue;
          if (idx !== lastC) {
            cx.fillStyle = colors[idx];
            lastC = idx;
          }
          cx.fillText(c, rx * cw, py);
        }
      }
    }

    function frame(ts: number) {
      if (!running) return;
      raf = requestAnimationFrame(frame);
      if (ts - last < 33) return;
      last = ts;
      draw(ts);
    }

    function start() {
      if (running) return;
      if (reduce) {
        draw(2200);
        return;
      }
      running = true;
      raf = requestAnimationFrame(frame);
    }
    function stop() {
      running = false;
      cancelAnimationFrame(raf);
    }

    resize();
    draw(2200);

    const ro = new ResizeObserver(resize);
    ro.observe(cv);
    const io = new IntersectionObserver(
      (es) => {
        for (const e of es) e.isIntersecting ? start() : stop();
      },
      { threshold: 0.01 }
    );
    io.observe(cv);

    const onMove = (e: PointerEvent) => {
      const r = cv.getBoundingClientRect();
      mouse.current = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, on: true };
    };
    const onLeave = () => {
      mouse.current.on = false;
    };
    const onVis = () => {
      if (document.hidden) stop();
    };
    cv.addEventListener("pointermove", onMove);
    cv.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onVis);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(resize).catch(() => {});

    return () => {
      stop();
      ro.disconnect();
      io.disconnect();
      cv.removeEventListener("pointermove", onMove);
      cv.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [variant]);

  return <canvas ref={ref} className="fascii" aria-hidden="true" />;
}
