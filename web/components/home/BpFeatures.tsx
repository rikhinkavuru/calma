"use client";

import { useEffect, useState, type ReactNode } from "react";
import Image from "next/image";
import { motion, useReducedMotion } from "framer-motion";
import { SiPython, SiJupyter, SiGithub } from "react-icons/si";
import { FaTerminal, FaCheck } from "react-icons/fa6";
import { useInView } from "../chrome";

/* ============================================================================
   FEATURES — three alternating rows under the flow. Copy is grounded in the
   current engine (pipeline.py three-way diff, core/leakage + redteam_gate
   validity checks, runner/e2b_runner hermetic sandbox, hook/hook_stop.py).

   Each row pairs a bold headline + prose against a large rounded painting with
   a LIVE looping demo floating on frosted glass — a different glass treatment
   per row (panel / loose pills / dark terminal) so no two scenes read alike.
   All three demo stages share one fixed size. Reduced-motion shows the final
   frame statically.
   ========================================================================== */

const EASE = [0.22, 1, 0.36, 1] as const;

/* step through `durations` (ms per step), looping, once `run` is true */
function useLoopStep(durations: readonly number[], run: boolean, reduce: boolean) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!run || reduce) return;
    const t = setTimeout(() => setStep((s) => (s + 1) % durations.length), durations[step]);
    return () => clearTimeout(t);
  }, [step, run, reduce, durations]);
  return reduce ? durations.length - 1 : step;
}

const rise = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.45, ease: EASE },
};

/* ---- demo 1: connect GitHub → run → logs → verdict (light glass panel) ---- */

const D1 = [900, 1200, 1300, 700, 750, 750, 850, 950, 3000] as const;

function ConnectDemo({ active }: { active: boolean }) {
  const reduce = useReducedMotion();
  const step = useLoopStep(D1, active, !!reduce);
  return (
    <div className="fdemo fdemo--panel">
      <div className="fdemo__connect">
        <span className="fdemo__node">
          <SiGithub style={{ color: "#1f1a13", fontSize: 17 }} />
          acme/churn-model
        </span>
        <span className={"fdemo__wire" + (step >= 1 ? " is-on" : "")} aria-hidden="true">
          {step >= 1 && (
            <motion.i initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 400, damping: 20 }}>
              <FaCheck />
            </motion.i>
          )}
        </span>
        <span className="fdemo__node">
          <Image src="/img/calma-lotus.png" alt="" width={24} height={15} style={{ display: "block" }} />
          calma
        </span>
      </div>

      {step >= 2 && (
        <motion.div {...rise} className="fdemo__runwrap">
          <span className={"fdemo__runbtn" + (step >= 3 ? " is-pressed" : "")}>Run verification</span>
          {step >= 2 && step < 4 && (
            <motion.svg
              className="fdemo__cursor"
              viewBox="0 0 24 24"
              initial={{ x: 92, y: 44, opacity: 0 }}
              animate={step >= 3 ? { x: 10, y: 8, opacity: 1, scale: 0.88 } : { x: 10, y: 8, opacity: 1, scale: 1 }}
              transition={{ duration: 0.7, ease: EASE }}
            >
              <path d="M5 3l14 9-6.5 1.5L9 20z" fill="#fff" stroke="#1f1a13" strokeWidth="1.6" />
            </motion.svg>
          )}
        </motion.div>
      )}

      <div className="fdemo__logs mono">
        {step >= 4 && <motion.span {...rise}>→ cloning into sandbox · network off</motion.span>}
        {step >= 5 && <motion.span {...rise}>→ rebuilding env · python 3.10</motion.span>}
        {step >= 6 && <motion.span {...rise}>→ re-running train.py · 41s</motion.span>}
        {step >= 7 && <motion.span {...rise}>→ recomputing from predictions.csv</motion.span>}
      </div>

      {step >= 8 && (
        <motion.div {...rise} className="fdemo__result">
          <span className="fdemo__claim">accuracy 0.94</span>
          <span className="fdemo__real">0.71</span>
          <span className="fbadge fbadge--no">REFUTED</span>
        </motion.div>
      )}
    </div>
  );
}

