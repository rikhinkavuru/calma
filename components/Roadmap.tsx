"use client";

/* Roadmap — the plan as a timeline, for demos and pitches. Open-source skill
   today, on a path to a CLI and a managed layer. Dark island for tonal rhythm. */
import { motion } from "framer-motion";
import { Eyebrow, useInView } from "./primitives";
import { Reveal } from "./Reveal";

type Phase = {
  num: string;
  phase: string;
  status: string;
  title: string;
  desc: string;
  surface: string;
  live?: boolean;
  now?: boolean;
};

const PHASES: Phase[] = [
  {
    num: "01",
    phase: "now",
    status: "open source · shipping",
    title: "Claude skill",
    desc: "The four checks, runnable inside Claude. Point it at a backtest; it flags look-ahead, survivorship, leakage and non-reproduction. Runs on your machine — your code never leaves.",
    surface: "claude ▸ /calma verify momentum_v4.py",
    live: true,
    now: true,
  },
  {
    num: "02",
    phase: "next",
    status: "in design",
    title: "Python package",
    desc: "The same checks as importable functions. Drop verification straight into a notebook or an existing research pipeline.",
    surface: "from calma import verify",
  },
  {
    num: "03",
    phase: "then",
    status: "planned",
    title: "CI check",
    desc: "A signed verdict on every pull request. Research can't merge until the backtest reproduces out-of-sample.",
    surface: "uses: calma/verify@v1",
  },
  {
    num: "04",
    phase: "later",
    status: "planned",
    title: "Calma CLI",
    desc: "The full independent layer as one command. Recomputed from your raw fills, with a reproducible signed report.",
    surface: "$ calma verify --holdout 2023Q4 strategy.py",
  },
  {
    num: "05",
    phase: "horizon",
    status: "the vision",
    title: "Managed verification",
    desc: "Outside verification before capital is committed. The auditor that quant research never had.",
    surface: "an independent third party for research",
  },
];

export function Roadmap() {
  const [ref, inView] = useInView<HTMLDivElement>({ threshold: 0.15 });
  // progress fill: caps on the second station so it never dies in a gap
  const fill = inView ? "20%" : "0%";

  return (
    <section id="roadmap" className="road theme-ink">
      <div className="road__grid" aria-hidden="true" />
      <span className="sec__wm mono" aria-hidden="true">
        03
      </span>
      <div className="wrap sec__wrap road__wrap">
        <Reveal className="road__head">
          <Eyebrow num="03">The plan</Eyebrow>
          <h2 className="road__title">From a skill you run today to the layer funds trust.</h2>
          <p className="road__sub">
            Calma starts as something you run yourself: open source, on your own machine. Independence gets earned one step at a time, not asked for on day one.
          </p>
        </Reveal>

        <div className="road__track" ref={ref}>
          <div className="road__line" aria-hidden="true">
            <span className="road__fill" style={{ "--fill": fill } as React.CSSProperties} />
          </div>
          {PHASES.map((p, i) => (
            <Reveal className={"rstep" + (p.now ? " is-now" : "")} key={p.num} delay={i * 0.07}>
              <div className="rstep__rail">
                <span className="rstep__node mono">{p.num}</span>
              </div>
              <motion.div className="rstep__card" whileHover={{ y: -4 }} transition={{ type: "spring", stiffness: 300, damping: 24 }}>
                <div className="rstep__meta mono">
                  <span className="rstep__phase">{p.phase}</span>
                  <span className="rstep__status">{p.status}</span>
                </div>
                <h3 className="rstep__title">{p.title}</h3>
                <p className="rstep__desc">{p.desc}</p>
                <div className="rstep__surface mono">
                  {p.live && <span className="rstep__livedot" aria-hidden="true" />}
                  <code>{p.surface}</code>
                </div>
              </motion.div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
