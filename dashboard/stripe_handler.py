"""
Stripe webhook handler for TPCR Premium subscriptions.

Handles checkout.session.completed, customer.subscription.deleted,
customer.subscription.updated, and invoice.payment_failed events.
Assigns/removes Discord Premium role based on subscription status.

Requires: stripe, requests
Env: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID,
     PREMIUM_ROLE_ID, DISCORD_GUILD_ID, DISCORD_BOT_TOKEN
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests
import stripe

logger = logging.getLogger(__name__)

# Subscription store: JSON file mapping stripe_customer_id -> discord_user_id
STORE_PATH = Path(os.environ.get("STRIPE_STORE_PATH", "/home/wilma/hazeydata/stripe_subscriptions.json"))


def _load_store() -> dict:
    """Load subscription store from JSON file."""
    if not STORE_PATH.exists():
        return {}
    try:
        with open(STORE_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Could not load stripe store: %s", e)
        return {}


def _save_store(data: dict) -> None:
    """Save subscription store to JSON file."""
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _get_discord_user_id(discord_username: str) -> Optional[str]:
    """
    Look up Discord user ID by username in the guild.
    User must already be a member of the guild.
    """
    guild_id = os.environ.get("DISCORD_GUILD_ID")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not guild_id or not bot_token:
        logger.warning("DISCORD_GUILD_ID or DISCORD_BOT_TOKEN not set")
        return None

    # Discord search: query matches usernames and nicknames
    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/search"
    params = {"query": discord_username.strip(), "limit": 10}
    headers = {"Authorization": f"Bot {bot_token}"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        members = r.json()
    except Exception as e:
        logger.warning("Discord member search failed: %s", e)
        return None

    if not members:
        logger.warning("No Discord member found for username: %s", discord_username)
        return None

    # Prefer exact match on user.global_name or user.username
    query_lower = discord_username.strip().lower()
    for m in members:
        user = m.get("user") or {}
        uname = (user.get("global_name") or user.get("username") or "").lower()
        if uname == query_lower:
            return str(user.get("id"))
    # Fallback: first result
    return str(members[0].get("user", {}).get("id"))


def _add_premium_role(discord_user_id: str) -> bool:
    """Add Premium role to Discord user."""
    guild_id = os.environ.get("DISCORD_GUILD_ID")
    role_id = os.environ.get("PREMIUM_ROLE_ID")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not all([guild_id, role_id, bot_token]):
        logger.warning("Missing Discord env vars for role assignment")
        return False

    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{discord_user_id}/roles/{role_id}"
    headers = {"Authorization": f"Bot {bot_token}"}

    try:
        r = requests.put(url, headers=headers, timeout=10)
        if r.status_code == 204:
            logger.info("Added Premium role for Discord user %s", discord_user_id)
            return True
        logger.warning("Discord add role failed: %s %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        logger.warning("Discord add role error: %s", e)
        return False


def _remove_premium_role(discord_user_id: str) -> bool:
    """Remove Premium role from Discord user."""
    guild_id = os.environ.get("DISCORD_GUILD_ID")
    role_id = os.environ.get("PREMIUM_ROLE_ID")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not all([guild_id, role_id, bot_token]):
        logger.warning("Missing Discord env vars for role removal")
        return False

    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{discord_user_id}/roles/{role_id}"
    headers = {"Authorization": f"Bot {bot_token}"}

    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 204:
            logger.info("Removed Premium role for Discord user %s", discord_user_id)
            return True
        logger.warning("Discord remove role failed: %s %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        logger.warning("Discord remove role error: %s", e)
        return False


def _discord_username_from_session(session: dict) -> Optional[str]:
    """Extract Discord username from checkout session custom_fields or metadata."""
    for cf in session.get("custom_fields") or []:
        if cf.get("key") == "discord_username":
            text = cf.get("text") or {}
            return text.get("value") or ""
    return (session.get("metadata") or {}).get("discord_username")


def handle_checkout_session_completed(session: dict) -> None:
    """Assign Premium role when checkout completes."""
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    if not customer_id or not subscription_id:
        logger.warning("checkout.session.completed missing customer or subscription")
        return

    discord_username = _discord_username_from_session(session)
    if not discord_username:
        logger.warning("No Discord username in checkout session")
        return

    discord_user_id = _get_discord_user_id(discord_username)
    if not discord_user_id:
        logger.warning("Could not resolve Discord user for: %s", discord_username)
        return

    if _add_premium_role(discord_user_id):
        store = _load_store()
        store[customer_id] = {
            "discord_user_id": discord_user_id,
            "discord_username": discord_username,
            "subscription_id": subscription_id,
            "status": "active",
        }
        _save_store(store)


def handle_subscription_deleted(subscription: dict) -> None:
    """Remove Premium role when subscription is cancelled."""
    customer_id = subscription.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    if not customer_id:
        return

    store = _load_store()
    record = store.get(str(customer_id))
    if not record:
        logger.warning("No store record for customer %s", customer_id)
        return

    discord_user_id = record.get("discord_user_id")
    if discord_user_id:
        _remove_premium_role(discord_user_id)

    record["status"] = "cancelled"
    store[str(customer_id)] = record
    _save_store(store)


def handle_subscription_updated(subscription: dict) -> None:
    """Handle plan changes; remove role if status is cancelled/past_due."""
    status = subscription.get("status")
    if status in ("canceled", "cancelled", "unpaid", "past_due"):
        handle_subscription_deleted(subscription)
    # If active: role should already be assigned from checkout


def handle_invoice_payment_failed(invoice: dict) -> None:
    """On payment failure: remove role after grace period (or immediately for now)."""
    customer_id = invoice.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    if not customer_id:
        return

    # For simplicity: remove role on first failed payment.
    # In production you might want a grace period (e.g. 3 days).
    store = _load_store()
    record = store.get(str(customer_id))
    if not record:
        return

    discord_user_id = record.get("discord_user_id")
    if discord_user_id:
        _remove_premium_role(discord_user_id)
        record["status"] = "payment_failed"
        store[str(customer_id)] = record
        _save_store(store)


def handle_stripe_event(event: dict) -> bool:
    """
    Dispatch Stripe event to appropriate handler.
    Returns True if event was handled.
    """
    if not event:
        return False

    ev_type = event.get("type")
    data = event.get("data", {}).get("object") or {}

    if ev_type == "checkout.session.completed":
        handle_checkout_session_completed(data)
        return True
    if ev_type == "customer.subscription.deleted":
        handle_subscription_deleted(data)
        return True
    if ev_type == "customer.subscription.updated":
        handle_subscription_updated(data)
        return True
    if ev_type == "invoice.payment_failed":
        handle_invoice_payment_failed(data)
        return True

    logger.debug("Unhandled Stripe event type: %s", ev_type)
    return False
