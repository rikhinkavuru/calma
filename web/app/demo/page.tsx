import type { Metadata } from "next";
import { SiteNav } from "../../components/SiteNav";
import { DemoClient } from "./DemoClient";

export const metadata: Metadata = {
  title: "Live demo — no signup",
  description:
    "Watch Calma re-run a real repo and recompute its reported number, live, with no account required.",
};

export default function DemoPage() {
  return (
    <>
      <div className="grain" aria-hidden="true"></div>
      <SiteNav />

      <main className="rpage texture">
        <section className="sec rpage__head">
          <div className="wrap">
            <div className="sec__head">
              <span className="kicker">Live demo</span>
              <h1 className="h2">No signup. Just watch it catch one.</h1>
              <p className="lead">
                One button, one fixed sample repo. Calma clones it, re-runs the code in an isolated sandbox,
                and recomputes the reported number independently — then tells you whether the README was
                telling the truth.
              </p>
            </div>
          </div>
        </section>

        <section className="sec sec--alt">
          <div className="wrap">
            <DemoClient />
          </div>
        </section>

        <section className="sec rpage__foot">
          <div className="wrap">
            <p className="rpage__verify">
              Ready for your own repo? <a href="/dashboard">Verify a repo →</a>
            </p>
          </div>
        </section>
      </main>
    </>
  );
}
