"use client";

import { CropFrame, Eyebrow, Orns, Reveal } from "./chrome";

/* The $1Million moment, ours: the giant metallic number is the catch. */
export function Giant() {
  return (
    <>
      <section className="giant" id="catch">
        <Orns top="30%" />
        <Reveal>
          <Eyebrow>exhibit 001 — a real catch</Eyebrow>
        </Reveal>
        <Reveal delay={120} dir="pop">
          <div className="giant__n">−32.4%</div>
        </Reveal>
        <div className="wrap">
          <Reveal delay={240}>
            <CropFrame className="giant__frame">
              <p>
                An agent reported a <b>+14,698%</b> backtest — the survivor of{" "}
                <b>100 in-sample tries</b>. Calma re-ran it on data it had never seen:{" "}
                <span className="serif-acc">−32.4%</span>, caught{" "}
                <b>before the money moved</b>.
              </p>
              <p className="giant__sub mono">$ calma replay ./btc-backtest/.calma/run</p>
            </CropFrame>
          </Reveal>
        </div>
      </section>
      <div className="horizon" aria-hidden="true" />
    </>
  );
}
