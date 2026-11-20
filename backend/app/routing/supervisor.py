from .contracts import RouteWorkflow
from .policy import PolicyEngine
from .validator import RoutingValidator
from ..services import route_request
from .contracts import AgentName, Capability, Intent
from ..agents.classifier import InvalidRoutingOutput, RoutingDecision as LLMRoutingDecision, classify
from ..agents.llm import get_llm_client
from ..config import get_settings


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
        if validated.workflow is Intent.RENEWAL_QUERY:
            from ..mcp.adapters.renewal import RenewalMCPAdapter
            from ..mcp.client import MCPClient
            from ..mcp.contracts import (
                MCPAuthorizationContext,
                MCPInvocationRequest,
                MCPToolIdentity,
            )
            from ..mcp.transport import RenewalMCPTransport

            renewal_client = MCPClient(
                transport=RenewalMCPTransport(RenewalMCPAdapter(repo))
            )
            renewal_result = renewal_client.invoke(
                MCPInvocationRequest(
                    request_id=request_id,
                    identity=MCPToolIdentity(
                        server_name="personalos-safe-mock",
                        tool_name="renewal.read",
                    ),
                    capability=Capability.RENEWAL_READ,
                    authenticated_user_id=user.id,
                    agent=AgentName.RENEWAL_SHORT,
                    input={"query": validated.normalized_query},
                ),
                MCPAuthorizationContext(
                    user_id=user.id,
                    agent=AgentName.RENEWAL_SHORT,
                    policy_decision=decision,
                ),
            )
            renewals = renewal_result.data["renewals"]
            result = {
                "agent": "Renewal Agent",
                "workflow": "renewal",
                "requiresHumanApproval": False,
                "response": f"I found {len(renewals)} items that may need attention.",
                "data": {"renewals": renewals},
            }
        elif validated.workflow is Intent.HEALTH_QUERY:
            from ..mcp.adapters.health import HealthMCPAdapter
            from ..mcp.client import MCPClient
            from ..mcp.contracts import (
                MCPAuthorizationContext,
                MCPInvocationRequest,
                MCPToolIdentity,
            )
            from ..mcp.transport import HealthMCPTransport

            health_client = MCPClient(
                transport=HealthMCPTransport(HealthMCPAdapter(repo))
            )
            health_result = health_client.invoke(
                MCPInvocationRequest(
                    request_id=request_id,
                    identity=MCPToolIdentity(
                        server_name="personalos-safe-mock",
                        tool_name="health.read",
                    ),
                    capability=Capability.HEALTH_READ,
                    authenticated_user_id=user.id,
                    agent=AgentName.HEALTH_SHORT,
                    input={"metric": ""},
                ),
                MCPAuthorizationContext(
                    user_id=user.id,
                    agent=AgentName.HEALTH_SHORT,
                    policy_decision=decision,
                ),
            )
            result = {
                "agent": "Health Agent",
                "workflow": "health",
                "requiresHumanApproval": False,
                "response": "Health records retrieved with privacy safeguards.",
                "data": {"rawData": health_result.data["records"]},
            }
        else:
            result = route_request(validated.normalized_query, repo)
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
