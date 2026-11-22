from __future__ import annotations

from .base import AgentContext, AgentResult, BaseAgent
from ..audit import audit
from ..models import InvestmentApproval, InvestmentProposal
from ..repositories import Repository
from ..approval import ApprovalState


class FinanceAgent(BaseAgent):
    name = "Stock Analysis Agent"
    declared_tools = ("stock.read",)
    required_capability = {
        "read": "stock.read",
        "propose": "investment.propose",
    }

    def _handle_action(self, ctx: AgentContext, action: str) -> AgentResult:
        repository = Repository(ctx.db, ctx.user_id)
        if action == "propose":
            def propose() -> dict:
                # Demo proposal: fixed symbol and amount; the query is not parsed.
                proposal = InvestmentProposal(
                    owner_id=ctx.user_id,
                    symbol="HDFCBANK",
                    amount=10000,
                    risk_level="Medium",
                    status=ApprovalState.PENDING_USER.value,
                )
                ctx.db.add(proposal)
                ctx.db.flush()
                approval = InvestmentApproval(
                    proposal_id=proposal.id,
                    owner_id=ctx.user_id,
                    requested_by=ctx.user_id,
                    status=ApprovalState.PENDING_USER.value,
                )
                ctx.db.add(approval)
                ctx.db.commit()
                ctx.db.refresh(proposal)
                ctx.db.refresh(approval)
                audit(ctx.db, ctx.user_id,
                      "investment-proposal", {"proposalId": proposal.id})
                return {
                    "id": proposal.id,
                    "symbol": proposal.symbol,
                    "amount": proposal.amount,
                    "status": ApprovalState.PENDING_USER.value,
                    "demo": True,
                    "note": "Fixed demo proposal; the query is not parsed.",
                }

            proposal, call = self._tool_call(
                ctx, "investment.propose", action,
                self.required_capability[action], propose
            )
            return AgentResult(
                agent="Investment Agent",
                answer="Demo proposal: fixed symbol and amount, the query is not parsed.",
                data={"proposal": proposal},
                tool_calls=[call],
                requires_approval=True,
            )

        def read_demo() -> dict:
            holdings = [
                {"symbol": item.symbol, "shares": item.shares,
                 "price": item.price, "allocation": item.allocation}
                for item in repository.holdings()
            ]
            total = sum(item["shares"] * item["price"] for item in holdings)
            return {"portfolio": holdings, "total": total,
                    "source": "demo data", "risk": "Moderate"}

        analysis, call = self._tool_call(
            ctx, "stock.read", action, self.required_capability[action], read_demo
        )
        return AgentResult(
            agent=self.name,
            answer="Read-only demo portfolio analysis.",
            data=analysis,
            tool_calls=[call],
        )
