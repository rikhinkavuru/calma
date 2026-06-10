"use client";

import { useEffect, useRef, useState } from "react";

/* The one loud element: a stack of iridescent chrome notes on the void stage.
   Hover — the stack fans apart, under inspection.
   Click — a flare scan line sweeps it, one counterfeit note flashes, gets ejected,
   and falls out of the stack; the rest close ranks. Then the stack resets.
   That is the product: Calma inspects the money before it moves.
   SVG fallback without WebGL; a static fanned pose under reduced motion. */

const COUNT = 9;
const BAD = 5;

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
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
      renderer.toneMappingExposure = 1.1;
      el.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(34, el.clientWidth / el.clientHeight, 0.1, 60);
      camera.position.set(3.0, 2.6, 4.6);
      camera.lookAt(0, 0.45, 0);

      const pmrem = new THREE.PMREMGenerator(renderer);
      const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      scene.environment = env;

      const l1 = new THREE.PointLight(0x18e0ff, 30, 0, 2);
      l1.position.set(-4, 3, 3);
      const l2 = new THREE.PointLight(0xff8fd6, 24, 0, 2);
      l2.position.set(4, 1.5, -2.5);
      const l3 = new THREE.PointLight(0xc9f24a, 12, 0, 2);
      l3.position.set(0, -2.5, 3.5);
      scene.add(l1, l2, l3);

      // notes
      const geo = new THREE.BoxGeometry(2.3, 0.085, 1.15);
      const baseMat = new THREE.MeshPhysicalMaterial({
        color: 0xc9ccd3,
        metalness: 1,
        roughness: 0.22,
        envMapIntensity: 1.4,
        iridescence: 0.9,
        iridescenceIOR: 1.7,
        iridescenceThicknessRange: [120, 700],
        clearcoat: 0.5,
        clearcoatRoughness: 0.3,
      });
      const badMat = baseMat.clone();
      badMat.transparent = true;

      const group = new THREE.Group();
      const notes: import("three").Mesh[] = [];
      const jit: { ry: number; x: number; z: number }[] = [];
      for (let i = 0; i < COUNT; i++) {
        const m = new THREE.Mesh(geo, i === BAD ? badMat : baseMat);
        const j = {
          ry: (Math.sin(i * 12.9898) * 0.5) * 0.16,
          x: Math.sin(i * 78.233) * 0.05,
          z: Math.cos(i * 39.425) * 0.04,
        };
        jit.push(j);
        group.add(m);
        notes.push(m);
      }
      scene.add(group);

      // flare scan plane
      const scanMat = new THREE.MeshBasicMaterial({
        color: 0xff4a14,
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
      });
      const scan = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 1.7), scanMat);
      scan.rotation.x = -Math.PI / 2;
      group.add(scan);

      // interaction state
      let hover = 0; // lerped 0..1
      let hoverTarget = 0;
      let clickT = -1; // seconds since click, -1 = idle
      const onEnter = () => (hoverTarget = 1);
      const onLeave = () => (hoverTarget = 0);
      const onClick = () => {
        if (clickT < 0 || clickT > 4.4) clickT = 0;
      };
      el.addEventListener("pointerenter", onEnter);
      el.addEventListener("pointerleave", onLeave);
      el.addEventListener("click", onClick);

      const H = 0.105; // note pitch
      const clock = new THREE.Clock();
      let raf = 0;

      const frame = () => {
        const dt = Math.min(clock.getDelta(), 0.05);
        const t = clock.elapsedTime;
        if (clickT >= 0) clickT += dt;

        hover = hover + (hoverTarget - hover) * Math.min(1, dt * 6);
        group.rotation.y = t * 0.22;
        group.position.y = -0.35 + Math.sin(t * 0.8) * 0.03;

        // click phases
        const c = clickT;
        const scanning = c >= 0 && c < 0.8;
        const flash = c >= 0.8 && c < 1.2;
        const eject = c >= 1.0 && c < 2.2;
        const fall = c >= 1.6 && c < 3.4;
        const restack = c >= 1.6;
        const resetting = c >= 3.6 && c < 4.4;

        scanMat.opacity = scanning ? 0.55 : 0;
        if (scanning) scan.position.y = (1 - c / 0.8) * COUNT * H + 0.1;

        badMat.emissive.setHex(0xff4a14);
        badMat.emissiveIntensity = flash ? (1 - (c - 0.8) / 0.4) * 1.6 : eject ? 0.5 : 0;

        for (let i = 0; i < COUNT; i++) {
          const n = notes[i];
          // restacked index: notes above the ejected one settle down
          const idx = restack && i > BAD ? i - 1 : i;
          let tx = jit[i].x + (i % 2 ? 1 : -1) * 0.1 * hover;
          let ty = idx * H + idx * 0.085 * hover;
          let tz = jit[i].z;
          let rz = (i - (COUNT - 1) / 2) * 0.055 * hover;
          const ry = jit[i].ry + (i - (COUNT - 1) / 2) * 0.06 * hover;

          if (i === BAD && c >= 1.0) {
            const e = Math.min(1, (c - 1.0) / 0.6);
            tx += e * e * 2.9; // slide out
            ty = BAD * H + (fall ? -4.2 * Math.pow(Math.max(0, c - 1.6), 2) : 0);
            rz = -e * 0.35 - Math.max(0, c - 1.6) * 1.4;
            badMat.opacity = fall ? Math.max(0, 1 - (c - 1.6) / 1.4) : 1;
          } else {
            badMat.opacity = badMat.opacity; // unchanged for others
          }
          if (i === BAD && resetting) {
            const r = (c - 3.6) / 0.8;
            tx = jit[i].x + (1 - r) * 0.4;
            ty = BAD * H;
            rz = 0;
            badMat.opacity = r;
          }

          n.position.x += (tx - n.position.x) * Math.min(1, dt * 7);
          n.position.y += (ty - n.position.y) * Math.min(1, dt * 7);
          n.position.z += (tz - n.position.z) * Math.min(1, dt * 7);
          n.rotation.z += (rz - n.rotation.z) * Math.min(1, dt * 7);
          n.rotation.y += (ry - n.rotation.y) * Math.min(1, dt * 7);
        }

        if (clickT > 4.4) clickT = -1;

        renderer.render(scene, camera);
        if (!reduced) raf = requestAnimationFrame(frame);
      };

      if (reduced) {
        // a single considered pose: gently fanned
        hover = 0.6;
        for (let i = 0; i < COUNT; i++) {
          const n = notes[i];
          n.position.set(
            jit[i].x + (i % 2 ? 1 : -1) * 0.06,
            i * H + i * 0.05,
            jit[i].z
          );
          n.rotation.z = (i - 4) * 0.035;
          n.rotation.y = jit[i].ry;
        }
        group.position.y = -0.35;
        group.rotation.y = 0.5;
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
        el.removeEventListener("click", onClick);
        geo.dispose();
        baseMat.dispose();
        badMat.dispose();
        scan.geometry.dispose();
        scanMat.dispose();
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
      style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
      role="img"
      aria-label="A stack of chrome notes under audit — click to watch Calma catch the counterfeit one"
    >
      {fallback && (
        <svg viewBox="0 0 240 200" aria-hidden="true" style={{ width: "56%", maxWidth: 360 }}>
          <defs>
            <linearGradient id="holoNote" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#18e0ff" />
              <stop offset=".33" stopColor="#c9f24a" />
              <stop offset=".62" stopColor="#ff8fd6" />
              <stop offset="1" stopColor="#29c8ff" />
            </linearGradient>
          </defs>
          {[0, 1, 2, 3, 4, 5, 6].map((i) => (
            <rect
              key={i}
              x={30 + (i % 2) * 6}
              y={150 - i * 18}
              width="170"
              height="14"
              fill={i === 4 ? "#ff4a14" : "url(#holoNote)"}
              stroke="#0b0b0a"
              strokeWidth="1.5"
              transform={`rotate(${(i - 3) * 1.6} 120 ${157 - i * 18})`}
            />
          ))}
        </svg>
      )}
    </div>
  );
}
