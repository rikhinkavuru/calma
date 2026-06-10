"use client";

import { Fragment, useEffect, useId, useRef, useState } from "react";
import { Arrow } from "./primitives";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),textarea,select,[tabindex]:not([tabindex="-1"])';

export function RequestDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [sent, setSent] = useState(false);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const prevFocus = useRef<HTMLElement | null>(null);
  const titleId = useId();

  // open/close lifecycle: capture + restore focus, trap Tab, close on Escape
  useEffect(() => {
    if (!open) {
      setSent(false);
      return;
    }
    prevFocus.current = (document.activeElement as HTMLElement) || null;
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
      prevFocus.current?.focus?.();
    };
  }, [open, onClose]);

  // keep focus inside after the form flips to the confirmation state
  useEffect(() => {
    if (open && sent) requestAnimationFrame(() => cardRef.current?.querySelector<HTMLElement>("button")?.focus());
  }, [sent, open]);

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
        {!sent ? (
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
            <form
              className="dlg__form"
              onSubmit={(e) => {
                e.preventDefault();
                setSent(true);
              }}
            >
              <label className="fld">
                <span className="fld__l mono">work email</span>
                <input className="fld__i mono" type="email" required placeholder="you@fund.com" />
              </label>
              <label className="fld">
                <span className="fld__l mono">fund / team</span>
                <input className="fld__i mono" type="text" required placeholder="Systematic equity, $— AUM" />
              </label>
              <label className="fld">
                <span className="fld__l mono">what should we verify?</span>
                <input className="fld__i mono" type="text" placeholder="e.g. a backtest ahead of a raise" />
              </label>
              <button className="btn btn-primary dlg__submit" type="submit">
                Request verification <Arrow />
              </button>
            </form>
          </Fragment>
        ) : (
          <div className="dlg__done">
            <div className="dlg__check mono" aria-hidden="true">
              ✓
            </div>
            <h3 className="dlg__title" id={titleId}>
              Request received.
            </h3>
            <p className="dlg__sub">
              We read every one personally. If there's a fit, you'll hear from a real person — usually within two business days.
            </p>
            <button className="btn btn-ghost" onClick={onClose}>
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
