import { Reveal } from "../chrome";
import { GITHUB_URL } from "../contact";

const WHO = [
  { ic: "⚒", who: "Builders", h: "Catch it before your users do", p: "Your agent checks its own work as it goes — the wrong backtest, eval, or metric dies in the loop, not in production.", cta: "Get the free skill", href: GITHUB_URL, amber: true },
  { ic: "⎈", who: "Teams", h: "Block the merge on a wrong number", p: "Calma runs as a required PR check — a blocking gate, not a comment-bot opinion. A refuted or invalidated number fails the check, so it can't be merged. The proof travels with the work, and anyone can replay it.", cta: "Read the docs", href: "/install", amber: false },
  { ic: "◆", who: "Investors & funds", h: "Proof before the money moves", p: "Before you act on a number, the lab independently re-executes the research — with a reproduction your own side can run.", cta: "How the lab works", href: "/lab", amber: false },
];

export function BpWho() {
  return (
    <div className="bp-block" id="benefits">
      <Reveal>
        <div className="bp-head">
          <span className="bp-kicker">Who it&apos;s for</span>
          <h2 className="bp-h2">Three ways people use <span className="am">Calma.</span></h2>
        </div>
      </Reveal>
      <div className="bp-who">
        {WHO.map((w, i) => (
          <Reveal key={w.who} delay={i * 90}>
            <a className={"bp-whocard" + (w.amber ? " bp-whocard--amber" : "")} href={w.href} target={w.href.startsWith("http") ? "_blank" : undefined} rel="noreferrer">
              <span className="bp-whocard__ic">{w.ic}</span>
              <span className="bp-whocard__who">{w.who}</span>
              <h3 className="bp-whocard__h">{w.h}</h3>
              <p className="bp-whocard__p">{w.p}</p>
              <span className="bp-whocard__cta">{w.cta} →</span>
            </a>
          </Reveal>
        ))}
      </div>
    </div>
  );
}
