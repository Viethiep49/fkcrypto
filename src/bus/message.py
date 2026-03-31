"""Message schema for the pub/sub message bus."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class Message:
    """A message published on the bus connecting FKCrypto agents.

    Messages are immutable once created and carry a correlation_id
    for tracing across the signal → decision → execution pipeline.
    """

    topic: str
    payload: dict[str, Any]
    source: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = field(default_factory=lambda: uuid4().hex)

    def to_json(self) -> str:
        """Serialize the message to a JSON string."""
        return json.dumps(
            {
                "topic": self.topic,
                "payload": self.payload,
                "source": self.source,
                "timestamp": self.timestamp.isoformat(),
                "correlation_id": self.correlation_id,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> Message:
        """Deserialize a Message from a JSON string."""
        data = json.loads(raw)
        ts = data.get("timestamp")
        if isinstance(ts, str):
            data["timestamp"] = datetime.fromisoformat(ts)
        return cls(
            topic=data["topic"],
            payload=data["payload"],
            source=data["source"],
            timestamp=data.get("timestamp", datetime.now(timezone.utc)),
            correlation_id=data.get("correlation_id", uuid4().hex),
        )
