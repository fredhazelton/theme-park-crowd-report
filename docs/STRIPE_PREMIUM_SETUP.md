# Stripe Premium Subscription Setup

TPCR Premium ($12/mo) — users subscribe on hazeydata.ai and get the Premium Discord role automatically.

## Environment Variables (wilma-server ~/.env)

```bash
# Stripe (use test keys for testing)
STRIPE_SECRET_KEY=sk_test_...   # or sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_test_...  # or pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...     # from Stripe Dashboard → Webhooks
STRIPE_PRICE_ID=price_...           # Monthly premium price ID

# Site URL for checkout redirects
SITE_BASE_URL=https://hazeydata.ai

# Discord (for role assignment)
PREMIUM_ROLE_ID=...                 # Create "Premium" role in Discord server
DISCORD_GUILD_ID=1471374656253591695
DISCORD_BOT_TOKEN=...

# Optional: custom path for subscription store
STRIPE_STORE_PATH=/home/wilma/hazeydata/stripe_subscriptions.json
```

## Stripe Dashboard Setup

1. **Product + Price**: Create product "TPCR Premium", recurring $12/mo. Copy the Price ID.
2. **Webhook**: Add endpoint `https://YOUR_API_URL/api/webhooks/stripe`
   - Events: `checkout.session.completed`, `customer.subscription.deleted`, `customer.subscription.updated`, `invoice.payment_failed`
   - Copy the Signing secret → `STRIPE_WEBHOOK_SECRET`
3. **Test mode**: Use `sk_test_` and `pk_test_` keys. Test with card `4242 4242 4242 4242`.

## Discord Setup

1. Create a "Premium" role in your server (Server Settings → Roles).
2. Ensure the bot has **Manage Roles** permission and the Premium role is **below** the bot's role in the hierarchy.
3. Copy the role ID (Developer Mode → right-click role → Copy ID).

## End-to-End Test (Stripe Test Mode)

1. Set all env vars with test keys.
2. Start the API: `python dashboard/api.py` (or your production server).
3. Serve subscribe page: ensure `subscribe.html` is reachable at `https://hazeydata.ai/subscribe.html`.
4. Click "Start Free Trial — $12/month" → Stripe Checkout opens.
5. Enter Discord username in the custom field, use test card `4242 4242 4242 4242`.
6. Complete checkout → redirect to success page.
7. Webhook fires → check API logs for "Added Premium role".
8. Verify user has Premium role in Discord.

## Files

| File | Purpose |
|------|---------|
| `web/subscribe.html` | Premium landing page, Stripe Checkout button |
| `web/subscribe-success.html` | Post-payment thank you page |
| `dashboard/api.py` | `/api/create-checkout-session`, `/api/webhooks/stripe` |
| `dashboard/stripe_handler.py` | Webhook logic, Discord role add/remove |
| `tpcr-discord-bot/bot.py` | Premium role check for extended forecasts |
