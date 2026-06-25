"use client";

import { useEffect, useRef } from "react";

/* A live ASCII rendering of a MEANINGFUL icon, one per feature:
   rerun   -> a refresh / re-run loop
   verdict -> a stamped seal with a check
   claim   -> a document of text being read (magnifier)
   signed  -> a signed shield
   The icon is drawn to an offscreen buffer and sampled into the character grid
   (brightness -> character). A soft shimmer + sparse background twinkle keep it
   alive; it also brightens under the cursor. Static frame under reduced motion. */

export type AsciiVariant = "rerun" | "verdict" | "claim" | "signed";

const RAMP = " .,:;-~+=icsxoXZO0Qmw*#MW8%B@$";
const MONO = "'Space Mono', ui-monospace, Menlo, monospace";

function arrowHead(g: CanvasRenderingContext2D, x: number, y: number, ang: number, s: number) {
  g.beginPath();
  g.moveTo(x, y);
  g.lineTo(x + s * Math.cos(ang - 2.5), y + s * Math.sin(ang - 2.5));
  g.moveTo(x, y);
  g.lineTo(x + s * Math.cos(ang + 2.5), y + s * Math.sin(ang + 2.5));
  g.stroke();
}

function drawIcon(g: CanvasRenderingContext2D, variant: AsciiVariant, w: number, h: number) {
  g.clearRect(0, 0, w, h);
  g.strokeStyle = "#fff";
  g.fillStyle = "#fff";
  g.lineCap = "round";
  g.lineJoin = "round";
  const cx = w * 0.5;
  const cy = h * 0.5;
  const R = Math.min(w, h) * 0.52;
  const lw = Math.max(1.4, Math.min(w, h) * 0.038);
  g.lineWidth = lw;

  if (variant === "rerun") {
    const a0 = -Math.PI * 0.62;
    const a1 = Math.PI * 0.28;
    g.beginPath();
    g.arc(cx, cy, R, a1, a0 + Math.PI * 2 - 0.0, false);
    g.stroke();
    // two arrowheads tangent to the ring (clockwise re-run)
    arrowHead(g, cx + R * Math.cos(a1), cy + R * Math.sin(a1), a1 - Math.PI / 2, lw * 2.6);
    const ag = a0 + Math.PI;
    arrowHead(g, cx + R * Math.cos(ag), cy + R * Math.sin(ag), ag - Math.PI / 2, lw * 2.6);
  } else if (variant === "verdict") {
    // notary seal: two rings + radiating ticks + a check
    g.beginPath();
    g.arc(cx, cy, R, 0, Math.PI * 2);
    g.stroke();
    g.beginPath();
    g.arc(cx, cy, R * 0.74, 0, Math.PI * 2);
    g.stroke();
    g.lineWidth = lw * 0.7;
    for (let i = 0; i < 24; i++) {
      const a = (i / 24) * Math.PI * 2;
      g.beginPath();
      g.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R);
      g.lineTo(cx + Math.cos(a) * R * 1.12, cy + Math.sin(a) * R * 1.12);
      g.stroke();
    }
    g.lineWidth = lw * 1.2;
    g.beginPath();
    g.moveTo(cx - R * 0.34, cy + R * 0.02);
    g.lineTo(cx - R * 0.06, cy + R * 0.3);
    g.lineTo(cx + R * 0.42, cy - R * 0.34);
    g.stroke();
  } else if (variant === "claim") {
    // a page of text, with a magnifier over it
    const pw = R * 1.4;
    const ph = R * 1.95;
    const px = cx - pw * 0.62;
    const py = cy - ph / 2;
    g.strokeRect(px, py, pw, ph);
    g.lineWidth = lw * 0.7;
    for (let i = 0; i < 6; i++) {
      const ly = py + ph * (0.16 + i * 0.135);
      g.beginPath();
      g.moveTo(px + pw * 0.16, ly);
      g.lineTo(px + pw * (i % 3 === 2 ? 0.6 : 0.84), ly);
      g.stroke();
    }
    // magnifier
    g.lineWidth = lw;
    const mx = px + pw * 0.96;
    const my = py + ph * 0.62;
    const mr = R * 0.46;
    g.beginPath();
    g.arc(mx, my, mr, 0, Math.PI * 2);
    g.stroke();
    g.beginPath();
    g.moveTo(mx + mr * 0.72, my + mr * 0.72);
    g.lineTo(mx + mr * 1.5, my + mr * 1.5);
    g.stroke();
  } else {
    // signed shield with a check + a baseline (signature)
    const sw = R * 1.7;
    const sh = R * 2.0;
    const sx = cx;
    const top = cy - sh * 0.52;
    g.beginPath();
    g.moveTo(sx, top);
    g.lineTo(sx + sw / 2, top + sh * 0.16);
    g.lineTo(sx + sw / 2, top + sh * 0.52);
    g.quadraticCurveTo(sx + sw / 2, top + sh * 0.9, sx, top + sh);
    g.quadraticCurveTo(sx - sw / 2, top + sh * 0.9, sx - sw / 2, top + sh * 0.52);
    g.lineTo(sx - sw / 2, top + sh * 0.16);
    g.closePath();
    g.stroke();
    g.lineWidth = lw * 1.2;
    g.beginPath();
    g.moveTo(sx - R * 0.36, top + sh * 0.48);
    g.lineTo(sx - R * 0.06, top + sh * 0.64);
    g.lineTo(sx + R * 0.42, top + sh * 0.34);
    g.stroke();
  }
}

