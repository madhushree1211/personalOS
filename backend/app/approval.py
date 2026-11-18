import hashlib
import hmac
import secrets
import sys
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from fastapi import HTTPException

from .config import get_settings
from .models import InvestmentApproval


class ApprovalState(StrEnum):
    PENDING_USER = "pending_user"
    PENDING_MFA = "pending_mfa"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


_TRANSITIONS = {
    ApprovalState.PENDING_USER: {ApprovalState.PENDING_MFA, ApprovalState.REJECTED},
    ApprovalState.PENDING_MFA: {ApprovalState.APPROVED, ApprovalState.REJECTED},
    ApprovalState.APPROVED: {ApprovalState.EXECUTED},
    ApprovalState.REJECTED: set(),
    ApprovalState.EXECUTED: set(),
}

_TEST_MFA_CODES: dict[str, str] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _issue_mfa_code(approval: InvestmentApproval) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    approval.mfa_code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    approval.mfa_expires_at = _now() + timedelta(minutes=5)
    approval.mfa_used = False
    approval.mfa_failed_attempts = 0

    settings = get_settings()
    if settings.environment.lower() == "dev":
        sys.stdout.write(f"Development MFA code for approval {approval.id}: {code}\n")
        sys.stdout.flush()
    elif settings.environment.lower() == "test":
        _TEST_MFA_CODES[approval.id] = code
    return code


def get_test_mfa_code(approval_id: str) -> str:
    """Test-only accessor; never called by API routes."""
    if get_settings().environment.lower() != "test":
        raise RuntimeError("test MFA codes are available only in ENV=test")
    try:
        return _TEST_MFA_CODES[approval_id]
    except KeyError as exc:
        raise KeyError("No test MFA code is available for that approval") from exc


def transition(approval: InvestmentApproval, target: ApprovalState, *, user_id: str):
    current = ApprovalState(approval.status)
    if target not in _TRANSITIONS[current]:
        raise HTTPException(
            409,
            detail={"code": "invalid_approval_transition", "from": current.value, "to": target.value},
        )
    now = _now()
    approval.status = target.value
    approval.updated_at = now
    if target is ApprovalState.PENDING_MFA:
        approval.approved_by = None
        _issue_mfa_code(approval)
    elif target is ApprovalState.APPROVED:
        approval.approved_by, approval.approved_at = user_id, now
    elif target is ApprovalState.REJECTED:
        approval.rejected_at = now
    elif target is ApprovalState.EXECUTED:
        approval.executed_at = now
    return approval


def verify_mfa(approval: InvestmentApproval, *, user_id: str, code: str | None = None):
    if approval.owner_id != user_id:
        raise HTTPException(404, "Investment approval not found")
    if ApprovalState(approval.status) is not ApprovalState.PENDING_MFA:
        raise HTTPException(409, detail={"code": "mfa_not_expected", "state": approval.status})
    if approval.mfa_failed_attempts >= 5:
        raise HTTPException(423, detail={"code": "mfa_locked", "mfa_required": True})
    if approval.mfa_used:
        raise HTTPException(403, detail={"code": "mfa_code_already_used", "mfa_required": True})
    if approval.mfa_expires_at is None or approval.mfa_expires_at <= _now():
        raise HTTPException(403, detail={"code": "mfa_code_expired", "mfa_required": True})
    if not approval.mfa_code_hash or not code:
        raise HTTPException(403, detail={"code": "mfa_verification_failed", "mfa_required": True})

    supplied_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(supplied_hash, approval.mfa_code_hash):
        approval.mfa_failed_attempts += 1
        if approval.mfa_failed_attempts >= 5:
            raise HTTPException(423, detail={"code": "mfa_locked", "mfa_required": True})
        raise HTTPException(403, detail={"code": "mfa_verification_failed", "mfa_required": True})

    approval.mfa_used = True
    approval.mfa_verified_at = _now()
    transition(approval, ApprovalState.APPROVED, user_id=user_id)
    return approval
