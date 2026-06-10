"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useInView } from "./chrome";

/* The demo: one verification, typed out like a real terminal session.
   When the run finishes, four flowchart lines fan out from a single
   junction on the terminal's edge to boxes that show what happened
   inside each step. A faint light then circulates through the outlines
   forever. Each step shares a subtle hue between its terminal line,
   its connector, and its box. */

type Line = { text: string; cls: string; typed?: boolean; pause: number };

const SCRIPT: Line[] = [
  { text: '$ calma verify . "the model is 87% accurate"', cls: "p", typed: true, pause: 600 },
  { text: "  re-running the work in a sandbox ......... done", cls: "t-rerun", pause: 900 },
  { text: "  rebuilding the number from raw outputs ... 0.84", cls: "t-recompute", pause: 900 },
  { text: "  comparing  reported 0.87  vs  rebuilt 0.84", cls: "t-compare", pause: 1000 },
  { text: "", cls: "out", pause: 100 },
  { text: "  VERDICT: REFUTED — the real number is 0.84", cls: "verdict", pause: 400 },
];

const STEPS: { key: string; hue: string; kicker: string; body: ReactNode }[] = [
  {
    key: "rerun",
    hue: "rgba(127, 184, 158, 0.55)",
    kicker: "Re-run",
    body: <>The sandbox proves itself before it&apos;s trusted — network blocked, secrets unreadable. Then the work runs again from scratch.</>,
  },
  {
    key: "recompute",
    hue: "rgba(217, 179, 128, 0.55)",
    kicker: "Recompute",
    body: <>The number is rebuilt from the raw output files. The AI&apos;s report is never trusted — or even read.</>,
  },
  {
    key: "compare",
    hue: "rgba(122, 156, 189, 0.6)",
    kicker: "Compare",
    body: <>0.87 vs 0.84 is outside the calibrated tolerance — a real break, not hardware noise. Calma never cries wolf.</>,
  },
  {
    key: "verdict",
    hue: "rgba(232, 154, 93, 0.6)",
    kicker: "Verdict",
    body: <>Decided by a deterministic script, not a model&apos;s opinion. Anyone can replay the whole check with one command.</>,
  },
];

type Geom = { w: number; h: number; term: string; conns: string[]; boxes: string[] };

/* terminal outline, starting AT the junction (right edge, mid-height) so the
   light's lap begins and ends where the connectors leave */
const termPath = (x: number, y: number, w: number, h: number) =>
  `M ${x + w} ${y + h / 2} V ${y} H ${x} V ${y + h} H ${x + w} Z`;

/* box outline, starting at its left-center — where the connector arrives */
const boxPath = (x: number, y: number, w: number, h: number) =>
  `M ${x} ${y + h / 2} V ${y} H ${x + w} V ${y + h} H ${x} Z`;

