/**
 * Cloudflare Pages Function: POST /api/create-checkout-session
 *
 * Creates a Stripe Checkout session for the Theme Park Crowd Report
 * premium subscription. Currently set to $0/mo (alpha free tier).
 *
 * Environment variables (set in Cloudflare Pages dashboard):
 *   STRIPE_SECRET_KEY — Stripe API secret key
 *   STRIPE_PRICE_ID   — Price ID to use (alpha: $0/mo)
 */

export async function onRequestPost(context) {
  const { env } = context;

  const STRIPE_KEY = env.STRIPE_SECRET_KEY;
  const PRICE_ID = env.STRIPE_PRICE_ID;

  if (!STRIPE_KEY || !PRICE_ID) {
    return Response.json(
      { error: "Stripe not configured" },
      { status: 500, headers: corsHeaders() }
    );
  }

  try {
    // Create Stripe Checkout Session via REST API (no SDK needed in Workers)
    const params = new URLSearchParams();
    params.append("mode", "subscription");
    params.append("line_items[0][price]", PRICE_ID);
    params.append("line_items[0][quantity]", "1");
    params.append("success_url", "https://hazeydata.ai/subscribe-success.html");
    params.append("cancel_url", "https://hazeydata.ai/subscribe.html");
    // Collect Discord username during checkout
    params.append("custom_fields[0][key]", "discord_username");
    params.append("custom_fields[0][label][type]", "custom");
    params.append("custom_fields[0][label][custom]", "Discord Username");
    params.append("custom_fields[0][type]", "text");
    // Allow promo codes
    params.append("allow_promotion_codes", "true");

    const response = await fetch("https://api.stripe.com/v1/checkout/sessions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${STRIPE_KEY}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: params.toString(),
    });

    const session = await response.json();

    if (!response.ok) {
      console.error("Stripe error:", JSON.stringify(session));
      return Response.json(
        { error: session.error?.message || "Stripe checkout failed" },
        { status: 500, headers: corsHeaders() }
      );
    }

    return Response.json(
      { url: session.url },
      { headers: corsHeaders() }
    );
  } catch (err) {
    console.error("Checkout error:", err);
    return Response.json(
      { error: "Internal server error" },
      { status: 500, headers: corsHeaders() }
    );
  }
}

// Handle CORS preflight
export async function onRequestOptions() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "https://hazeydata.ai",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}
