"use client";

// The Pro tier's CTA: kicks off Stripe Checkout via POST /api/billing/checkout and redirects to the
// Stripe-hosted page. Signed-out users are sent to the dashboard sign-in gate instead (the checkout
// session must be tied to a real identity — entitlement is resolved by the account email).
import { useState } from "react";

export function StartProButton({ className }: { className: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startCheckout() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/billing/checkout", { method: "POST" });
      if (res.status === 401) {
        window.location.href = "/dashboard"; // sign-in gate; checkout again from /pricing after
        return;
      }
      const data = (await res.json().catch(() => ({}))) as { url?: string };
      if (!res.ok || !data.url) throw new Error("checkout_failed");
      window.location.href = data.url;
    } catch {
      setError("Couldn't start checkout — please try again.");
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className={className} onClick={startCheckout} disabled={busy}>
        {busy ? "Redirecting…" : "Start Pro"}
      </button>
      {error && (
        <p role="alert" style={{ marginTop: 8, fontSize: 12, color: "#e89a5d" }}>
          {error}
        </p>
      )}
    </>
  );
}
