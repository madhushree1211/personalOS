from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..audit import audit


@dataclass(frozen=True)
class AgentContext:
    user_id: str
    permissions: set[str]
    db: Session
    request_id: str
    query: str = ""


@dataclass
class AgentResult:
    agent: str
    answer: str
    data: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    requires_approval: bool = False


class BaseAgent:
    name: str = "base"
    declared_tools: tuple[str, ...] = ()
    required_capability: dict[str, str] = {}

    def handle(self, ctx: AgentContext, decision: Any) -> AgentResult:
        action = decision if isinstance(decision, str) else getattr(decision, "action", "read")
        capability = self.required_capability.get(action)
        if capability and capability not in ctx.permissions:
            return AgentResult(
                agent=self.name,
                answer="Permission denied.",
                data={"denied": True, "capability": capability},
            )
        return self._handle_action(ctx, action)

    def _handle_action(self, ctx: AgentContext, action: str) -> AgentResult:
        raise NotImplementedError

    def _tool_call(
        self,
        ctx: AgentContext,
        tool: str,
        action: str,
        capability: str,
        call: Callable[[], Any],
    ) -> tuple[Any, dict[str, Any]]:
        if capability not in ctx.permissions:
            return None, {"tool": tool, "ok": False, "denied": True}

        ok = True
        try:
            result = call()
        except Exception:
            ok = False
            raise
        finally:
            audit(ctx.db, ctx.user_id, "agent-tool-call", {
                "tool": tool,
                "ok": ok,
            })
        return result, {"tool": tool, "ok": ok}
