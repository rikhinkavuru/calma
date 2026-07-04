import { Reveal } from "../chrome";

// The GTM validity wedge front door: "check your repo for leakage / trivial baseline / misreport — no
// setup, no run." A dark band directly under the hero (BpFlow opens the first light band below it). Backed
// by spike/validity_scan.py (deep=false), which grades these three no-reproduction checks. Reuses the site's
// bp-head + .steps kit so it inherits the shared hover language and palette with zero new CSS.

const CHECKS: { n: string; title: string; body: string; out?: boolean }[] = [
  {
    n: "01",
    title: "Data leakage",
    body: "Committed train/test splits that share rows — duplicate-row and near-duplicate (homology) contamination that quietly inflates the headline.",
  },
  {
    n: "02",
    title: "Trivial baseline",
    body: "A number a constant or majority-class guess already beats — an accuracy at the label prior, an AUROC at 0.5, a degenerate single-class split.",
  },
  {
    n: "03",
    title: "Misreport",
    body: "A reported number that a recompute of the repo's own committed predictions doesn't reproduce — the claim and the code disagree.",
    out: true,
  },
];

export function BpValidityWedge() {
  return (
    <section className="sec" id="validity">
      <div className="wrap">
        <Reveal>
          <div className="bp-head bp-head--center">
            <span className="bp-kicker">No setup · no run</span>
            <h2 className="bp-h2">
              Catch the three ways a number lies — <span className="am">before it ships.</span>
            </h2>
            <p className="bp-lead">
              Point Calma at a repo and it grades the failure modes that don&apos;t need a re-run:{" "}
              <b>data leakage</b>, a <b>trivially-beatable baseline</b>, and a <b>misreport</b> — no
              environment to build, no code to execute. A fast, fail-closed report card.
            </p>
          </div>
        </Reveal>

        <Reveal delay={80}>
          <div className="steps" style={{ marginTop: "clamp(32px, 4vw, 56px)" }}>
            {CHECKS.map((c) => (
              <div key={c.n} className={`step${c.out ? " step--out" : ""}`}>
                <span className="step__n">{c.n}</span>
                <h3>{c.title}</h3>
                <p>{c.body}</p>
              </div>
            ))}
          </div>
        </Reveal>

        <Reveal delay={140}>
          <div style={{ display: "flex", justifyContent: "center", marginTop: "clamp(28px, 3.5vw, 44px)" }}>
            <a className="btn-primary" href="/dashboard/verify">
              Check a repo <span className="arrow" aria-hidden="true">→</span>
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export default BpValidityWedge;
