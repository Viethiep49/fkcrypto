"""LiteLLM unified LLM gateway for FKCrypto."""

from __future__ import annotations

import json
import time
from typing import Any

import litellm
import structlog

litellm.set_verbose = False
logger = structlog.get_logger()


class LLMGateway:
    """Unified LLM gateway with fallback support."""

    def __init__(self, config: dict[str, Any]) -> None:
        llm_config = config.get("llm", {})
        self.provider = llm_config.get("provider", "openai")
        self.model = llm_config.get("model", "gpt-4o-mini")
        self.fallback_model = llm_config.get("fallback_model", "gpt-3.5-turbo")
        self.temperature = llm_config.get("temperature", 0.1)
        self.max_tokens = llm_config.get("max_tokens", 500)
        self.timeout = llm_config.get("timeout", 30)
        self.retries = llm_config.get("retries", 3)
        logger.info(
            "llm_gateway_initialized",
            provider=self.provider,
            model=self.model,
            fallback=self.fallback_model,
        )

    def _build_model_name(self, base_model: str) -> str:
        if base_model.startswith(("gpt-", "o1", "o3")):
            return base_model
        if base_model.startswith("claude"):
            return f"anthropic/{base_model}"
        if base_model.startswith("gemini"):
            return f"gemini/{base_model}"
        if base_model.startswith("llama") or base_model.startswith("mistral"):
            return f"openai/{base_model}"
        return base_model

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            code_lines = []
            in_code = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    code_lines.append(line)
            content = "\n".join(code_lines)
        return json.loads(content)

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        target_model = self._build_model_name(model or self.model)
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = litellm.completion(
                    model=target_model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                    timeout=self.timeout,
                )
                content = response.choices[0].message.content
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                logger.info(
                    "llm_call_success",
                    model=target_model,
                    attempt=attempt + 1,
                    tokens=usage,
                )
                return {"content": content, "usage": usage}
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_call_failed",
                    model=target_model,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)

        logger.warning(
            "llm_fallback_triggered",
            primary=target_model,
            fallback=self.fallback_model,
        )
        fallback_model = self._build_model_name(self.fallback_model)
        for attempt in range(self.retries):
            try:
                response = litellm.completion(
                    model=fallback_model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                    timeout=self.timeout,
                )
                content = response.choices[0].message.content
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                logger.info(
                    "llm_fallback_success",
                    model=fallback_model,
                    attempt=attempt + 1,
                )
                return {"content": content, "usage": usage}
            except Exception as exc:
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)

        logger.error("llm_all_attempts_failed", error=str(last_error))
        raise RuntimeError(f"LLM call failed after all retries and fallback: {last_error}")

    def classify_sentiment(self, text: str, symbol: str) -> float:
        system_prompt = (
            "You are a crypto sentiment classifier. "
            "Analyze the given text and return ONLY a JSON object with:\n"
            '{"sentiment": <float between -1.0 and 1.0>, "reason": "<brief explanation>"}\n'
            "-1.0 = extremely bearish, 0.0 = neutral, 1.0 = extremely bullish. "
            "Be concise and objective."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Symbol: {symbol}\n\nText to analyze:\n{text}"},
        ]

        result = self.chat_completion(messages, temperature=0.0, max_tokens=200)
        try:
            data = self._parse_json_response(result["content"])
            sentiment = float(data.get("sentiment", 0.0))
            sentiment = max(-1.0, min(1.0, sentiment))
            logger.info(
                "sentiment_classified",
                symbol=symbol,
                sentiment=sentiment,
                reason=data.get("reason", ""),
            )
            return sentiment
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("sentiment_parse_failed", error=str(exc))
            return 0.0

    def explain_decision(self, decision_dict: dict[str, Any]) -> str:
        system_prompt = (
            "You are a trading decision explainer. "
            "Given the decision data below, generate a clear, concise "
            "human-readable explanation of why this decision was made. "
            "Keep it under 200 words. Focus on the key factors."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Decision data:\n{json.dumps(decision_dict, indent=2)}"},
        ]

        result = self.chat_completion(messages, temperature=0.2, max_tokens=300)
        explanation = result["content"].strip()
        logger.info("decision_explained", symbol=decision_dict.get("symbol", "unknown"))
        return explanation
