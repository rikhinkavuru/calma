import type { Metadata } from "next";
import { Nav } from "../../components/chrome";
import { FAMILIES, RECIPE_COUNT } from "./data";

export const metadata: Metadata = {
  title: "The recipe library",
  description:
    `All ${RECIPE_COUNT} verification recipes: what each one checks, how the number is rebuilt ` +
    "from raw outputs, and the reference implementation it is validated against.",
};

export default function RecipesPage() {
  return (
    <>
      <div className="grain" aria-hidden="true"></div>
      <Nav />

      <main className="rpage texture">
        <section className="sec rpage__head">
          <div className="wrap">
            <div className="sec__head">
              <span className="kicker">The recipe library</span>
              <h1 className="h2">
                {RECIPE_COUNT} ways to rebuild a number. Zero opinions.
              </h1>
              <p className="lead">
                A recipe is the deterministic procedure Calma uses to recompute one kind of claim
                from raw output files. Every recipe obeys the same four rules: it reads{" "}
                <b>only machine-readable raw outputs</b> — never the number that was reported; it
                runs on <b>bit-stable deterministic kernels</b> (no GPU, no platform math
                libraries, no model anywhere in the path); it is{" "}
                <b>validated against the published reference implementation</b> — scikit-learn,
                SciPy, NumPy, numpy-financial, the HumanEval estimator — across 385 pinned
                reference vectors before it ships; and when its input is broken or ambiguous it{" "}
                <b>degrades to “can&apos;t confirm”</b> instead of guessing.
              </p>
            </div>
          </div>
        </section>

        <div className="rpage__body">
          <aside className="rtoc" aria-label="Recipe families">
            <span className="rtoc__title">Contents</span>
            <ol>
              {FAMILIES.map((fam, fi) => (
                <li key={fam.key}>
                  <a href={`#${fam.key}`}>
                    <span className="rtoc__n">{String(fi + 1).padStart(2, "0")}</span>
                    <span className="rtoc__label">{fam.title}</span>
                    <span className="rtoc__c">{fam.recipes.length}</span>
                  </a>
                </li>
              ))}
            </ol>
          </aside>

          <div className="rpage__fams">
            {FAMILIES.map((fam, fi) => (
              <section className="rfam" key={fam.key} id={fam.key}>
                <div className="rfam__head">
                  <span className="kicker">
                    {String(fi + 1).padStart(2, "0")} · {fam.title}
                  </span>
                  <span className="rfam__count mono">
                    {fam.recipes.length} recipe{fam.recipes.length > 1 ? "s" : ""}
                  </span>
                </div>
                <p className="rfam__blurb">{fam.blurb}</p>
                <div className="rlist">
                  {fam.recipes.map((r) => (
                    <article className="rcp" key={r.id} id={r.id}>
                      <div className="rcp__top">
                        <h3 className="rcp__name">{r.name}</h3>
                        <span className="rcp__id mono">{r.id}</span>
                      </div>
                      <p className="rcp__claim">{r.claim}</p>
                      <p className="rcp__what">{r.what}</p>
                      <p className="rcp__how">
                        <span className="rcp__k">recompute</span> {r.how}
                      </p>
                      <div className="rcp__meta">
                        <span className="rcp__ref">
                          <span className="rcp__k">validated against</span> {r.ref}
                        </span>
                        {r.conv ? (
                          <span className="rcp__conv">
                            <span className="rcp__k">conventions</span> {r.conv}
                          </span>
                        ) : null}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>

        <section className="sec rpage__foot">
          <div className="wrap">
            <hr className="hline" />
            <p className="lead" style={{ marginTop: 28 }}>
              Every recipe above is exercised by the open-source test suite against its reference
              implementation, and the whole library is one dependency-free folder. If your claim
              isn&apos;t covered yet, the contract format lets you pin any column to any recipe —
              and the library grows in validated packs, never one-off hacks.
            </p>
            <div style={{ marginTop: 30, display: "flex", gap: 16, flexWrap: "wrap" }}>
              <a
                className="pbtn"
                href="https://github.com/rikhinkavuru/calma"
                target="_blank"
                rel="noreferrer"
              >
                Get the free skill
              </a>
              <a className="pbtn pbtn--amber" href="/">
                ← Back to Calma
              </a>
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
