"use client";

import { useEffect, useRef, useState } from "react";
import { Cross, Reveal, useInView } from "../chrome";

/* the rotating, animated 3-view benchmark, now flush in the continuous column. */
type BarView = { key: string; title: string; desc: string; note: string; unit: "%" | "count"; max: number; bars: { label: string; value: number; tone: "amber" | "mid" | "dim" }[] };
type GroupView = { key: string; title: string; desc: string; note: string; groups: { label: string; calma: number; judge: number }[] };

const CATCH: BarView = {
  key: "catch", title: "Catch rate",
  desc: "77 wrong numbers were planted across 30 metrics. How many did each approach catch?",
  note: "catch rate on 77 planted wrong numbers", unit: "%", max: 100,
  bars: [{ label: "Calma", value: 100, tone: "amber" }, { label: "Claude as judge", value: 82, tone: "mid" }, { label: "Trust the number", value: 0, tone: "dim" }],
};
const WRONG: BarView = {
  key: "wrong", title: "Wrong verdicts",
  desc: "Times each approach blessed a wrong number or rejected an honest one. The LLM judge silently blessed 14 wrong numbers as correct — the dangerous error. Calma proves it or says “can’t confirm,” and is never wrong.",
  note: "wrong verdicts across all 117 cases · lower is better", unit: "count", max: 77,
  bars: [{ label: "Calma", value: 0, tone: "amber" }, { label: "Claude as judge", value: 26, tone: "mid" }, { label: "Trust the number", value: 77, tone: "dim" }],
};
const HARD: GroupView = {
  key: "hard", title: "The hard cases",
  desc: "Obvious errors are easy. The gap shows on subtle shading and on real-world cases like a published leakage study and a +14,698% backtest.",
  note: "catch rate by difficulty · calma vs claude-as-judge",
  groups: [{ label: "Obvious", calma: 100, judge: 97 }, { label: "Subtle", calma: 100, judge: 68 }, { label: "Real-world", calma: 100, judge: 50 }],
};
const VIEWS: (BarView | GroupView)[] = [CATCH, WRONG, HARD];
const CYCLE_MS = 6000;
const isGroup = (v: BarView | GroupView): v is GroupView => (v as GroupView).groups !== undefined;

export function BpBench() {
  const [ref, seen] = useInView<HTMLDivElement>(0.35);
  const [view, setView] = useState(0);
  const [manual, setManual] = useState(false);
  const [armed, setArmed] = useState(false);
  const raf = useRef(0);

  useEffect(() => {
    setArmed(false);
    raf.current = requestAnimationFrame(() => requestAnimationFrame(() => setArmed(true)));
    return () => cancelAnimationFrame(raf.current);
  }, [view, seen]);

  useEffect(() => {
    if (!seen || manual) return;
    const id = setInterval(() => setView((v) => (v + 1) % VIEWS.length), CYCLE_MS);
    return () => clearInterval(id);
  }, [seen, manual]);

  const v = VIEWS[view];
  const grow = seen && armed;

  return (
    <div className="bp-block bp-benchwrap" id="benchmarks">
      <div className="bench" ref={ref}>
        <Reveal>
          <div className="bench__side">
            <span className="bp-kicker">Benchmarks</span>
            <h2 className="bp-h2" style={{ marginTop: 12 }}>We don&apos;t trust <span className="am">the reported number.</span></h2>
            <p className="bp-lead">117 labeled results — honest and tampered — built on UCI benchmark datasets, scikit-learn ground truth, and published real-world cases. Calma versus trusting the report, and versus asking Claude to judge the same data.</p>
            <div className="bench__tabs" role="tablist" aria-label="Benchmark views">
              {VIEWS.map((t, i) => (
                <button key={t.key} role="tab" aria-selected={i === view} className={"bench__tab" + (i === view ? " is-on" : "")} onClick={() => { setManual(true); setView(i); }}>
                  <span className="bench__tabtitle">{t.title}</span>
                  <span className="bench__tabdesc">{t.desc}</span>
                  {i === view && !manual && <span className="bench__timer" key={`t${i}`} aria-hidden="true" />}
                </button>
              ))}
            </div>
          </div>
        </Reveal>

        <Reveal delay={150}>
          <div className="panel bench__panel" aria-live="polite">
            <Cross className="tl" />
            <Cross className="br" />
            <div className="bench__note">{v.note}</div>
            {!isGroup(v) ? (
              <div className="bench__rows" key={v.key} role="img" aria-label={v.desc}>
                {v.bars.map((b, i) => (
                  <div className="bench__row" key={b.label}>
                    <span className="bench__rowlabel">{b.label}</span>
                    <span className="bench__track">
                      <span className={`bench__bar bench__bar--${b.tone}`} style={{ transform: `scaleX(${grow ? Math.max(b.value / v.max, 0.004) : 0})`, transitionDelay: `${i * 120}ms` }} />
                    </span>
                    <span className="bench__val" style={{ transitionDelay: `${350 + i * 120}ms`, opacity: grow ? 1 : 0 }}>{v.unit === "%" ? `${b.value}%` : b.value}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bench__cols" key={v.key} role="img" aria-label={v.desc}>
                {v.groups.map((g, gi) => (
                  <div className="bench__group" key={g.label}>
                    <div className="bench__colpair">
                      {([["calma", g.calma, "amber"], ["judge", g.judge, "mid"]] as const).map(([who, val, tone], si) => (
                        <div className="bench__colslot" key={who}>
                          <span className="bench__colval" style={{ transitionDelay: `${420 + gi * 140 + si * 70}ms`, opacity: grow ? 1 : 0 }}>{val}%</span>
                          <span className={`bench__col bench__bar--${tone}`} style={{ transform: `scaleY(${grow ? val / 100 : 0})`, transitionDelay: `${gi * 140 + si * 70}ms` }} />
                        </div>
                      ))}
                    </div>
                    <span className="bench__grouplabel">{g.label}</span>
                  </div>
                ))}
                <div className="bench__legend" aria-hidden="true">
                  <span><i className="bench__dot bench__bar--amber" /> Calma</span>
                  <span><i className="bench__dot bench__bar--mid" /> Claude as judge</span>
                </div>
              </div>
            )}
            <div className="bench__prov">
              <a href="https://github.com/rikhinkavuru/calma/tree/main/benchmark" target="_blank" rel="noreferrer">Full methodology &amp; data →</a>
            </div>
          </div>
        </Reveal>
      </div>

      <Reveal>
        <aside className="bench__berkeley">
          <span className="bp-kicker">Why not just trust the score?</span>
          <p>
            In 2026 a UC Berkeley team built an agent that scored <b>~100% on six major AI agent
            benchmarks</b> — SWE-bench, WebArena, GAIA — <b>without solving a single task</b>, by gaming
            the grader: a planted <code>conftest.py</code> makes the test suite report every test as
            passing. A score is the thing that gets gamed.{" "}
            <b>You can&apos;t game a number recomputed from raw outputs.</b>{" "}
            <a
              href="https://www.rdworldonline.com/how-a-berkeley-team-broke-8-major-ai-benchmarks-six-of-them-hit-100-without-solving-a-single-task/"
              target="_blank"
              rel="noreferrer"
            >
              Source →
            </a>
          </p>
        </aside>
      </Reveal>
    </div>
  );
}
