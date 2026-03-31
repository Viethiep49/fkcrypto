"""Alpha Seeker Agent — hunts for high-impact market events (Alpha Events).

Monitors:
- Exchange listings (Binance, OKX, Coinbase new listings)
- Whale movements (large deposits/withdrawals)
- Key influencer tweets (Elon, Vitalik, etc.)
- Breaking crypto news (hacks, partnerships, mainnets)

Classifies events by priority:
- IMMEDIATE: Listings, hacks, exploits
- HIGH: Major partnerships, regulatory approval
- MEDIUM: Upgrades, AMAs, conferences
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.base import BaseAgent
from src.agents.reasoning import Reasoning, ReasoningFactor
from src.agents.signal import Signal

logger = structlog.get_logger()

EVENT_PRIORITY_IMMEDIATE = "immediate"
EVENT_PRIORITY_HIGH = "high"
EVENT_PRIORITY_MEDIUM = "medium"

VALID_EVENT_TYPES = (
    "listing",
    "delisting",
    "partnership",
    "hack",
    "exploit",
    "mainnet",
    "upgrade",
    "regulation",
    "whale_movement",
    "influencer",
    "other",
)


class AlphaEvent:
    """Represents a detected alpha event."""

    def __init__(
        self,
        event_type: str,
        token: str,
        title: str,
        description: str,
        priority: str,
        source: str,
        url: str = "",
        timestamp: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.event_type = event_type
        self.token = token
        self.title = title
        self.description = description
        self.priority = priority
        self.source = source
        self.url = url
        self.timestamp = timestamp or datetime.now(UTC)
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "token": self.token,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "source": self.source,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class AlphaSeekerAgent(BaseAgent):
    """Alpha event hunter agent.

    Scans multiple data sources for high-impact events that can
    cause sudden price movements. Emits signals with high priority
    flags that can override technical analysis signals.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(name="alpha_seeker", config=config)
        alpha_config = config.get("alpha_seeker", {})

        # Check interval
        self.check_interval_sec = alpha_config.get("check_interval_sec", 60)

        # Enabled sources
        sources_cfg = alpha_config.get("sources", {})
        self.exchange_news_enabled = sources_cfg.get("exchange_news", {}).get("enabled", True)
        self.whale_alert_enabled = sources_cfg.get("whale_alert", {}).get("enabled", False)
        self.influencer_enabled = sources_cfg.get("influencer", {}).get("enabled", False)

        # API keys
        self.whale_alert_api_key = sources_cfg.get("whale_alert", {}).get("api_key", "")
        self.twitter_bearer_token = sources_cfg.get("influencer", {}).get("bearer_token", "")

        # Symbols to watch
        self.watch_symbols = config.get("pairs", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        self.watch_tokens = [s.split("/")[0] for s in self.watch_symbols]

        # Priority overrides
        self.priority_overrides = alpha_config.get("priority_overrides", {})

        # Override permission
        override_cfg = alpha_config.get("override", {})
        self.can_override_ta = override_cfg.get("can_override_technical", True)
        self.override_min_priority = override_cfg.get("min_priority", EVENT_PRIORITY_HIGH)

        # LLM gateway for event classification
        self._llm_gateway = config.get("llm_gateway")

        # Data sources (injected)
        self._news_source = config.get("news_source")

        # Tracking
        self._seen_events: set[str] = set()
        self._monitor_task: asyncio.Task | None = None

        # Influencer accounts to track
        self.influencers = alpha_config.get("influencers", [
            "elonmusk",
            "VitalikButerin",
            "cz_binance",
            "aeyakovenko",
            "APompliano",
        ])

    # ── Event detection ──────────────────────────────────────────────────

    async def _fetch_exchange_listings(self) -> list[AlphaEvent]:
        """Fetch new exchange listing announcements."""
        events: list[AlphaEvent] = []
        if not self.exchange_news_enabled or not self._news_source:
            return events

        try:
            listing_keywords = [
                "new listing",
                "will list",
                "listing announcement",
                "added to",
                "launchpool",
                "megadrop",
            ]
            news_items = await self._news_source.search_news(
                query="crypto exchange new listing announcement",
                limit=50,
            )

            for item in news_items:
                title = item.get("title", "").lower()
                if any(kw in title for kw in listing_keywords):
                    token = self._extract_token_from_title(item.get("title", ""))
                    if token:
                        events.append(AlphaEvent(
                            event_type="listing",
                            token=token,
                            title=item.get("title", ""),
                            description=item.get("summary", item.get("title", "")),
                            priority=self._classify_event_priority("listing", token),
                            source="exchange_news",
                            url=item.get("url", ""),
                            metadata={"exchange": self._detect_exchange(item.get("title", ""))},
                        ))
        except Exception as exc:
            self._logger.error("exchange_listings_fetch_failed", error=str(exc))

        return events

    async def _fetch_whale_alerts(self) -> list[AlphaEvent]:
        """Fetch whale movement alerts from WhaleAlert API."""
        events: list[AlphaEvent] = []
        if not self.whale_alert_enabled or not self.whale_alert_api_key:
            return events

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    "https://api.whale-alert.io/v1/transactions",
                    params={
                        "api_key": self.whale_alert_api_key,
                        "min_amount": 1000000,
                        "limit": 20,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    for tx in data.get("transactions", []):
                        token = tx.get("symbol", "")
                        if token in self.watch_tokens:
                            amount = tx.get("amount", 0)
                            to_address = tx.get("to", {}).get("owner", "")
                            from_address = tx.get("from", {}).get("owner", "")

                            is_exchange_deposit = self._is_exchange_address(to_address)
                            is_exchange_withdraw = self._is_exchange_address(from_address)

                            if is_exchange_deposit:
                                priority = EVENT_PRIORITY_HIGH
                                desc = f"Whale deposit {amount:,.0f} {token} to exchange"
                            elif is_exchange_withdraw:
                                priority = EVENT_PRIORITY_HIGH
                                desc = f"Whale withdraw {amount:,.0f} {token} from exchange"
                            else:
                                priority = EVENT_PRIORITY_MEDIUM
                                desc = f"Large transfer: {amount:,.0f} {token}"

                            events.append(AlphaEvent(
                                event_type="whale_movement",
                                token=token,
                                title=f"Whale Alert: {amount:,.0f} {token}",
                                description=desc,
                                priority=priority,
                                source="whale_alert",
                                metadata={
                                    "amount": amount,
                                    "to": to_address,
                                    "from": from_address,
                                    "tx_hash": tx.get("hash", ""),
                                },
                            ))
        except Exception as exc:
            self._logger.error("whale_alerts_fetch_failed", error=str(exc))

        return events

    async def _fetch_influencer_signals(self) -> list[AlphaEvent]:
        """Monitor key influencer accounts for crypto mentions."""
        events: list[AlphaEvent] = []
        if not self.influencer_enabled or not self.twitter_bearer_token:
            return events

        try:
            import httpx

            for influencer in self.influencers:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(
                        "https://api.twitter.com/2/tweets/search/recent",
                        headers={
                            "Authorization": f"Bearer {self.twitter_bearer_token}",
                        },
                        params={
                            "query": (
                                f"from:{influencer} "
                                "(bitcoin OR crypto OR BTC OR ETH OR SOL "
                                "OR listing OR launch)"
                            ),
                            "max_results": 5,
                            "tweet.fields": "created_at,public_metrics",
                        },
                    )
                    if response.status_code == 200:
                        data = response.json()
                        for tweet in data.get("data", []):
                            token = self._extract_token_from_title(tweet.get("text", ""))
                            if token:
                                events.append(AlphaEvent(
                                    event_type="influencer",
                                    token=token,
                                    title=f"{influencer}: {tweet.get('text', '')[:80]}",
                                    description=tweet.get("text", ""),
                                    priority=EVENT_PRIORITY_HIGH,
                                    source="influencer",
                                    metadata={
                                        "influencer": influencer,
                                        "tweet_id": tweet.get("id", ""),
                                        "likes": tweet.get(
                                            "public_metrics", {},
                                        ).get("like_count", 0),
                                        "retweets": tweet.get(
                                            "public_metrics", {},
                                        ).get("retweet_count", 0),
                                    },
                                ))
        except Exception as exc:
            self._logger.error("influencer_signals_fetch_failed", error=str(exc))

        return events

    async def _detect_breaking_news(self) -> list[AlphaEvent]:
        """Detect breaking crypto news (hacks, exploits, regulation)."""
        events: list[AlphaEvent] = []
        if not self._news_source:
            return events

        try:
            breaking_keywords = [
                "hack", "exploit", "drained", "stolen",
                "ban", "regulation", "sec",
                "partnership", "collaboration",
                "mainnet", "upgrade", "hard fork",
            ]
            news_items = await self._news_source.search_news(
                query="crypto breaking news hack exploit regulation",
                limit=30,
            )

            for item in news_items:
                title = item.get("title", "").lower()
                for kw in breaking_keywords:
                    if kw in title:
                        event_type = self._map_keyword_to_event_type(kw)
                        token = self._extract_token_from_title(item.get("title", ""))
                        if not token:
                            token = "MARKET"
                        priority = self._classify_event_priority(event_type, token)
                        events.append(AlphaEvent(
                            event_type=event_type,
                            token=token,
                            title=item.get("title", ""),
                            description=item.get("summary", item.get("title", "")),
                            priority=priority,
                            source="breaking_news",
                            url=item.get("url", ""),
                            metadata={"keyword": kw},
                        ))
                        break
        except Exception as exc:
            self._logger.error("breaking_news_detection_failed", error=str(exc))

        return events

    # ── Event classification ─────────────────────────────────────────────

    def _classify_event_priority(self, event_type: str, token: str) -> str:
        """Assign priority level to an event type."""
        overrides = self.priority_overrides.get(event_type, {})
        if overrides.get("force_priority"):
            return overrides["force_priority"]

        if event_type in ("listing", "hack", "exploit"):
            return EVENT_PRIORITY_IMMEDIATE
        elif event_type in ("partnership", "whale_movement", "influencer"):
            return EVENT_PRIORITY_HIGH
        elif event_type in ("mainnet", "upgrade", "regulation"):
            return EVENT_PRIORITY_MEDIUM
        return EVENT_PRIORITY_MEDIUM

    def _map_keyword_to_event_type(self, keyword: str) -> str:
        """Map a keyword to an event type."""
        mapping = {
            "hack": "hack",
            "exploit": "exploit",
            "drained": "hack",
            "stolen": "hack",
            "ban": "regulation",
            "regulation": "regulation",
            "sec": "regulation",
            "partnership": "partnership",
            "collaboration": "partnership",
            "mainnet": "mainnet",
            "upgrade": "upgrade",
            "hard fork": "upgrade",
        }
        return mapping.get(keyword, "other")

    def _extract_token_from_title(self, title: str) -> str:
        """Extract token symbol from a news title."""
        token_map = {
            "bitcoin": "BTC",
            "btc": "BTC",
            "ethereum": "ETH",
            "eth": "ETH",
            "solana": "SOL",
            "sol": "SOL",
            "bnb": "BNB",
            "binance coin": "BNB",
            "dogecoin": "DOGE",
            "doge": "DOGE",
            "xrp": "XRP",
            "ripple": "XRP",
            "cardano": "ADA",
            "ada": "ADA",
            "avalanche": "AVAX",
            "avax": "AVAX",
            "polkadot": "DOT",
            "dot": "DOT",
        }
        title_lower = title.lower()
        for keyword, symbol in token_map.items():
            if keyword in title_lower:
                return symbol
        return ""

    def _detect_exchange(self, title: str) -> str:
        """Detect which exchange is mentioned in the title."""
        title_lower = title.lower()
        if "binance" in title_lower:
            return "Binance"
        elif "coinbase" in title_lower:
            return "Coinbase"
        elif "okx" in title_lower:
            return "OKX"
        elif "bybit" in title_lower:
            return "Bybit"
        elif "kucoin" in title_lower:
            return "KuCoin"
        return "Unknown"

    def _is_exchange_address(self, address: str) -> bool:
        """Check if an address belongs to a known exchange."""
        exchange_labels = [
            "binance", "coinbase", "kraken", "okx",
            "bybit", "kucoin", "huobi", "bitfinex",
        ]
        address_lower = address.lower()
        return any(label in address_lower for label in exchange_labels)

    # ── Signal generation ────────────────────────────────────────────────

    def _event_to_signal(self, event: AlphaEvent) -> Signal:
        """Convert an AlphaEvent to a trading Signal with reasoning."""
        action = self._determine_action_from_event(event)
        confidence = self._calculate_event_confidence(event)

        reasoning = self._build_alpha_reasoning(event, action, confidence)

        return Signal(
            symbol=f"{event.token}/USDT",
            timeframe="1m",
            action=action,
            confidence=confidence,
            strength=self._calculate_event_strength(event),
            source="alpha",
            metadata={
                "event_type": event.event_type,
                "priority": event.priority,
                "title": event.title,
                "url": event.url,
                "source": event.source,
                "can_override_ta": self.can_override_ta,
                "event_data": event.to_dict(),
            },
            reasoning=reasoning,
        )

    def _determine_action_from_event(self, event: AlphaEvent) -> str:
        """Determine buy/sell/hold based on event type."""
        bullish_events = ("listing", "partnership", "mainnet", "upgrade")
        bearish_events = ("hack", "exploit", "delisting", "regulation")

        if event.event_type in bullish_events:
            return "buy"
        elif event.event_type in bearish_events:
            return "sell"
        elif event.event_type == "whale_movement":
            to_addr = event.metadata.get("to", "").lower()
            from_addr = event.metadata.get("from", "").lower()
            if any(ex in to_addr for ex in ["binance", "coinbase", "okx"]):
                return "sell"
            elif any(ex in from_addr for ex in ["binance", "coinbase", "okx"]):
                return "buy"
        elif event.event_type == "influencer":
            return "buy"

        return "hold"

    def _calculate_event_confidence(self, event: AlphaEvent) -> float:
        """Calculate confidence based on event priority and source reliability."""
        base_confidence = {
            EVENT_PRIORITY_IMMEDIATE: 0.95,
            EVENT_PRIORITY_HIGH: 0.80,
            EVENT_PRIORITY_MEDIUM: 0.60,
        }.get(event.priority, 0.50)

        source_reliability = {
            "exchange_news": 1.0,
            "whale_alert": 0.85,
            "breaking_news": 0.75,
            "influencer": 0.65,
        }
        reliability = source_reliability.get(event.source, 0.5)

        return min(base_confidence * reliability, 0.99)

    def _calculate_event_strength(self, event: AlphaEvent) -> float:
        """Calculate signal strength from event impact."""
        if event.priority == EVENT_PRIORITY_IMMEDIATE:
            return 0.8 if event.event_type in ("listing", "hack") else 0.6
        elif event.priority == EVENT_PRIORITY_HIGH:
            return 0.5
        return 0.3

    def _build_alpha_reasoning(
        self,
        event: AlphaEvent,
        action: str,
        confidence: float,
    ) -> Reasoning:
        """Build structured reasoning for an alpha event signal."""
        priority_labels = {
            EVENT_PRIORITY_IMMEDIATE: "KHẨN CẤP",
            EVENT_PRIORITY_HIGH: "CAO",
            EVENT_PRIORITY_MEDIUM: "TRUNG BÌNH",
        }
        priority_label = priority_labels.get(event.priority, event.priority)

        event_type_labels = {
            "listing": "Listing mới trên sàn",
            "hack": "Bị hack/exploit",
            "exploit": "Bị khai thác lỗ hổng",
            "partnership": "Hợp tác đối tác",
            "mainnet": "Ra mắt mainnet",
            "upgrade": "Nâng cấp mạng lưới",
            "regulation": "Tin quy định/pháp lý",
            "whale_movement": "Cá voi di chuyển",
            "influencer": "KOL ảnh hưởng",
        }
        event_label = event_type_labels.get(event.event_type, event.event_type)

        direction = "MUA" if action == "buy" else "BÁN" if action == "sell" else "GIỮ"

        reasoning = Reasoning(
            agent="alpha_seeker",
            confidence=confidence,
            summary=(
                f"ALPHA {priority_label}: {event_label} cho {event.token}. "
                f"Hành động: {direction}. Nguồn: {event.source}. "
                f"{event.description[:100]}"
            ),
            factors=[
                ReasoningFactor(
                    type="event",
                    description=f"{event_label}: {event.title}",
                    impact=0.3 if action == "buy" else -0.3 if action == "sell" else 0.0,
                    metadata={
                        "event_type": event.event_type,
                        "priority": event.priority,
                        "source": event.source,
                        "token": event.token,
                    },
                ),
            ],
        )

        if event.event_type == "whale_movement":
            amount = event.metadata.get("amount", 0)
            reasoning.add_factor(ReasoningFactor(
                type="event",
                description=f"Khối lượng: {amount:,.0f} {event.token}",
                impact=0.1,
                metadata={"amount": amount},
            ))
        elif event.event_type == "influencer":
            influencer = event.metadata.get("influencer", "")
            likes = event.metadata.get("likes", 0)
            reasoning.add_factor(ReasoningFactor(
                type="social",
                description=f"{influencer} đề cập ({likes:,} likes)",
                impact=0.1,
                metadata={"influencer": influencer, "likes": likes},
            ))

        return reasoning

    # ── Main run ─────────────────────────────────────────────────────────

    async def run(self) -> list[Signal]:
        """Execute one alpha detection cycle.

        Returns:
            List of Signal objects from detected alpha events.
        """
        all_events: list[AlphaEvent] = []

        # Fetch from all sources in parallel
        tasks = []
        if self.exchange_news_enabled:
            tasks.append(self._fetch_exchange_listings())
        if self.whale_alert_enabled:
            tasks.append(self._fetch_whale_alerts())
        if self.influencer_enabled:
            tasks.append(self._fetch_influencer_signals())
        tasks.append(self._detect_breaking_news())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                all_events.extend(result)
            elif isinstance(result, Exception):
                self._logger.error("alpha_source_error", error=str(result))

        # Deduplicate
        unique_events: list[AlphaEvent] = []
        for event in all_events:
            event_key = f"{event.token}:{event.event_type}:{event.title[:50]}"
            if event_key not in self._seen_events:
                self._seen_events.add(event_key)
                unique_events.append(event)

        # Keep seen_events set bounded
        if len(self._seen_events) > 1000:
            self._seen_events = set(list(self._seen_events)[-500:])

        # Convert to signals
        signals = [self._event_to_signal(e) for e in unique_events]

        for signal in signals:
            self._logger.info(
                "alpha_signal_emitted",
                token=signal.symbol,
                event_type=signal.metadata.get("event_type"),
                priority=signal.metadata.get("priority"),
                action=signal.action,
                confidence=signal.confidence,
            )

        self._logger.info(
            "alpha_cycle_complete",
            events_found=len(all_events),
            unique_events=len(unique_events),
            signals_emitted=len(signals),
        )

        return signals

    async def start_monitoring(self) -> None:
        """Start continuous alpha event monitoring."""
        if self._monitor_task and not self._monitor_task.done():
            self._logger.warning("monitoring_already_running")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._logger.info(
            "alpha_monitoring_started",
            interval_sec=self.check_interval_sec,
        )

    async def _monitor_loop(self) -> None:
        """Continuous monitoring loop."""
        while self._running:
            try:
                await self.safe_run()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.error("alpha_monitor_loop_error", error=str(exc))

            try:
                await asyncio.sleep(self.check_interval_sec)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        """Stop the alpha seeker agent."""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        await super().stop()
