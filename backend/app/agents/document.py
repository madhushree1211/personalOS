from __future__ import annotations

import hashlib

from .base import AgentContext, AgentResult, BaseAgent
from ..documents.tfidf import lexical_tfidf_search
from ..repositories import Repository


class DocumentAgent(BaseAgent):
    name = "Document Agent"
    declared_tools = ("document.search",)
    required_capability = {"read": "document.read"}

    def _handle_action(self, ctx: AgentContext, action: str) -> AgentResult:
        repository = Repository(ctx.db, ctx.user_id)

        def search() -> list[dict]:
            chunks: list[dict] = []
            for document in repository.documents(limit=1000):
                metadata = document.metadata_json or {}
                for chunk in metadata.get("chunks", []):
                    chunks.append({
                        "document_id": document.id,
                        "filename": document.filename,
                        "chunk_id": chunk["chunk_id"],
                        "text": chunk["text"],
                    })
            return lexical_tfidf_search(
                getattr(ctx, "query", ""),
                chunks,
                20,
            )

        results, call = self._tool_call(
            ctx, "document.search", action,
            self.required_capability[action], search
        )
        from ..main import audit

        audit(ctx.db, type("AuditUser", (), {"id": ctx.user_id})(), "document-searched", {
            "query_length": len(ctx.query),
            "query_sha256": hashlib.sha256(ctx.query.encode("utf-8")).hexdigest(),
            "result_count": len(results),
        })
        return AgentResult(
            agent=self.name,
            answer=f"Found {len(results)} lexical (TF-IDF) retrieval results.",
            data={"results": results},
            tool_calls=[call],
        )
