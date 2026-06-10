"use client";

import { useEffect, useRef, useState } from "react";

/* A pallet of strapped cash bundles, rendered honestly: procedural banknote faces
   (engraved border, portrait oval, corner denominations, guilloche shading), striped
   note-edge sides, mustard currency straps, crisscross stacking. Paper, not chrome.
   Interaction: HOVER ONLY — layers breathe apart and the pallet leans toward the cursor. */

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

/* engraved banknote face, drawn once */
function noteFace(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 256;
  const x = c.getContext("2d")!;
  // paper — proper money green
  const bg = x.createLinearGradient(0, 0, 0, 256);
  bg.addColorStop(0, "#9fb292");
  bg.addColorStop(1, "#86997a");
  x.fillStyle = bg;
  x.fillRect(0, 0, 512, 256);
  // fine horizontal engraving lines
  x.strokeStyle = "rgba(38, 54, 34, 0.28)";
  x.lineWidth = 1;
  for (let y = 6; y < 256; y += 5) {
    x.beginPath();
    x.moveTo(8, y);
    x.lineTo(504, y);
    x.stroke();
  }
  // double border
  x.strokeStyle = "#2c3d27";
  x.lineWidth = 5;
  x.strokeRect(12, 12, 488, 232);
  x.lineWidth = 1.5;
  x.strokeRect(24, 24, 464, 208);
  // guilloche corners (overlapping arcs)
  x.strokeStyle = "rgba(66, 86, 60, 0.5)";
  x.lineWidth = 1;
  for (const [cx, cy] of [[40, 40], [472, 40], [40, 216], [472, 216]] as const) {
    for (let r = 6; r <= 26; r += 4) {
      x.beginPath();
      x.arc(cx, cy, r, 0, Math.PI * 2);
      x.stroke();
    }
  }
  // central portrait oval
  x.save();
  x.translate(256, 128);
  for (let r = 0; r < 26; r++) {
    x.beginPath();
    x.ellipse(0, 0, 64 - r * 1.6, 88 - r * 2.4, 0, 0, Math.PI * 2);
    x.strokeStyle = `rgba(58, 76, 52, ${0.10 + r * 0.012})`;
    x.stroke();
  }
  x.restore();
  // side ornament medallions
  for (const ox of [110, 402]) {
    x.beginPath();
    x.arc(ox, 128, 34, 0, Math.PI * 2);
    x.strokeStyle = "rgba(66, 86, 60, 0.65)";
    x.lineWidth = 2;
    x.stroke();
    x.beginPath();
    x.arc(ox, 128, 26, 0, Math.PI * 2);
    x.lineWidth = 1;
    x.stroke();
  }
  // denominations
  x.fillStyle = "#33452e";
  x.font = "700 34px Georgia, serif";
  x.textAlign = "center";
  x.textBaseline = "middle";
  for (const [dx, dy] of [[58, 58], [454, 58], [58, 198], [454, 198]] as const) {
    x.fillText("100", dx, dy);
  }
  x.font = "700 13px Georgia, serif";
  x.fillText("VERIFIED RESERVE NOTE", 256, 38);
  return c;
}

/* stacked note edges (the side of a bundle) */
function noteEdge(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 64;
  const x = c.getContext("2d")!;
  x.fillStyle = "#c3ccb4";
  x.fillRect(0, 0, 256, 64);
  for (let y = 0; y < 64; y += 2) {
    x.fillStyle = y % 4 ? "rgba(74, 88, 64, 0.5)" : "rgba(240, 244, 230, 0.6)";
    x.fillRect(0, y, 256, 1);
  }
  // slight unevenness
  x.fillStyle = "rgba(58, 72, 50, 0.3)";
  for (let i = 0; i < 40; i++) {
    x.fillRect(Math.random() * 256, Math.random() * 64, 12 + Math.random() * 30, 1);
  }
  return c;
}

