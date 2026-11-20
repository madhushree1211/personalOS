from __future__ import annotations

from typing import Any

from .base import AgentContext, AgentResult, BaseAgent
from ..repositories import Repository
from ..services import serialize_renewal


class RenewalAgent(BaseAgent):
    name = "Renewal Agent"
    declared_tools = ("renewal.read", "renewal.manage")
    required_capability = {
        "read": "renewal.read",
        "manage": "renewal.update",
    }

    def _handle_action(self, ctx: AgentContext, action: str) -> AgentResult:
        repository = Repository(ctx.db, ctx.user_id)
        tool = "renewal.read" if action == "read" else "renewal.manage"
        capability = self.required_capability[action]

        def read_renewals() -> list[dict[str, Any]]:
            return [serialize_renewal(item) for item in repository.renewals()]

        renewals, call = self._tool_call(
            ctx, tool, action, capability, read_renewals
        )
        return AgentResult(
            agent=self.name,
            answer=f"I found {len(renewals)} renewal items.",
            data={"renewals": renewals},
            tool_calls=[call],
        )