function smooth(e0: number, e1: number, x: number) {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
}

export function FeatureAscii({ variant }: { variant: AsciiVariant }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const mouse = useRef({ x: 0.5, y: 0.5, on: false });

  useEffect(() => {
    const cvRaw = ref.current;
    if (!cvRaw) return;
    const cxRaw = cvRaw.getContext("2d", { alpha: true });
    if (!cxRaw) return;
    const cv = cvRaw;
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
    let base = new Float32Array(0); // icon brightness per cell

    const colors: string[] = [];
    for (let i = 0; i < RAMP.length; i++) {
      const f = i / (RAMP.length - 1);
      const a = 0.2 + 0.8 * f;
      colors[i] =
        f > 0.78
          ? `rgba(232,154,93,${Math.min(1, a + 0.08).toFixed(3)})`
          : `rgba(233,221,196,${a.toFixed(3)})`;
    }

    const off = document.createElement("canvas");
    const og = off.getContext("2d", { willReadFrequently: true });

    function buildBase() {
      if (!og) return;
      const SS = 2; // supersample for smoother edges
      off.width = Math.max(2, cols * SS);
      off.height = Math.max(2, rows * SS);
      // Each character cell renders ch/cw (~1.85x) taller than wide, so a circle
      // drawn round in this cell grid would stretch vertically on screen. Pre-
      // compress the icon vertically by cw/ch about the buffer center so it
      // renders with the correct (un-smushed) aspect ratio.
      og.save();
      og.clearRect(0, 0, off.width, off.height);
      og.translate(off.width / 2, off.height / 2);
      og.scale(1, cw / ch);
      og.translate(-off.width / 2, -off.height / 2);
      drawIcon(og, variant, off.width, off.height);
      og.restore();
      const data = og.getImageData(0, 0, off.width, off.height).data;
      base = new Float32Array(cols * rows);
      for (let ry = 0; ry < rows; ry++) {
        for (let rx = 0; rx < cols; rx++) {
          let sum = 0;
          for (let sy = 0; sy < SS; sy++) {
            for (let sx = 0; sx < SS; sx++) {
              const px = (rx * SS + sx) + (ry * SS + sy) * off.width;
              sum += data[px * 4 + 3]; // alpha = ink coverage
            }
          }
          base[ry * cols + rx] = sum / (SS * SS * 255);
        }
      }
    }

    function resize() {
      const r = cv.getBoundingClientRect();
      W = Math.max(1, r.width);
      H = Math.max(1, r.height);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = Math.floor(W * dpr);
      cv.height = Math.floor(H * dpr);
      cx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cw = Math.max(6, Math.round(W / 96));
      ch = Math.round(cw * 1.85);
      cols = Math.ceil(W / cw);
      rows = Math.ceil(H / ch);
      cx.font = `${Math.round(ch * 0.9)}px ${MONO}`;
      cx.textBaseline = "top";
      buildBase();
      if (!running) draw(2200);
    }

    function twinkle(x: number, y: number, t: number) {
      const s = Math.sin(x * 12.9 + t * 0.7) * Math.cos(y * 7.3 - t * 0.9);
      return s * 0.5 + 0.5;
    }

    function draw(ts: number) {
      if (!t0) t0 = ts;
      const t = (ts - t0) / 1000;
      cx.clearRect(0, 0, W, H);
      const len = RAMP.length;
      let lastC = -1;
      const m = mouse.current;
      for (let ry = 0; ry < rows; ry++) {
        const v = (ry + 0.5) / rows;
        const py = ry * ch;
        for (let rx = 0; rx < cols; rx++) {
          const u = (rx + 0.5) / cols;
          const ink = base[ry * cols + rx] || 0;
          let b: number;
          if (ink > 0.04) {
            // the icon: full brightness with a gentle vertical shimmer
            b = ink * (0.78 + 0.22 * (0.5 + 0.5 * Math.sin((v * 3.2 - t * 1.1) * Math.PI)));
          } else {
            // sparse background twinkle — texture, never noise-soup
            const tw = twinkle(u, v, t);
            b = tw > 0.9 ? (tw - 0.9) * 1.4 : 0;
          }
          b *= smooth(0.03, 0.42, u); // fade toward the text on the left
          if (m.on) {
            const md = Math.exp(-((u - m.x) * (u - m.x) + (v - m.y) * (v - m.y)) / 0.012);
            b = Math.min(1, b + md * 0.5);
          }
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
      if (ts - last < 40) return;
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
