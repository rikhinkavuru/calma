"use client";

import { useEffect, useRef, useState } from "react";

/* The one loud element: the four-point chrome star from the design system, rendered as a
   real 3D object and spun like a top — fast around its vertical axis, with a slow precession
   wobble. Iridescent chrome via MeshPhysicalMaterial iridescence + spectrum rim lights.
   Geometry: a sphere displaced by an astroid radial field — concave points along ±x/±y,
   a lens-thin profile in z. Static single frame under prefers-reduced-motion. */

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function StarSpinner() {
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
      renderer.toneMappingExposure = 1.15;
      el.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(36, el.clientWidth / el.clientHeight, 0.1, 50);
      camera.position.set(0, 0.35, 5.4);
      camera.lookAt(0, 0, 0);

      const pmrem = new THREE.PMREMGenerator(renderer);
      const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      scene.environment = env;

      // ---- geometry: astroid-displaced sphere = rounded four-point star, lens-thin in z
      const geo = new THREE.SphereGeometry(1, 220, 220);
      const pos = geo.attributes.position;
      const v = new THREE.Vector3();
      const A = 0.46; // azimuthal exponent (<1 = concave star points on ±x/±y)
      const B = 1.9;  // polar exponent (z stays rounded)
      for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i).normalize();
        const f =
          Math.pow(Math.abs(v.x), A) + Math.pow(Math.abs(v.y), A) + Math.pow(Math.abs(v.z), B);
        const r = Math.pow(f, -1.05);
        pos.setXYZ(i, v.x * r, v.y * r, v.z * r * 0.52);
      }
      geo.computeVertexNormals();

      const mat = new THREE.MeshPhysicalMaterial({
        color: 0xc8cbd2,
        metalness: 1,
        roughness: 0.18,
        envMapIntensity: 1.5,
        iridescence: 1,
        iridescenceIOR: 1.8,
        iridescenceThicknessRange: [120, 760],
        clearcoat: 0.6,
        clearcoatRoughness: 0.25,
      });
      const star = new THREE.Mesh(geo, mat);
      star.scale.setScalar(1.32);

      // precession group: the spin axis itself leans and slowly wanders, like a settling top
      const tilt = new THREE.Group();
      tilt.add(star);
      tilt.rotation.z = 0.16;
      scene.add(tilt);

      // spectrum rim lights — the holo gradient as physical light
      const l1 = new THREE.PointLight(0x18e0ff, 26, 0, 2);
      l1.position.set(-4, 2.5, 3);
      const l2 = new THREE.PointLight(0xff8fd6, 22, 0, 2);
      l2.position.set(4, -1.5, 2.5);
      const l3 = new THREE.PointLight(0xc9f24a, 14, 0, 2);
      l3.position.set(0, 3.5, -3);
      scene.add(l1, l2, l3);

      let raf = 0;
      const t0 = performance.now();
      const frame = () => {
        const t = (performance.now() - t0) / 1000;
        star.rotation.y = t * 1.5;                     // the top spin
        tilt.rotation.z = 0.16 + Math.sin(t * 0.45) * 0.09; // precession lean
        tilt.rotation.x = Math.sin(t * 0.3) * 0.05;
        tilt.position.y = Math.sin(t * 0.8) * 0.06;    // float
        renderer.render(scene, camera);
        if (!reduced) raf = requestAnimationFrame(frame);
      };
      if (reduced) {
        star.rotation.y = 0.7; // a single, considered pose
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
        geo.dispose();
        mat.dispose();
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
      aria-label="The Calma mark — an iridescent chrome four-point star, spinning like a top"
    >
      {fallback && (
        <svg
          viewBox="0 0 240 240"
          aria-hidden="true"
          style={{
            width: "58%",
            maxWidth: 380,
            filter: "drop-shadow(0 24px 40px rgba(0,0,0,.5))",
            animation: "starfall 16s linear infinite, starfloat 7s ease-in-out infinite",
          }}
        >
          <defs>
            <linearGradient id="holoFb" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#18e0ff" />
              <stop offset=".16" stopColor="#46e7a0" />
              <stop offset=".33" stopColor="#c9f24a" />
              <stop offset=".46" stopColor="#f4e64b" />
              <stop offset=".62" stopColor="#ff8fd6" />
              <stop offset=".8" stopColor="#9a6cff" />
              <stop offset="1" stopColor="#29c8ff" />
            </linearGradient>
            <radialGradient id="specFb" cx=".34" cy=".3" r=".5">
              <stop offset="0" stopColor="#ffffff" stopOpacity=".85" />
              <stop offset=".4" stopColor="#ffffff" stopOpacity="0" />
            </radialGradient>
          </defs>
          <path
            d="M120 4 C129 94 146 111 236 120 C146 129 129 146 120 236 C111 146 94 129 4 120 C94 111 111 94 120 4 Z"
            fill="url(#holoFb)"
          />
          <path
            d="M120 4 C129 94 146 111 236 120 C146 129 129 146 120 236 C111 146 94 129 4 120 C94 111 111 94 120 4 Z"
            fill="url(#specFb)"
          />
          <style>{`@keyframes starfall{from{filter:hue-rotate(0)}to{filter:hue-rotate(360deg)}}
@keyframes starfloat{0%,100%{transform:translateY(-2%)}50%{transform:translateY(2%)}}`}</style>
        </svg>
      )}
    </div>
  );
}
