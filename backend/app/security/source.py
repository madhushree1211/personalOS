from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditEntry


def read_audit_events(db: Session, owner_id: str | None = None) -> list[dict[str, Any]]:
    """Read audit entries and convert them into engine events. Read-only."""
    query = select(AuditEntry)
    if owner_id is not None:
        query = query.where(AuditEntry.user_id == owner_id)
    entries = list(db.scalars(query.order_by(AuditEntry.timestamp.asc())))

    events: list[dict[str, Any]] = []
    for entry in entries:
        details = dict(entry.details or {})
        events.append({
            "event": entry.event,
            "timestamp": entry.timestamp,
            "user_id": entry.user_id,
            "ip": details.get("ip") or details.get("client_ip"),
            "details": details,
        })
    return events
