"use client";

import { useState } from "react";
import { Reveal } from "../chrome";

const QA: { q: string; a: React.ReactNode }[] = [
  { q: "What is Calma, in one sentence?", a: <>An automatic guardrail for AI-generated results — it re-runs your agent&apos;s work, recomputes the numbers it reported, and <b>blocks the wrong ones before they ship.</b></> },
  { q: "Why can't the AI just check its own work?", a: <>Because it grades its own homework. Even when it re-runs the code, it still decides whether the answer matches — and it tends to agree with itself. <b>Calma&apos;s decision is made by code the AI can&apos;t influence.</b></> },
  { q: "What do I get back?", a: <>One of three outcomes — <b>Confirmed</b>, <b>Caught</b>, or <b>Can&apos;t-tell</b> — each with the precise verdict and the reason behind it, the fix when something&apos;s missing, and <b>a one-command replay anyone can run.</b></> },
  { q: "Can it block a PR from merging?", a: <>Yes — that&apos;s a distinct surface. Calma runs as a <b>required PR check</b>, a blocking gate rather than a comment-bot opinion: a refuted or invalidated number fails the check, so a wrong number is blocked from merging once you mark the gate required in branch protection. <b>Prove your own numbers before you ship.</b></> },
  { q: "Does my code or data leave my machine?", a: <>No. Calma re-runs everything locally, inside a sandbox that blocks the network — <b>your code, your data, and your results are never uploaded by the verifier.</b> (Optional tiers you turn on explicitly — a remote microVM for untrusted code, an RFC-3161 timestamp — make a network call, and the ledger records which.)</> },
  { q: "What does it cost?", a: <>The skill is free and open source — install it and your agents use it today. The lab&apos;s signed verification reports are paid engagements, <b>for when money is about to move on a number.</b></> },
];

export function BpFaq() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <div className="bp-block" id="faq">
      <Reveal>
        <div className="bp-head">
          <span className="bp-kicker">Questions</span>
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
