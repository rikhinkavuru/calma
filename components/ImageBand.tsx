"use client";

import { Reveal } from "./Reveal";

/* Full-bleed image band. The prototype used a drag-drop <image-slot> backed by
   a host runtime; here it renders a framed real <img> (or a labelled
   placeholder when no src is supplied). Height is intrinsic via aspect-ratio so
   it stays editorial on phones instead of a fixed-px dead zone. */
export function ImageBand({ label, caption, src }: { label?: string; caption?: string; src?: string }) {
  return (
    <Reveal className="band">
      <div className="wrap">
        <div className={"band__frame" + (src ? " has-img" : "")}>
          <div className="band__img">
            {src ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={src} alt="" />
            ) : (
              <span className="band__ph mono">{label}</span>
            )}
          </div>
          {caption && <div className="band__cap mono">{caption}</div>}
        </div>
      </div>
    </Reveal>
  );
}
