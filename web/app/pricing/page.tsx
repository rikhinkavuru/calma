import type { Metadata } from "next";
import { SiteNav } from "../../components/SiteNav";
import { GITHUB_URL, CONTACT_EMAIL } from "../../components/contact";
import styles from "./pricing.module.css";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Calma pricing — open-source engine, a free hosted tier, Pro for teams putting Calma in the deploy " +
    "path, and Enterprise for neutral third-party attestation. The verdict is never gated; tiers meter how " +
    "much you re-execute.",
  alternates: { canonical: "/pricing" },
};

type Tier = {
  id: string;
  name: string;
  price: string;
  per?: string;
  blurb: string;
  cta: { label: string; href: string; amber?: boolean };
  featured?: boolean;
  badge?: string;
  features: string[];
};

const TIERS: Tier[] = [
  {
    id: "oss",
    name: "Open Source",
    price: "$0",
    per: "self-host",
    blurb: "The recompute engine as a library + CLI. Verify on your own machine, bring your own compute.",
    cta: { label: "View on GitHub", href: GITHUB_URL },
    features: [
      "Recompute from committed artifacts + local runs",
      "628-recipe trusted metric catalog",
      "Full fail-closed verdict taxonomy",
      "Validity checks (leakage / overfitting)",
      "Self-hosted badge + CI gate",
      "Community support",
    ],
  },
  {
    id: "free",
    name: "Free",
    price: "$0",
    per: "hosted",
    blurb: "Connect a public repo and verify the numbers — the static layer always lights up, deep verify is capped.",
    cta: { label: "Start free", href: "/dashboard", amber: true },
    features: [
      "Connect any public repo",
      "5 deep-verify scans / day",
      "Top-3 claims per scan by salience",
      "30 sandbox-minutes / month",
      "Reproducibility badge + 7-day history",
      "Community support",
    ],
  },
  {
    id: "pro",
    name: "Pro / Team",
    price: "$49",
    per: "/ user / mo",
    blurb: "For teams putting Calma in the deploy path — private repos, CI merge-gate, signed proofs.",
    cta: { label: "Start Pro", href: "/dashboard", amber: true },
    featured: true,
    badge: "Most popular",
    features: [
      "Private repos + GitHub App connector",
      "100 deep-verify scans / day",
      "Top-25 claims + un-foolability anti-cheat",
      "600 sandbox-minutes / mo + metered overage",
      "CI / merge-gate + PR status checks",
      "Signed verdict attestation (ed25519)",
      "90-day history · email support",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "Custom",
    blurb: "For funds, labs, and regulated orgs where a wrong number costs millions — and neutrality is the point.",
    cta: { label: "Contact us", href: `mailto:${CONTACT_EMAIL}?subject=Calma%20Enterprise` },
    features: [
      "GPU verification (CUDA repos)",
      "Neutral third-party attestation",
      "Transparency log + Rekor anchor",
      "Audit / compliance evidence pack",
      "SSO / SAML · RLS / roles",
      "Dedicated capacity · BYOC / on-prem",
      "SLAs + dedicated support",
    ],
  },
];

export default function PricingPage() {
  return (
    <>
      <SiteNav />
      <main>
        <header className={`wrap ${styles.head}`}>
          <span className="kicker">Pricing</span>
          <h1>Meter the re-execution. Never the verdict.</h1>
          <p>
            Calma re-executes the world&apos;s computations, so compute is the real cost — tiers gate{" "}
            <em>how much</em> and <em>how deep</em> you re-run, never <em>whether</em> a wrong number can slip
            through. The full fail-closed verdict taxonomy is identical on every plan.
          </p>
          <p className={styles.note}>Placeholder pricing · billing (Stripe) coming soon</p>
        </header>

        <section className="wrap">
          <div className={styles.grid}>
            {TIERS.map((t) => (
              <div key={t.id} className={`${styles.card} ${t.featured ? styles.featured : ""}`}>
                {t.badge && <span className={styles.badge}>{t.badge}</span>}
                <span className={styles.tier}>{t.name}</span>
                <div className={styles.priceRow}>
                  <span className={styles.price}>{t.price}</span>
                  {t.per && <span className={styles.per}>{t.per}</span>}
                </div>
                <p className={styles.blurb}>{t.blurb}</p>
                <a
                  className={`${styles.cta} ${t.cta.amber ? styles.ctaAmber : ""}`}
                  href={t.cta.href}
                  {...(t.cta.href.startsWith("http") ? { target: "_blank", rel: "noreferrer" } : {})}
                >
                  {t.cta.label}
                </a>
                <ul className={styles.feats}>
                  {t.features.map((f) => (
                    <li key={f} className={styles.feat}>
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.foot}>
          <div className="wrap">
            <div className={styles.footGrid}>
              <div className={styles.footItem}>
                <h3>What a scan actually costs</h3>
                <p>
                  Discovery (listing every claimed number) is ~free and stays generous on every tier. Only the
                  expensive part — re-running the repo in an isolated sandbox — draws down your budget. At the
                  ceiling, deep verify pauses and discovery keeps running; you always get the claim list.
                </p>
              </div>
              <div className={styles.footItem}>
                <h3>Usage-metered, value-anchored</h3>
                <p>
                  Marginal cost is cents per scan; the buyer&apos;s alternative — one wrong number reaching a
                  trade, a shipped model, or an audit — is thousands to millions. Pro includes a monthly
                  sandbox-minute budget with metered overage; GPU is an Enterprise add-on.
                </p>
              </div>
              <div className={styles.footItem}>
                <h3>Open at the core</h3>
                <p>
                  The recompute engine is open-source — re-executing to ground truth is the defense, not hiding
                  the formulas. Read the code on{" "}
                  <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                    GitHub
                  </a>
                  , or{" "}
                  <a href="/dashboard">verify a repo</a> right now.
                </p>
              </div>
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