export function Demo() {
  const [ref, seen] = useInView<HTMLDivElement>(0.35);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<HTMLDivElement | null>(null);
  const boxRefs = useRef<(HTMLDivElement | null)[]>([]);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const [run, setRun] = useState(0);
  const [lines, setLines] = useState<{ text: string; cls: string }[]>([]);
  const [done, setDone] = useState(false);
  const [connected, setConnected] = useState(0);
  const [live, setLive] = useState(false);
  const [geom, setGeom] = useState<Geom | null>(null);

  const measure = useCallback(() => {
    const c = containerRef.current;
    const t = termRef.current;
    if (!c || !t) return;
    const cr = c.getBoundingClientRect();
    const tr = t.getBoundingClientRect();
    if (tr.width === 0) return;
    /* light paths sit on the 1px border's centerline (inset 0.5), so the
       light reads as the existing outline glowing — not a line on top */
    const inset = 0.5;
    const jx = tr.right - cr.left - inset;
    const jy = tr.top - cr.top + tr.height / 2;
    const conns: string[] = [];
    const boxes: string[] = [];
    boxRefs.current.forEach((b) => {
      if (!b) return;
      const br = b.getBoundingClientRect();
      const bx = br.left - cr.left; /* the border's outer edge — touch, never cross */
      const by = br.top - cr.top + br.height / 2;
      const mx = jx + (bx - jx) * 0.5;
      conns.push(`M ${jx} ${jy} C ${mx} ${jy}, ${mx} ${by}, ${bx} ${by}`);
      boxes.push(
        boxPath(br.left - cr.left + inset, br.top - cr.top + inset, br.width - 1, br.height - 1)
      );
    });
    setGeom({
      w: cr.width,
      h: cr.height,
      term: termPath(tr.left - cr.left + inset, tr.top - cr.top + inset, tr.width - 1, tr.height - 1),
      conns,
      boxes,
    });
  }, []);

  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(c);
    return () => ro.disconnect();
  }, [measure]);

  useEffect(() => {
    if (!seen) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setDone(false);
    setConnected(0);
    setLive(false);

    if (reduced) {
      setLines(SCRIPT.map(({ text, cls }) => ({ text, cls })));
      setDone(true);
      setConnected(STEPS.length);
      setLive(true);
      requestAnimationFrame(() => requestAnimationFrame(measure));
      return;
    }

    setLines([]);
    let at = 400;
    const later = (fn: () => void, ms: number) => {
      timers.current.push(setTimeout(fn, ms));
    };

    SCRIPT.forEach((line, i) => {
      if (line.typed) {
        for (let c = 1; c <= line.text.length; c++) {
          const part = line.text.slice(0, c);
          later(() => {
            setLines((prev) => {
              const next = prev.slice(0, i);
              next[i] = { text: part, cls: line.cls };
              return next;
            });
          }, at);
          at += 28;
        }
      } else {
        const full = line.text;
        later(() => {
          setLines((prev) => {
            const next = prev.slice(0, i);
            next[i] = { text: full, cls: line.cls };
            return next;
          });
        }, at);
      }
      at += line.pause;
    });

    /* terminal done → wait for the final layout (prompt line included) →
       measure → fan the connectors out one by one → light up */
    later(() => {
      setDone(true);
      requestAnimationFrame(() => requestAnimationFrame(measure));
    }, at);
    at += 250;
    STEPS.forEach((_, i) => {
      later(() => setConnected(i + 1), at + i * 380);
    });
    at += STEPS.length * 380 + 600;
    later(() => setLive(true), at);

    return () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
  }, [seen, run, measure]);

  return (
    <div className={"demo" + (live ? " demo--live" : "")} ref={(el) => { containerRef.current = el; ref.current = el; }}>
      {geom && (
        <svg
          className="demo__net"
          viewBox={`0 0 ${geom.w} ${geom.h}`}
          width={geom.w}
          height={geom.h}
          aria-hidden="true"
        >
          {/* ONE light, one journey: a lap of the terminal outline, out through
              the junction, splitting along the four curves, a lap around each
              box — then again, forever. The phases share one 9s cycle. */}
          <path
            className="net__light net__light--term"
            d={geom.term}
            pathLength={1}
            stroke="rgba(233, 221, 196, 0.85)"
          />
          {STEPS.map((s, i) => (
            <g key={s.key}>
              {/* the connector, drawn from the junction when its step lands */}
              <path
                className={"net__line" + (i < connected ? " is-on" : "")}
                d={geom.conns[i]}
                pathLength={1}
              />
              <path
                className="net__light net__light--conn"
                d={geom.conns[i]}
                pathLength={1}
                stroke={s.hue}
              />
              <path
                className="net__light net__light--box"
                d={geom.boxes[i]}
                pathLength={1}
                stroke={s.hue}
              />
            </g>
          ))}
        </svg>
      )}

      <div className="term" ref={termRef} aria-label="Demo: calma verifies a claimed number and refutes it">
        <div className="term__bar">
          <span className="term__dots" aria-hidden="true"><i /><i /><i /></span>
          <span className="term__title">calma — one check, start to finish</span>
          <button className="term__replay" onClick={() => setRun((n) => n + 1)} disabled={!done}>
            replay ↺
          </button>
        </div>
        <div className="term__body" aria-live="off">
          {lines.map((l, i) => (
            <div key={i} className={l.cls}>
              {l.text || " "}
              {i === lines.length - 1 && !done && <span className="term__caret" />}
            </div>
          ))}
          {done && (
            <div>
              <span className="p">$ </span>
              <span className="term__caret" />
            </div>
          )}
        </div>
      </div>

      <div className="dsteps" aria-label="What happens inside each step">
        {STEPS.map((s, i) => (
          <div
            key={s.key}
            ref={(el) => { boxRefs.current[i] = el; }}
            className={`dstep dstep--${s.key}` + (i < connected ? " in" : "")}
          >
            <span className="dstep__k">{`0${i + 1} — ${s.kicker}`}</span>
            <p>{s.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
