"""
School Schedule Database (SSD) API — Stripe-authenticated data access.

Subscription-based access to the complete US school calendar dataset.
API keys are tied to Stripe subscriptions and auto-deactivate on cancellation.

Plans:
  - Single State: $1,200/yr — access to one state's districts
  - National: $15,000/yr — full dataset access

Endpoints:
  POST /api/ssd/subscribe          — Create Stripe checkout session
  GET  /api/ssd/districts          — Query districts (requires API key)
  GET  /api/ssd/states             — List available states (requires API key)
  GET  /api/ssd/coverage           — Coverage stats (public)
  POST /api/ssd/webhooks/stripe    — Stripe webhook handler

Usage:
  # Register as blueprint on the main Flask app
  from ssd_api import ssd_bp
  app.register_blueprint(ssd_bp)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Optional

import pandas as pd
import stripe
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

SSD_DATA_PATH = Path("/home/wilma/theme-park-crowd-report/data/school_schedules/districts_comprehensive.csv")
SSD_STORE_PATH = Path(os.environ.get("SSD_STORE_PATH", "/home/wilma/hazeydata/ssd_subscriptions.json"))

# Stripe IDs
SSD_PRODUCT_ID = os.environ.get("SSD_PRODUCT_ID", "prod_U9Ow4PBxBjgucB")
SSD_PRICE_STATE = os.environ.get("SSD_PRICE_STATE", "price_1TB68WKC6gFbIqtFjvsOMEeQ")
SSD_PRICE_NATIONAL = os.environ.get("SSD_PRICE_NATIONAL", "price_1TB68WKC6gFbIqtF7uDCnuAx")
SSD_WEBHOOK_SECRET = os.environ.get("SSD_WEBHOOK_SECRET", "")

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://hazeydata.ai")

# US states (for validation)
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR",
}

# ---------------------------------------------------------------------------
# Subscription store
# ---------------------------------------------------------------------------

def _load_store() -> dict:
    """Load SSD subscription store.
    
    Schema:
    {
      "api_keys": {
        "<api_key_hash>": {
            "customer_id": "cus_...",
            "subscription_id": "sub_...",
            "plan": "single_state" | "national",
            "state": "FL" | null,
            "email": "buyer@example.com",
            "created": "2026-03-15T...",
            "active": true
        }
      },
      "customer_to_key": {
        "cus_...": "<api_key_hash>"
      }
    }
    """
    if not SSD_STORE_PATH.exists():
        return {"api_keys": {}, "customer_to_key": {}}
    try:
        with open(SSD_STORE_PATH) as f:
            data = json.load(f)
        # Ensure schema
        data.setdefault("api_keys", {})
        data.setdefault("customer_to_key", {})
        return data
    except Exception as e:
        logger.warning("Could not load SSD store: %s", e)
        return {"api_keys": {}, "customer_to_key": {}}


def _save_store(data: dict) -> None:
    SSD_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SSD_STORE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _generate_api_key() -> str:
    """Generate a human-readable API key: ssd_live_<32 hex chars>"""
    return f"ssd_live_{secrets.token_hex(16)}"


def _validate_api_key(api_key: str) -> Optional[dict]:
    """Validate an API key and return subscription info, or None."""
    if not api_key:
        return None
    key_hash = _hash_key(api_key)
    store = _load_store()
    sub = store["api_keys"].get(key_hash)
    if not sub or not sub.get("active"):
        return None
    return sub


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def require_ssd_key(f):
    """Decorator: require valid SSD API key in Authorization header or ?api_key param."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check Authorization: Bearer <key>
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            api_key = auth[7:].strip()
        else:
            api_key = request.args.get("api_key", "").strip()

        sub = _validate_api_key(api_key)
        if not sub:
            return jsonify({
                "error": "Invalid or inactive API key",
                "hint": "Subscribe at https://hazeydata.ai/ssd to get an API key",
            }), 401

        # Attach subscription info to request context
        request.ssd_sub = sub
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_DATA_CACHE: dict = {"df": None, "loaded_at": 0}
CACHE_TTL = 300  # 5 min


def _load_data() -> pd.DataFrame:
    """Load SSD data with caching."""
    now = time.time()
    if _DATA_CACHE["df"] is not None and (now - _DATA_CACHE["loaded_at"]) < CACHE_TTL:
        return _DATA_CACHE["df"]

    if not SSD_DATA_PATH.exists():
        logger.error("SSD data file not found: %s", SSD_DATA_PATH)
        return pd.DataFrame()

    df = pd.read_csv(SSD_DATA_PATH, low_memory=False)
    df["state"] = df["state"].astype(str).str.strip().str.upper()
    _DATA_CACHE["df"] = df
    _DATA_CACHE["loaded_at"] = now
    logger.info("Loaded SSD data: %d districts", len(df))
    return df


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

ssd_bp = Blueprint("ssd", __name__)


# ---- Public: coverage stats ----

