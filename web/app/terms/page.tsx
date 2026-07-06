import Image from "next/image";
import Link from "next/link";
import type { Metadata } from "next";
import s from "../legal.module.css";

export const metadata: Metadata = {
  title: "Terms of Service — Calma",
  description: "The terms that govern your use of Calma.",
};

const UPDATED = "July 6, 2026";

export default function TermsPage() {
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

        <h1 className={s.h1}>Terms of Service</h1>
        <p className={s.meta}>Effective {UPDATED} · Last updated {UPDATED}</p>
        <p className={s.lede}>
          These Terms govern your access to and use of Calma. By creating an account or using the service, you
          agree to them. Please read them carefully — they include important limits on our liability and a
          disclaimer about what a verification result does and does not mean.
        </p>

        <div className={s.body}>
          <h2>1. What Calma is</h2>
          <p>
            Calma is a correctness layer for computational results. You connect a repository; Calma clones it
            into an isolated sandbox, re-runs it, independently recomputes the numbers it reports, and returns a
            deterministic verdict (for example CONFIRMED, REFUTED, or INCONCLUSIVE). Calma is designed to be
            fail-closed: when it cannot verify something, it says so.
          </p>

          <h2>2. Verification disclaimer</h2>
          <p>
            A Calma verdict is an <strong>automated, informational assessment</strong> produced by re-running
            code and recomputing metrics. It is not a certification, an audit opinion, a warranty of
            correctness, or professional, legal, financial, or compliance advice. &ldquo;Never a false
            confirm&rdquo; describes a design goal of our verification pipeline, not a guarantee of any specific
            outcome. You are responsible for how you interpret and act on a verdict, and you should not rely on
            Calma as the sole basis for a decision with material consequences.
          </p>

          <h2>3. Eligibility and accounts</h2>
          <p>
            You must be at least 16 years old and able to form a binding contract to use Calma. You are
            responsible for the activity under your account and for keeping your credentials secure. Accounts are
            authenticated through our identity provider; you agree to provide accurate information and to notify
            us of any unauthorized use.
          </p>

          <h2>4. Your repositories and content</h2>
          <p>
            You retain all ownership of the repositories, code, data, and results you submit (&ldquo;Your
            Content&rdquo;). You grant Calma a limited, non-exclusive license to access, clone, execute, store,
            and process Your Content <strong>solely to provide the service</strong> — that is, to run the
            verification you requested and return results to you. We do not use Your Content to train models. You
            represent that you have the rights necessary to submit Your Content and to authorize us to run it.
          </p>

          <h2>5. Acceptable use</h2>
          <p>You agree not to use Calma to:</p>
          <ul>
            <li>violate any law, or infringe anyone&rsquo;s intellectual property or privacy rights;</li>
            <li>submit code intended to attack, exfiltrate from, or abuse our infrastructure or third parties,
              or to mine cryptocurrency, send spam, or run unrelated general-purpose workloads;</li>
            <li>attempt to break out of the execution sandbox, circumvent resource limits, or gain unauthorized
              access to any system or data;</li>
            <li>reverse engineer, resell, or build a competing service from the non-public parts of Calma; or</li>
            <li>submit content you do not have the right to submit.</li>
          </ul>
          <p>
            Calma executes untrusted code in network-isolated sandboxes. We may throttle, sandbox, or refuse any
            workload that threatens the security, integrity, or availability of the service.
          </p>

          <h2>6. Intellectual property</h2>
          <p>
            Calma and everything that powers it — the software, verification engine, models, UI, and
            documentation — remain our property or that of our licensors. These Terms grant you a limited,
            revocable, non-transferable right to use the service; they do not transfer any ownership to you.
            Feedback you send us may be used without obligation to you.
          </p>

          <h2>7. Third-party services</h2>
          <p>
            Calma relies on third parties to operate — including a source-control provider (to read the
            repositories you connect), an identity provider (for sign-in), sandbox and compute providers (to run
            your code), and an AI provider (to assist with run planning). Your use of those integrations is also
            subject to their terms. We are not responsible for third-party services, and their availability may
            affect ours. Our current sub-processors are described in our{" "}
            <Link href="/privacy">Privacy Policy</Link>.
          </p>

          <h2>8. Plans, trials, and fees</h2>
          <p>
            Some features are free and others require a paid plan. Fees, usage limits, and billing terms for a
            paid plan are presented at purchase. Unless stated otherwise, fees are non-refundable except where
            required by law, and we may change pricing prospectively with notice. You are responsible for taxes
            other than those on our net income.
          </p>

          <h2>9. Disclaimer of warranties</h2>
          <p>
            The service is provided <strong>&ldquo;as is&rdquo; and &ldquo;as available,&rdquo;</strong> without
            warranties of any kind, whether express, implied, or statutory, including merchantability, fitness
            for a particular purpose, title, non-infringement, and any warranty that the service will be
            uninterrupted, error-free, or that any verdict is accurate or complete. Some jurisdictions do not
            allow certain disclaimers, so parts of this section may not apply to you.
          </p>

          <h2>10. Limitation of liability</h2>
          <p>
            To the fullest extent permitted by law, Calma and its suppliers will not be liable for any indirect,
            incidental, special, consequential, or exemplary damages, or for lost profits, revenue, data, or
            goodwill, arising out of or related to the service or a verification result — even if advised of the
            possibility. Our total liability for any claim will not exceed the greater of the amounts you paid us
            in the twelve months before the claim, or US$100.
          </p>

          <h2>11. Indemnification</h2>
          <p>
            You agree to defend and indemnify Calma against claims, damages, and expenses arising from Your
            Content, your use of the service, or your breach of these Terms or of any third party&rsquo;s rights.
          </p>

          <h2>12. Suspension and termination</h2>
          <p>
            You may stop using Calma and close your account at any time. We may suspend or terminate access if
            you breach these Terms, create risk or legal exposure for us, or if we discontinue the service. On
            termination, your right to use the service ends; sections that by their nature should survive
            (ownership, disclaimers, limitation of liability, indemnification) will survive.
          </p>

          <h2>13. Changes</h2>
          <p>
            We may update the service and these Terms. If we make a material change, we will take reasonable
            steps to notify you (for example, by updating the date above or by email). Continuing to use Calma
            after a change means you accept the updated Terms.
          </p>

          <h2>14. Governing law and disputes</h2>
          <p>
            These Terms are governed by the laws of the State of Delaware, USA, without regard to conflict-of-law
            rules. You and Calma will try to resolve disputes informally first; unresolved disputes will be
            handled by the state or federal courts located in Delaware, and you consent to their jurisdiction,
            except where applicable law gives you the right to a different forum.
          </p>

          <h2>15. Contact</h2>
          <p>
            Questions about these Terms? Email{" "}
            <a href="mailto:legal@trycalma.ai">legal@trycalma.ai</a>.
          </p>

          <p className={s.note}>
            This document is a plain-language starting point written for clarity, not a substitute for legal
            advice. Have counsel review and localize it before you rely on it in production.
          </p>
        </div>
      </div>
    </main>
  );
}
