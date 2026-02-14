"""
TPCR Discord Bot — Premium role check for extended forecasts.

Integrates with Stripe Premium: users with the Premium Discord role
unlock 90-day and 1-year forecasts in /best-day and related commands.

Env: PREMIUM_ROLE_ID (Discord role ID for Premium subscribers)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord import Member

PREMIUM_ROLE_ID = os.environ.get("PREMIUM_ROLE_ID", "")
SUBSCRIBE_URL = "https://hazeydata.ai/subscribe.html"


def has_premium_role(member: "Member") -> bool:
    """
    Check if a Discord member has the Premium role.
    Use this before allowing 90-day or 1-year forecast ranges.
    """
    if not PREMIUM_ROLE_ID:
        return False
    return any(str(r.id) == PREMIUM_ROLE_ID for r in (member.roles or []))


def premium_teaser_message() -> str:
    """Message shown when a free user tries to access premium features."""
    return (
        "🔒 **Premium feature** — 90-day and 1-year forecasts are available for TPCR Premium subscribers. "
        f"Subscribe at {SUBSCRIBE_URL} to unlock extended forecasts!"
    )


def max_forecast_days(member: "Member") -> int:
    """
    Return max forecast days allowed for this member.
    Premium: 365 (1 year), Free: 7.
    """
    return 365 if has_premium_role(member) else 7


# ---------------------------------------------------------------------------
# Integration example for /best-day (or similar) command
# ---------------------------------------------------------------------------
#
# In your slash command handler:
#
#   @bot.tree.command(name="best-day", ...)
#   async def best_day(interaction: discord.Interaction, park: str, days: int = 7):
#       member = interaction.user
#       if isinstance(interaction.user, discord.Member):
#           member = interaction.user
#       else:
#           # Try to get member from guild
#           member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
#
#       max_days = max_forecast_days(member) if member else 7
#       if days > max_days:
#           await interaction.response.send_message(
#               premium_teaser_message(),
#               ephemeral=True
#           )
#           return
#
#       # ... proceed with forecast logic for requested days
#
