"""
Slack notifier for Seer V4 Intelligence Reports.

Sends a formatted Block Kit message to a configured Slack webhook after
each recon run. Completely optional -- if SLACK_WEBHOOK_URL is not set,
all functions return silently without raising.

Setup:
  1. Create an incoming webhook at https://api.slack.com/apps
  2. Add SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... to .env
"""
import datetime
import logging
import os

import requests

logger = logging.getLogger(__name__)

_EMOJI_BY_STATUS = {
    "all_ok": ":white_check_mark:",
    "mixed": ":warning:",
    "all_failed": ":x:",
}


def _status_emoji(ok_count: int, total: int) -> str:
    if ok_count == total:
        return _EMOJI_BY_STATUS["all_ok"]
    if ok_count == 0:
        return _EMOJI_BY_STATUS["all_failed"]
    return _EMOJI_BY_STATUS["mixed"]


def _build_blocks(
    tech: str,
    strategy: str,
    gold_mine: str,
    status_counts: dict[str, int],
    fallback_counts: dict[str, int],
    output_file: str,
    total: int,
) -> list[dict]:
    ok_count = status_counts.get("ok", 0)
    emoji = _status_emoji(ok_count, total)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    summary_parts = [f"{v} `{k}`" for k, v in status_counts.items()]
    summary_str = "  |  ".join(summary_parts)

    fallback_str = (
        "  |  ".join(f"`{m}` x{n}" for m, n in fallback_counts.items())
        if fallback_counts else "none"
    )

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji}  Seer V4 -- Intelligence Report",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Architecture*\n{tech}"},
                {"type": "mrkdwn", "text": f"*Strategy*\n{strategy}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Probe summary*\n{summary_str}"},
                {"type": "mrkdwn", "text": f"*Fallback needed*\n{fallback_str}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Gold Mine*\n{gold_mine}"},
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":page_facing_up: `{os.path.basename(output_file)}`  |  {timestamp}  |  dih-engine v4",
                }
            ],
        },
    ]


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
    Sends a Seer Intelligence Report to Slack.
    Returns True on success, False on any failure (never raises).
    No-ops silently if SLACK_WEBHOOK_URL is not configured.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.debug("slack_notify skipped -- SLACK_WEBHOOK_URL not set")
        return False

    total = sum(status_counts.values())
    blocks = _build_blocks(tech, strategy, gold_mine, status_counts, fallback_counts, output_file, total)

    try:
        response = requests.post(
            webhook_url,
            json={"blocks": blocks},
            timeout=timeout,
        )
        response.raise_for_status()
        logger.info("slack_notify_sent status=%d", response.status_code)
        return True
    except requests.exceptions.RequestException as exc:
        logger.warning("slack_notify_failed reason=%s", exc)
        return False
