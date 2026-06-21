"use client";

import { useState } from "react";
import { Reveal } from "../chrome";
import { CapIllo, type IlloKind } from "./CapIllo";

const CAPS: { label: string; desc: string; kind: IlloKind }[] = [
  { label: "Re-execution", desc: "Re-runs your code from scratch in a sandbox that proves its own isolation before it trusts a byte.", kind: "rerun" },
  { label: "Recompute · 623 recipes", desc: "Rebuilds the headline metric from raw output files — never the reported number — across 16 families.", kind: "recompute" },
  { label: "Validity layer", desc: "Eleven families catch the silently wrong: leakage, overfitting, survivorship, contamination, shift.", kind: "validity" },
  { label: "Determinism", desc: "One pure function maps the input vector to one label, re-derived byte-for-byte at the gate.", kind: "determinism" },
  { label: "Isolation", desc: "Network-off Seatbelt, bubblewrap, Docker, or a remote Firecracker microVM, self-tested each run.", kind: "isolation" },
  { label: "Attestation", desc: "A hash-chained ledger and a signed, offline-verifiable proof anyone can replay.", kind: "attestation" },
  { label: "Plausibility", desc: "Flags implausible Sharpe and too-smooth equity curves from the return series alone.", kind: "plausibility" },
];

export function BpFeatures() {
  const [active, setActive] = useState(0);
  const cur = CAPS[active];

  return (
    <div className="bp-block" id="features">
      <Reveal>
        <div className="bp-head">
          <span className="bp-kicker">Capabilities</span>
          <h2 className="bp-h2">One engine. <span className="am">Every check.</span></h2>
          <p className="bp-lead">Re-execute, recompute, and validate — every claim, in any language. Click through what the engine does.</p>
        </div>
      </Reveal>

      <div className="bp-feat">
        <div className="bp-acc">
          {CAPS.map((c, i) => (
            <button key={c.label} className={"bp-acc__item" + (i === active ? " is-on" : "")} onClick={() => setActive(i)} type="button">
              <span className="bp-acc__n">{String(i + 1).padStart(2, "0")}</span>
              <span className="bp-acc__label">{c.label}</span>
              <span className="bp-acc__chev">›</span>
            </button>
          ))}
        </div>

        <div className="bp-featviz">
          <div className="bp-featviz__top">
            <CapIllo key={active} kind={cur.kind} />
          </div>
          <div className="bp-featviz__cap" key={`cap-${active}`}>
            <h4>{cur.label}</h4>
            <p>{cur.desc}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
