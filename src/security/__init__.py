"""Security module — prompt injection detection, input sanitization,
and agent security middleware for FKCrypto.

Inspired by OpenClaw security best practices:
- Detect hidden instructions in external content
- Sanitize inputs before LLM processing
- Contain blast radius when injection occurs
- Least privilege for agent permissions
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class ThreatLevel(Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityResult:
    """Result of a security scan on input content."""

    passed: bool
    threat_level: ThreatLevel = ThreatLevel.SAFE
    threats_found: list[str] = field(default_factory=list)
    sanitized_content: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ── Prompt Injection Patterns ────────────────────────────────────────────

# Common prompt injection patterns from real-world attacks
INJECTION_PATTERNS = [
    # Direct instruction override
    (r"(?i)ignore\s+(your\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules|directives)", "instruction_override"),
    (r"(?i)disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)", "instruction_override"),
    (r"(?i)forget\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)", "instruction_override"),

    # Role/identity manipulation
    (r"(?i)you\s+are\s+(now|actually)\s+(a|an)\s+(new\s+)?(role|assistant|system|admin|developer)", "role_manipulation"),
    (r"(?i)system\s*(override|prompt|instruction|message)\s*:", "role_manipulation"),
    (r"(?i)\[system\]\s*:", "role_manipulation"),
    (r"(?i)\[system\s+override\]", "role_manipulation"),
    (r"(?i)\[developer\s+mode\]", "role_manipulation"),
    (r"(?i)\[admin\s+mode\]", "role_manipulation"),

    # Data exfiltration attempts
    (r"(?i)(send|forward|email|post|upload)\s+(your|the)\s+(config|settings|keys|credentials|secrets|tokens|passwords|api_key|\.env)", "data_exfiltration"),
    (r"(?i)(read|find|locate|search)\s+(all\s+)?(files|directories|\.env|config|credentials|keys|secrets)", "data_exfiltration"),
    (r"(?i)(dump|export|leak|expose)\s+(your|the)\s+(memory|context|history|config|files|keys)", "data_exfiltration"),

    # Command injection
    (r"(?i)(execute|run|perform)\s+(this|the\s+following)\s+(command|code|script|instruction)", "command_injection"),
    (r"(?i)new\s+(first\s+)?(priority|goal|objective|rule|instruction)\s*(is|:)", "command_injection"),
    (r"(?i)your\s+(new\s+)?(task|mission|objective)\s+(is|:)", "command_injection"),

    # Hidden content markers (white-on-white, tiny font, etc.)
    (r"(?i)(color|font|size)\s*[:=]\s*(white|transparent|0px|hidden|invisible)", "hidden_content"),
    (r"(?i)(display|visibility)\s*[:=]\s*(none|hidden)", "hidden_content"),
    (r"(?i)<!--.*?-->", "hidden_content"),  # HTML comments with hidden text
    (r"(?i)<span[^>]*style[^>]*>[^<]*</span>", "hidden_content"),  # Empty spans

    # Jailbreak patterns
    (r"(?i)(dan|jailbreak|bypass|circumvent)\s+(safety|filter|restriction|guard|limit)", "jailbreak"),
    (r"(?i)act\s+as\s+(if\s+)?(you\s+(can|were|are)\s+)?(unrestricted|unfiltered|uncensored)", "jailbreak"),
    (r"(?i)bypass\s+(all\s+)?(safety|filter|restriction|guard|limit)", "jailbreak"),

    # Social engineering
    (r"(?i)this\s+(is|was)\s+(a|an)\s+(test|simulation|exercise|drill|debug)", "social_engineering"),
    (r"(?i)pretend\s+(to\s+)?(be|you\s+are)\s+(a|an)\s+(different|new|another)", "social_engineering"),
]

# Suspicious patterns that warrant extra scrutiny
SUSPICIOUS_PATTERNS = [
    (r"(?i)(please|important|urgent|critical)\s+(do|execute|follow)\s+(this|the)", "urgent_manipulation"),
    (r"(?i)do\s+not\s+(tell|inform|notify|share)\s+(the|a|any)\s+(user|human|operator|admin)", "secrecy_instruction"),
    (r"(?i)keep\s+(this|your|the)\s+(secret|hidden|quiet|silent|confidential)", "secrecy_instruction"),
    (r"(?i)never\s+(mention|reveal|disclose|tell|say)", "secrecy_instruction"),
]

# Compiled patterns for performance
_COMPILED_INJECTIONS = [(re.compile(p), label) for p, label in INJECTION_PATTERNS]
_COMPILED_SUSPICIOUS = [(re.compile(p), label) for p, label in SUSPICIOUS_PATTERNS]


# ── Detection Engine ─────────────────────────────────────────────────────

def detect_prompt_injection(content: str) -> SecurityResult:
    """Scan content for prompt injection patterns.

    Args:
        content: Text to scan (news headlines, tweets, emails, etc.)

    Returns:
        SecurityResult with threat assessment and sanitized content.
    """
    if not content:
        return SecurityResult(passed=True)

    threats: list[str] = []
    suspicious: list[str] = []

    # Check injection patterns
    for pattern, label in _COMPILED_INJECTIONS:
        if pattern.search(content):
            threats.append(f"{label}: {pattern.pattern[:50]}...")

    # Check suspicious patterns
    for pattern, label in _COMPILED_SUSPICIOUS:
        if pattern.search(content):
            suspicious.append(f"{label}: {pattern.pattern[:50]}...")

    # Determine threat level
    threat_count = len(threats)
    suspicious_count = len(suspicious)

    if threat_count >= 3:
        threat_level = ThreatLevel.CRITICAL
    elif threat_count >= 2:
        threat_level = ThreatLevel.HIGH
    elif threat_count >= 1:
        threat_level = ThreatLevel.MEDIUM
    elif suspicious_count >= 2:
        threat_level = ThreatLevel.LOW
    else:
        threat_level = ThreatLevel.SAFE

    passed = threat_level in (ThreatLevel.SAFE, ThreatLevel.LOW)

    # Sanitize content
    sanitized = _sanitize_content(content, threats)

    return SecurityResult(
        passed=passed,
        threat_level=threat_level,
        threats_found=threats + suspicious,
        sanitized_content=sanitized,
        details={
            "injection_count": threat_count,
            "suspicious_count": suspicious_count,
            "content_length": len(content),
        },
    )


def _sanitize_content(content: str, threats: list[str]) -> str:
    """Remove or neutralize detected injection patterns from content.

    Args:
        content: Original content.
        threats: List of detected threat descriptions.

    Returns:
        Sanitized content with injection patterns removed.
    """
    sanitized = content

    # Remove HTML comments (common hidden content vector)
    sanitized = re.sub(r"<!--.*?-->", "", sanitized, flags=re.DOTALL)

    # Remove hidden spans
    sanitized = re.sub(
        r"<span[^>]*style[^>]*>[^<]*</span>",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Remove common injection markers
    sanitized = re.sub(
        r"\[(system|developer|admin)\s*(override|mode|instruction|message)?\s*\]",
        "[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\[(system|developer|admin)\s*(override|mode|instruction|message)?\]\s*:",
        "[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Truncate if extremely long (prevent context flooding)
    max_length = 5000
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "...[truncated]"

    return sanitized.strip()


# ── Input Sanitization ───────────────────────────────────────────────────

def sanitize_for_llm(content: str) -> str:
    """Sanitize external content before passing to LLM.

    This is the LAST LINE OF DEFENSE before LLM processing.
    All external content (news, tweets, emails, web pages) MUST
    pass through this function.

    Args:
        content: Raw external content.

    Returns:
        Sanitized content safe for LLM processing.
    """
    if not content:
        return ""

    # Step 1: Remove HTML entirely (we don't need formatting)
    sanitized = re.sub(r"<[^>]+>", "", content)

    # Step 2: Remove control characters
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", sanitized)

    # Step 3: Normalize whitespace
    sanitized = re.sub(r"\s+", " ", sanitized)

    # Step 4: Truncate to prevent context flooding
    max_length = 3000
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "...[truncated]"

    return sanitized.strip()


def sanitize_news_headlines(headlines: list[str]) -> list[str]:
    """Sanitize a list of news headlines for safe LLM processing.

    Args:
        headlines: Raw news headlines.

    Returns:
        Filtered and sanitized headlines.
    """
    safe_headlines: list[str] = []
    for headline in headlines:
        result = detect_prompt_injection(headline)
        if result.threat_level in (ThreatLevel.SAFE, ThreatLevel.LOW):
            safe_headlines.append(sanitize_for_llm(headline))
        else:
            logger.warning(
                "injection_detected_in_headline",
                threat_level=result.threat_level.value,
                threats=result.threats_found[:3],
            )
    return safe_headlines


# ── Security Middleware ──────────────────────────────────────────────────

class SecurityMiddleware:
    """Security middleware for agent input/output.

    Wraps agent operations with security checks:
    - Input sanitization before LLM calls
    - Output validation before execution
    - Rate limiting on security alerts
    - Audit logging of security events
    """

    def __init__(
        self,
        max_injection_alerts_per_hour: int = 10,
        auto_block_threat_level: ThreatLevel = ThreatLevel.HIGH,
    ) -> None:
        self.max_alerts_per_hour = max_injection_alerts_per_hour
        self.auto_block_level = auto_block_threat_level
        self._alert_count: int = 0
        self._blocked_sources: set[str] = set()

    def check_input(self, content: str, source: str = "unknown") -> SecurityResult:
        """Check input content for security threats.

        Args:
            content: Input content to check.
            source: Source of the content (for logging).

        Returns:
            SecurityResult with assessment.
        """
        result = detect_prompt_injection(content)

        if result.threat_level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL):
            self._alert_count += 1
            self._blocked_sources.add(source)

            logger.warning(
                "security_alert",
                source=source,
                threat_level=result.threat_level.value,
                threats=result.threats_found[:3],
                total_alerts=self._alert_count,
            )

            if self._alert_count >= self.max_alerts_per_hour:
                logger.critical(
                    "security_rate_limit_exceeded",
                    source=source,
                    alerts=self._alert_count,
                )

        return result

    def is_source_blocked(self, source: str) -> bool:
        """Check if a source has been blocked due to security alerts."""
        return source in self._blocked_sources

    def unblock_source(self, source: str) -> None:
        """Manually unblock a source."""
        self._blocked_sources.discard(source)
        logger.info("source_unblocked", source=source)

    def get_blocked_sources(self) -> list[str]:
        """Get list of currently blocked sources."""
        return list(self._blocked_sources)

    def reset_alerts(self) -> None:
        """Reset alert counter (call hourly)."""
        self._alert_count = 0

    def wrap_llm_input(self, content: str, source: str = "unknown") -> str:
        """Wrap LLM input with full security pipeline.

        Pipeline: detect → sanitize → return safe content.
        If threats are too severe, returns empty string.

        Args:
            content: Raw external content.
            source: Content source identifier.

        Returns:
            Safe content for LLM, or empty string if blocked.
        """
        # Check if source is blocked
        if self.is_source_blocked(source):
            logger.warning("blocked_source_attempt", source=source)
            return ""

        # Scan for injections
        result = self.check_input(content, source)

        # Auto-block high threats
        if result.threat_level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL):
            logger.warning(
                "auto_blocked_content",
                source=source,
                threat_level=result.threat_level.value,
            )
            return ""

        # Sanitize and return
        return sanitize_for_llm(result.sanitized_content)
