"use client";
// Split sign-in: a single STILL landscape on the left, the credential panel on the right. No carousel, no
// rotation, one small caption. Auth is real (WorkOS): Google/hosted via continueWithProvider, inline
// email+password via passwordSignIn.
import { useActionState } from "react";
import Image from "next/image";
import Link from "next/link";
import { FcGoogle } from "react-icons/fc";
import { FiArrowRight } from "react-icons/fi";
import { continueWithProvider, createAccount, passwordSignIn } from "./login-actions";
import s from "./login.module.css";

export function LoginScreen() {
  const [state, action, pending] = useActionState(passwordSignIn, {});

  return (
    <div className={s.login}>
      <aside className={s.art}>
        <Image
          src="/img/login-art.jpg"
          alt=""
          fill
          sizes="(max-width: 920px) 0px, 50vw"
          priority
          className={s.artImg}
        />
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
          <p className={s.sub}>Access your console — verify AI-generated results before they ship.</p>

          <form action={continueWithProvider}>
            <button type="submit" className={s.google}>
              <FcGoogle size={18} /> Continue with Google
            </button>
          </form>

          <form action={createAccount}>
            <button type="submit" className={s.create}>
              Don&rsquo;t have an account? <strong>Create one</strong>
            </button>
          </form>

          <div className={s.divider}>
            <span>OR CONTINUE WITH EMAIL</span>
          </div>

          <form action={action} className={s.fields}>
            <label className={s.label} htmlFor="email">Email</label>
            <input
              id="email"
              name="email"
              type="email"
              required
              autoComplete="email"
              placeholder="name@company.com"
              className={s.input}
            />

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
              placeholder="••••••••"
              className={s.input}
            />

            {state.error && <p className={s.err}>{state.error}</p>}

            <button type="submit" className={s.submit} disabled={pending}>
              {pending ? "Signing in…" : (<>Sign in <FiArrowRight size={16} /></>)}
            </button>
          </form>

          <p className={s.legal}>
            By continuing, you agree to our <Link href="/terms">Terms of Service</Link> and acknowledge our{" "}
            <Link href="/privacy">Privacy Policy</Link>.
          </p>
        </div>
      </section>
    </div>
  );
}
