from fastapi import Depends
from sqlalchemy.orm import Session

from fastapi import APIRouter

from ..auth import require_permission
from ..db import get_db
from .loader import load_rules
from .engine import evaluate
from .source import read_audit_events


router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/alerts")
def security_alerts(
    db: Session = Depends(get_db),
    user=Depends(require_permission("audit.read")),
) -> dict:
    events = read_audit_events(db, owner_id=user.id)
    alerts = evaluate(load_rules(), events)
    return {"alerts": [alert.model_dump(mode="json") for alert in alerts]}
