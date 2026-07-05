"use client";

import { useState } from "react";
import Link from "next/link";
import { Reveal } from "../chrome";

/* Copy is grounded in the current engine: pipeline.py (three-way diff, deep=False validity scan),
   core/verdict.py taxonomy, runner/e2b_runner (single-use microVM, network-off execution),
   attest/ (signed verdict attestations), and the FCR=0 release gate. */
const QA: { q: string; a: React.ReactNode }[] = [
  { q: "What is Calma, in one sentence?", a: <>Connect a repo and Calma independently re-runs the work, recomputes every number it claims, and tells you which ones hold — <b>Confirmed, Refuted, Invalidated, or Inconclusive.</b></> },
  { q: "Why can't the AI just check its own work?", a: <>Because it grades its own homework. Even when it re-runs the code, it still decides whether the answer matches — and it tends to agree with itself. <b>Calma&apos;s verdict is produced by deterministic code the AI can&apos;t influence.</b></> },
  { q: "What do I get back?", a: <>A verdict per claim, with the recomputed number next to the claimed one, the reason behind the verdict, and the evidence — which artifact it was recomputed from and whether the run was deterministic. <b>When Calma can&apos;t verify a claim it says so; it never guesses.</b></> },
  { q: "Where does my code run?", a: <>In an isolated, single-use microVM sandbox with the network cut off while your code executes. <b>The sandbox is created for your run and destroyed when it finishes.</b></> },
  { q: "Do you have to re-run my code to catch anything?", a: <>No. The validity scan works without executing anything — it checks committed train/eval splits for leakage, compares the score against a trivial baseline, and recomputes from committed predictions. <b>The full re-run is what upgrades a claim to Confirmed.</b></> },
  { q: "What does it cost?", a: <>Verifying starts free. Paid tiers add depth and volume — <b><Link href="/pricing">see pricing</Link>.</b></> },
];

export function BpFaq() {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="bp-block" id="faq">
      <Reveal>
        <div className="bp-head">
          <h2 className="bp-h2">The fine print, in <span className="am">plain English.</span></h2>
        </div>
      </Reveal>
      <div className="bp-faq">
        {QA.map((item, i) => (
          <div className={"bp-faq__item" + (open === i ? " is-open" : "")} key={item.q}>
            <button className="bp-faq__q" type="button" onClick={() => setOpen(open === i ? null : i)}>
              {item.q}
              <span className="pm">+</span>
            </button>
            <div className="bp-faq__a"><p>{item.a}</p></div>
          </div>
        ))}
      </div>
    </div>
  );
}
