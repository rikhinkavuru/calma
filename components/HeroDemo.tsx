"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";

/* The hero demo: a guided, animated walkthrough of one verification, one idea at a time.
   Each step types/reveals a line, zooms the focused line, lands a pointer on the key number with a
   click ripple, and shows a plain-English sidenote. Loops. Static "catch" frame under reduced motion.
   Styled with the site tokens (amber/sun/teal on void) so it complements the hero by construction. */

type Tone = "dim" | "prompt" | "claim" | "run" | "refute" | "confirm";
type Seg = { t: string; tone?: Tone; mark?: boolean };

const SCENES: Record<string, Seg[][]> = {
  A: [
    [{ t: "agent", tone: "prompt" }, { t: "  reports a backtest return of  ", tone: "dim" }, { t: "+14,698%", tone: "claim", mark: true }],
    [{ t: "$ calma verify . ", tone: "prompt" }, { t: '"+14,698% return"', tone: "dim" }],
    [{ t: "  re-running the code, rebuilding the number from raw outputs", tone: "run", mark: true }],
    [{ t: "✗ REFUTED", tone: "refute" }, { t: "   claimed +14,698%   →   actually  ", tone: "dim" }, { t: "−32.4%", tone: "refute", mark: true }],
  ],
  B: [
    [{ t: "$ calma verify . ", tone: "prompt" }, { t: '"accuracy 0.91"', tone: "dim" }],
    [{ t: "✓ CONFIRMED", tone: "confirm", mark: true }, { t: "   accuracy 0.91   →   rebuilt  ", tone: "dim" }, { t: "0.91", tone: "confirm" }],
  ],
};

type Step = { scene: keyof typeof SCENES; upTo: number; focus: number; ripple?: boolean; hold: number; note: { k: string; b: string } };
const STEPS: Step[] = [
  { scene: "A", upTo: 0, focus: 0, hold: 2700, note: { k: "01 · the claim", b: "Your AI states a number and calls the work done." } },
  { scene: "A", upTo: 2, focus: 2, hold: 3900, note: { k: "02 · re-execute", b: "Calma re-runs the code in a sandbox and rebuilds the number from the raw output files — never the value the AI reported." } },
  { scene: "A", upTo: 3, focus: 3, ripple: true, hold: 3700, note: { k: "03 · the catch", b: "The real result is −32.4%. The wrong number is blocked before it ever reaches you." } },
  { scene: "B", upTo: 1, focus: 1, ripple: true, hold: 3700, note: { k: "04 · honest passes", b: "Real numbers confirm untouched. Every verdict is computed by code, never a model's opinion." } },
];

export function HeroDemo() {
  const reduced = useReducedMotion();
  const [step, setStep] = useState(0);
  const [ver, setVer] = useState(0); // bumped on resize to re-measure
  const cardRef = useRef<HTMLDivElement>(null);
  const focusRef = useRef<HTMLSpanElement>(null);
  const [cur, setCur] = useState<{ x: number; y: number } | null>(null);

  // advance the timeline, looping
  useEffect(() => {
    if (reduced) return;
    const id = setTimeout(() => setStep((s) => (s + 1) % STEPS.length), STEPS[step].hold);
    return () => clearTimeout(id);
  }, [step, reduced]);

  // re-measure on resize
  useEffect(() => {
    const c = cardRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => setVer((v) => v + 1));
    ro.observe(c);
    return () => ro.disconnect();
  }, []);

  // land the pointer on the focused line's marked token
  useEffect(() => {
    const card = cardRef.current, f = focusRef.current;
    if (!card || !f) return;
    const cr = card.getBoundingClientRect(), fr = f.getBoundingClientRect();
    setCur({ x: fr.left - cr.left + 7, y: fr.top - cr.top + fr.height / 2 });
  }, [step, ver, reduced]);

  const cfg = STEPS[reduced ? 2 : step];
  const lines = SCENES[cfg.scene].slice(0, cfg.upTo + 1);

  return (
    <div className="hdemo" ref={cardRef}>
      <div className="hdemo__term">
        <div className="hdemo__bar">
          <span className="hdemo__dots" aria-hidden="true"><i /><i /><i /></span>
          <span className="hdemo__title">calma — verify a result</span>
        </div>
        <div className="hdemo__body" aria-label="Demo: an AI reports an inflated backtest; calma re-runs it, refutes the wrong number, and confirms an honest one.">
          <AnimatePresence mode="popLayout" initial={false}>
            {lines.map((segs, i) => {
              const isFocus = i === cfg.focus;
              return (
                <motion.div
                  key={cfg.scene + ":" + i}
                  className="hdemo__line"
                  initial={reduced ? false : { opacity: 0, y: 7 }}
                  animate={{ opacity: isFocus ? 1 : 0.45, y: 0, scale: isFocus && !reduced ? 1.035 : 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.42, ease: [0.25, 0.6, 0.2, 1] }}
                  style={{ transformOrigin: "left center" }}
                >
                  {segs.map((s, j) => (
                    <span
                      key={j}
                      ref={isFocus && s.mark ? focusRef : undefined}
                      className={"t-" + (s.tone || "dim") + (isFocus && s.mark ? " hdemo__mark" : "")}
                    >
                      {s.t}
                    </span>
                  ))}
                </motion.div>
              );
            })}
          </AnimatePresence>

          {!reduced && cur && (
            <>
              {cfg.ripple && (
                <motion.span
                  key={"ripple-" + step}
                  className="hdemo__ripple"
                  aria-hidden="true"
                  style={{ left: cur.x, top: cur.y }}
                  initial={{ scale: 0, opacity: 0.7 }}
                  animate={{ scale: 2.3, opacity: 0 }}
                  transition={{ duration: 0.75, ease: "easeOut" }}
                />
              )}
              <motion.span
                className="hdemo__cursor"
                aria-hidden="true"
                animate={{ x: cur.x, y: cur.y }}
                transition={{ duration: 0.6, ease: [0.3, 0.7, 0.2, 1] }}
              >
                <svg viewBox="0 0 14 20" width="15" height="21">
                  <path d="M2 1.6 L2 16.4 L6 12.6 L8.7 18.4 L11 17.3 L8.3 11.6 L13.2 11.4 Z" />
                </svg>
              </motion.span>
            </>
          )}
        </div>
      </div>

      <div className="hdemo__rail">
        <AnimatePresence mode="wait">
          <motion.div
            key={reduced ? "static" : step}
            className="hdemo__note"
            initial={reduced ? false : { opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={{ duration: 0.35, ease: [0.25, 0.6, 0.2, 1] }}
          >
            <span className="hdemo__notek">{cfg.note.k}</span>
            <p>{cfg.note.b}</p>
          </motion.div>
        </AnimatePresence>
        {!reduced && (
          <div className="hdemo__steps" aria-hidden="true">
            {STEPS.map((_, i) => (
              <i key={i} className={i === step ? "on" : ""} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
