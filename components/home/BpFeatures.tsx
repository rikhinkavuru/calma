import { SiPython, SiR, SiJulia, SiCplusplus, SiRust } from "react-icons/si";
import { FaArrowRightLong, FaCircleCheck, FaLock } from "react-icons/fa6";
import { Reveal } from "../chrome";

/* Features — three pillars on the same light band, beneath the flow:
   recompute → validity → proof. Each column is a visual card + title +
   a description with inline chips (Shepherd-style). */

export function BpFeatures() {
  return (
    <section className="flowsec">
      <div className="wrap">
        <div className="bp-block feat" id="features">
          <Reveal>
            <div className="bp-head bp-head--center">
              <h2 className="bp-h2">Proof, <span className="am">not opinion.</span></h2>
              <p className="bp-lead">
                Calma re-derives the number, checks the result is actually valid, and seals a proof
                anyone can replay — not a score you have to trust.
              </p>
            </div>
          </Reveal>

          <div className="feat__grid">
            {/* 1 — recompute */}
            <Reveal>
              <article className="featcol">
                <div className="featviz">
                  <div className="vrec">
                    <div className="vrec__row">
                      <span className="vrec__k">claimed Sharpe</span>
                      <span className="vrec__claim">2.61</span>
                    </div>
                    <span className="vrec__arrow" aria-hidden="true"><FaArrowRightLong /></span>
                    <div className="vrec__row">
                      <span className="vrec__k">recomputes to</span>
                      <span className="vrec__real">0.41</span>
                    </div>
                    <span className="fbadge fbadge--no">REFUTED</span>
                  </div>
                </div>
                <h3 className="featcol__h">Recompute, not trust</h3>
                <p className="featcol__p">
                  Re-executes your code in a network-off sandbox and recomputes the headline from the
                  raw output files — never the reported number. Black-box over{" "}
                  <span className="chip"><SiPython /> Python</span>{" "}
                  <span className="chip"><SiR /> R</span>{" "}
                  <span className="chip"><SiJulia /> Julia</span>{" "}
                  <span className="chip"><SiCplusplus /> C++</span>{" "}
                  <span className="chip"><SiRust /> Rust</span>.
                </p>
              </article>
            </Reveal>

            {/* 2 — validity */}
            <Reveal delay={90}>
              <article className="featcol">
                <div className="featviz">
                  <div className="vval">
                    <div className="vval__row"><FaCircleCheck className="vval__ok" /> the number reproduces</div>
                    <div className="vval__flag">40% of the eval set is in the training corpus</div>
                    <span className="fbadge fbadge--inv">INVALIDATED</span>
                  </div>
                </div>
                <h3 className="featcol__h">Validity, not arithmetic</h3>
                <p className="featcol__p">
                  A number can reproduce perfectly and still be wrong. Calma flags{" "}
                  <span className="chip chip--p"><i style={{ background: "var(--sky)" }} /> leakage</span>{" "}
                  <span className="chip chip--p"><i style={{ background: "var(--amber)" }} /> overfitting</span>{" "}
                  <span className="chip chip--p"><i style={{ background: "var(--teal)" }} /> survivorship</span>{" "}
                  <span className="chip chip--p"><i style={{ background: "var(--sun)" }} /> contamination</span>{" "}
                  and stamps it INVALIDATED.
                </p>
              </article>
            </Reveal>

            {/* 3 — proof */}
            <Reveal delay={180}>
              <article className="featcol">
                <div className="featviz">
                  <div className="vproof">
                    <div className="vproof__row"><FaLock className="vproof__ico" /> verdict sealed</div>
                    <div className="vproof__chips">
                      <span>DSSE</span><span>SSHSIG</span><span>RFC-3161</span>
                    </div>
                    <div className="vproof__row vproof__row--ok"><FaCircleCheck className="vval__ok" /> re-verifies offline</div>
                  </div>
                </div>
                <h3 className="featcol__h">A proof, not a promise</h3>
                <p className="featcol__p">
                  One deterministic verdict, signed and timestamped — a proof a counterparty re-verifies{" "}
                  <span className="chip chip--p"><i style={{ background: "var(--teal)" }} /> offline</span>, with no
                  Calma server, runnable from the{" "}
                  <span className="chip chip--p"><i style={{ background: "var(--amber)" }} /> CLI</span>{" "}
                  <span className="chip chip--p"><i style={{ background: "var(--sky)" }} /> CI</span>{" "}
                  <span className="chip chip--p"><i style={{ background: "var(--sun)" }} /> MCP</span>.
                </p>
              </article>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
