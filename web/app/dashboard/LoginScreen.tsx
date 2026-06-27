"use client";
// Redesigned sign-in gate: split layout — credential panel on the left, an art carousel on the right.
// Auth is real (WorkOS): Google/hosted via continueWithProvider, inline email+password via passwordSignIn.
import { useActionState, useCallback, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { FcGoogle } from "react-icons/fc";
import { FiArrowLeft, FiArrowRight } from "react-icons/fi";
import { continueWithProvider, createAccount, passwordSignIn } from "./login-actions";
import s from "./login.module.css";

// Captions are Calma's own product principles (not third-party testimonials), paired with calm,
// public-domain Monet landscapes that echo the brand's blue/green/amber palette.
const SLIDES = [
  {
    img: "/img/login-art.jpg",
    quote: "AI did the work. Calma checks it.",
    sub: "Every result re-run to ground truth — recomputed from the raw outputs.",
    art: "Claude Monet · Springtime · 1872",
  },
  {
    img: "/img/login-art-2.jpg",
    quote: "Catch the wrong number before it ships.",
    sub: "A calm, automatic guardrail for AI-generated results.",
    art: "Claude Monet · Water Lilies · 1906",
  },
  {
    img: "/img/login-art-3.jpg",
    quote: "Trust the result, not the claim.",
    sub: "Calma re-executes the work and proves the headline figure.",
    art: "Claude Monet · Haystacks, End of Summer · 1891",
  },
];

export function LoginScreen() {
  const [state, action, pending] = useActionState(passwordSignIn, {});
  const [i, setI] = useState(0);
  const go = useCallback((d: number) => setI((p) => (p + d + SLIDES.length) % SLIDES.length), []);

  useEffect(() => {
    const t = setInterval(() => setI((p) => (p + 1) % SLIDES.length), 7000);
    return () => clearInterval(t);
  }, []);

  const slide = SLIDES[i];

  return (
    <div className={s.login}>
      <section className={s.panel}>
        <Link className={s.brand} href="/">
          <Image src="/img/calma-lotus.png" alt="" width={30} height={30} priority />
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
        </div>

        <p className={s.foot}>© 2026 Calma. All rights reserved.</p>
      </section>

      <aside className={s.art}>
        {SLIDES.map((sl, idx) => (
          <Image
            key={sl.img}
            src={sl.img}
            alt=""
            fill
            sizes="(max-width: 920px) 0px, 50vw"
            priority={idx === 0}
            className={`${s.slide} ${idx === i ? s.slideOn : ""}`}
          />
        ))}
        <div className={s.scrim} />

        <div className={s.artNav}>
          <button type="button" onClick={() => go(-1)} aria-label="Previous">
            <FiArrowLeft size={16} />
          </button>
          <button type="button" onClick={() => go(1)} aria-label="Next">
            <FiArrowRight size={16} />
          </button>
        </div>

        <figure className={s.quote}>
          <blockquote className={s.quoteText}>&ldquo;{slide.quote}&rdquo;</blockquote>
          <figcaption className={s.quoteSub}>{slide.sub}</figcaption>
          <p className={s.quoteArt}>{slide.art}</p>
        </figure>
      </aside>
    </div>
  );
}
