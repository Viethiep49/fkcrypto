"""Multi-channel notification system for FKCrypto."""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class Notifier:
    """Send alerts through multiple channels.

    Channels are activated by presence of credentials in config.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        notif_cfg = config.get("notifications", {})

        # Telegram
        tg_cfg = notif_cfg.get("telegram", {})
        self.tg_token = tg_cfg.get("bot_token", "")
        self.tg_chat_id = tg_cfg.get("chat_id", "")
        self.tg_enabled = bool(self.tg_token and self.tg_chat_id)

        # Discord
        dc_cfg = notif_cfg.get("discord", {})
        self.dc_webhook_url = dc_cfg.get("webhook_url", "")
        self.dc_enabled = bool(self.dc_webhook_url)

        # Slack
        sl_cfg = notif_cfg.get("slack", {})
        self.sl_webhook_url = sl_cfg.get("webhook_url", "")
        self.sl_enabled = bool(self.sl_webhook_url)

        self._active_channels = [
            ch for ch, enabled in [
                ("telegram", self.tg_enabled),
                ("discord", self.dc_enabled),
                ("slack", self.sl_enabled),
            ]
            if enabled
        ]

        logger.info(
            "notifier_initialized",
            channels=self._active_channels,
        )

    async def send(self, message: str, priority: str = "info") -> None:
        """Send a message to all active channels.

        Args:
            message: The notification text.
            priority: One of "info", "warning", "error", "urgent".
        """
        for channel in self._active_channels:
            try:
                if channel == "telegram":
                    await self._send_telegram(message, priority)
                elif channel == "discord":
                    await self._send_discord(message, priority)
                elif channel == "slack":
                    await self._send_slack(message, priority)
            except Exception as exc:
                logger.error(
                    "notification_send_failed",
                    channel=channel,
                    error=str(exc),
                )

    async def send_trade(
        self,
        symbol: str,
        action: str,
        score: float,
        confidence: float,
        order_id: str = "",
    ) -> None:
        """Send a trade notification."""
        message = (
            f"Trade Executed\n"
            f"Symbol: {symbol}\n"
            f"Action: {action.upper()}\n"
            f"Score: {score:.4f}\n"
            f"Confidence: {confidence:.4f}"
        )
        if order_id:
            message += f"\nOrder ID: {order_id}"

        await self.send(message, priority="info")

    async def send_kill_switch(self, reason: str) -> None:
        """Send urgent kill switch alert."""
        message = (
            f"KILL SWITCH TRIGGERED\n"
            f"Reason: {reason}\n"
            f"All positions will be closed. Manual reset required."
        )
        await self.send(message, priority="urgent")

    async def send_daily_report(self, summary: dict[str, Any]) -> None:
        """Send a daily summary report."""
        lines = [
            "Daily Trading Report",
            f"Trades: {summary.get('trades', 0)}",
            f"Win Rate: {summary.get('win_rate', 0):.1%}",
            f"P&L: {summary.get('pnl', 0):.2f} USD",
            f"Best Trade: {summary.get('best_trade', 0):.2f} USD",
            f"Worst Trade: {summary.get('worst_trade', 0):.2f} USD",
        ]
        await self.send("\n".join(lines), priority="info")

    async def _send_telegram(self, message: str, priority: str) -> None:
        """Send message via Telegram Bot API."""
        import aiohttp

        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        payload = {
            "chat_id": self.tg_chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        if priority == "urgent":
            payload["disable_notification"] = False
        elif priority in ("error", "warning"):
            pass

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Telegram API error: {resp.status} {text}")

        logger.debug("telegram_sent", priority=priority)

    async def _send_discord(self, message: str, priority: str) -> None:
        """Send message via Discord webhook."""
        import aiohttp

        color_map = {
            "info": 0x3498db,
            "warning": 0xf39c12,
            "error": 0xe74c3c,
            "urgent": 0xc0392b,
        }

        payload = {
            "embeds": [{
                "title": "FKCrypto Alert",
                "description": message,
                "color": color_map.get(priority, 0x3498db),
            }]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.dc_webhook_url, json=payload) as resp:
                if resp.status not in (200, 204):
                    text = await resp.text()
                    raise RuntimeError(f"Discord webhook error: {resp.status} {text}")

        logger.debug("discord_sent", priority=priority)

    async def _send_slack(self, message: str, priority: str) -> None:
        """Send message via Slack webhook."""
        import aiohttp

        color_map = {
            "info": "#3498db",
            "warning": "#f39c12",
            "error": "#e74c3c",
            "urgent": "#c0392b",
        }

        payload = {
            "attachments": [{
                "color": color_map.get(priority, "#3498db"),
                "text": message,
            }]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.sl_webhook_url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Slack webhook error: {resp.status} {text}")

        logger.debug("slack_sent", priority=priority)
