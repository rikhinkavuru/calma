"use client";

import { useEffect, useState } from "react";
import { DecryptedText } from "./DecryptedText";
import s from "./landing.module.css";

type Verdict = "CONFIRMED" | "REFUTED" | "INVALIDATED";
type Case = {
  claim: string;
  claimed: string;
  recomputed: string;
  third: { k: string; v: string; tone: "pos" | "neg" | "flag" };
  verdict: Verdict;
  note: string;
};

// Three teaching cases: a number that breaks, one that holds, one that reproduces but isn't valid.
const CASES: Case[] = [
  {
    claim: "Sharpe ratio of 2.10",
    claimed: "2.10",
    recomputed: "1.34",
    third: { k: "gap", v: "−0.76", tone: "neg" },
    verdict: "REFUTED",
    note: "Recomputed from the raw returns — the headline doesn't reproduce.",
  },
  {
    claim: "Total return +0.77%",
    claimed: "+0.77%",
    recomputed: "+0.77%",
    third: { k: "gap", v: "0.00", tone: "pos" },
    verdict: "CONFIRMED",
    note: "Rebuilt from the raw outputs, inside tolerance. The claim holds.",
  },
  {
    claim: "ROC-AUC of 0.94",
    claimed: "0.94",
    recomputed: "0.94",
    third: { k: "validity", v: "train∩test", tone: "flag" },
    verdict: "INVALIDATED",
    note: "The number reproduces — but train and test rows overlap. The split leaks.",
  },
];

const RUN_MS = 1200;
const HOLD_MS = 3600;

export function RecomputeDemo() {
  const [i, setI] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    setDone(false);
    const t1 = setTimeout(() => setDone(true), RUN_MS);
    const t2 = setTimeout(() => setI((x) => (x + 1) % CASES.length), RUN_MS + HOLD_MS);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [i]);

  const c = CASES[i];
  const toneClass = c.third.tone === "neg" ? s.gapNeg : c.third.tone === "pos" ? s.gapPos : s.recomp;

  return (
    <div className={s.demo} aria-label="Calma recompute-and-diff demo">
      <div className={s.demoBar}>
        <i /><i /><i />
        <span>calma verify</span>
      </div>
      <div className={s.demoBody}>
        <div className={s.demoLabel}>Claim</div>
        <p className={s.demoClaim}>{c.claim}</p>

        <div className={s.demoStatus}>
          {!done ? (
            <>
              <span className={s.pulse} />
              re-executing in isolation · recomputing…
            </>
          ) : (
            <>recomputed host-side from raw outputs</>
          )}
        </div>

        <div className={s.rows}>
          <div className={s.row}>
            <span className={s.rowK}>claimed</span>
            <span className={s.rowV}>{c.claimed}</span>
          </div>
          <div className={s.row}>
            <span className={s.rowK}>recomputed</span>
            <span className={`${s.rowV} ${s.recomp}`}>
              {done ? <DecryptedText text={c.recomputed} runKey={i} /> : "·····"}
            </span>
          </div>
          <div className={s.row}>
            <span className={s.rowK}>{c.third.k}</span>
            <span className={`${s.rowV} ${done ? toneClass : ""}`}>{done ? c.third.v : "·····"}</span>
          </div>
        </div>

        {done && (
          <div className={s.verdict}>
            <span
              className={`${s.badge} ${
                c.verdict === "CONFIRMED"
                  ? s.confirmed
                  : c.verdict === "REFUTED"
                  ? s.refuted
                  : s.invalidated
              }`}
            >
              {c.verdict}
            </span>
            <span className={s.verdictNote}>{c.note}</span>
          </div>
        )}
      </div>
      <div className={s.dots}>
        {CASES.map((_, k) => (
          <span key={k} className={`${s.dot} ${k === i ? s.on : ""}`} />
        ))}
      </div>
    </div>
  );
}
