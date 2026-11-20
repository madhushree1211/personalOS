from contextvars import ContextVar
from typing import Iterator
from contextlib import contextmanager


request_id_context: ContextVar[str | None] = ContextVar("audit_request_id", default=None)


@contextmanager
def audit_request(request_id: str) -> Iterator[None]:
    token = request_id_context.set(request_id)
    try:
        yield
    finally:
        request_id_context.reset(token)
