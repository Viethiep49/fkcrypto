"""News & Sentiment Agent — analyzes crypto news and social sentiment using LLM."""

from __future__ import annotations

from typing import Any

import structlog

from src.agents.base import BaseAgent
from src.agents.reasoning import Reasoning, ReasoningFactor
from src.agents.signal import Signal

logger = structlog.get_logger()


class NewsSentimentAgent(BaseAgent):
    """News and sentiment analysis agent.

    Fetches news from CryptoPanic/SerpAPI, uses LLM to classify sentiment,
    calculates weighted sentiment scores, and emits sentiment signals.

    LLM is only used for sentiment classification (NLP task).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(name="news_sentiment", config=config)
        sentiment_config = config.get("sentiment", {})

        # Schedule
        self.schedule = sentiment_config.get("schedule", "0 * * * *")
        self.news_max_age_hours = sentiment_config.get("news_max_age_hours", 24)

        # Source configuration
        sources_cfg = sentiment_config.get("sources", {})
        cp_cfg = sources_cfg.get("cryptopanic", {})
        serp_cfg = sources_cfg.get("serpapi", {})
        lc_cfg = sources_cfg.get("lunarcrush", {})

        self.cp_enabled = cp_cfg.get("enabled", False)
        self.cp_api_key = cp_cfg.get("api_key", "")
        self.serp_enabled = serp_cfg.get("enabled", False)
        self.serp_api_key = serp_cfg.get("api_key", "")
        self.lc_enabled = lc_cfg.get("enabled", False)
        self.lc_api_key = lc_cfg.get("api_key", "")

        # LLM configuration
        llm_cfg = sentiment_config.get("llm", {})
        self.llm_model = llm_cfg.get("model", "gpt-4o-mini")
        self.llm_max_tokens = llm_cfg.get("max_tokens", 500)
        self.llm_temperature = llm_cfg.get("temperature", 0.1)

        # Thresholds
        thresholds = sentiment_config.get("thresholds", {})
        self.strong_bullish = thresholds.get("strong_bullish", 0.5)
        self.strong_bearish = thresholds.get("strong_bearish", -0.5)
        self.min_news_count = thresholds.get("min_news_count", 3)

        # Symbols to analyze
        self.symbols = config.get("pairs", ["BTC", "ETH", "SOL"])

        # Data sources (injected)
        self._news_source = config.get("news_source")
        self._social_source = config.get("social_source")
        self._llm_gateway = config.get("llm_gateway")

        # Sentiment weights
        self.sentiment_weights = {
            "llm": 0.40,
            "news_ratio": 0.25,
            "social_volume": 0.20,
            "fear_greed": 0.15,
        }

    def _build_news_query(self, symbol: str) -> str:
        """Build a search query for a given symbol."""
        symbol_names = {
            "BTC": "Bitcoin",
            "ETH": "Ethereum",
            "SOL": "Solana",
            "BNB": "BNB Binance Coin",
            "DOGE": "Dogecoin",
        }
        name = symbol_names.get(symbol, symbol)
        return f"{name} crypto price news"

    async def _fetch_news(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch news from all configured sources."""
        all_news: list[dict[str, Any]] = []

        # CryptoPanic
        if self.cp_enabled and self._news_source:
            try:
                cp_news = await self._news_source.get_crypto_news(
                    currencies=[symbol],
                    limit=30,
                )
                all_news.extend(cp_news)
                self._logger.info(
                    "cryptopanic_news_fetched",
                    symbol=symbol,
                    count=len(cp_news),
                )
            except Exception as exc:
                self._logger.error(
                    "cryptopanic_fetch_failed",
                    symbol=symbol,
                    error=str(exc),
                )

        # SerpAPI
        if self.serp_enabled and self._news_source:
            try:
                query = self._build_news_query(symbol)
                serp_news = await self._news_source.search_news(
                    query=query,
                    limit=20,
                )
                all_news.extend(serp_news)
                self._logger.info(
                    "serpapi_news_fetched",
                    symbol=symbol,
                    count=len(serp_news),
                )
            except Exception as exc:
                self._logger.error(
                    "serpapi_fetch_failed",
                    symbol=symbol,
                    error=str(exc),
                )

        return all_news

    async def _fetch_social_data(self, symbol: str) -> dict[str, Any]:
        """Fetch social sentiment and volume data."""
        result = {
            "sentiment": 0.0,
            "social_volume": 0.0,
            "bullish_pct": 50.0,
            "bearish_pct": 50.0,
        }

        if not self.lc_enabled or not self._social_source:
            return result

        try:
            sentiment_data = await self._social_source.get_sentiment(symbol)
            result["sentiment"] = sentiment_data.get("sentiment", 0.0)
            result["bullish_pct"] = sentiment_data.get("bullish_pct", 50.0)
            result["bearish_pct"] = sentiment_data.get("bearish_pct", 50.0)
        except Exception as exc:
            self._logger.error(
                "social_sentiment_fetch_failed",
                symbol=symbol,
                error=str(exc),
            )

        try:
            volume_data = await self._social_source.get_social_volume(symbol)
            result["social_volume"] = volume_data.get("social_volume", 0)
        except Exception as exc:
            self._logger.error(
                "social_volume_fetch_failed",
                symbol=symbol,
                error=str(exc),
            )

        return result

    async def _classify_sentiment_llm(
        self,
        symbol: str,
        news_items: list[dict[str, Any]],
    ) -> tuple[float, float]:
        """Use LLM to classify sentiment from news items.

        Returns:
            Tuple of (sentiment_score, confidence).
        """
        if not self._llm_gateway:
            return 0.0, 0.0

        # Format news for LLM
        news_text = "\n".join(
            f"- {item.get('title', '')}" for item in news_items[:20]
        )

        prompt = (
            f"You are a crypto market sentiment analyst. Analyze the following "
            f"news and social media content for {symbol} and return a structured "
            f"sentiment assessment.\n\n"
            f"Content:\n{news_text}\n\n"
            f"Return ONLY a JSON object with this structure:\n"
            f'{{"sentiment_score": <float -1.0 to 1.0>, "confidence": <float 0.0 to 1.0>, '
            f'"key_factors": ["factor1", "factor2"], "summary": "<max 100 chars>"}}\n\n'
            f"Sentiment scale:\n"
            f"-1.0 = Extremely bearish (crash, ban, hack, regulatory crackdown)\n"
            f"-0.5 = Bearish (negative news, FUD, selling pressure)\n"
            f" 0.0 = Neutral (mixed or no significant news)\n"
            f"+0.5 = Bullish (positive adoption, partnerships, good metrics)\n"
            f"+1.0 = Extremely bullish (major breakthrough, institutional adoption)"
        )

        try:
            result = self._llm_gateway.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a crypto sentiment analyst."},
                    {"role": "user", "content": prompt},
                ],
                model=self.llm_model,
                temperature=self.llm_temperature,
                max_tokens=self.llm_max_tokens,
            )

            content = result.get("content", "{}")
            import json

            data = json.loads(content)
            sentiment = float(data.get("sentiment_score", 0.0))
            confidence = float(data.get("confidence", 0.5))

            sentiment = max(-1.0, min(1.0, sentiment))
            confidence = max(0.0, min(1.0, confidence))

            self._logger.info(
                "llm_sentiment_classified",
                symbol=symbol,
                sentiment=sentiment,
                confidence=confidence,
            )
            return sentiment, confidence

        except Exception as exc:
            self._logger.error(
                "llm_sentiment_classification_failed",
                symbol=symbol,
                error=str(exc),
            )
            return 0.0, 0.0

    def _calculate_news_ratio(self, news_items: list[dict[str, Any]]) -> float:
        """Calculate ratio of positive to total news."""
        if not news_items:
            return 0.5

        positive = 0
        for item in news_items:
            sentiment = item.get("sentiment", 0.0)
            if sentiment > 0.1:
                positive += 1

        return positive / len(news_items)

    def _normalize_social_volume(self, volume: int) -> float:
        """Normalize social volume to 0-1 range."""
        if volume <= 0:
            return 0.0
        # Simple normalization — cap at 10000 mentions
        return min(volume / 10000.0, 1.0)

    def calculate_sentiment_score(
        self,
        llm_score: float,
        news_ratio: float,
        social_volume: float,
        fear_greed: float,
    ) -> float:
        """Weighted sentiment score from multiple sources.

        Args:
            llm_score: LLM-classified sentiment (-1.0 to 1.0).
            news_ratio: Positive news ratio (0.0 to 1.0).
            social_volume: Normalized social volume (0.0 to 1.0).
            fear_greed: Fear & Greed index (0 to 100).

        Returns:
            Weighted sentiment score (-1.0 to 1.0).
        """
        normalized_fg = (fear_greed - 50) / 50  # -1 to 1

        score = (
            self.sentiment_weights["llm"] * llm_score
            + self.sentiment_weights["news_ratio"] * (news_ratio * 2 - 1)
            + self.sentiment_weights["social_volume"] * (social_volume * 2 - 1)
            + self.sentiment_weights["fear_greed"] * normalized_fg
        )
        return max(-1.0, min(1.0, score))

    def _rule_based_sentiment(
        self,
        news_items: list[dict[str, Any]],
        social_data: dict[str, Any],
    ) -> float:
        """Fallback rule-based sentiment when LLM is unavailable."""
        if not news_items:
            return 0.0

        # Average sentiment from news sources
        news_sentiments = [
            item.get("sentiment", 0.0) for item in news_items
        ]
        avg_news_sentiment = (
            sum(news_sentiments) / len(news_sentiments) if news_sentiments else 0.0
        )

        # Social sentiment
        social_sentiment = social_data.get("sentiment", 0.0)

        # Weighted average
        score = 0.6 * avg_news_sentiment + 0.4 * social_sentiment
        return max(-1.0, min(1.0, score))

    async def _analyze_symbol(self, symbol: str) -> Signal | None:
        """Analyze sentiment for a single symbol."""
        # Fetch news
        news_items = await self._fetch_news(symbol)

        # Fetch social data
        social_data = await self._fetch_social_data(symbol)

        # Need minimum news count for valid signal
        if len(news_items) < self.min_news_count:
            self._logger.debug(
                "insufficient_news",
                symbol=symbol,
                count=len(news_items),
                min_required=self.min_news_count,
            )
            reasoning = Reasoning(
                agent="news_sentiment",
                summary=f"Không đủ tin tức để phân tích cho {symbol} ({len(news_items)} < {self.min_news_count})",
                confidence=0.0,
                factors=[ReasoningFactor(
                    type="news",
                    description=f"Chỉ có {len(news_items)} tin tức, cần tối thiểu {self.min_news_count}",
                    impact=0.0,
                    metadata={"news_count": len(news_items)},
                )],
            )
            return Signal(
                symbol=f"{symbol}/USDT",
                timeframe="1h",
                action="hold",
                confidence=0.0,
                strength=0.0,
                source="sentiment",
                metadata={
                    "news_count": len(news_items),
                    "reason": "insufficient_news",
                },
                reasoning=reasoning,
            )

        # LLM classification
        llm_score = 0.0
        llm_confidence = 0.5
        llm_failed = False

        if self._llm_gateway:
            llm_score, llm_confidence = await self._classify_sentiment_llm(
                symbol, news_items
            )
            if llm_confidence == 0.0:
                llm_failed = True
        else:
            llm_failed = True

        # Fallback to rule-based if LLM failed
        if llm_failed:
            llm_score = self._rule_based_sentiment(news_items, social_data)
            llm_confidence = max(0.0, llm_confidence - 0.2)
            self._logger.info(
                "fallback_to_rule_based",
                symbol=symbol,
                sentiment=llm_score,
            )

        # Calculate metrics
        news_ratio = self._calculate_news_ratio(news_items)
        social_volume = self._normalize_social_volume(
            social_data.get("social_volume", 0)
        )
        fear_greed = 50.0  # Default neutral — can be fetched from external API

        # Weighted sentiment score
        sentiment_score = self.calculate_sentiment_score(
            llm_score=llm_score,
            news_ratio=news_ratio,
            social_volume=social_volume,
            fear_greed=fear_greed,
        )

        # Determine action
        if sentiment_score >= self.strong_bullish:
            action = "buy"
        elif sentiment_score <= self.strong_bearish:
            action = "sell"
        else:
            action = "hold"

        # Confidence based on LLM confidence and data quality
        confidence = min(
            llm_confidence * 0.5 + (len(news_items) / 50.0) * 0.5,
            0.95,
        )
        confidence = max(0.0, min(1.0, confidence))

        positive_count = sum(1 for n in news_items if n.get("sentiment", 0) > 0.1)
        negative_count = sum(1 for n in news_items if n.get("sentiment", 0) < -0.1)

        # Build reasoning
        reasoning = self._build_sentiment_reasoning(
            symbol=symbol,
            sentiment_score=sentiment_score,
            llm_score=llm_score,
            llm_confidence=llm_confidence,
            news_items=news_items,
            social_data=social_data,
            action=action,
            confidence=confidence,
        )

        return Signal(
            symbol=f"{symbol}/USDT",
            timeframe="1h",
            action=action,
            confidence=round(confidence, 4),
            strength=round(sentiment_score, 4),
            source="sentiment",
            metadata={
                "sentiment_score": round(sentiment_score, 4),
                "llm_score": round(llm_score, 4),
                "llm_confidence": round(llm_confidence, 4),
                "news_count": len(news_items),
                "positive_count": positive_count,
                "negative_count": negative_count,
                "positive_ratio": round(news_ratio, 4),
                "social_volume": social_data.get("social_volume", 0),
                "social_sentiment": social_data.get("sentiment", 0.0),
                "bullish_pct": social_data.get("bullish_pct", 50.0),
                "bearish_pct": social_data.get("bearish_pct", 50.0),
                "llm_fallback": llm_failed,
            },
            reasoning=reasoning,
        )

    def _build_sentiment_reasoning(
        self,
        symbol: str,
        sentiment_score: float,
        llm_score: float,
        llm_confidence: float,
        news_items: list[dict[str, Any]],
        social_data: dict[str, Any],
        action: str,
        confidence: float,
    ) -> Reasoning:
        """Build structured reasoning for a sentiment signal.

        Args:
            symbol: Trading symbol.
            sentiment_score: Overall sentiment score (-1.0 to 1.0).
            llm_score: LLM-classified sentiment score.
            llm_confidence: LLM confidence in classification.
            news_items: List of news items analyzed.
            social_data: Social media sentiment data.
            action: Signal action (buy/sell/hold).
            confidence: Overall signal confidence.

        Returns:
            Reasoning object with structured factors and summary.
        """
        reasoning = Reasoning(
            agent="news_sentiment",
            confidence=confidence,
        )

        # LLM sentiment factor
        if llm_score != 0.0 or llm_confidence > 0:
            direction = "tích cực" if llm_score > 0 else "tiêu cực" if llm_score < 0 else "trung tính"
            reasoning.add_factor(ReasoningFactor(
                type="news",
                description=f"LLM đánh giá sentiment {direction} ({llm_score:+.2f}, độ tin cậy {llm_confidence:.0%})",
                impact=llm_score * 0.4,
                metadata={"llm_score": round(llm_score, 4), "llm_confidence": round(llm_confidence, 4)},
            ))

        # News ratio factor
        positive_count = sum(1 for n in news_items if n.get("sentiment", 0) > 0.1)
        negative_count = sum(1 for n in news_items if n.get("sentiment", 0) < -0.1)
        neutral_count = len(news_items) - positive_count - negative_count

        if positive_count > negative_count:
            reasoning.add_factor(ReasoningFactor(
                type="news",
                description=f"{positive_count}/{len(news_items)} tin tức tích cực, {negative_count} tiêu cực",
                impact=0.15,
                metadata={"positive": positive_count, "negative": negative_count, "neutral": neutral_count},
            ))
        elif negative_count > positive_count:
            reasoning.add_factor(ReasoningFactor(
                type="news",
                description=f"{negative_count}/{len(news_items)} tin tức tiêu cực, {positive_count} tích cực",
                impact=-0.15,
                metadata={"positive": positive_count, "negative": negative_count, "neutral": neutral_count},
            ))

        # Social volume factor
        social_vol = social_data.get("social_volume", 0)
        if social_vol > 0:
            reasoning.add_factor(ReasoningFactor(
                type="social",
                description=f"Khối lượng thảo luận xã hội: {social_vol}",
                impact=0.05 if social_vol > 1000 else 0.0,
                metadata={"social_volume": social_vol},
            ))

        # Social sentiment factor
        social_sent = social_data.get("sentiment", 0.0)
        if abs(social_sent) > 0.1:
            direction = "ủng hộ" if social_sent > 0 else "phản đối"
            reasoning.add_factor(ReasoningFactor(
                type="social",
                description=f"Cộng đồng {direction} ({social_sent:+.2f})",
                impact=social_sent * 0.1,
                metadata={"social_sentiment": round(social_sent, 4)},
            ))

        # Bullish/Bearish percentage
        bullish_pct = social_data.get("bullish_pct", 50.0)
        bearish_pct = social_data.get("bearish_pct", 50.0)
        if abs(bullish_pct - 50) > 10:
            reasoning.add_factor(ReasoningFactor(
                type="social",
                description=f"Tỷ lệ bullish/bearish: {bullish_pct:.0f}%/{bearish_pct:.0f}%",
                impact=(bullish_pct - 50) / 100 * 0.1,
                metadata={"bullish_pct": bullish_pct, "bearish_pct": bearish_pct},
            ))

        # Build summary
        direction_word = "tích cực" if sentiment_score > 0 else "tiêu cực" if sentiment_score < 0 else "trung tính"
        reasoning.summary = (
            f"Phân tích sentiment {direction_word} cho {symbol}: "
            f"điểm tổng {sentiment_score:+.2f}, "
            f"{len(news_items)} tin tức ({positive_count} tích cực, {negative_count} tiêu cực), "
            f"cộng đồng {bullish_pct:.0f}% ủng hộ."
        )

        return reasoning

    async def run(self) -> list[Signal]:
        """Analyze sentiment for all configured symbols.

        Returns:
            List of Signal objects with sentiment analysis results.
        """
        all_signals: list[Signal] = []

        for symbol in self.symbols:
            try:
                signal = await self._analyze_symbol(symbol)
                if signal:
                    all_signals.append(signal)
                    self._logger.info(
                        "sentiment_signal_emitted",
                        symbol=symbol,
                        action=signal.action,
                        sentiment=signal.metadata.get("sentiment_score"),
                    )
            except Exception as exc:
                self._logger.error(
                    "symbol_analysis_failed",
                    symbol=symbol,
                    error=str(exc),
                )

        self._logger.info(
            "sentiment_cycle_complete",
            symbols_analyzed=len(self.symbols),
            signals_emitted=len(all_signals),
        )
        return all_signals
