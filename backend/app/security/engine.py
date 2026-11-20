from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Iterable

from pydantic import BaseModel, Field


class Mitre(BaseModel):
    technique_id: str
    technique_name: str
    note: str = ""


class Alert(BaseModel):
    rule_id: str
    severity: str
    group_key: str
    count: int
    first_seen: datetime
    last_seen: datetime
    mitre: Mitre


def _value(event: Any, name: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


def _timestamp(event: Any) -> datetime:
    value = _value(event, "timestamp", _value(event, "ts"))
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Every event must have a timestamp or ts field")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _group_key(event: Any, group_by: str) -> str:
    if group_by == "ip":
        value = _value(event, "ip")
        if value is None:
            details = _value(event, "details", {}) or {}
            value = details.get("ip") or details.get("client_ip")
        return str(value or "unknown")
    value = _value(event, "user_id")
    if value is None:
        details = _value(event, "details", {}) or {}
        value = details.get("user_id")
    return str(value or "unknown")


def evaluate(rules: Iterable[Any], events: Iterable[Any]) -> list[Alert]:
    """Evaluate detection rules without reading from or mutating input storage."""
    event_list = list(events)
    alerts: list[Alert] = []

    for rule in rules:
        rule_event = getattr(rule, "event", None) if not isinstance(rule, dict) else rule["event"]
        rule_id = getattr(rule, "id", None) if not isinstance(rule, dict) else rule["id"]
        severity = getattr(rule, "severity", None) if not isinstance(rule, dict) else rule["severity"]
        group_by = getattr(rule, "group_by", None) if not isinstance(rule, dict) else rule["group_by"]
        threshold = getattr(rule, "threshold", None) if not isinstance(rule, dict) else rule["threshold"]
        window_seconds = getattr(rule, "window_seconds", None) if not isinstance(rule, dict) else rule["window_seconds"]
        mitre_value = getattr(rule, "mitre", None) if not isinstance(rule, dict) else rule["mitre"]
        mitre = Mitre.model_validate(mitre_value) if isinstance(mitre_value, dict) else mitre_value

        grouped: dict[str, list[Any]] = defaultdict(list)
        for event in event_list:
            event_name = _value(event, "event")
            if event_name == rule_event:
                grouped[_group_key(event, group_by)].append(event)

        for group_key, group_events in grouped.items():
            ordered = sorted(group_events, key=_timestamp)
            window: deque[Any] = deque()
            emitted = False
            for event in ordered:
                now = _timestamp(event)
                while window and (now - _timestamp(window[0])).total_seconds() > window_seconds:
                    window.popleft()
                window.append(event)
                if not emitted and len(window) >= threshold:
                    timestamps = [_timestamp(item) for item in window]
                    alerts.append(Alert(
                        rule_id=rule_id,
                        severity=severity,
                        group_key=group_key,
                        count=len(window),
                        first_seen=min(timestamps),
                        last_seen=max(timestamps),
                        mitre=mitre,
                    ))
                    emitted = True
    return alerts
