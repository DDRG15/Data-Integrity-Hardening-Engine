from . import discord_notifier, slack_notifier


def notify_all(
    tech: str,
    strategy: str,
    gold_mine: str,
    status_counts: dict[str, int],
    fallback_counts: dict[str, int],
    output_file: str,
    flavor: str = "",
) -> None:
    """Fires all configured notification channels. Skips unconfigured ones silently."""
    kwargs = dict(
        tech=tech,
        strategy=strategy,
        gold_mine=gold_mine,
        status_counts=status_counts,
        fallback_counts=fallback_counts,
        output_file=output_file,
        flavor=flavor,
    )
    slack_notifier.notify_recon_complete(**kwargs)
    discord_notifier.notify_recon_complete(**kwargs)


__all__ = ["notify_all", "slack_notifier", "discord_notifier"]
