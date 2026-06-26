import type { ReactNode } from "react";
import { FaArrowRightLong, FaCircleCheck, FaLock } from "react-icons/fa6";
import { Reveal } from "../chrome";
import { FeatureMedia } from "./FeatureMedia";

/* ============================================================================
   MOATS — the features section under the flow. Alternating copy / screen-recording
   rows, four to a page, each one a thing a model grading its own work cannot do.
   Copy is grounded in the actual engine (run_hermetic.py, the *_checks.py validity
   detectors, attest.py/sshsig.py/ed25519.py, hook_stop.py) — not the README.

   Each row ships an illustrated fallback now; drop /video/feature-<key>.mp4 into
   web/public/video and flip `videoReady` to true to swap in the screen recording.
   ========================================================================== */

type Moat = {
  key: string;
  idx: string;
  title: ReactNode;
  body: ReactNode;
  tags: string[];
  video: string;
  videoReady: boolean;
  viz: ReactNode;
};

/* ---- illustrated fallbacks (shown until a recording is dropped in) ---- */

const RecViz = (
  <div className="mvz">
    <div className="mvz__rec">
      <div className="mvz__recrow">
        <span className="mvz__k">agent reported</span>
        <span className="mvz__claim">Sharpe 2.61</span>
      </div>
      <span className="mvz__arrow" aria-hidden="true">
        <FaArrowRightLong />
      </span>
      <div className="mvz__recrow">
        <span className="mvz__k">recomputes from raw output</span>
        <span className="mvz__real">0.41</span>
      </div>
    </div>
    <span className="mvz__badge mvz__badge--no">REFUTED</span>
  </div>
);

const ValViz = (
  <div className="mvz">
    <div className="mvz__line">
      <FaCircleCheck className="mvz__ok" /> the number reproduces, to the bit
    </div>
    <div className="mvz__flag">38% of the eval set also appears in the training split</div>
    <span className="mvz__badge mvz__badge--inv">INVALIDATED</span>
  </div>
);

const ProofViz = (
  <div className="mvz">
    <div className="mvz__line">
      <FaLock className="mvz__lock" /> verdict sealed &amp; signed
    </div>
    <div className="mvz__chips">
      <span>DSSE</span>
      <span>SSHSIG</span>
      <span>Ed25519</span>
      <span>RFC-3161</span>
    </div>
    <div className="mvz__line mvz__line--ok">
      <FaCircleCheck className="mvz__ok" /> re-verifies offline, no server
    </div>
  </div>
);

const GuardViz = (
  <div className="mvz mvz--term">
    <div className="mvz__t">
      <span className="mvz__tp">agent</span> &ldquo;…final return came out to +312%.&rdquo;
    </div>
    <div className="mvz__t mvz__t--hook">
      <span className="mvz__ttag">calma · stop-hook</span> re-runs the work on backtest.csv
    </div>
    <div className="mvz__t mvz__t--end">
      <span className="mvz__badge mvz__badge--no">REFUTED</span> turn blocked before it ships
    </div>
  </div>
);

const MOATS: Moat[] = [
  {
    key: "recompute",
    idx: "01",
    title: (
      <>
        Recompute, <em>not trust.</em>
      </>
    ),
    body: (
      <>
        Calma re-executes your agent&apos;s code in a network-off sandbox and recomputes the headline
        number straight from the files it actually wrote — the CSVs, JSON, <span className="mono">.npy</span>{" "}
        and Parquet — <b>never the number it reported in chat</b>. It treats your code as a black box, so
        the language doesn&apos;t matter.
      </>
    ),
    tags: ["Python", "R", "Julia", "C/C++", "Rust"],
    video: "/video/feature-recompute.mp4",
    videoReady: false,
    viz: RecViz,
  },
  {
    key: "validity",
    idx: "02",
    title: (
      <>
        Validity, <em>not arithmetic.</em>
      </>
    ),
    body: (
      <>
        A number can reproduce perfectly and still be a lie. Calma runs structural checks the model
        can&apos;t talk its way past — <b>row-level leakage</b> by hash, look-ahead and point-in-time,
        purged-era embargo, multiple-testing haircuts, regime and distribution shift — and stamps a
        contaminated result <b>INVALIDATED</b>.
      </>
    ),
    tags: ["leakage", "look-ahead", "embargo", "data-snooping", "shift"],
    video: "/video/feature-validity.mp4",
    videoReady: false,
    viz: ValViz,
  },
  {
    key: "proof",
    idx: "03",
    title: (
      <>
        A proof, <em>not a promise.</em>
      </>
    ),
    body: (
      <>
        Every verdict is sealed in a signed bundle — a DSSE envelope over an in-toto statement, signed
        with Ed25519 <i>and</i> OpenSSH SSHSIG, with an optional RFC-3161 timestamp. A counterparty
        re-derives the verdict byte-for-byte and checks the signature <b>offline, with stock{" "}
        <span className="mono">ssh-keygen</span></b> — no Calma server, years later.
      </>
    ),
    tags: ["DSSE", "SSHSIG", "Ed25519", "RFC-3161"],
    video: "/video/feature-proof.mp4",
    videoReady: false,
    viz: ProofViz,
  },
  {
    key: "guardrail",
    idx: "04",
    title: (
      <>
        A guardrail, <em>not a report.</em>
      </>
    ),
    body: (
      <>
        Install the plugin and it&apos;s invisible until it isn&apos;t: a Stop-hook reads your agent&apos;s
        last message, spots a checkable number, and re-runs the work to prove it <b>before the turn
        ends</b>. It blocks only on a definitive break, fails open on any error, and never nags twice.
        The same engine runs as a required PR check.
      </>
    ),
    tags: ["Stop-hook", "PR gate", "fail-open"],
    video: "/video/feature-guardrail.mp4",
    videoReady: false,
    viz: GuardViz,
  },
];

export function BpMoats() {
  return (
    <section className="moats flowsec" id="features">
      <div className="wrap">
        <Reveal>
          <div className="bp-head bp-head--center">
            <span className="bp-kicker">Under the hood</span>
            <h2 className="bp-h2">
              Anyone can read your number. <span className="am">Calma re-derives it.</span>
            </h2>
            <p className="bp-lead">
              Four things that happen to every result — each one something a model grading its own
              homework can&apos;t do.
            </p>
          </div>
        </Reveal>

        <div className="moats__list">
          {MOATS.map((m) => (
            <Reveal key={m.key}>
              <article className="fmoat">
                <div className="fmoat__copy">
                  <span className="fmoat__idx mono">{m.idx}</span>
                  <h3 className="fmoat__h">{m.title}</h3>
                  <p className="fmoat__p">{m.body}</p>
                  <div className="fmoat__meta">
                    {m.tags.map((t) => (
                      <span key={t} className="fmoat__tag mono">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="fmoat__media">
                  <FeatureMedia label={`calma · ${m.key}`} src={m.video} videoReady={m.videoReady}>
                    {m.viz}
                  </FeatureMedia>
                </div>
              </article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

export default BpMoats;
