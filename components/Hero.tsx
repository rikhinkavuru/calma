"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Atmo, Reveal } from "./chrome";
import { ErrorBoundary } from "./site/ErrorBoundary";

/* WebGL / window-touching decorations — client-only, and guarded so a machine
   without WebGL degrades to the existing atmosphere instead of blanking. */
const GradientBlinds = dynamic(() => import("./GradientBlinds"), { ssr: false });

export function Hero() {
  const heroRef = useRef<HTMLElement>(null);
  const [blindsPaused, setBlindsPaused] = useState(false);

  /* pause the WebGL loop once the hero scrolls out of view — no GPU cost while
     reading the rest of the page. */
  useEffect(() => {
    const el = heroRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setBlindsPaused(!e.isIntersecting), {
      threshold: 0,
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section className="hero" id="top" ref={heroRef}>
      <Atmo />

      {/* added: gradient blinds behind the hero, with a grain overlay on top */}
      <div className="hero__blinds" aria-hidden="true">
        <ErrorBoundary fallback={null}>
          <GradientBlinds
            gradientColors={["#2e4f6d", "#7fb89e", "#e89a5d", "#ffb36b"]}
            angle={20}
            blindCount={16}
            blindMinWidth={55}
            noise={0.25}
            spotlightRadius={2.5}
            spotlightSoftness={0.8}
            spotlightOpacity={0.5}
            mouseDampening={0.15}
            dpr={1}
            paused={blindsPaused}
            mixBlendMode="lighten"
          />
        </ErrorBoundary>
        <div className="hero__grain" />
      </div>

      <div className="wrap hero__inner hero__inner--center">
        <Reveal>
          <h1 className="h1">AI did the work. Calma checks it.</h1>
        </Reveal>

        <Reveal delay={200}>
          <p className="lead hero__lead">
            Everyone else reads the diff or trusts the score. <b>Calma re-runs the work and
            recomputes the number</b> — from the raw outputs, never the one your agent reported —
            and blocks the wrong one before it ships.
          </p>
        </Reveal>

        <Reveal delay={400} className="hero__fill">
          <div className="hero__demo">
            <figure className="hero__movie">
              <video
                src="/video/hero-demo.mp4"
                autoPlay
                muted
                loop
                playsInline
                controls
                preload="metadata"
                aria-label="Screen recording: an AI agent reports an inflated backtest return; calma blocks the turn, refutes the number, and the agent corrects itself"
              />
            </figure>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
