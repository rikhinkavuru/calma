"use client";
// Minimal two-step sign-in. Left: a single still landscape, full-bleed on three sides. Right: provider
// buttons (icon-only, so more can sit beside Google later), then email → password on the next step.
// Auth is real (WorkOS): continueWithProvider (hosted) and passwordSignIn (inline email+password).
import { useActionState, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { FcGoogle } from "react-icons/fc";
import { FiArrowRight } from "react-icons/fi";
import { continueWithProvider, passwordSignIn } from "./login-actions";
import s from "./login.module.css";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function LoginScreen() {
  const [state, action, pending] = useActionState(passwordSignIn, {});
  const [step, setStep] = useState<"email" | "password">("email");
  const [email, setEmail] = useState("");
  const emailOk = EMAIL_RE.test(email.trim());

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

        <div className={s.form}>
          <h1 className={s.h1}>Welcome back</h1>

          {/* provider row — icon-only, more can sit beside it */}
          <div className={s.providers}>
            <form action={continueWithProvider}>
              <input type="hidden" name="email" value={email} />
              <button type="submit" className={s.provider} aria-label="Continue with Google" title="Continue with Google">
                <FcGoogle size={20} />
              </button>
            </form>
          </div>

          <div className={s.divider}><span>or</span></div>

          {step === "email" ? (
            <form
              className={s.fields}
              onSubmit={(e) => { e.preventDefault(); if (emailOk) setStep("password"); }}
            >
              <label className={s.label} htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                autoFocus
                placeholder="name@company.com"
                className={s.input}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <button type="submit" className={s.submit} disabled={!emailOk}>
                Continue <FiArrowRight size={16} />
              </button>
            </form>
          ) : (
            <form action={action} className={s.fields}>
              <input type="hidden" name="email" value={email} />

              <button type="button" className={s.emailChip} onClick={() => setStep("email")}>
                <span>{email}</span>
                <span className={s.change}>Change</span>
              </button>

              <div className={s.pwrow}>
                <label className={s.label} htmlFor="password">Password</label>
                <button type="submit" name="intent" value="reset" formNoValidate className={s.forgot}>
                  Forgot password?
                </button>
              </div>
              <input
                id="password"
                name="password"
                type="password"
                required
                autoComplete="current-password"
                autoFocus
                placeholder="••••••••"
                className={s.input}
              />

              {state.error && <p className={s.err}>{state.error}</p>}
              {state.notice && <p className={s.notice}>{state.notice}</p>}

              <button type="submit" className={s.submit} disabled={pending}>
                {pending ? "Signing in…" : (<>Sign in <FiArrowRight size={16} /></>)}
              </button>
            </form>
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
