"""Gateway entry point — starts the LangGraph orchestrator."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import structlog

from src.agents.analyst import TechnicalAnalystAgent
from src.agents.decision_engine import DecisionEngine
from src.agents.market_monitor import MarketMonitorAgent
from src.agents.news_sentiment import NewsSentimentAgent
from src.agents.risk_guardian import RiskGuardianAgent
from src.data.ccxt_source import CCXTSource
from src.data.news import NewsSource
from src.data.social import SocialSource
from src.execution.service import ExecutionService
from src.freqtrade_client.client import FreqtradeClient
from src.gateway.graph import create_app
from src.gateway.nodes import (
    make_analyst_node,
    make_decision_node,
    make_execution_node,
    make_market_monitor_node,
    make_risk_node,
    make_sentiment_node,
)
from src.llm.litellm_gateway import LLMGateway
from src.risk.engine import RiskEngine
from src.utils.config import load_config
from src.utils.notifications import Notifier
from src.utils.scheduler import TaskScheduler

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)
logger = structlog.get_logger(__name__)


class FKCryptoApp:
    """Main application that wires all components together."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._data_source: CCXTSource | None = None
        self._market_monitor: MarketMonitorAgent | None = None
        self._analyst: TechnicalAnalystAgent | None = None
        self._sentiment: NewsSentimentAgent | None = None
        self._risk_guardian: RiskGuardianAgent | None = None
        self._decision_engine: DecisionEngine | None = None
        self._execution_service: ExecutionService | None = None
        self._freqtrade_client: FreqtradeClient | None = None
        self._llm_gateway: LLMGateway | None = None
        self._risk_engine: RiskEngine | None = None
        self._notifier: Notifier | None = None
        self._scheduler = TaskScheduler()
        self._repository = None

    def _init_components(self) -> None:
        """Initialize all system components."""
        pairs = self.config.get("trading", {}).get("pairs", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

        # Data source
        self._data_source = CCXTSource(self.config.get("data_sources", {}))

        # LLM Gateway
        self._llm_gateway = LLMGateway(self.config)

        # Database repository
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.database.models import Base
        from src.database.repository import Repository

        db_cfg = self.config.get("database", {})
        db_url = db_cfg.get("url", "sqlite:///fkcrypto.db")
        engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        self._repository = Repository(session_factory())

        # Agents — inject data source into config
        agent_config = {**self.config, "data_source": self._data_source, "pairs": pairs}

        self._market_monitor = MarketMonitorAgent(agent_config)
        self._analyst = TechnicalAnalystAgent(agent_config)

        # News & sentiment agents
        news_config = {**self.config, "pairs": [p.split("/")[0] for p in pairs]}
        news_source = NewsSource(self.config.get("data_sources", {}))
        social_source = SocialSource(self.config.get("data_sources", {}))
        news_config["news_source"] = news_source
        news_config["social_source"] = social_source
        news_config["llm_gateway"] = self._llm_gateway
        self._sentiment = NewsSentimentAgent(news_config)

        # Risk Guardian
        risk_config = {**self.config, "data_source": self._data_source, "pairs": pairs}
        self._risk_guardian = RiskGuardianAgent(risk_config)

        # Decision Engine
        self._decision_engine = DecisionEngine(
            config=self.config,
            llm_gateway=self._llm_gateway,
            repository=self._repository,
        )

        # Risk Engine (for execution validation)
        self._risk_engine = RiskEngine(
            config=self.config,
            repository=self._repository,
        )

        # Freqtrade Client
        exec_cfg = self.config.get("execution", {})
        self._freqtrade_client = FreqtradeClient(
            base_url=exec_cfg.get("freqtrade_url", "http://freqtrade:8080"),
            api_key=exec_cfg.get("freqtrade_api_key", ""),
        )

        # Execution Service
        self._execution_service = ExecutionService(
            config=self.config,
            risk_engine=self._risk_engine,
            freqtrade_client=self._freqtrade_client,
            repository=self._repository,
        )

        # Notifier
        self._notifier = Notifier(self.config)

        logger.info("all_components_initialized")

    def _build_graph(self):
        """Build LangGraph with wired agent nodes."""
        node_fns = {
            "market_monitor": make_market_monitor_node(self._market_monitor),
            "analyst": make_analyst_node(self._analyst),
            "sentiment": make_sentiment_node(self._sentiment),
            "risk": make_risk_node(self._risk_guardian),
            "decision": make_decision_node(self._decision_engine),
            "execution": make_execution_node(self._execution_service),
        }
        return create_app(node_fns)

    def _schedule_tasks(self) -> None:
        """Set up scheduled analysis runs."""
        schedule_cfg = self.config.get("schedule", {})

        # Analyst schedule (default: every 15 minutes)
        analyst_cron = schedule_cfg.get("analyst", "*/15 * * * *")
        parts = analyst_cron.split()
        if len(parts) == 5:
            self._scheduler.schedule_cron(
                self._run_analysis_cycle,
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
            )

        # News sentiment schedule (default: every hour)
        news_cron = schedule_cfg.get("news", "0 * * * *")
        parts = news_cron.split()
        if len(parts) == 5:
            self._scheduler.schedule_cron(
                self._run_sentiment_cycle,
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
            )

        # Risk check interval (default: every 30 seconds)
        risk_interval = schedule_cfg.get("risk_check_interval_sec", 30)
        self._scheduler.schedule_interval(
            self._run_risk_cycle,
            seconds=risk_interval,
        )

        logger.info("scheduled_tasks_configured")

    async def _run_analysis_cycle(self) -> None:
        """Run a full analysis cycle through LangGraph."""
        pairs = self.config.get("trading", {}).get("pairs", ["BTC/USDT"])

        for symbol in pairs:
            try:
                initial_state = {
                    "symbol": symbol,
                    "signals": [],
                    "score": 0.0,
                    "decision": "hold",
                    "confidence": 0.0,
                    "kill_switch_active": False,
                    "kill_switch_reason": "",
                    "portfolio_value": 0.0,
                    "positions": [],
                    "errors": [],
                    "retry_count": 0,
                    "execution_result": {},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                }

                app = self._build_graph()
                result = await app.ainvoke(initial_state)

                if result.get("decision") in ("buy", "sell"):
                    exec_result = result.get("execution_result", {})
                    if self._notifier:
                        await self._notifier.send_trade(
                            symbol=symbol,
                            action=result["decision"],
                            score=result.get("score", 0.0),
                            confidence=result.get("confidence", 0.0),
                            order_id=exec_result.get("order_id", ""),
                        )

                if result.get("kill_switch_active"):
                    if self._notifier:
                        await self._notifier.send_kill_switch(
                            result.get("kill_switch_reason", "unknown")
                        )

            except Exception as exc:
                logger.error(
                    "analysis_cycle_failed",
                    symbol=symbol,
                    error=str(exc),
                )

    async def _run_sentiment_cycle(self) -> None:
        """Run sentiment analysis cycle."""
        if not self._sentiment:
            return
        try:
            signals = await self._sentiment.run()
            logger.info(
                "sentiment_cycle_complete",
                signals=len(signals),
            )
        except Exception as exc:
            logger.error("sentiment_cycle_failed", error=str(exc))

    async def _run_risk_cycle(self) -> None:
        """Run risk check cycle."""
        if not self._risk_guardian:
            return
        try:
            signals = await self._risk_guardian.run()
            if self._risk_guardian.is_kill_switch_active and self._notifier:
                await self._notifier.send_kill_switch(
                    self._risk_guardian.kill_switch_reason or "unknown"
                )
        except Exception as exc:
            logger.error("risk_cycle_failed", error=str(exc))

    async def start(self) -> None:
        """Start the FKCrypto trading system."""
        logger.info("FKCrypto starting...")

        self._init_components()
        self._scheduler.start()
        self._schedule_tasks()

        # Start continuous monitors
        if self._market_monitor:
            await self._market_monitor.start_monitoring()

        if self._risk_guardian:
            await self._risk_guardian.start_monitoring()

        logger.info("FKCrypto ready — all systems operational")

        # Keep running
        try:
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("shutdown_requested")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully shut down all components."""
        logger.info("shutting_down...")

        await self._scheduler.stop()

        if self._market_monitor:
            await self._market_monitor.stop()
        if self._risk_guardian:
            await self._risk_guardian.stop()
        if self._data_source:
            await self._data_source.stop()
        if self._freqtrade_client:
            await self._freqtrade_client.close()

        logger.info("shutdown_complete")


async def main() -> None:
    """Entry point."""
    config = load_config()
    if not config:
        raise RuntimeError("No configuration loaded. Check config/default.yaml and .env")

    app = FKCryptoApp(config)
    await app.start()


if __name__ == "__main__":
    asyncio.run(main())
