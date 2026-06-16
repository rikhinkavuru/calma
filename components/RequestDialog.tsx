"use client";

import { Fragment, useEffect, useId, useRef, useState } from "react";
import { CONTACT_EMAIL, FORM_ENDPOINT } from "./contact";

function Arrow() {
  return (
    <span className="arrow" aria-hidden="true">
      →
    </span>
  );
}

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),textarea,select,[tabindex]:not([tabindex="-1"])';

const REQUEST_SUBJECT = "Calma — verification request";

type SendState = "idle" | "sending" | "sent" | "failed";

export function RequestDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [state, setState] = useState<SendState>("idle");
  const [fields, setFields] = useState({ email: "", fund: "", what: "" });
  const cardRef = useRef<HTMLDivElement | null>(null);
  const prevFocus = useRef<HTMLElement | null>(null);
  const titleId = useId();

  // open/close lifecycle: capture + restore focus, trap Tab, close on Escape, lock body scroll
  useEffect(() => {
    if (!open) {
      setState("idle");
      return;
    }
    prevFocus.current = (document.activeElement as HTMLElement) || null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const card = cardRef.current;
    requestAnimationFrame(() => {
      const first = card?.querySelector<HTMLElement>("input") || card?.querySelector<HTMLElement>("button");
      (first || card)?.focus();
    });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "Tab" && card) {
        const els = Array.from(card.querySelectorAll<HTMLElement>(FOCUSABLE));
        if (!els.length) return;
        const first = els[0];
        const last = els[els.length - 1];
        const active = document.activeElement as HTMLElement;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      prevFocus.current?.focus?.();
    };
  }, [open, onClose]);

  // keep focus inside after the form flips to the confirmation state
  useEffect(() => {
    if (open && (state === "sent" || state === "failed"))
      requestAnimationFrame(() => cardRef.current?.querySelector<HTMLElement>("button, a")?.focus());
  }, [state, open]);

  const mailtoHref = () => {
    const subject = encodeURIComponent(REQUEST_SUBJECT);
    const body = encodeURIComponent(
      `Fund / team: ${fields.fund}\nWhat to verify: ${fields.what}\nReply to: ${fields.email}`,
    );
    return `mailto:${CONTACT_EMAIL}?subject=${subject}&body=${body}`;
  };

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const next = {
      email: String(data.get("email") || ""),
      fund: String(data.get("fund") || ""),
      what: String(data.get("what") || ""),
    };
    setFields(next);
    setState("sending");
    try {
      const res = await fetch(FORM_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          email: next.email,
          "fund / team": next.fund,
          "what to verify": next.what,
          _subject: REQUEST_SUBJECT,
          _template: "table",
          _captcha: "false",
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setState("sent");
    } catch {
      setState("failed");
    }
  };

  if (!open) return null;
  return (
    <div className="dlg" onMouseDown={onClose}>
      <div
        className="dlg__card"
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button className="dlg__close mono" onClick={onClose} aria-label="Close">
          esc
        </button>
        {state === "idle" || state === "sending" ? (
          <Fragment>
            <div className="dlg__eyebrow mono">
              <span className="closing__dot" /> request verification
            </div>
            <h3 className="dlg__title" id={titleId}>
              Talk to us about an independent verification.
            </h3>
            <p className="dlg__sub">
              For managers raising capital and allocators doing diligence. We run a small number of
              engagements at a time — tell us a little and a real person will reach out.
            </p>
            <form className="dlg__form" onSubmit={submit}>
              <label className="fld">
                <span className="fld__l mono">work email</span>
                <input className="fld__i mono" name="email" type="email" required placeholder="you@fund.com" />
              </label>
              <label className="fld">
                <span className="fld__l mono">fund / team</span>
                <input
                  className="fld__i mono"
                  name="fund"
                  type="text"
                  required
                  placeholder="e.g. systematic equity, $250M AUM"
                />
              </label>
              <label className="fld">
                <span className="fld__l mono">what should we verify?</span>
                <input
                  className="fld__i mono"
                  name="what"
                  type="text"
                  placeholder="e.g. a backtest ahead of a raise"
                />
              </label>
              <button className="btn btn-primary dlg__submit" type="submit" disabled={state === "sending"}>
                {state === "sending" ? "Sending…" : <Fragment>Request verification <Arrow /></Fragment>}
              </button>
              <p className="dlg__alt mono">
                prefer email? <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
              </p>
            </form>
          </Fragment>
        ) : state === "sent" ? (
          <div className="dlg__done">
            <div className="dlg__check mono" aria-hidden="true">
              ✓
            </div>
            <h3 className="dlg__title" id={titleId}>
              Request sent.
            </h3>
            <p className="dlg__sub">
              We read every one personally. If there&apos;s a fit, you&apos;ll hear from a real
              person — usually within two business days. Need us sooner?{" "}
              <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
            </p>
            <button className="btn btn-ghost" onClick={onClose}>
              Close
            </button>
          </div>
        ) : (
          <div className="dlg__done">
            <h3 className="dlg__title" id={titleId}>
              That didn&apos;t go through.
            </h3>
            <p className="dlg__sub">
              Our form service couldn&apos;t be reached — but your note isn&apos;t lost. Email us
              directly and we&apos;ll pick it up:
            </p>
            <a className="btn btn-primary" href={mailtoHref()}>
              Email {CONTACT_EMAIL} <Arrow />
            </a>
            <button className="btn btn-ghost" onClick={onClose} style={{ marginTop: 10 }}>
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
