import type { Metadata } from "next";
import { SiteNav } from "../../components/SiteNav";
import { GITHUB_URL } from "../../components/contact";
import { RECIPE_COUNT } from "../recipes/data";

export const metadata: Metadata = {
  title: "Install & CLI",
  description:
    "Install the Calma skill as a Claude Code plugin or drop it into any project, plus the full " +
    "calma CLI command reference. One self-contained folder, pure Python standard library, no dependencies.",
};

/* A static terminal-style code block, reusing the site's .term chrome. `lines`
   is a list of [prompt, rest, comment] — prompt in amber, comment muted. */
function Term({
  title,
  lines,
}: {
  title: string;
  lines: { p?: string; t?: string; c?: string }[];
}) {
  return (
    <div className="term inst__term">
      <div className="term__bar">
        <span className="term__dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="term__title">{title}</span>
      </div>
      <div className="term__body">
        {lines.map((l, i) => (
          <div key={i} className="inst__line">
            {l.p && <span className="p">{l.p}</span>}
            {l.t && <span className="cl">{l.t}</span>}
            {l.c && <span className="out">{l.c}</span>}
            {!l.p && !l.t && !l.c && " "}
          </div>
        ))}
      </div>
    </div>
  );
}

const COMMANDS: { p: string; t?: string; c?: string }[] = [
  { p: "calma up", c: "    # one command: detect the result + recipe, verify, prove — then it's bare `calma verify`" },
  { p: "calma demo", c: "  # zero-setup: catch a bundled real inflated backtest (offline, seconds)" },
  { p: "calma verify", t: " <folder> \"<claim>\"", c: "   # check a result against a claim (exit codes below)" },
  { p: "calma verify", t: " <folder>", c: "             # no claim: just check the result reproduces" },
  { p: "calma init", c: "  # auto-detect + write calma.toml (so the next verify is bare); --yes for CI" },
  { p: "calma status", c: "                          # is the guardrail on? recent checks + signing key" },
  { p: "calma doctor", t: " [--fix]", c: "             # health check: hook wired, runtime, signing key" },
  { p: "calma batch", t: " <dir>... | --manifest m.tsv", c: " # verify MANY results + one summary table (CI/sprint)" },
  { p: "calma recipes search", t: " \"<term>\"", c: "    # find a metric by name; `calma recipes` lists all" },
  { p: "calma recipes", c: `                       # the ${RECIPE_COUNT} built-in metrics, grouped by family` },
  { p: "calma schema", c: "                          # machine-readable CLI spec (agents; no --help parsing)" },
  { p: "calma verify", t: " ... --json", c: "          # machine-readable verdict (for agents / CI)" },
  { p: "calma verify", t: " ... --check-determinism", c: " # run twice; flaky outputs can't confirm anything" },
  { p: "calma verify", t: " ... --timeout 300", c: "   # raise the re-execution budget (default 120s)" },
  { p: "calma verify", t: " ... --trust third-party", c: " # counterparty code: refuse unless a sandbox tier is live" },
  { p: "calma teardown", t: " <folder> \"<claim>\"", c: " # shareable \"claimed X -> really Y\" card (+ --svg)" },
  { p: "calma replay", t: " <run_dir>", c: "            # re-run a saved verification; exit 0 iff it reproduces" },
  { p: "calma stats", t: " <folder>", c: "             # verification history: catches, hook activity" },
  { p: "calma proof show", t: " <dir>", c: "           # the proof at a glance + a shareable permalink + badge" },
  { p: "calma proof verify", t: " <proof>", c: "       # re-verify a proof OFFLINE (no network, no trust in our servers)" },
  { p: "calma seal", t: " <run_dir> [--publish]", c: "  # sign + RFC-3161 timestamp + counterparty instructions" },
  { p: "calma attest keygen", c: "                 # one-time signing key; after this every verify is signed" },
  { p: "calma registry verify", t: " [dir]", c: "      # audit the public catch-history chain offline" },
];

const EXIT_CODES: { code: string; meaning: string }[] = [
  { code: "0", meaning: "Confirmed — clean (CONFIRMED / CONFIRMED-WITH-CAVEATS)" },
  { code: "1", meaning: "Caught / Can't-tell — not clean (REFUTED / INVALIDATED / FLAG_FOR_DECLARATION / MIXED / CAN'T-CONFIRM)" },
  { code: "2", meaning: "bad input — missing target, malformed contract, unknown --metric" },
  { code: "3", meaning: "refused — execution declined (e.g. third-party code, no verified sandbox)" },
  { code: "4", meaning: "killed — the re-execution exceeded the --timeout budget" },
];

