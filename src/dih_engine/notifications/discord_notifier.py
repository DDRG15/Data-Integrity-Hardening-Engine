"""
Discord notifier for Seer V4 Intelligence Reports.

Sends a rich embed message to a configured Discord webhook after each
recon run. Completely optional -- if DISCORD_WEBHOOK_URL is not set,
all functions return silently without raising.

Setup:
  1. Open Discord -> Server Settings -> Integrations -> Webhooks -> New Webhook
  2. Copy the webhook URL and add to .env:
       DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
"""
import datetime
import logging
import os

import requests

logger = logging.getLogger(__name__)

_COLOR_OK = 3066993       # green
_COLOR_MIXED = 16776960   # yellow
_COLOR_FAILED = 15158332  # red


def _embed_color(ok_count: int, total: int) -> int:
    if ok_count == total:
        return _COLOR_OK
    if ok_count == 0:
        return _COLOR_FAILED
    return _COLOR_MIXED


def notify_recon_complete(
    tech: str,
    strategy: str,
    gold_mine: str,
    status_counts: dict[str, int],
    fallback_counts: dict[str, int],
    output_file: str,
    timeout: int = 8,
) -> bool:
    """
    Sends a Seer Intelligence Report to Discord as a rich embed.
    Returns True on success, False on any failure (never raises).
    No-ops silently if DISCORD_WEBHOOK_URL is not configured.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.debug("discord_notify skipped -- DISCORD_WEBHOOK_URL not set")
        return False

    total = sum(status_counts.values())
    ok_count = status_counts.get("ok", 0)

    summary_str = "  |  ".join(f"`{k}` x{v}" for k, v in status_counts.items())
    fallback_str = (
        "  |  ".join(f"`{m}` x{n}" for m, n in fallback_counts.items())
        if fallback_counts else "none"
    )

    embed = {
        "title": "Seer V4 -- Intelligence Report",
        "color": _embed_color(ok_count, total),
        "fields": [
            {"name": "Architecture", "value": tech, "inline": True},
            {"name": "Strategy", "value": strategy, "inline": True},
            {"name": "Probe summary", "value": summary_str, "inline": False},
            {"name": "Fallback needed", "value": fallback_str, "inline": False},
            {"name": "Gold Mine", "value": gold_mine, "inline": False},
        ],
        "footer": {
            "text": f"dih-engine v4  |  {os.path.basename(output_file)}",
        },
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    try:
        response = requests.post(
            webhook_url,
            json={"embeds": [embed]},
            timeout=timeout,
        )
        response.raise_for_status()
        logger.info("discord_notify_sent status=%d", response.status_code)
        return True
    except requests.exceptions.RequestException as exc:
        logger.warning("discord_notify_failed reason=%s", exc)
        return False
