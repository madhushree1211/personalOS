from __future__ import annotations

from .base import AgentContext, AgentResult, BaseAgent
from ..repositories import Repository
from ..services import serialize_health


class HealthAgent(BaseAgent):
    name = "Health Agent"
    declared_tools = ("health.read", "health.analysis")
    required_capability = {
        "read": "health.read",
        "analysis": "health.read",
    }

    def _handle_action(self, ctx: AgentContext, action: str) -> AgentResult:
        repository = Repository(ctx.db, ctx.user_id)

        def read_health() -> list[dict]:
            return [serialize_health(item) for item in repository.health()]

        records, call = self._tool_call(
            ctx, "health.read", action, self.required_capability[action], read_health
        )
        return AgentResult(
            agent=self.name,
            answer="Health records retrieved with privacy safeguards.",
            data={"rawData": records},
            tool_calls=[call],
        )
