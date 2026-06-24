"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Atmo, Reveal } from "../chrome";
import { ErrorBoundary } from "../site/ErrorBoundary";
import { RecomputeDemo } from "./RecomputeDemo";
import s from "./landing.module.css";

const GradientBlinds = dynamic(() => import("../GradientBlinds"), { ssr: false });

/* ───────────────── hero ───────────────── */
function Hero() {
  const ref = useRef<HTMLElement>(null);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setPaused(!e.isIntersecting), { threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section className={`${s.section} ${s.hero}`} id="top" ref={ref}>
      <Atmo />
      <div aria-hidden="true" style={{ position: "absolute", inset: 0, zIndex: 0, opacity: 0.5, pointerEvents: "none" }}>
        <ErrorBoundary fallback={null}>
          <GradientBlinds
            gradientColors={["#2e4f6d", "#7fb89e", "#e89a5d", "#ffb36b"]}
            angle={20}
            blindCount={16}
            blindMinWidth={55}
            noise={0.3}
            spotlightRadius={0.9}
            spotlightSoftness={0.85}
            spotlightOpacity={0.6}
            mouseDampening={0.15}
            dpr={1}
            paused={paused}
            mixBlendMode="lighten"
          />
        </ErrorBoundary>
      </div>

      <div className={`${s.wrap} ${s.heroGrid}`} style={{ position: "relative", zIndex: 1 }}>
        <div>
          <Reveal>
            <span className={s.kicker}>Recompute, don&apos;t trust</span>
          </Reveal>
          <Reveal delay={120}>
            <h1 className={s.h1}>
              Catch the wrong <span className={s.accent}>number</span> before it ships.
            </h1>
          </Reveal>
          <Reveal delay={240}>
            <p className={s.lead}>
              Everyone else reads the diff or trusts the score. <b>Calma re-runs the work and
              recomputes the number</b> from the raw outputs — then proves it or breaks it.
            </p>
          </Reveal>
          <Reveal delay={340}>
            <div className={s.ctaRow}>
              <Link href="/dashboard" className={s.btnPrimary}>Start verifying</Link>
              <Link href="/install" className={s.btnGhost}>Read the docs</Link>
            </div>
            <p className={s.heroNote}>
              <code>$ pip install calma</code> &nbsp;·&nbsp; pure-stdlib engine
            </p>
          </Reveal>
        </div>

        <Reveal delay={420}>
          <RecomputeDemo />
        </Reveal>
      </div>
    </section>
  );
}

/* ───────────────── wedge ───────────────── */
function Wedge() {
  return (
    <section className={`${s.section} ${s.wedge}`} id="why">
      <div className={s.wrap}>
        <Reveal>
          <span className={s.kicker}>The wedge</span>
        </Reveal>
        <Reveal delay={120}>
          <h2 className={s.wedgeH}>
            A green checkmark is a claim about a claim. <em>Recompute it instead.</em>
          </h2>
        </Reveal>
        <div className={s.wedgeGrid}>
          <Reveal delay={200}>
            <p className={s.wedgeP}>
              Reading the diff tells you the code changed. Trusting the score tells you what the
              author wanted you to see. <b>Calma re-executes the work in an isolated environment and
              rebuilds the headline number from the raw outputs</b> — the load-bearing step that
              evals, observability, and provenance tools skip. Then it diffs the rebuilt number
              against the claim and a trivial baseline, and runs the validity battery on top.
            </p>
          </Reveal>
          <Reveal delay={300}>
            <div className={s.stat}>
              <div className={s.statN}>~21%</div>
              <p className={s.statL}>
                how well the best agents judge reproducibility on REPRO-Bench. The auditor can&apos;t
                be the auditee — Calma decides with code, not a second opinion.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* ───────────────── capabilities marquee ───────────────── */
const ROW_A = [
  "Sharpe", "Sortino", "Calmar", "max drawdown", "total return", "CAGR", "VaR", "CVaR",
  "alpha", "beta", "information ratio", "Brinson", "implied vol", "Black-Scholes Δ",
];
const ROW_B = [
  "AUC", "F1", "log-loss", "ECE", "Brier", "RMSE", "MAE", "R²", "recall@k", "NDCG", "MRR",
  "pass@k", "p-value", "effect size", "MAPE", "latency p99", "throughput", "peak memory", "coverage",
];

function Chips({ items, track }: { items: string[]; track: string }) {
  const doubled = [...items, ...items];
  return (
    <div className={s.marquee}>
      <div className={`${s.track} ${track}`}>
        {doubled.map((m, k) => (
          <span className={s.chip} key={k}>
            <b>▸</b> {m}
          </span>
        ))}
      </div>
    </div>
  );
}

function Caps() {
  return (
    <section className={`${s.section} ${s.caps}`} id="capabilities">
      <div className={s.wrap}>
        <div className={s.capsHead}>
          <Reveal>
            <h2 className={s.capsTitle}>One engine. Every kind of number.</h2>
          </Reveal>
          <Reveal delay={120}>
            <p className={s.capsSub}>
              Trading, ML, analytics, statistics, quant risk — recomputed across Python, R, Julia,
              C++ and Rust, as a black box.
            </p>
          </Reveal>
        </div>
      </div>
      <Chips items={ROW_A} track={s.track1} />
      <Chips items={ROW_B} track={s.track2} />
    </section>
  );
}

/* ───────────────── how it works ───────────────── */
const STEPS: [string, string, string][] = [
  ["01", "Run", "Re-execute the work from scratch in a network-denied sandbox — verified seatbelt, a read-only container, or a Firecracker microVM."],
  ["02", "Recompute", "Rebuild the headline number from the raw run outputs, host-side, on deterministic kernels. Never read from the report."],
  ["03", "Check", "Run the validity battery — data leakage, overfitting, multiple-testing, look-ahead, regime shift — that a reproducing number can still fail."],
  ["04", "Verdict", "CONFIRMED, REFUTED, or INVALIDATED — with the recomputed value, the gap, and a signed bundle you re-derive offline."],
];

function How() {
  return (
    <section className={`${s.section} ${s.how}`} id="how">
      <div className={s.wrap}>
        <Reveal>
          <span className={s.kicker}>How it works</span>
        </Reveal>
        <Reveal delay={120}>
          <h2 className={s.capsTitle} style={{ marginTop: 14, maxWidth: "26ch" }}>
            Re-execute to ground truth, then prove or break the claim.
          </h2>
        </Reveal>
        <div className={s.steps}>
          {STEPS.map(([n, t, d], idx) => (
            <Reveal key={n} delay={160 + idx * 90}>
              <div className={s.step}>
                <div className={s.stepN}>{n}</div>
                <h3 className={s.stepT}>{t}</h3>
                <p className={s.stepD}>{d}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Landing() {
  return (
    <>
      <Hero />
      <Wedge />
      <Caps />
      <How />
    </>
  );
}
