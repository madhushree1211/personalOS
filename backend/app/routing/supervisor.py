from .contracts import RouteWorkflow
from .policy import PolicyEngine
from .validator import RoutingValidator
from ..services import route_request
from .contracts import AgentName, Capability, Intent
from ..agents.classifier import InvalidRoutingOutput, RoutingDecision as LLMRoutingDecision, classify
from ..agents.llm import get_llm_client
from ..config import get_settings
from ..agents.base import AgentContext
from ..agents.renewal import RenewalAgent
from ..agents.health import HealthAgent
from ..agents.finance import FinanceAgent
from ..agents.document import DocumentAgent
from ..db import SessionLocal


_LLM_CAPABILITY_ROUTES = {
    ("renewal", "read"): (Intent.RENEWAL_QUERY, Capability.RENEWAL_READ),
    ("renewal", "manage"): (Intent.RENEWAL_MANAGEMENT, Capability.RENEWAL_UPDATE),
    ("health", "read"): (Intent.HEALTH_QUERY, Capability.HEALTH_READ),
    ("finance", "read"): (Intent.STOCK_ANALYSIS, Capability.STOCK_READ),
    ("finance", "propose"): (Intent.INVESTMENT_PROPOSAL, Capability.INVESTMENT_PROPOSE),
    ("document", "read"): (Intent.DOCUMENT_SEARCH, Capability.DOCUMENT_READ),
}


def _llm_route(text: str, client: object | None) -> tuple[LLMRoutingDecision | None, str | None]:
    if client is None:
        return None, "no_client"
    try:
        decision = classify(text, client)
    except InvalidRoutingOutput:
        return None, "invalid_output"
    except Exception:
        return None, "error"
    if decision.agent == "unknown":
        return None, "unknown_agent"
    if decision.confidence < 0.6:
        return None, "low_confidence"
    if (decision.agent, decision.action) not in _LLM_CAPABILITY_ROUTES:
        return None, "invalid_output"
    return decision, None


class SupervisorRoutingService:
    def __init__(self, validator=None, policy=None, llm_client=None) -> None:
        self.validator = validator or RoutingValidator()
        self.policy = policy or PolicyEngine()
        self.llm_client = get_llm_client(get_settings()) if llm_client is None else llm_client

    def route(self, query: str, repo, user) -> dict:
        import uuid
        request_id = str(uuid.uuid4())
        llm_decision, fallback_reason = _llm_route(query, self.llm_client)
        if llm_decision is not None:
            workflow, capability = _LLM_CAPABILITY_ROUTES[(llm_decision.agent, llm_decision.action)]
            validated = self.validator.validate(query, request_id)
            validated = validated.__class__(
                workflow=workflow,
                normalized_query=validated.normalized_query,
                request_id=request_id,
            )
            routing_path = "llm"
            fallback_reason = None
        else:
            validated = self.validator.validate(query, request_id)
            capability = None
            routing_path = "fallback"
        decision = self.policy.evaluate(validated.workflow, set(user.permissions or []),
                                         user=user, ownership_verified=bool(repo.owner_id),
                                         request_id=request_id)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        repo_db = getattr(repo, "db", None)
        own_session = repo_db is None
        ctx_db = repo_db or SessionLocal()
        try:
            ctx = AgentContext(
                user_id=user.id,
                permissions=set(user.permissions or []),
                db=ctx_db,
                request_id=request_id,
                query=validated.normalized_query,
            )
            if validated.workflow in (Intent.RENEWAL_QUERY, Intent.RENEWAL_MANAGEMENT):
                agent_result = RenewalAgent().handle(
                    ctx,
                    "manage" if validated.workflow is Intent.RENEWAL_MANAGEMENT else "read",
                )
                result = {
                    "agent": agent_result.agent,
                    "workflow": "renewal",
                    "requiresHumanApproval": agent_result.requires_approval,
                    "response": agent_result.answer,
                    "data": agent_result.data,
                    "tool_calls": agent_result.tool_calls,
                }
            elif validated.workflow in (Intent.HEALTH_QUERY, Intent.HEALTH_ANALYSIS):
                agent_result = HealthAgent().handle(ctx, "analysis" if validated.workflow is Intent.HEALTH_ANALYSIS else "read")
                result = {
                    "agent": agent_result.agent,
                    "workflow": "health",
                    "requiresHumanApproval": agent_result.requires_approval,
                    "response": agent_result.answer,
                    "data": agent_result.data,
                    "tool_calls": agent_result.tool_calls,
                }
            elif validated.workflow in (Intent.STOCK_ANALYSIS, Intent.PORTFOLIO_ANALYSIS):
                agent_result = FinanceAgent().handle(ctx, "read")
                result = {
                    "agent": agent_result.agent,
                    "workflow": "finance",
                    "requiresHumanApproval": agent_result.requires_approval,
                    "response": agent_result.answer,
                    "data": agent_result.data,
                    "tool_calls": agent_result.tool_calls,
                }
            elif validated.workflow is Intent.INVESTMENT_PROPOSAL:
                agent_result = FinanceAgent().handle(ctx, "propose")
                result = {
                    "agent": agent_result.agent,
                    "workflow": "investment",
                    "requiresHumanApproval": agent_result.requires_approval,
                    "response": agent_result.answer,
                    "data": agent_result.data,
                    "tool_calls": agent_result.tool_calls,
                }
            elif validated.workflow is Intent.DOCUMENT_SEARCH:
                agent_result = DocumentAgent().handle(ctx, "read")
                result = {
                    "agent": agent_result.agent,
                    "workflow": "document",
                    "requiresHumanApproval": agent_result.requires_approval,
                    "response": agent_result.answer,
                    "data": agent_result.data,
                    "tool_calls": agent_result.tool_calls,
                }
            else:
                result = route_request(validated.normalized_query, repo)
                result["tool_calls"] = []
        finally:
            if own_session:
                ctx_db.close()
        typed = self.validator.validate_decision(decision.decision)
        # Preserve the legacy response contract while exposing deterministic policy metadata.
        result["policy"] = {"allowed": decision.allowed, "approval": decision.approval.value,
                            "reason": decision.reason, "request_id": request_id,
                            "risk_level": typed.risk_level.value,
                            "approval_type": typed.approval_type.value}
        result["request_id"] = request_id
        result["routing_decision"] = typed.model_dump(mode="json")
        result["routing_path"] = routing_path
        result["fallback_reason"] = fallback_reason
        return result
