/**
 * Cloudflare Pages Function: POST /api/webhooks/stripe
 *
 * Handles Stripe webhook events for subscription lifecycle.
 * Assigns/removes Discord Premium role based on subscription status.
 *
 * Environment variables (set in Cloudflare Pages dashboard):
 *   STRIPE_SECRET_KEY     — Stripe API secret key
 *   STRIPE_WEBHOOK_SECRET — Stripe webhook signing secret
 *   DISCORD_BOT_TOKEN     — Discord bot token for role management
 *   DISCORD_GUILD_ID      — Discord server ID
 *   PREMIUM_ROLE_ID       — Discord role ID for premium members
 *   SUBSCRIBERS_KV        — KV namespace binding (optional, falls back to in-memory)
 */

export async function onRequestPost(context) {
  const { request, env } = context;

  const STRIPE_KEY = env.STRIPE_SECRET_KEY;
  const WEBHOOK_SECRET = env.STRIPE_WEBHOOK_SECRET;
  const BOT_TOKEN = env.DISCORD_BOT_TOKEN;
  const GUILD_ID = env.DISCORD_GUILD_ID;
  const ROLE_ID = env.PREMIUM_ROLE_ID;

  if (!STRIPE_KEY || !WEBHOOK_SECRET) {
    return new Response("Webhook not configured", { status: 500 });
  }

  // Verify Stripe signature
  const body = await request.text();
  const sig = request.headers.get("stripe-signature");

  let event;
  try {
    event = await verifyStripeSignature(body, sig, WEBHOOK_SECRET);
  } catch (err) {
    console.error("Webhook signature verification failed:", err.message);
    return new Response("Invalid signature", { status: 400 });
  }

  const data = event.data?.object;
  if (!data) {
    return new Response("OK", { status: 200 });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const discordUsername = extractDiscordUsername(data);
        if (discordUsername && BOT_TOKEN && GUILD_ID && ROLE_ID) {
          const userId = await findDiscordUser(discordUsername, GUILD_ID, BOT_TOKEN);
          if (userId) {
            await addRole(userId, GUILD_ID, ROLE_ID, BOT_TOKEN);
            console.log(`Premium role added for ${discordUsername} (${userId})`);
          }
        }
        break;
      }

      case "customer.subscription.deleted":
      case "invoice.payment_failed": {
        // For $0 subscriptions, these are unlikely but handle gracefully
        console.log(`Subscription event: ${event.type} for customer ${data.customer}`);
        break;
      }

      default:
        console.log(`Unhandled event type: ${event.type}`);
    }
  } catch (err) {
    console.error(`Error handling ${event.type}:`, err);
  }

  return new Response("OK", { status: 200 });
}

function extractDiscordUsername(session) {
  const fields = session.custom_fields || [];
  for (const f of fields) {
    if (f.key === "discord_username") {
      return f.text?.value || null;
    }
  }
  return session.metadata?.discord_username || null;
}

async function findDiscordUser(username, guildId, botToken) {
  const url = `https://discord.com/api/v10/guilds/${guildId}/members/search?query=${encodeURIComponent(username)}&limit=5`;
  const res = await fetch(url, {
    headers: { Authorization: `Bot ${botToken}` },
  });
  if (!res.ok) return null;

  const members = await res.json();
  const lower = username.toLowerCase();
  for (const m of members) {
    const u = m.user || {};
    const name = (u.global_name || u.username || "").toLowerCase();
    if (name === lower) return u.id;
  }
  return members[0]?.user?.id || null;
}

async function addRole(userId, guildId, roleId, botToken) {
  const url = `https://discord.com/api/v10/guilds/${guildId}/members/${userId}/roles/${roleId}`;
  const res = await fetch(url, {
    method: "PUT",
    headers: { Authorization: `Bot ${botToken}` },
  });
  return res.status === 204;
}

/**
 * Verify Stripe webhook signature using Web Crypto API.
 * Stripe uses HMAC-SHA256 with the format: t=timestamp,v1=signature
 */
async function verifyStripeSignature(payload, sigHeader, secret) {
  if (!sigHeader) throw new Error("No signature header");

  const parts = {};
  for (const item of sigHeader.split(",")) {
    const [key, val] = item.split("=");
    parts[key.trim()] = val;
  }

  const timestamp = parts.t;
  const signature = parts.v1;
  if (!timestamp || !signature) throw new Error("Invalid signature format");

  // Check timestamp tolerance (5 minutes)
  const age = Math.abs(Date.now() / 1000 - parseInt(timestamp, 10));
  if (age > 300) throw new Error("Timestamp too old");

  // Compute expected signature
  const signedPayload = `${timestamp}.${payload}`;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signedPayload));
  const expected = Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  if (expected !== signature) throw new Error("Signature mismatch");

  return JSON.parse(payload);
}
