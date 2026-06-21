"use client";

import { useState } from "react";
import { Reveal } from "./chrome";
import { SiteNav } from "./SiteNav";
import { CONTACT_EMAIL } from "./contact";
import { RequestDialog } from "./RequestDialog";

/* The lab surface: forensic verification for the capital side. The OSS skill is the
   free, loud proof the engine is real; THIS is the company. */

const WHO: [string, string, string][] = [
  [
    "Allocators & ODD teams",
    "Before the allocation",
    "A result in a pitch — a backtest, a model, a research claim — independently re-executed and recomputed before it enters your IC memo. Slots into the operational due diligence you already run.",
  ],
  [
    "Seeders & platforms",
    "Before the seed",
    "The same forensic pass across a stable of candidate managers or internal research teams — with a verdict per claim and a reproduction your own analysts can run.",
  ],
  [
    "Managers & research teams",
    "Before you present",
    "Attestation, under terms that make it mean something: prepaid, logged in the registry, and a disclosed trial log behind any headline performance stamp. A stamp anyone could buy would be worthless to you.",
  ],
];

const STEPS: [string, string, string][] = [
  [
    "01",
    "Scope",
    "You name the claims that matter — the return, the Sharpe, the accuracy, the capacity figure. We contract the exact artifacts, code, and data that produced them. Prepaid, non-contingent.",
  ],
  [
    "02",
    "Re-execute",
    "The work runs again in an isolated environment, from scratch. The headline numbers are rebuilt from the raw outputs on deterministic kernels — never read from the deck.",
  ],
  [
    "03",
    "Report",
    "Per claim: confirmed, refuted, invalidated, confirmed-with-caveats, or can't-confirm — with the recomputed number, the gap, what was and wasn't verified, and a signed, trusted-timestamped attestation bundle your side checks offline: verify the signature with stock OpenSSH, re-derive every verdict, replay the entire run.",
  ],
  [
    "04",
    "Registry",
    "The engagement is logged in the consented public registry — including engagements that were withdrawn or refuted. The population of stamps carries signal because the misses are in it too.",
  ],
];

const TERMS: [string, string][] = [
  [
    "Prepaid and non-contingent",
    "The fee is the same whether the result confirms or breaks. Nobody can buy a verdict, and no verdict is softened to keep a client.",
  ],
  [
    "Every engagement is logged",
    "The registry records every engagement — confirmed, refuted, withdrawn — clinical-trial style. A stamp only means something if the stamps that failed are visible too.",
  ],
  [
    "Headline stamps require the trial log",
    "A backtest stamp without the other attempts behind it is marketing. Headline performance claims require a disclosed trial log, and we deflate for multiple testing before any stamp.",
  ],
  [
    "Every report states its limits",
    "Reproducible is not the same as right. Each report stamps exactly what was verified, what wasn't, and at what isolation and determinism tier — no verdict ever overreaches its evidence.",
  ],
  [
    "Your code and data stay yours",
    "Engagements run under NDA in an isolated environment scoped in the engagement letter. What enters the public registry is redacted by construction — claim, metric, claimed vs recomputed, verdict, and content hashes. Never code, never data, never positions.",
  ],
];

const VS: [string, string][] = [
  [
    "vs. asking your own agent",
    "The auditor can't be the auditee. The best agents score ~21% at assessing reproducibility on REPRO-Bench (arxiv.org/abs/2507.18901); Calma re-executes and decides with code.",
  ],
  [
    "vs. eval & observability tools",
    "They sell self-evaluation to the builder. The lab sells verdicts to the counterparty — the side whose money moves on the answer.",
  ],
  [
    "vs. provenance & timestamping",
    "They prove when you knew the number. Calma proves the number is real.",
  ],
];

