from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from jose import jwt

from app.auth import hash_password
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import AuditEntry, Renewal, User
from app.security.engine import evaluate
from app.security.loader import load_rules
from app.security.source import read_audit_events


client = TestClient(app)


def make_token(user_id: str, jti: str) -> str:
    settings = get_settings()
    claims = {
        "sub": user_id,
        "jti": jti,
        "exp": datetime.now(timezone.utc).timestamp() + 3600,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def ensure_user(user_id: str, email: str, permissions: list[str]) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            db.add(User(id=user_id, name=email, email=email,
                        password_hash=hash_password("test-password"), permissions=permissions))
            db.commit()
    finally:
        db.close()


def test_failed_login_records_lowercase_email_and_ip() -> None:
    client.post("/api/auth/login", json={"email": "NEW-USER@Example.com", "password": "wrong"})
    db = SessionLocal()
    try:
        entry = db.query(AuditEntry).filter_by(event="login-failed").order_by(AuditEntry.timestamp.desc()).first()
        assert entry is not None
        assert entry.details["email"] == "new-user@example.com"
        assert entry.details["ip"]
        assert "password" not in entry.details
    finally:
        db.close()


def test_permission_denial_records_capability_route_and_method() -> None:
    ensure_user("audit-denied-user", "audit-denied@personalos.ai", ["health.read"])
    token = make_token("audit-denied-user", "audit-denied-token")
    response = client.get("/api/stock/summary", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    db = SessionLocal()
    try:
        entry = db.query(AuditEntry).filter_by(
            user_id="audit-denied-user", event="permission-denied").order_by(AuditEntry.timestamp.desc()).first()
        assert entry is not None
        assert entry.details["capability"] == "stock.read"
        assert entry.details["route"] == "/api/stock/summary"
        assert entry.details["method"] == "GET"
    finally:
        db.close()


def test_cross_user_renewal_delete_records_denial_without_data() -> None:
    ensure_user("audit-user-a", "audit-a@personalos.ai", ["renewal.delete"])
    ensure_user("audit-user-b", "audit-b@personalos.ai", ["renewal.delete"])
    db = SessionLocal()
    try:
        renewal = Renewal(id="audit-renewal-other", owner_id="audit-user-b",
                          name="Other owner's renewal", category="Test",
                          due_date=datetime.now().date(), reminder_days=1, status="upcoming")
        db.add(renewal)
        db.commit()
    finally:
        db.close()
    token = make_token("audit-user-a", "audit-cross-token")
    response = client.delete("/api/renewals/audit-renewal-other",
                             headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404
    db = SessionLocal()
    try:
        entry = db.query(AuditEntry).filter_by(
            user_id="audit-user-a", event="cross-user-access-denied").order_by(AuditEntry.timestamp.desc()).first()
        assert entry is not None
        assert entry.details["resource_type"] == "renewal"
        assert entry.details["resource_id"] == "audit-renewal-other"
    finally:
        db.close()


def test_supervisor_routed_records_hash_not_raw_query_and_tool_call() -> None:
    ensure_user("audit-router", "audit-router@personalos.ai",
                ["renewal.read", "supervisor.route"])
    token = make_token("audit-router", "audit-router-token")
    response = client.post("/api/supervisor/route",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"query": "renewals"})
    assert response.status_code == 200
    db = SessionLocal()
    try:
        entries = db.query(AuditEntry).filter_by(user_id="audit-router").order_by(AuditEntry.timestamp.desc()).limit(10).all()
        routed = next(entry for entry in entries if entry.event == "supervisor-routed")
        assert "renewals" not in routed.details
        assert routed.details["query_length"] == len("renewals")
        assert "query_sha256" in routed.details
        assert routed.details["routing_path"] in {"llm", "fallback"}
        assert "agent" in routed.details
        assert "capability" in routed.details
        assert "policy_verdict" in routed.details
        tool = next(entry for entry in entries if entry.event == "agent-tool-call")
        assert tool.details["tool"] == "renewal.read"
        assert tool.details["ok"] is True
    finally:
        db.close()


def test_audit_entries_have_no_password_token_or_raw_query_and_owner_isolation() -> None:
    ensure_user("audit-visible-a", "audit-visible-a@personalos.ai", ["audit.read"])
    ensure_user("audit-visible-b", "audit-visible-b@personalos.ai", ["audit.read"])
    db = SessionLocal()
    try:
        db.add(AuditEntry(user_id="audit-visible-a", timestamp=datetime.utcnow(),
                          event="login", details={"email": "audit-visible-a@personalos.ai"}))
        db.add(AuditEntry(user_id="audit-visible-b", timestamp=datetime.utcnow(),
                          event="login", details={"email": "audit-visible-b@personalos.ai"}))
        db.commit()
    finally:
        db.close()
    token_a = make_token("audit-visible-a", "audit-visible-token-a")
    token_b = make_token("audit-visible-b", "audit-visible-token-b")
    response_a = client.get("/api/audit-log", headers={"Authorization": f"Bearer {token_a}"})
    response_b = client.get("/api/audit-log", headers={"Authorization": f"Bearer {token_b}"})
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    entries_a = response_a.json()["entries"]
    entries_b = response_b.json()["entries"]
    assert all("audit-visible-b" not in str(entry) for entry in entries_a)
    assert all("audit-visible-a" not in str(entry) for entry in entries_b)
    for entry in entries_a + entries_b:
        serialized = str(entry["details"]).lower()
        assert "password" not in serialized
        assert "token" not in serialized
        assert "raw_query" not in serialized
        assert "query" not in entry["details"] or isinstance(entry["details"]["query"], (int, float))


def test_mfa_failure_and_approval_transition_events() -> None:
    ensure_user("audit-mfa", "audit-mfa@personalos.ai", ["investment.confirm", "investment.propose"])
    token = make_token("audit-mfa", "audit-mfa-token")
    proposed = client.post("/api/investment/propose",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"symbol": "AAPL", "amount": 100, "riskLevel": "Medium"})
    assert proposed.status_code == 200
    proposal_id = proposed.json()["proposal"]["id"]
    waiting = client.post("/api/investment/confirm",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"proposalId": proposal_id, "approved": True})
    assert waiting.status_code == 403
    failed = client.post(f"/api/investment/{proposal_id}/mfa/verify",
                         headers={"Authorization": f"Bearer {token}"},
                         json={"code": "000000"})
    assert failed.status_code == 403
    db = SessionLocal()
    try:
        mfa = db.query(AuditEntry).filter_by(
            user_id="audit-mfa", event="investment-mfa-failed").order_by(AuditEntry.timestamp.desc()).first()
        transition = db.query(AuditEntry).filter_by(
            user_id="audit-mfa", event="approval-state-transition").order_by(AuditEntry.timestamp.desc()).first()
        assert mfa is not None
        assert mfa.details["proposalId"] == proposal_id
        assert transition is not None
        assert transition.details["proposalId"] == proposal_id
    finally:
        db.close()


def test_login_rate_limiter_is_audited() -> None:
    email = "rate-limited-phase4@example.com"
    for _ in range(5):
        assert client.post("/api/auth/login",
                           json={"email": email, "password": "wrong"}).status_code == 401
    response = client.post("/api/auth/login",
                           json={"email": email, "password": "wrong"})
    assert response.status_code == 429
    db = SessionLocal()
    try:
        entry = db.query(AuditEntry).filter_by(event="login-rate-limited").order_by(AuditEntry.timestamp.desc()).first()
        assert entry is not None
        assert entry.details["email"] == email
        assert entry.details["ip"]
    finally:
        db.close()


def test_brute_force_integration_reaches_rule_threshold() -> None:
    rule = next(rule for rule in load_rules() if rule.id == "brute-force-login")
    email = "brute-phase4@example.com"
    statuses = []
    for _ in range(rule.threshold):
        statuses.append(client.post("/api/auth/login",
                                    json={"email": email, "password": "wrong"}).status_code)
    assert statuses == [401] * rule.threshold

    db = SessionLocal()
    try:
        events = read_audit_events(db)
    finally:
        db.close()
    alerts = evaluate([rule], events)
    assert any(alert.rule_id == rule.id for alert in alerts)
