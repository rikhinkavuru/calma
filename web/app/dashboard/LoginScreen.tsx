"use client";
// Sign-in: still landscape on the left (full-bleed on three sides), a clean panel on the right. Colour lives
// in the lotus + the provider logos; everything else is black-and-white. Passwordless email (Magic Auth code)
// with OAuth providers and enterprise SSO.
import { useActionState, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { FcGoogle } from "react-icons/fc";
import { FaGithub, FaApple } from "react-icons/fa";
import { FiArrowRight, FiUsers } from "react-icons/fi";
import {
  continueWithGoogle, continueWithGithub, continueWithMicrosoft, continueWithApple, continueWithSSO, signUp,
  startMagicAuth, verifyMagicAuth,
} from "./login-actions";
import s from "./login.module.css";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function MicrosoftLogo({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 23 23" aria-hidden focusable="false">
      <path fill="#f25022" d="M1 1h10v10H1z" />
      <path fill="#7fba00" d="M12 1h10v10H12z" />
      <path fill="#00a4ef" d="M1 12h10v10H1z" />
      <path fill="#ffb900" d="M12 12h10v10H12z" />
    </svg>
  );
}

const PROVIDERS = [
  { action: continueWithGoogle, label: "Continue with Google", icon: <FcGoogle size={20} /> },
  { action: continueWithMicrosoft, label: "Continue with Microsoft", icon: <MicrosoftLogo size={18} /> },
  { action: continueWithGithub, label: "Continue with GitHub", icon: <FaGithub size={19} color="#181717" /> },
  { action: continueWithApple, label: "Continue with Apple", icon: <FaApple size={20} color="#000" /> },
];

export function LoginScreen() {
  const [sendState, sendAction, sending] = useActionState(startMagicAuth, {});
  const [verifyState, verifyAction, verifying] = useActionState(verifyMagicAuth, {});
  const [email, setEmail] = useState("");
  const [step, setStep] = useState<"email" | "code">("email");
  const emailOk = EMAIL_RE.test(email.trim());

  useEffect(() => { if (sendState.sent) setStep("code"); }, [sendState.sent, sendState.notice]);

  return (
    <div className={s.login}>
      <aside className={s.art}>
        <Image src="/img/login-art.jpg" alt="" fill sizes="(max-width: 920px) 0px, 46vw" priority className={s.artImg} />
        <div className={s.scrim} />
        <p className={s.caption}>AI did the work. Calma checks it.</p>
      </aside>

      <section className={s.panel}>
        <Link className={s.brand} href="/">
          <Image src="/img/calma-lotus.png" alt="Calma" width={523} height={332} priority className={s.brandLogo} />
          <span>calma</span>
        </Link>

        <form action={signUp} className={s.signupForm}>
          <button type="submit" className={s.signup}>Sign up</button>
        </form>

        <div className={s.form}>
          <h1 className={s.h1}>Sign in to Calma</h1>
          <p className={s.sub}>
            Re-run your repositories, recompute every number they report, and confirm the results before they ship.
          </p>

          {/* OAuth providers — colour from their own logos */}
          <div className={s.providers}>
            {PROVIDERS.map((p) => (
              <form action={p.action} key={p.label}>
                <button type="submit" className={s.provider} aria-label={p.label} title={p.label}>
                  {p.icon}
                </button>
              </form>
            ))}
          </div>

          <div className={s.divider}><span>or</span></div>

          {step === "email" ? (
            <>
              <form action={sendAction} className={s.fields}>
                <label className={s.label} htmlFor="email">Work email</label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  autoFocus
                  placeholder="you@company.com"
                  className={s.input}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                {sendState.error && <p className={s.err}>{sendState.error}</p>}
                <button type="submit" className={s.submit} disabled={!emailOk || sending}>
                  {sending ? "Sending code…" : (<>Continue <FiArrowRight size={16} /></>)}
                </button>
              </form>

              <form action={continueWithSSO}>
                <button type="submit" className={s.sso}>
                  <FiUsers size={17} /> Continue with SSO
                </button>
              </form>
            </>
          ) : (
            <>
              <button type="button" className={s.emailChip} onClick={() => setStep("email")}>
                <span>{email}</span>
                <span className={s.change}>Change</span>
              </button>

              <form action={verifyAction} className={s.fields}>
                <input type="hidden" name="email" value={email} />
                <label className={s.label} htmlFor="code">Enter the code sent to your email</label>
                <input
                  id="code"
                  name="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  placeholder="6-digit code"
                  className={`${s.input} ${s.code}`}
                />
                {verifyState.error && <p className={s.err}>{verifyState.error}</p>}
                {sendState.notice && <p className={s.notice}>{sendState.notice}</p>}
                <button type="submit" className={s.submit} disabled={verifying}>
                  {verifying ? "Verifying…" : (<>Sign in <FiArrowRight size={16} /></>)}
                </button>
              </form>

              <form action={sendAction} className={s.resendForm}>
                <input type="hidden" name="email" value={email} />
                <button type="submit" className={s.resend} disabled={sending}>
                  {sending ? "Sending…" : "Resend code"}
                </button>
              </form>
            </>
          )}

          <p className={s.legal}>
            By continuing, you agree to our <Link href="/terms">Terms of Service</Link> and acknowledge our{" "}
            <Link href="/privacy">Privacy Policy</Link>.
          </p>
        </div>
      </section>
    </div>
  );
}