@ssd_bp.route("/api/ssd/coverage", methods=["GET"])
def ssd_coverage():
    """Public endpoint — coverage statistics."""
    df = _load_data()
    if df.empty:
        return jsonify({"error": "Data not available"}), 503

    total = len(df)
    confirmed = int((df["confidence"] == "confirmed").sum())
    enrollment = int(df["enrollment"].fillna(0).astype(int).sum())
    confirmed_enrollment = int(
        df.loc[df["confidence"] == "confirmed", "enrollment"].fillna(0).astype(int).sum()
    )
    states = sorted(df["state"].unique().tolist())

    return jsonify({
        "total_districts": total,
        "confirmed_districts": confirmed,
        "confirmed_pct": round(confirmed / total * 100, 1) if total else 0,
        "total_enrollment": enrollment,
        "confirmed_enrollment": confirmed_enrollment,
        "enrollment_coverage_pct": round(confirmed_enrollment / enrollment * 100, 1) if enrollment else 0,
        "states_covered": len(states),
        "states": states,
        "school_year": "2025-2026",
        "last_updated": datetime.fromtimestamp(SSD_DATA_PATH.stat().st_mtime).isoformat()
        if SSD_DATA_PATH.exists() else None,
    })


# ---- Public: subscribe ----

@ssd_bp.route("/api/ssd/subscribe", methods=["POST"])
def ssd_subscribe():
    """Create a Stripe checkout session for SSD subscription.
    
    Body JSON:
      plan: "single_state" | "national"
      state: "FL" (required if plan=single_state)
      email: "buyer@example.com" (optional, pre-fills checkout)
    """
    body = request.get_json(silent=True) or {}
    plan = body.get("plan", "").lower()
    state = body.get("state", "").upper()
    email = body.get("email", "")

    if plan == "single_state":
        if not state or state not in US_STATES:
            return jsonify({"error": f"Valid US state required. Got: '{state}'"}), 400
        price_id = SSD_PRICE_STATE
    elif plan == "national":
        price_id = SSD_PRICE_NATIONAL
        state = None
    else:
        return jsonify({"error": "plan must be 'single_state' or 'national'"}), 400

    try:
        session_kwargs = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{SITE_BASE_URL}/ssd/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{SITE_BASE_URL}/ssd",
            "metadata": {
                "product": "ssd",
                "plan": plan,
                "state": state or "",
            },
        }
        if email:
            session_kwargs["customer_email"] = email

        session = stripe.checkout.Session.create(**session_kwargs)
        return jsonify({"checkout_url": session.url, "session_id": session.id})

    except stripe.error.StripeError as e:
        logger.error("Stripe checkout creation failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ---- Webhook: Stripe ----

@ssd_bp.route("/api/ssd/webhooks/stripe", methods=["POST"])
def ssd_stripe_webhook():
    """Handle Stripe webhook events for SSD subscriptions."""
    payload = request.get_data(as_text=True)
    sig = request.headers.get("Stripe-Signature", "")

    if SSD_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig, SSD_WEBHOOK_SECRET)
        except (stripe.error.SignatureVerificationError, ValueError) as e:
            logger.warning("Webhook signature verification failed: %s", e)
            return jsonify({"error": "Invalid signature"}), 400
    else:
        # No webhook secret configured — parse raw (dev/test mode)
        event = json.loads(payload)

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        _handle_subscription_change(data)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data)

    return jsonify({"received": True})


def _handle_checkout_completed(session: dict) -> None:
    """On successful checkout, generate API key and store subscription."""
    metadata = session.get("metadata", {})
    if metadata.get("product") != "ssd":
        return  # Not an SSD subscription

    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    email = session.get("customer_email") or session.get("customer_details", {}).get("email", "")
    plan = metadata.get("plan", "national")
    state = metadata.get("state", "")

    # Generate API key
    api_key = _generate_api_key()
    key_hash = _hash_key(api_key)

    store = _load_store()
    store["api_keys"][key_hash] = {
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "plan": plan,
        "state": state if plan == "single_state" else None,
        "email": email,
        "created": datetime.utcnow().isoformat(),
        "active": True,
    }
    store["customer_to_key"][customer_id] = key_hash
    _save_store(store)

    logger.info("SSD subscription created: %s (%s) — plan=%s state=%s",
                customer_id, email, plan, state)

    # TODO: Send welcome email with API key
    # For now, log it (the success page will show it)
    logger.info("API key generated for %s: %s", email, api_key)

    # Store plaintext key temporarily for the success page to retrieve
    # (expires after first retrieval)
    _pending_keys_path = SSD_STORE_PATH.parent / "ssd_pending_keys.json"
    pending = {}
    if _pending_keys_path.exists():
        try:
            pending = json.load(open(_pending_keys_path))
        except Exception:
            pass
    pending[session.get("id", "")] = {
        "api_key": api_key,
        "email": email,
        "created": datetime.utcnow().isoformat(),
    }
    with open(_pending_keys_path, "w") as f:
        json.dump(pending, f, indent=2)


