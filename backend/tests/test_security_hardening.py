import os

import pytest
from fastapi.testclient import TestClient

from app.approval import ApprovalState, transition, verify_mfa
from app.config import cors_middleware_options, get_settings
from app.db import SessionLocal
from app.main import app
from app.models import InvestmentApproval, User

client = TestClient(app)


def test_startup_rejects_missing_or_short_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    original_env = os.environ.get("ENV")
    original_secret = os.environ.get("JWT_SECRET")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DEMO_PASSWORD", "test-demo-password")
    try:
        monkeypatch.setenv("JWT_SECRET", "short")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="JWT_SECRET"):
            get_settings()

        monkeypatch.delenv("JWT_SECRET", raising=False)
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="JWT_SECRET"):
            get_settings()
    finally:
        get_settings.cache_clear()
        if original_env is None:
            os.environ.pop("ENV", None)
        else:
            os.environ["ENV"] = original_env
        if original_secret is None:
            os.environ.pop("JWT_SECRET", None)
        else:
            os.environ["JWT_SECRET"] = original_secret


def test_cors_wildcard_never_combines_with_credentials() -> None:
    options = cors_middleware_options(["*"])
    assert options["allow_origins"] == ["*"]
    assert options["allow_credentials"] is False


def test_login_rate_limit_returns_429() -> None:
    email = "limited-rate@personalos.ai"
    for _ in range(5):
        response = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
        assert response.status_code == 401
    response = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    assert response.status_code == 429


def test_old_development_bearer_token_is_rejected() -> None:
    response = client.get(
        "/api/renewals",
        headers={"Authorization": "Bearer legacy-development-bearer-token"},
    )
    assert response.status_code == 401


def pending_approval() -> InvestmentApproval:
    return InvestmentApproval(
        id="mfa-test-approval",
        proposal_id="mfa-test-proposal",
        owner_id="mfa-test-owner",
        requested_by="mfa-test-owner",
        status=ApprovalState.PENDING_USER.value,
    )


def test_mfa_wrong_code_is_rejected() -> None:
    approval = pending_approval()
    transition(approval, ApprovalState.PENDING_MFA, user_id="mfa-test-owner")
    with pytest.raises(Exception) as exc:
        verify_mfa(approval, user_id="mfa-test-owner", code="999999")
    assert getattr(exc.value, "status_code", None) == 403
    assert approval.mfa_failed_attempts == 1


def test_mfa_expired_code_is_rejected() -> None:
    approval = pending_approval()
    transition(approval, ApprovalState.PENDING_MFA, user_id="mfa-test-owner")
    approval.mfa_expires_at = approval.mfa_expires_at.__class__.fromtimestamp(0)
    with pytest.raises(Exception) as exc:
        verify_mfa(approval, user_id="mfa-test-owner", code="123456")
    assert getattr(exc.value, "status_code", None) == 403


def test_mfa_code_is_single_use() -> None:
    approval = pending_approval()
    transition(approval, ApprovalState.PENDING_MFA, user_id="mfa-test-owner")
    code = __import__("app.approval", fromlist=["get_test_mfa_code"]).get_test_mfa_code(approval.id)
    verify_mfa(approval, user_id="mfa-test-owner", code=code)
    assert approval.mfa_used is True
    assert approval.status == ApprovalState.APPROVED.value
    with pytest.raises(Exception) as exc:
        verify_mfa(approval, user_id="mfa-test-owner", code=code)
    assert getattr(exc.value, "status_code", None) == 409


def test_mfa_lockout_after_five_failures() -> None:
    approval = pending_approval()
    transition(approval, ApprovalState.PENDING_MFA, user_id="mfa-test-owner")
    for attempt in range(5):
        with pytest.raises(Exception) as exc:
            verify_mfa(approval, user_id="mfa-test-owner", code="999998" if attempt < 4 else "999999")
        assert getattr(exc.value, "status_code", None) in (403, 423)
    assert approval.mfa_failed_attempts >= 5
