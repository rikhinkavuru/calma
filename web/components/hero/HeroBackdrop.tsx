"use client";
// Client island: the WebGL gradient-blinds backdrop. Kept tiny and isolated so the rest of the hero
// stays server-rendered. All props are module CONSTANTS -> stable identities, so GradientBlinds' init
// effect runs exactly once and never rebuilds the WebGL context on a parent re-render.
import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { ErrorBoundary } from "../site/ErrorBoundary";

const GradientBlinds = dynamic(() => import("../GradientBlinds"), { ssr: false });

const COLORS = ["#2e4f6d", "#7fb89e", "#e89a5d", "#ffb36b"];

export function HeroBackdrop() {
  const ref = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);
  const [shown, setShown] = useState(false);

  // Pause the shader whenever the hero leaves the viewport — zero GPU cost while reading the page.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setPaused(!e.isIntersecting), { threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // Fade the canvas in once mounted instead of a hard pop-in.
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <div ref={ref} className={`hero__webgl${shown ? " is-shown" : ""}`}>
      <ErrorBoundary fallback={null}>
        <GradientBlinds
          gradientColors={COLORS}
          angle={20}
          blindCount={16}
          blindMinWidth={55}
          noise={0.25}
          spotlightRadius={2.5}
          spotlightSoftness={0.8}
          spotlightOpacity={0.5}
          mouseDampening={0.15}
          dpr={1}
          paused={paused}
          mixBlendMode="lighten"
        />
      </ErrorBoundary>
    </div>
  );
}
