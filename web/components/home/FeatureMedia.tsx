"use client";

import { useState, type ReactNode } from "react";

/* The media side of a moat row. Shows the illustrated fallback immediately, then
   fades the screen-recording in over it once it can play. If the video is absent
   (videoReady=false) or 404s, the fallback stays — so the section is complete
   today and upgrades itself the moment a /video/feature-*.mp4 is dropped in. */
export function FeatureMedia({
  label,
  src,
  videoReady = false,
  poster,
  children,
}: {
  label: string;
  src?: string;
  videoReady?: boolean;
  poster?: string;
  children: ReactNode;
}) {
  const [playing, setPlaying] = useState(false);
  const showVideo = videoReady && !!src;

  return (
    <div className="fmoat__frame">
      <div className="fmoat__chrome" aria-hidden="true">
        <span className="fmoat__dots">
          <i />
          <i />
          <i />
        </span>
        <span className="fmoat__cap">{label}</span>
      </div>
      <div className="fmoat__stage">
        <div className={"fmoat__ph" + (playing ? " is-hidden" : "")}>{children}</div>
        {showVideo && (
          <video
            className={"fmoat__vid" + (playing ? " is-on" : "")}
            src={src}
            poster={poster}
            autoPlay
            muted
            loop
            playsInline
            preload="metadata"
            aria-label={label}
            onCanPlay={() => setPlaying(true)}
            onError={() => setPlaying(false)}
          />
        )}
      </div>
    </div>
  );
}

export default FeatureMedia;
