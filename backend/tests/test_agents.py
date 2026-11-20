from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from jose import jwt

from app.auth import hash_password
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import AuditEntry, HealthRecord, InvestmentProposal, Renewal, User
from app.agents.base import AgentContext
from app.agents.renewal import RenewalAgent
from app.agents.health import HealthAgent
from app.agents.finance import FinanceAgent
from app.agents.document import DocumentAgent
from app.models import Document


client = TestClient(app)


def token_for(user_id: str) -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": user_id, "jti": f"agent-{user_id}", "exp": datetime.now(timezone.utc).timestamp() + 3600},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def ensure_user(user_id: str, permissions: list[str]) -> None:
    db = SessionLocal()
    try:
        if not db.query(User).filter_by(id=user_id).first():
            db.add(User(id=user_id, name=user_id,
                        email=f"{user_id}@personalos.ai",
                        password_hash=hash_password("test-password"),
                        permissions=permissions))
            db.commit()
    finally:
        db.close()


def test_each_agent_success_path() -> None:
    ensure_user("agent-renewal", ["renewal.read"])
    ensure_user("agent-health", ["health.read"])
    ensure_user("agent-finance", ["stock.read", "investment.propose"])
    db = SessionLocal()
    try:
        renewal_result = RenewalAgent().handle(
            AgentContext("agent-renewal", {"renewal.read"}, db, "request-renewal"), "read")
        health_result = HealthAgent().handle(
            AgentContext("agent-health", {"health.read"}, db, "request-health"), "read")
        finance_result = FinanceAgent().handle(
            AgentContext("agent-finance", {"stock.read"}, db, "request-finance"), "read")
        proposal_result = FinanceAgent().handle(
            AgentContext("agent-finance", {"investment.propose"}, db, "request-proposal"), "propose")
        assert renewal_result.agent == "Renewal Agent"
        assert health_result.agent == "Health Agent"
        assert finance_result.data["source"] == "demo data"
        assert proposal_result.requires_approval is True
        assert proposal_result.data["proposal"]["status"] == "pending_user"
    finally:
        db.close()


def test_wrong_owner_never_sees_renewals_or_health() -> None:
    owner_a = f"agent-owner-a-{uuid4().hex}"
    owner_b = f"agent-owner-b-{uuid4().hex}"
    renewal_a = f"renewal-a-{uuid4().hex}"
    renewal_b = f"renewal-b-{uuid4().hex}"
    db = SessionLocal()
    try:
        db.add(Renewal(id=renewal_a, owner_id=owner_a, name="A",
                       category="Test", due_date=datetime.now().date(), reminder_days=1, status="upcoming"))
        db.add(Renewal(id=renewal_b, owner_id=owner_b, name="B",
                       category="Test", due_date=datetime.now().date(), reminder_days=1, status="upcoming"))
        db.add(HealthRecord(owner_id=owner_a, date=datetime.now().date(),
                            metric="sleep", value=8.0, unit="hours"))
        db.add(HealthRecord(owner_id=owner_b, date=datetime.now().date(),
                            metric="sleep", value=7.0, unit="hours"))
        db.commit()
        renewal = RenewalAgent().handle(
            AgentContext(owner_b, {"renewal.read"}, db, "wrong-owner"), "read")
        health = HealthAgent().handle(
            AgentContext(owner_b, {"health.read"}, db, "wrong-owner"), "read")
        assert {item["id"] for item in renewal.data["renewals"]} == {renewal_b}
        assert all(item["id"] != renewal_a for item in renewal.data["renewals"])
        assert health.data["rawData"]
        assert all(item["unit"] == "hours" for item in health.data["rawData"])

        renewal_a_view = RenewalAgent().handle(
            AgentContext(owner_a, {"renewal.read"}, db, "wrong-owner-a"), "read")
        health_a_view = HealthAgent().handle(
            AgentContext(owner_a, {"health.read"}, db, "wrong-owner-a"), "read")
        assert {item["id"] for item in renewal_a_view.data["renewals"]} == {renewal_a}
        assert all(item["value"] == 8.0 for item in health_a_view.data["rawData"])
    finally:
        db.close()


def test_missing_capability_denied_and_tool_not_called(monkeypatch) -> None:
    db = SessionLocal()
    try:
        agent = RenewalAgent()
        spy = {"called": False}

        def forbidden_call(*args, **kwargs):
            spy["called"] = True

        monkeypatch.setattr(agent, "_tool_call", forbidden_call)
        result = agent.handle(
            AgentContext("agent-no-cap", set(), db, "denied-request"), "read")
        assert result.data["denied"] is True
        assert spy["called"] is False
    finally:
        db.close()


def test_finance_cannot_execute_and_creates_only_pending_user() -> None:
    ensure_user("finance-agent-no-execute", ["investment.propose"])
    db = SessionLocal()
    try:
        result = FinanceAgent().handle(
            AgentContext("finance-agent-no-execute", {"investment.propose"},
                        db, "proposal-request"), "propose")
        proposal_id = result.data["proposal"]["id"]
        proposal = db.get(InvestmentProposal, proposal_id)
        assert proposal is not None
        assert proposal.status == "pending_user"
        assert not hasattr(FinanceAgent(), "execute")
        declared = " ".join(FinanceAgent.declared_tools).lower()
        required = " ".join(str(value) for value in FinanceAgent.required_capability.values()).lower()
        assert "execute" not in declared
        assert "execute" not in required

        agents_dir = Path(__file__).parents[1] / "app" / "agents"
        for source_file in agents_dir.glob("*.py"):
            assert "broker" not in source_file.read_text(encoding="utf-8").lower()
    finally:
        db.close()


def test_buy_query_creates_no_executed_proposal_through_supervisor() -> None:
    user_id = f"finance-supervisor-{uuid4().hex}"
    ensure_user(user_id, ["investment.propose", "supervisor.route"])
    token = token_for(user_id)
    response = client.post("/api/supervisor/route",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"query": "buy 100 shares"})
    assert response.status_code == 200
    db = SessionLocal()
    try:
        proposals = db.query(InvestmentProposal).filter_by(owner_id=user_id).all()
        assert proposals
        assert all(proposal.status == "pending_user" for proposal in proposals)
    finally:
        db.close()


def test_agent_tool_call_is_audited() -> None:
    ensure_user("audited-agent", ["renewal.read"])
    db = SessionLocal()
    try:
        RenewalAgent().handle(
            AgentContext("audited-agent", {"renewal.read"}, db, "audited-request"), "read")
        entry = db.query(AuditEntry).filter_by(
            user_id="audited-agent", event="agent-tool-call").order_by(AuditEntry.timestamp.desc()).first()
        assert entry is not None
        assert entry.details["tool"] == "renewal.read"
        assert entry.details["ok"] is True
        assert "query" not in entry.details
    finally:
        db.close()
