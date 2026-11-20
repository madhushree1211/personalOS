from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.auth import hash_password
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import AuditEntry, User
from app.security.engine import evaluate
from app.security.loader import DetectionRule, load_rules


client = TestClient(app)
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def rule_event(rule_id: str) -> DetectionRule:
    return next(rule for rule in load_rules() if rule.id == rule_id)


@pytest.mark.parametrize("rule_id,user_field", [
    ("brute-force-login", "ip"),
    ("repeated-capability-denials", "user_id"),
    ("cross-user-resource-access", "user_id"),
    ("repeated-mfa-failures", "user_id"),
])
def test_each_rule_threshold_and_mix(rule_id: str, user_field: str) -> None:
    rule = rule_event(rule_id)
    matching = [
        {"event": rule.event, "timestamp": NOW + timedelta(seconds=index),
         "user_id": "u1", "ip": "10.0.0.1"}
        for index in range(rule.threshold)
    ]
    assert any(alert.rule_id == rule_id for alert in evaluate([rule], matching))

    below = matching[:-1]
    assert not any(alert.rule_id == rule_id for alert in evaluate([rule], below))

    outside = [
        {"event": rule.event, "timestamp": NOW,
         "user_id": "u1", "ip": "10.0.0.1"},
        {"event": rule.event, "timestamp": NOW + timedelta(seconds=rule.window_seconds + 1),
         "user_id": "u1", "ip": "10.0.0.1"},
        {"event": rule.event, "timestamp": NOW + timedelta(seconds=2 * rule.window_seconds + 2),
         "user_id": "u1", "ip": "10.0.0.1"},
    ]
    if rule.threshold > 3:
        outside += [
            {"event": rule.event, "timestamp": NOW + timedelta(seconds=3 * rule.window_seconds + 3),
             "user_id": "u1", "ip": "10.0.0.1"}
            for _ in range(rule.threshold - 3)
        ]
    assert not any(alert.rule_id == rule_id for alert in evaluate([rule], outside))

    split = []
    for index in range(rule.threshold):
        values = {"ip": "10.0.0.1" if index % 2 == 0 else "10.0.0.2",
                  "user_id": "u1" if index % 2 == 0 else "u2"}
        split.append({"event": rule.event, "timestamp": NOW + timedelta(seconds=index),
                      **values})
    assert not any(alert.rule_id == rule_id for alert in evaluate([rule], split))


def test_loader_rejects_missing_field(tmp_path) -> None:
    path = tmp_path / "missing.yml"
    path.write_text(
        "id: test\n"
        "title: Test\n"
        "description: Test\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid detection rule"):
        load_rules(tmp_path)


def test_engine_does_not_mutate_input() -> None:
    rule = rule_event("repeated-mfa-failures")
    events = [
        {"event": rule.event, "timestamp": NOW + timedelta(seconds=index),
         "user_id": "u1", "ip": "10.0.0.1"}
        for index in range(rule.threshold)
    ]
    original = deepcopy(events)
    evaluate([rule], events)
    assert events == original


def token_for(user: User) -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": user.id, "jti": "security-test", "exp": datetime.now(timezone.utc).timestamp() + 3600},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def test_api_denied_without_audit_read_and_owner_scoped() -> None:
    db = SessionLocal()
    try:
        denied = db.query(User).filter_by(email="security-denied@personalos.ai").first()
        if not denied:
            denied = User(id="security-denied", name="Denied", email="security-denied@personalos.ai",
                          password_hash=hash_password("password"), permissions=["health.read"])
            db.add(denied)
        allowed = db.query(User).filter_by(email="security-owner@personalos.ai").first()
        if not allowed:
            allowed = User(id="security-owner", name="Owner", email="security-owner@personalos.ai",
                           password_hash=hash_password("password"), permissions=["audit.read"])
            db.add(allowed)
        db.commit()
        db.refresh(denied)
        db.refresh(allowed)
        denied_id = denied.id
        allowed_id = allowed.id
        if not db.query(AuditEntry).filter_by(id="other-owner-entry").first():
            db.add(AuditEntry(id="other-owner-entry", user_id="security-other",
                              timestamp=datetime.utcnow(), event="login-failed",
                              details={"ip": "203.0.113.7"}))
        db.commit()
    finally:
        db.close()

    denied_response = client.get(
        "/api/security/alerts",
        headers={"Authorization": f"Bearer {jwt.encode({'sub': denied_id, 'jti': 'denied-test', 'exp': datetime.now(timezone.utc).timestamp() + 3600}, get_settings().jwt_secret, algorithm=get_settings().jwt_algorithm)}"},
    )
    assert denied_response.status_code == 403

    owner_response = client.get(
        "/api/security/alerts",
        headers={"Authorization": f"Bearer {jwt.encode({'sub': allowed_id, 'jti': 'owner-test', 'exp': datetime.now(timezone.utc).timestamp() + 3600}, get_settings().jwt_secret, algorithm=get_settings().jwt_algorithm)}"},
    )
    assert owner_response.status_code == 200
    assert all(alert["group_key"] != "203.0.113.7"
               for alert in owner_response.json()["alerts"])
