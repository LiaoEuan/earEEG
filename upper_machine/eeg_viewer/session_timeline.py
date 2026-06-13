"""Session timeline — unified event recording for earEEG experiments."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TimelineEvent:
    event_id: str
    type: str
    time_monotonic: float
    session_time: float | None
    wall_time: str
    source: str
    payload: dict = field(default_factory=dict)


class SessionTimeline:
    def __init__(self) -> None:
        self._events: list[TimelineEvent] = []
        self._session_id: str = ""
        self._start_monotonic: float | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    def start_session(self, session_id: str, start_monotonic: float | None = None) -> None:
        self._session_id = session_id
        self._start_monotonic = start_monotonic if start_monotonic is not None else time.monotonic()

    def stop_session(self, stop_monotonic: float | None = None) -> None:
        pass

    def add_event(self, event_type: str, source: str = "viewer", payload: dict | None = None, now: float | None = None) -> TimelineEvent:
        t = now if now is not None else time.monotonic()
        session_time = (t - self._start_monotonic) if self._start_monotonic is not None else None
        event = TimelineEvent(
            event_id=uuid.uuid4().hex[:12],
            type=event_type,
            time_monotonic=t,
            session_time=round(session_time, 3) if session_time is not None else None,
            wall_time=datetime.now(timezone.utc).isoformat(),
            source=source,
            payload=payload or {},
        )
        self._events.append(event)
        return event

    def add_trigger(self, label: str, payload: dict | None = None, now: float | None = None) -> TimelineEvent:
        p = {"label": label}
        if payload:
            p.update(payload)
        return self.add_event("trigger_marker", source="keyboard", payload=p, now=now)

    def add_feedback(self, feedback: str, target: str = "current_audio", payload: dict | None = None, now: float | None = None) -> TimelineEvent:
        p = {"feedback": feedback, "target": target}
        if payload:
            p.update(payload)
        return self.add_event("user_feedback", source="viewer", payload=p, now=now)

    def get_events(self) -> list[dict]:
        return [self._event_to_dict(e) for e in self._events]

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        return [self._event_to_dict(e) for e in self._events[-limit:]]

    def clear(self) -> None:
        self._events.clear()
        self._session_id = ""
        self._start_monotonic = None

    def export_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"sessionId": self._session_id, "version": 1, "events": self.get_events()}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def _event_to_dict(event: TimelineEvent) -> dict:
        return {
            "eventId": event.event_id,
            "type": event.type,
            "timeMonotonic": round(event.time_monotonic, 3),
            "sessionTime": event.session_time,
            "wallTime": event.wall_time,
            "source": event.source,
            "payload": event.payload,
        }