def _handle_subscription_change(subscription: dict) -> None:
    """Deactivate API key if subscription is canceled or past_due."""
    customer_id = subscription.get("customer")
    status = subscription.get("status", "")

    store = _load_store()
    key_hash = store["customer_to_key"].get(customer_id)
    if not key_hash or key_hash not in store["api_keys"]:
        return

    if status in ("canceled", "unpaid", "past_due"):
        store["api_keys"][key_hash]["active"] = False
        logger.info("SSD subscription deactivated: %s (status=%s)", customer_id, status)
    elif status == "active":
        store["api_keys"][key_hash]["active"] = True
        logger.info("SSD subscription reactivated: %s", customer_id)

    _save_store(store)


def _handle_payment_failed(invoice: dict) -> None:
    """Log payment failure (subscription stays active until Stripe retries exhaust)."""
    customer_id = invoice.get("customer")
    logger.warning("SSD payment failed for customer %s", customer_id)


# ---- Authenticated: query districts ----

@ssd_bp.route("/api/ssd/districts", methods=["GET"])
@require_ssd_key
def ssd_districts():
    """Query school districts. Filtered by subscription scope.
    
    Query params:
      state       — Filter by state (e.g., FL, CA)
      city        — Filter by city (partial match)
      min_enrollment — Minimum enrollment
      confidence  — Filter by confidence level (confirmed, high, medium)
      format      — Response format: json (default) or csv
      limit       — Max results (default 1000, max 15000)
      offset      — Pagination offset
    """
    sub = request.ssd_sub
    df = _load_data()
    if df.empty:
        return jsonify({"error": "Data not available"}), 503

    # Scope filtering based on plan
    if sub["plan"] == "single_state" and sub.get("state"):
        allowed_state = sub["state"].upper()
        df = df[df["state"] == allowed_state]
        if df.empty:
            return jsonify({
                "error": f"No data for state '{allowed_state}'",
                "districts": [],
                "total": 0,
            })

    # User filters
    state_filter = request.args.get("state", "").upper()
    if state_filter:
        df = df[df["state"] == state_filter]

    city_filter = request.args.get("city", "").strip()
    if city_filter:
        df = df[df["city"].astype(str).str.contains(city_filter, case=False, na=False)]

    min_enroll = request.args.get("min_enrollment", type=int)
    if min_enroll:
        df = df[df["enrollment"].fillna(0).astype(int) >= min_enroll]

    confidence_filter = request.args.get("confidence", "").lower()
    if confidence_filter:
        df = df[df["confidence"].astype(str).str.lower() == confidence_filter]

    total = len(df)
    limit = min(int(request.args.get("limit", 1000)), 15000)
    offset = int(request.args.get("offset", 0))
    df = df.iloc[offset:offset + limit]

    # Format
    fmt = request.args.get("format", "json").lower()
    if fmt == "csv":
        csv_str = df.to_csv(index=False)
        return csv_str, 200, {
            "Content-Type": "text/csv",
            "Content-Disposition": f"attachment; filename=ssd_districts_{datetime.utcnow().strftime('%Y%m%d')}.csv",
        }

    districts = df.to_dict(orient="records")
    # Clean NaN values
    for d in districts:
        for k, v in d.items():
            if pd.isna(v):
                d[k] = None

    return jsonify({
        "districts": districts,
        "total": total,
        "limit": limit,
        "offset": offset,
        "plan": sub["plan"],
        "scope": sub.get("state") if sub["plan"] == "single_state" else "national",
    })


# ---- Authenticated: list states ----

@ssd_bp.route("/api/ssd/states", methods=["GET"])
@require_ssd_key
def ssd_states():
    """List available states with district counts."""
    sub = request.ssd_sub
    df = _load_data()
    if df.empty:
        return jsonify({"error": "Data not available"}), 503

    # Scope
    if sub["plan"] == "single_state" and sub.get("state"):
        df = df[df["state"] == sub["state"].upper()]

    states = (
        df.groupby("state")
        .agg(
            districts=("nces_leaid", "count"),
            confirmed=("confidence", lambda x: (x == "confirmed").sum()),
            total_enrollment=("enrollment", lambda x: int(x.fillna(0).sum())),
        )
        .reset_index()
        .sort_values("state")
        .to_dict(orient="records")
    )

    return jsonify({"states": states})


# ---- Retrieve API key after checkout ----

@ssd_bp.route("/api/ssd/retrieve-key", methods=["POST"])
def ssd_retrieve_key():
    """Retrieve API key after successful checkout. One-time use.
    
    Body JSON:
      session_id: Stripe checkout session ID
    """
    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id", "")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    pending_path = SSD_STORE_PATH.parent / "ssd_pending_keys.json"
    if not pending_path.exists():
        return jsonify({"error": "No pending keys"}), 404

    try:
        pending = json.load(open(pending_path))
    except Exception:
        return jsonify({"error": "Could not read pending keys"}), 500

    key_info = pending.pop(session_id, None)
    if not key_info:
        return jsonify({"error": "Key not found or already retrieved"}), 404

    # Save updated pending (key removed)
    with open(pending_path, "w") as f:
        json.dump(pending, f, indent=2)

    return jsonify({
        "api_key": key_info["api_key"],
        "email": key_info.get("email"),
        "message": "Save this API key securely — it won't be shown again.",
    })