export default function LabClient() {
  const [dlg, setDlg] = useState(false);
  return (
    <>
      <div className="grain" aria-hidden="true"></div>
      <SiteNav />

      <main className="rpage texture">
        <section className="sec rpage__head">
          <div className="wrap">
            <div className="sec__head">
              <Reveal>
                <span className="kicker">The Calma Lab</span>
              </Reveal>
              <Reveal delay={120}>
                <h1 className="h1">Proof before the money moves.</h1>
              </Reveal>
              <Reveal delay={220}>
                <p className="lead">
                  The lab is a verification practice for capital allocation in the age of
                  AI-produced research. Before a number changes a decision — an allocation, a seed,
                  a mandate — Calma <b>independently re-executes the work and recomputes the
                  result, deterministically</b>, for the people whose money is at stake. Not an
                  opinion on the methodology. The number, rebuilt.
                </p>
              </Reveal>
              <Reveal delay={300}>
                <p className="lead labwhy">
                  The failure modes that matter — overfitting, cherry-picking, leakage — are driven
                  by incentives, not model error. They get <b>stronger as models improve</b>: a
                  better optimizer produces more convincing overfits. That&apos;s why this is forensic
                  work, built to survive an adversarial author.
                </p>
              </Reveal>
            </div>
          </div>
        </section>

        <section className="sec rfam">
          <div className="wrap">
            <Reveal>
              <div className="rfam__head">
                <span className="kicker">01 · Who engages the lab</span>
              </div>
            </Reveal>
            <Reveal delay={150}>
              <div className="labwho">
                {WHO.map(([who, when, d]) => (
                  <div className="labcard" key={who}>
                    <span className="labcard__when mono">{when}</span>
                    <h3>{who}</h3>
                    <p>{d}</p>
                  </div>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <section className="sec rfam">
          <div className="wrap">
            <Reveal>
              <div className="rfam__head">
                <span className="kicker">02 · How an engagement works</span>
              </div>
            </Reveal>
            <Reveal delay={150}>
              <div className="steps steps--4">
                {STEPS.map(([n, t, d], i) => (
                  <div className={"step" + (i === 3 ? " step--out" : "")} key={n}>
                    <span className="step__n">{n}</span>
                    <h3>{t}</h3>
                    <p>{d}</p>
                  </div>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <section className="sec rfam">
          <div className="wrap">
            <Reveal>
              <div className="rfam__head">
                <span className="kicker">03 · Terms that make a verdict credible</span>
              </div>
            </Reveal>
            <Reveal delay={120}>
              <p className="rfam__blurb">
                A verification only has value if it would have caught the lie. Every engagement
                runs under terms designed for the adversarial case:
              </p>
            </Reveal>
            <Reveal delay={200}>
              <div className="terms">
                {TERMS.map(([t, d]) => (
                  <div className="term-row" key={t}>
                    <h3>{t}</h3>
                    <p>{d}</p>
                  </div>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        <section className="sec rfam">
          <div className="wrap">
            <Reveal>
              <div className="rfam__head">
                <span className="kicker">04 · Where this sits</span>
              </div>
            </Reveal>
            <Reveal delay={150}>
              <div className="labvs">
                {VS.map(([t, d]) => (
                  <div className="labvs__row" key={t}>
                    <span className="labvs__t mono">{t}</span>
                    <p>{d}</p>
                  </div>
                ))}
              </div>
            </Reveal>
            <Reveal delay={220}>
              <p className="labfine micro">
                The engine behind every engagement is open source — the free Calma skill is the
                live, public proof it&apos;s real. The lab is the practice built on top of it.
              </p>
            </Reveal>
          </div>
        </section>

        <section className="sec rpage__foot">
          <div className="wrap">
            <hr className="hline" />
            <Reveal>
              <div className="labcta">
                <div>
                  <h2 className="h2">Have a number that&apos;s about to move money?</h2>
                  <p className="lead" style={{ marginTop: 14 }}>
                    Send the claim. We&apos;ll scope what it would take to prove it — or break it.
                  </p>
                </div>
                <div className="labcta__btns">
                  <button className="pbtn pbtn--amber" onClick={() => setDlg(true)}>
                    Request verification
                  </button>
                  <span className="fine">
                    Engagements are limited — a person replies. Or email{" "}
                    <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
                  </span>
                </div>
              </div>
            </Reveal>
          </div>
        </section>
      </main>
      <RequestDialog open={dlg} onClose={() => setDlg(false)} />
    </>
  );
}
