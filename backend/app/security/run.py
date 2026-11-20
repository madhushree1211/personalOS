from __future__ import annotations

import json

from ..db import SessionLocal
from .engine import evaluate
from .loader import load_rules
from .source import read_audit_events


def main() -> None:
    db = SessionLocal()
    try:
        events = read_audit_events(db)
        alerts = evaluate(load_rules(), events)
        print(json.dumps([alert.model_dump(mode="json") for alert in alerts], indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
