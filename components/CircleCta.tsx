"use client";

import { Eyebrow, Orns, Reveal } from "./chrome";

export function CircleCta({ onRequest }: { onRequest: () => void }) {
  return (
    <section className="circle">
      <Orns top="42%" />
      <Reveal dir="pop">
        <button
          className="circle__ring"
          onClick={onRequest}
          aria-label="Get in touch — request a verification"
        >
          <i aria-hidden="true" />
          <i aria-hidden="true" />
          <i aria-hidden="true" />
          <i aria-hidden="true" />
          <span>
            <span className="k mono">get in touch</span>
            <br />
            <span className="v">Request verification</span>
          </span>
        </button>
      </Reveal>
    </section>
  );
}
