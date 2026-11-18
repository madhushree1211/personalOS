# Copilot instructions for PersonalOS

- Python 3.11+, type hints on all new code. Stack: FastAPI, SQLAlchemy, Alembic, pytest.
- One task per request. No unrelated refactors.
- Never invent metrics. Scripts write results to results/*.json, and README numbers must be copied from those files.
- Never print, log or commit secrets.
- Every new module needs tests. CI uses a FakeLLMClient and no real API key.
- The LLM may only choose from fixed enums. It can never grant capabilities, skip the PolicyEngine or call an execution tool.
- README claims are limited to what the code does.
- Report exact test output, never a summary.