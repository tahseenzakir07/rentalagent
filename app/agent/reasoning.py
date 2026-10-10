"""Reasoning trace module for recording auditable decision milestones.

Tracks transparent, observable reasoning steps and tool selection logic
without exposing raw token chains or unverified model internals.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.schemas.decision import ReasoningTraceEvent

logger = logging.getLogger(__name__)


class ReasoningTracer:
    """Collects chronological trace events for a single inquiry lifecycle."""

    def __init__(self, inquiry_id: str):
        self.inquiry_id = inquiry_id
        self._events: List[ReasoningTraceEvent] = []

    def log_event(
        self,
        event_type: str,
        explanation: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReasoningTraceEvent:
        """Record an auditable milestone event."""
        event = ReasoningTraceEvent(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            explanation=explanation,
            metadata=metadata or {},
        )
        self._events.append(event)
        logger.debug("[%s] %s: %s", self.inquiry_id, event_type, explanation)
        return event

    def get_events(self) -> List[ReasoningTraceEvent]:
        """Return the collected chronological trace events."""
        return list(self._events)
