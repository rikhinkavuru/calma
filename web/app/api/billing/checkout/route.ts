// POST /api/billing/checkout — start a Stripe Checkout session for the Pro plan. Auth required (the
// subscription must land on the signed-in identity's email, since lib/billing.ts resolves entitlement by
// email). Returns { url } for the client to redirect to; 401 tells the client to route through sign-in.
// NOTE: this route calls withAuth(), so it MUST stay in the middleware.ts matcher.
import { NextResponse } from "next/server";
import { withAuth } from "@workos-inc/authkit-nextjs";
import { stripeClient } from "@/lib/billing";

export async function POST(req: Request) {
  const { user } = await withAuth();
  if (!user) return NextResponse.json({ error: "sign_in_required" }, { status: 401 });

  const stripe = stripeClient();
  const price = process.env.STRIPE_PRO_PRICE_ID;
  if (!stripe || !price) {
    return NextResponse.json({ error: "billing_not_configured" }, { status: 503 });
  }

  const origin = new URL(req.url).origin;
  try {
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [
        // Per-seat: the buyer picks the seat count on the Stripe-hosted page.
        { price, quantity: 1, adjustable_quantity: { enabled: true, minimum: 1, maximum: 100 } },
      ],
      customer_email: user.email,
      client_reference_id: user.id,
      allow_promotion_codes: true,
      subscription_data: { metadata: { workos_user_id: user.id } },
      success_url: `${origin}/pricing?checkout=success`,
      cancel_url: `${origin}/pricing?checkout=cancelled`,
    });
    if (!session.url) throw new Error("Stripe returned no redirect URL");
    return NextResponse.json({ url: session.url });
  } catch (e) {
    console.error("[calma] checkout error:", e instanceof Error ? e.message : e);
    return NextResponse.json({ error: "checkout_failed" }, { status: 502 });
  }
}