/* ---- demo 2: validity scan — one calm checklist, statuses resolve in turn ---- */

const D2 = [1200, 1000, 1000, 3800] as const;

type ScanState = "pending" | "active" | "ok" | "fail";

function ScanStatus({ state }: { state: ScanState }) {
  if (state === "pending") return <span className="fdemo__dot" aria-hidden="true" />;
  if (state === "active") return <span className="fdemo__spin" aria-hidden="true" />;
  if (state === "ok")
    return (
      <motion.span className="fdemo__okmark" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
        <FaCheck />
      </motion.span>
    );
  return (
    <motion.span className="fdemo__failmark" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
      ✕
    </motion.span>
  );
}

function ValidityDemo({ active }: { active: boolean }) {
  const reduce = useReducedMotion();
  const step = useLoopStep(D2, active, !!reduce);
  const rows: { label: string; state: ScanState; note?: string }[] = [
    { label: "model reproduces", state: step >= 1 ? "ok" : "active" },
    { label: "beats trivial baseline", state: step >= 2 ? "ok" : step >= 1 ? "active" : "pending" },
    {
      label: "train / eval leakage",
      state: step >= 3 ? "fail" : step >= 2 ? "active" : "pending",
      note: step >= 3 ? "38% row overlap" : undefined,
    },
  ];
  return (
    <div className="fdemo fdemo--scan">
      <span className="fdemo__scancap mono">validity scan · no execution</span>
      <div className="fdemo__scanrows">
        {rows.map((r) => (
          <div className="fdemo__scanrow" key={r.label}>
            <ScanStatus state={r.state} />
            <span className={"fdemo__scanlabel" + (r.state === "pending" ? " is-dim" : "")}>{r.label}</span>
            {r.note && (
              <motion.span className="fdemo__scannote mono" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
                {r.note}
              </motion.span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---- demo 3: the stop-hook riding the agent loop — dark smoked-glass terminal ---- */

const D3 = [1300, 950, 1000, 1050, 3200] as const;

function HookDemo({ active }: { active: boolean }) {
  const reduce = useReducedMotion();
  const step = useLoopStep(D3, active, !!reduce);
  return (
    <div className="fdemo fdemo--term mono">
      <span className="fdemo__tline fdemo__tline--agent">
        <b>❯ agent</b> …done. Final accuracy: <b>0.94</b>
      </span>
      {step >= 1 && (
        <motion.span {...rise} className="fdemo__tline fdemo__tline--hook">
          ⏺ calma · stop-hook — checkable number found
        </motion.span>
      )}
      {step >= 2 && <motion.span {...rise} className="fdemo__tline">→ scanning repo · leakage / baseline / misreport</motion.span>}
      {step >= 3 && <motion.span {...rise} className="fdemo__tline">→ recompute from committed predictions: <b>0.71</b></motion.span>}
      {step >= 4 && (
        <motion.span {...rise} className="fdemo__tline fdemo__tline--verdict">
          ✕ REFUTED — flagged before it ships
        </motion.span>
      )}
    </div>
  );
}

/* ---- the rows ---- */

type Feature = {
  key: string;
  title: ReactNode;
  body: ReactNode;
  img: string;
  /* per-painting vibrance — the first painting is already heavily saturated */
  imgFilter: string;
  alt: string;
  Demo: ({ active }: { active: boolean }) => ReactNode;
};

const FEATURES: Feature[] = [
  {
    key: "recompute",
    title: <>Recompute, don&apos;t trust.</>,
    body: (
      <>
        Connect a repo and Calma rebuilds the environment, re-running{" "}
        <span className="chip">
          <FaTerminal style={{ color: "#1f1a13" }} />
          scripts
        </span>{" "}
        and{" "}
        <span className="chip">
          <SiJupyter style={{ color: "#f37626" }} />
          notebooks
        </span>{" "}
        in a network-off sandbox — even on{" "}
        <span className="chip">
          <SiPython style={{ color: "#3776ab" }} />
          era-pinned Python
        </span>
        . Then it recomputes the headline number from the raw arrays, never the README.
      </>
    ),
    img: "/img/features/recompute.jpg",
    imgFilter: "saturate(1.02) contrast(1.02) brightness(1.08)",
    alt: "Amber-toned painting of a vast planet rising over a rocky landscape",
    Demo: ConnectDemo,
  },
  {
    key: "validity",
    title: <>Reproducible isn&apos;t the same as true.</>,
    body: (
      <>
        A number can reproduce perfectly and still be a lie. Calma checks the structure behind
        it — train/eval leakage, trivial baselines, misreported predictions — and stamps a
        contaminated result <b>INVALIDATED</b>.
      </>
    ),
    img: "/img/features/validity.jpg",
    imgFilter: "saturate(1.3) contrast(1.06) brightness(1.05)",
    alt: "Amber-toned painting of a large planet over a sunset sea",
    Demo: ValidityDemo,
  },
  {
    key: "guardrail",
    title: <>A guardrail, not a report.</>,
    body: (
      <>
        A stop-hook in your agent&apos;s loop spots a checkable claim and runs the scan before the
        wrong number ships. The decision comes from deterministic code, never the model — when it
        can&apos;t prove a claim it says <b>INCONCLUSIVE</b>. Zero false confirms, ever.
      </>
    ),
    img: "/img/features/verdict.jpg",
    imgFilter: "saturate(1.3) contrast(1.06) brightness(1.05)",
    alt: "Amber-toned painting of a crescent moon and sun over calm water",
    Demo: HookDemo,
  },
];

function FeatureRow({ f, flip }: { f: Feature; flip: boolean }) {
  const reduce = useReducedMotion();
  const [ref, seen] = useInView<HTMLDivElement>(0.35);
  const inView = { once: true, margin: "0px 0px -12% 0px" as const };
  return (
    <article className={"featrow" + (flip ? " featrow--flip" : "")}>
      <motion.div
        className="featrow__copy"
        {...(reduce
          ? {}
          : {
              initial: { opacity: 0, x: flip ? 28 : -28, y: 24 },
              whileInView: { opacity: 1, x: 0, y: 0 },
              viewport: inView,
              transition: { duration: 0.8, ease: EASE },
            })}
      >
        <h3 className="featrow__h">{f.title}</h3>
        <p className="featrow__p">{f.body}</p>
      </motion.div>
      <motion.div
        ref={ref}
        className="featrow__media fscene"
        {...(reduce
          ? {}
          : {
              initial: { opacity: 0, y: 36, scale: 0.97 },
              whileInView: { opacity: 1, y: 0, scale: 1 },
              viewport: inView,
              transition: { duration: 0.9, ease: EASE },
            })}
      >
        <Image src={f.img} alt={f.alt} fill sizes="(max-width: 820px) 100vw, 55vw" className="fscene__img" style={{ filter: f.imgFilter }} />
        <div className="fscene__float">
          <f.Demo active={seen} />
        </div>
      </motion.div>
    </article>
  );
}

export function BpFeatures() {
  return (
    <section className="feats flowsec" id="features">
      <div className="wrap">
        <motion.div
          className="bp-head bp-head--center feats__head"
          initial={{ opacity: 0, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "0px 0px -8% 0px" }}
          transition={{ duration: 0.7, ease: EASE }}
        >
          <h2 className="bp-h2">
            Anyone can read your number. <span className="am">Calma re-derives it.</span>
          </h2>
          <p className="bp-lead">Three things a model grading its own homework can&apos;t do.</p>
        </motion.div>
        <div className="feats__rows">
          {FEATURES.map((f, i) => (
            <FeatureRow key={f.key} f={f} flip={i % 2 === 1} />
          ))}
        </div>
      </div>
    </section>
  );
}

export default BpFeatures;