export default function InstallPage() {
  return (
    <>
      <div className="grain" aria-hidden="true"></div>
      <SiteNav />

      <main className="rpage texture">
        <section className="sec rpage__head">
          <div className="wrap">
            <div className="sec__head">
              <span className="kicker">Install &amp; CLI</span>
              <h1 className="h2">Up and running in one command.</h1>
              <p className="lead">
                Calma is one self-contained folder — pure Python standard library,{" "}
                <b>no dependencies</b>, Python 3.9+. Install it as a Claude Code plugin, drop it into
                any project that reads <span className="mono">SKILL.md</span>, or put the{" "}
                <span className="mono">calma</span> CLI on your PATH. macOS is first-class (verified
                sandbox, proven by a built-in self-test); Linux runs with reduced isolation and says
                so in the ledger; Windows is unsupported.
              </p>
            </div>
          </div>
        </section>

        <section className="sec sec--alt">
          <div className="wrap">
            <div className="inst__grid">
              <article className="inst__card">
                <span className="inst__num mono">01</span>
                <h3 className="inst__title">
                  Claude Code plugin <span className="inst__rec">recommended</span>
                </h3>
                <p className="inst__p">
                  Installs the skill <em>and</em> the zero-touch Stop-hook guardrail — it watches your
                  agent&apos;s final message for checkable numbers and re-executes the work to confirm
                  them <em>before the turn finishes</em>. Invisible until a number doesn&apos;t hold.
                </p>
                <Term
                  title="claude code — run each line on its own"
                  lines={[
                    { p: "/plugin", t: " marketplace add rikhinkavuru/calma", c: "  # step 1" },
                    { p: "/plugin", t: " install calma@calma", c: "             # step 2, after step 1 finishes" },
                  ]}
                />
              </article>

              <article className="inst__card">
                <span className="inst__num mono">02</span>
                <h3 className="inst__title">Drop into any project</h3>
                <p className="inst__p">
                  Works with every agent that reads <span className="mono">SKILL.md</span> — Claude
                  Code, Codex, Cursor, and more. No build step, nothing to configure.
                </p>
                <Term
                  title="bash"
                  lines={[
                    { p: "git clone", t: " https://github.com/rikhinkavuru/calma" },
                    { p: "cp -r", t: " calma/.claude/skills/calma  your-project/.claude/skills/" },
                  ]}
                />
              </article>

              <article className="inst__card">
                <span className="inst__num mono">03</span>
                <h3 className="inst__title">Plain CLI</h3>
                <p className="inst__p">
                  Pure stdlib — no pip, no deps. <span className="mono">install.sh</span> symlinks{" "}
                  <span className="mono">bin/calma</span> onto your PATH and prints a hint if needed.
                </p>
                <Term
                  title="bash"
                  lines={[
                    { p: "cd calma", c: "      # the repo you just cloned" },
                    { p: "./install.sh", c: " # or: make install" },
                    { p: "calma demo" },
                  ]}
                />
              </article>
            </div>
          </div>
        </section>

        <section className="sec">
          <div className="wrap">
            <div className="sec__head">
              <span className="kicker">The CLI</span>
              <h2 className="h2">Every command, one binary.</h2>
              <p className="lead">
                The same engine the skill calls, on your terminal. Verify a result, batch a whole
                sprint, sign and timestamp a verdict, or audit the public registry — all offline,
                all from <span className="mono">calma</span>.
              </p>
            </div>
            <Term title="calma --help" lines={COMMANDS} />

            <div className="inst__exit">
              <span className="inst__exit-h kicker">
                Exit codes <span className="mono">(calma verify)</span>
              </span>
              <ul className="inst__codes">
                {EXIT_CODES.map((e) => (
                  <li key={e.code} className="inst__code">
                    <span className="inst__code-n mono">{e.code}</span>
                    <span className="inst__code-m">{e.meaning}</span>
                  </li>
                ))}
              </ul>
              <p className="inst__doctor mono micro">
                prove the sandbox on your machine:
                <br />
                python3 .claude/skills/calma/scripts/run_hermetic.py doctor
              </p>
            </div>
          </div>
        </section>

        <section className="sec rpage__foot">
          <div className="wrap">
            <p className="micro">
              Opt out of the guardrail any time: <span className="mono">CALMA_HOOK=0</span>,{" "}
              <span className="mono">touch .calma/hook-off</span>, or{" "}
              <span className="mono">.calma/config.json &rarr; {`{"hook": {"enabled": false}}`}</span>.
              Every decision is logged to <span className="mono">.calma/auto_history.jsonl</span>.
            </p>
            <p className="rpage__verify">
              Full docs and source on{" "}
              <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                GitHub
              </a>{" "}
              — and the {RECIPE_COUNT} recipes are listed on the <a href="/recipes">recipes page</a>.
            </p>
          </div>
        </section>
      </main>
    </>
  );
}
