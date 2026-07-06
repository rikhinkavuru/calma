import Image from "next/image";
import Link from "next/link";
import type { Metadata } from "next";
import s from "../legal.module.css";

export const metadata: Metadata = {
  title: "Privacy Policy — Calma",
  description: "What Calma collects, why, and the choices you have.",
};

const UPDATED = "July 6, 2026";

const SUBPROCESSORS = [
  ["WorkOS", "Authentication and identity (sign-in, SSO)", "USA"],
  ["Vercel", "Web application hosting and delivery", "USA / global edge"],
  ["Fly.io", "Verification engine hosting", "USA / global"],
  ["E2B", "Network-isolated sandboxes for running your code (CPU)", "USA"],
  ["Modal", "Sandboxes for running your code (GPU)", "USA"],
  ["Anthropic", "AI assistance for run planning (no training on your content)", "USA"],
  ["GitHub", "Reading the repositories you connect", "USA"],
  ["Supabase", "Application database (account and run metadata)", "USA / EU"],
];

export default function PrivacyPage() {
  return (
    <main className={s.page}>
      <div className={s.wrap}>
        <header className={s.top}>
          <Link href="/" className={s.brand}>
            <Image src="/img/calma-lotus.png" alt="Calma" width={523} height={332} className={s.brandLogo} />
            <span>calma</span>
          </Link>
          <Link href="/" className={s.back}>← Back to Calma</Link>
        </header>

        <h1 className={s.h1}>Privacy Policy</h1>
        <p className={s.meta}>Effective {UPDATED} · Last updated {UPDATED}</p>
        <p className={s.lede}>
          This policy explains what Calma collects, why, how long we keep it, and the choices you have. Our
          approach is to collect as little as we need and to hold your code only for as long as it takes to
          verify it.
        </p>

        <div className={s.body}>
          <h2>1. Who we are</h2>
          <p>
            Calma provides a service that re-runs a repository and independently verifies the numbers it reports.
            This policy applies to that service and to our website. For the code and data inside a repository you
            connect, we act as a <strong>processor</strong> on your behalf; for your account and how you use the
            product, we act as a <strong>controller</strong>.
          </p>

          <h2>2. What we collect</h2>
          <h3>Account information</h3>
          <p>
            When you sign in, our identity provider gives us your name, email address, and a user identifier.
            If you sign in with SSO, we receive the attributes your organization releases.
          </p>
          <h3>Repository and run content</h3>
          <p>
            To verify a repository, we clone it into an isolated sandbox and execute it. During a run we process
            the repository&rsquo;s code, any committed data and result files, and the outputs the run produces.
            We only access repositories you explicitly connect.
          </p>
          <h3>Results and metadata</h3>
          <p>
            We store the verification results, verdicts, and run metadata (such as the repository reference,
            timing, status, and logs) so you can view your history in the dashboard.
          </p>
          <h3>Usage and device data</h3>
          <p>
            Like most services, we log basic technical data — IP address, browser type, timestamps, and
            in-product actions — for security, debugging, and analytics.
          </p>

          <h2>3. How we use information</h2>
          <ul>
            <li>to run the verifications you request and show you results;</li>
            <li>to operate, secure, and improve the service;</li>
            <li>to authenticate you and prevent abuse of our sandboxes;</li>
            <li>to communicate with you about the service; and</li>
            <li>to comply with legal obligations.</li>
          </ul>
          <p>We do not sell your personal information, and we do not use your code or data to train AI models.</p>

          <h2>4. Legal bases (GDPR)</h2>
          <p>
            Where the GDPR applies, we process personal data to <strong>perform our contract</strong> with you
            (running verifications, providing your account), for our <strong>legitimate interests</strong>
            (securing and improving the service), to meet <strong>legal obligations</strong>, and with your
            <strong> consent</strong> where required (for example, non-essential cookies).
          </p>

          <h2>5. Sub-processors</h2>
          <p>
            We use the following service providers to run Calma. Each is bound by a data-processing agreement and
            processes data only to provide its service to us.
          </p>
          <div className={s.tableWrap}>
            <table>
              <thead>
                <tr><th>Provider</th><th>Purpose</th><th>Location</th></tr>
              </thead>
              <tbody>
                {SUBPROCESSORS.map(([name, purpose, loc]) => (
                  <tr key={name}><td><strong>{name}</strong></td><td>{purpose}</td><td>{loc}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            We will give reasonable notice before adding a new sub-processor that handles your content, so you
            can object.
          </p>

          <h2>6. Data retention</h2>
          <p>
            The sandbox that runs your code is <strong>ephemeral</strong>: it is created for a run and destroyed
            when the run ends, and the cloned copy of your repository is not kept afterward. We retain
            verification <strong>results and run metadata</strong> for as long as your account is active so you
            can review them, and we retain account information for the life of your account. When you delete a
            run or close your account, we delete the associated data from our live systems within 30 days;
            residual copies in encrypted backups age out on a rolling basis. We may retain limited records longer
            where the law requires it.
          </p>

          <h2>7. Security</h2>
          <ul>
            <li>encryption in transit (TLS) and at rest;</li>
            <li>untrusted code runs only inside network-isolated sandboxes, separated from our systems;</li>
            <li>scoped access controls and least-privilege internal access;</li>
            <li>tenant isolation so one customer cannot reach another&rsquo;s data; and</li>
            <li>signed, replayable verification receipts rather than retained raw data.</li>
          </ul>
          <p>No system is perfectly secure, but we work to protect your data and to respond quickly to incidents.</p>

          <h2>8. International transfers</h2>
          <p>
            We and our sub-processors may process data in the United States and other countries. Where we
            transfer personal data out of the EEA, UK, or Switzerland, we rely on appropriate safeguards such as
            the EU Standard Contractual Clauses.
          </p>

          <h2>9. Your rights</h2>
          <p>
            Depending on where you live, you may have the right to access, correct, delete, port, or restrict
            your personal data, and to object to certain processing. If you are in California, you may request to
            know, delete, and correct your information, and to opt out of &ldquo;sale&rdquo; or
            &ldquo;sharing&rdquo; — which we do not do. We will not discriminate against you for exercising these
            rights. To make a request, email{" "}
            <a href="mailto:privacy@trycalma.ai">privacy@trycalma.ai</a>; we respond within the timeframes the
            law requires.
          </p>

          <h2>10. Cookies</h2>
          <p>
            We use strictly necessary cookies to keep you signed in and to secure the service, and limited
            analytics to understand usage. You can control non-essential cookies through your browser.
          </p>

          <h2>11. Children</h2>
          <p>Calma is not directed to children under 16, and we do not knowingly collect their personal data.</p>

          <h2>12. Changes</h2>
          <p>
            We may update this policy. If a change is material, we will take reasonable steps to notify you and
            will update the date above.
          </p>

          <h2>13. Contact</h2>
          <p>
            Questions or requests? Email <a href="mailto:privacy@trycalma.ai">privacy@trycalma.ai</a>.
          </p>

          <p className={s.note}>
            This document is a plain-language starting point written for clarity, not a substitute for legal
            advice. Have counsel review and localize it, and confirm the sub-processor list and retention
            windows match your production setup, before you rely on it.
          </p>
        </div>
      </div>
    </main>
  );
}
