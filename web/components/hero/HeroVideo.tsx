"use client";
// Client island: the hero demo player. The lightweight poster is server-rendered into the page and
// paints immediately; the ~8 MB video bytes load (then autoplay) only once the player nears the
// viewport, so they never compete with the hero text, fonts, and JS on first paint.
import { useEffect, useRef, useState } from "react";

export function HeroVideo() {
  const ref = useRef<HTMLElement>(null);
  const [on, setOn] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setOn(true);
          io.disconnect();
        }
      },
      { rootMargin: "300px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <figure className="hero__movie" ref={ref}>
      <video
        src={on ? "/video/hero-demo.mp4" : undefined}
        poster="/img/hero-poster.jpg"
        autoPlay
        muted
        loop
        playsInline
        controls
        preload="none"
        aria-label="Screen recording: an AI agent reports an inflated backtest return; calma blocks the turn, refutes the number, and the agent corrects itself"
      />
    </figure>
  );
}