export function MoneyStack() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let disposed = false;
    let cleanup: (() => void) | null = null;

    if (!webglAvailable()) {
      setFallback(true);
      return;
    }

    (async () => {
      const THREE = await import("three");
      const { RoomEnvironment } = await import("three/examples/jsm/environments/RoomEnvironment.js");
      if (disposed || !el) return;

      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      let renderer: import("three").WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      } catch {
        setFallback(true);
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(el.clientWidth, el.clientHeight);
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 0.92;
      el.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(34, el.clientWidth / el.clientHeight, 0.1, 60);
      camera.position.set(3.6, 1.9, 5.0);
      camera.lookAt(0, 0.75, 0);

      const pmrem = new THREE.PMREMGenerator(renderer);
      const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      scene.environment = env;
      scene.environmentIntensity = 0.35;

      const key = new THREE.DirectionalLight(0xfff0d8, 1.25);
      key.position.set(4, 6, 3);
      const rim = new THREE.DirectionalLight(0x9db5ff, 0.7);
      rim.position.set(-5, 3, -4);
      scene.add(key, rim, new THREE.AmbientLight(0x35353f, 0.9));

      // textures
      const faceTex = new THREE.CanvasTexture(noteFace());
      faceTex.anisotropy = 4;
      const edgeTex = new THREE.CanvasTexture(noteEdge());
      edgeTex.wrapS = THREE.RepeatWrapping;

      const faceMat = new THREE.MeshStandardMaterial({ map: faceTex, roughness: 0.92, metalness: 0, envMapIntensity: 0.25 });
      const edgeMat = new THREE.MeshStandardMaterial({ map: edgeTex, roughness: 0.95, metalness: 0, envMapIntensity: 0.2 });
      const strapMat = new THREE.MeshStandardMaterial({ color: 0xc9962e, roughness: 0.55, metalness: 0, envMapIntensity: 0.4 });

      // one bundle: note box (W 2.2, H 0.42, D 1.0) + strap
      const W = 2.2, H = 0.46, D = 1.0;
      const bundleGeo = new THREE.BoxGeometry(W, H, D);
      const bundleMats = [edgeMat, edgeMat, faceMat, faceMat, edgeMat, edgeMat]; // +x,-x,+y,-y,+z,-z
      const strapGeo = new THREE.BoxGeometry(0.34, H + 0.02, D + 0.02);

      function makeBundle() {
        const g = new THREE.Group();
        const box = new THREE.Mesh(bundleGeo, bundleMats);
        const strap = new THREE.Mesh(strapGeo, strapMat);
        g.add(box, strap);
        return g;
      }

      // pallet: crisscross layers, 2 bundles per layer
      const pallet = new THREE.Group();
      type Slot = { g: import("three").Group; base: { x: number; y: number; z: number; ry: number }; layer: number };
      const slots: Slot[] = [];
      const LAYERS = 4;
      for (let l = 0; l < LAYERS; l++) {
        const cross = l % 2 === 1;
        for (let k = 0; k < 2; k++) {
          const g = makeBundle();
          const off = (k - 0.5) * (D + 0.06);
          const base = {
            x: cross ? off : (Math.sin(l * 7.3 + k) * 0.03),
            z: cross ? (Math.cos(l * 5.1 + k) * 0.03) : off,
            y: l * (H + 0.012) + H / 2,
            ry: (cross ? Math.PI / 2 : 0) + Math.sin(l * 12.9 + k * 3.7) * 0.05,
          };
          g.position.set(base.x, base.y, base.z);
          g.rotation.y = base.ry;
          pallet.add(g);
          slots.push({ g, base, layer: l });
        }
      }
      // one loose note resting on top
      const loose = new THREE.Mesh(
        new THREE.BoxGeometry(W * 0.98, 0.012, D * 0.98),
        [edgeMat, edgeMat, faceMat, faceMat, edgeMat, edgeMat]
      );
      loose.position.set(0.18, LAYERS * (H + 0.012) + 0.02, 0.1);
      loose.rotation.y = 0.4;
      pallet.add(loose);

      pallet.position.y = -0.95;
      scene.add(pallet);

      // hover state
      let hover = 0;
      let hoverTarget = 0;
      const mouse = { x: 0, y: 0 };
      const onEnter = () => (hoverTarget = 1);
      const onLeave = () => (hoverTarget = 0);
      const onMove = (e: PointerEvent) => {
        const r = el.getBoundingClientRect();
        mouse.x = ((e.clientX - r.left) / r.width - 0.5) * 2;
        mouse.y = ((e.clientY - r.top) / r.height - 0.5) * 2;
      };
      el.addEventListener("pointerenter", onEnter);
      el.addEventListener("pointerleave", onLeave);
      el.addEventListener("pointermove", onMove);

      const clock = new THREE.Clock();
      let raf = 0;
      const frame = () => {
        const dt = Math.min(clock.getDelta(), 0.05);
        const t = clock.elapsedTime;
        hover += (hoverTarget - hover) * Math.min(1, dt * 5);

        pallet.rotation.y = t * 0.16 + mouse.x * 0.22 * hover;
        pallet.rotation.x = mouse.y * 0.1 * hover;
        pallet.position.y = -0.95 + Math.sin(t * 0.7) * 0.025;

        for (const s of slots) {
          const lift = s.layer * 0.11 * hover;
          s.g.position.y += (s.base.y + lift - s.g.position.y) * Math.min(1, dt * 6);
          const spread = 1 + 0.06 * hover;
          s.g.position.x += (s.base.x * spread - s.g.position.x) * Math.min(1, dt * 6);
          s.g.position.z += (s.base.z * spread - s.g.position.z) * Math.min(1, dt * 6);
          s.g.rotation.y += (s.base.ry + s.layer * 0.05 * hover - s.g.rotation.y) * Math.min(1, dt * 6);
        }
        loose.position.y = LAYERS * (H + 0.012) + 0.02 + LAYERS * 0.11 * hover + Math.sin(t * 1.3) * 0.012;

        renderer.render(scene, camera);
        if (!reduced) raf = requestAnimationFrame(frame);
      };

      if (reduced) {
        renderer.render(scene, camera);
      } else {
        raf = requestAnimationFrame(frame);
      }

      const onResize = () => {
        const w = el.clientWidth;
        const h = el.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
        if (reduced) renderer.render(scene, camera);
      };
      const ro = new ResizeObserver(onResize);
      ro.observe(el);

      cleanup = () => {
        cancelAnimationFrame(raf);
        ro.disconnect();
        el.removeEventListener("pointerenter", onEnter);
        el.removeEventListener("pointerleave", onLeave);
        el.removeEventListener("pointermove", onMove);
        bundleGeo.dispose();
        strapGeo.dispose();
        faceMat.dispose();
        edgeMat.dispose();
        strapMat.dispose();
        faceTex.dispose();
        edgeTex.dispose();
        env.dispose();
        pmrem.dispose();
        renderer.dispose();
        el.contains(renderer.domElement) && el.removeChild(renderer.domElement);
      };
    })();

    return () => {
      disposed = true;
      cleanup?.();
    };
  }, []);

  return (
    <div
      ref={ref}
      style={{ position: "absolute", inset: 0 }}
      role="img"
      aria-label="A pallet of strapped cash bundles — the money that moves on AI's numbers"
    >
      {fallback && (
        <svg viewBox="0 0 240 200" aria-hidden="true" style={{ width: "60%", maxWidth: 360, margin: "auto", position: "absolute", inset: 0 }}>
          {[0, 1, 2, 3].map((i) => (
            <g key={i} transform={`translate(${(i % 2) * 8} ${140 - i * 26})`}>
              <rect x="40" y="0" width="150" height="22" fill="#b7c4ab" stroke="#42563c" strokeWidth="1.5" />
              <rect x="100" y="0" width="26" height="22" fill="#d7a93c" />
            </g>
          ))}
        </svg>
      )}
    </div>
  );
}
