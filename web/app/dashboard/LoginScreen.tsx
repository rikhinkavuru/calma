"use client";
// Minimal black-and-white two-step sign-in. Left: a single still landscape, full-bleed on three sides.
// Right: provider buttons (Google / GitHub / Microsoft / SSO), then a passwordless email → code (Magic Auth)
// flow. Only the lotus logo carries colour. A Sign-up pill sits top-right, aligned with the wordmark.
import { useActionState, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { FaGoogle, FaGithub, FaMicrosoft } from "react-icons/fa";
import { FiArrowRight, FiKey } from "react-icons/fi";
import {
  continueWithGoogle, continueWithGithub, continueWithMicrosoft, continueWithSSO, signUp,
  startMagicAuth, verifyMagicAuth,
} from "./login-actions";
import s from "./login.module.css";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const PROVIDERS = [
  { action: continueWithGoogle, label: "Continue with Google", icon: <FaGoogle size={18} /> },
  { action: continueWithGithub, label: "Continue with GitHub", icon: <FaGithub size={19} /> },
  { action: continueWithMicrosoft, label: "Continue with Microsoft", icon: <FaMicrosoft size={18} /> },
  { action: continueWithSSO, label: "Single sign-on (SSO)", icon: <FiKey size={18} /> },
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
          <h1 className={s.h1}>Welcome back</h1>

          {/* provider row — add more slots beside these as they come online */}
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
            <form action={sendAction} className={s.fields}>
              <label className={s.label} htmlFor="email">Email</label>
              <input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="email"
                autoFocus
                placeholder="name@company.com"
                className={s.input}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              {sendState.error && <p className={s.err}>{sendState.error}</p>}
              <button type="submit" className={s.submit} disabled={!emailOk || sending}>
                {sending ? "Sending code…" : (<>Continue <FiArrowRight size={16} /></>)}
              </button>
            </form>
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
