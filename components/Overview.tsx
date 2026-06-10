"use client";

import { Glyph, Reveal } from "./chrome";

/* OVERVIEW — what Calma is, shown as the instrument it is. */
export function Overview() {
  return (
    <section className="sec" id="overview">
      <div className="wrap overview">
        <div className="sec__head" style={{ marginBottom: 0 }}>
          <Reveal>
            <span className="kicker">Overview — what Calma does</span>
          </Reveal>
          <Reveal delay={120}>
            <p className="col" style={{ marginTop: 18, maxWidth: 440 }}>
              Calma is an independent checker for work done by AI. Point it at the work, say what
              was claimed — <b>it runs the work again, rebuilds the number itself, and tells you if
              the claim holds.</b>
            </p>
          </Reveal>
        </div>

        <Reveal delay={200}>
          <div className="flow">
            <div className="flow__cell">
              <b>Your AI&apos;s work</b>
              <small>code + its outputs</small>
              <p>The thing your agent just finished and the number it reported.</p>
            </div>
            <div className="flow__cell">
              <span className="spec__box"><Glyph kind="rerun" /></span>
              <b>Re-run</b>
              <p>The work executes again, in a sandbox that proves itself first.</p>
            </div>
            <div className="flow__cell">
              <span className="spec__box"><Glyph kind="recompute" /></span>
              <b>Recompute</b>
              <p>The number is rebuilt from the raw output files. Never the report.</p>
            </div>
            <div className="flow__cell">
              <span className="spec__box"><Glyph kind="diff" /></span>
              <b>Compare</b>
              <p>Rebuilt vs reported, with room for harmless noise. No false alarms.</p>
            </div>
            <div className="flow__cell flow__cell--out">
              <span className="spec__box"><Glyph kind="decide" /></span>
              <b>Verdict</b>
              <p>Decided by code. Nobody — including the AI — can argue it into passing.</p>
            </div>
          </div>
        </Reveal>

        <Reveal delay={300}>
          <p className="termline">
            <span className="amber">$</span> calma verify . &quot;accuracy 0.87&quot; &nbsp;→&nbsp;{" "}
            <b>CONFIRMED</b> <span style={{ color: "var(--cream-25)" }}>· the whole thing is one command</span>
          </p>
        </Reveal>
      </div>
    </section>
  );
}
