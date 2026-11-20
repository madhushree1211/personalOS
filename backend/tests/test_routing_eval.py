from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.agents.llm import FakeLLMClient
from app.routing.contracts import Intent
from app.routing.supervisor import SupervisorRoutingService


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.eval_routing as evaluator


def test_every_intent_maps_to_label_and_unmapped_is_rejected() -> None:
    for intent in Intent:
        assert evaluator.intent_to_label(intent) in evaluator.LABELS
    with pytest.raises(ValueError, match="Unmapped Intent"):
        evaluator.intent_to_label(object())


def write_cases(path: Path, cases: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(case) + "\n" for case in cases),
        encoding="utf-8",
    )


def test_keyword_only_tiny_cases_exact_counts(tmp_path: Path) -> None:
    cases = [
        {"id": 1, "query": "show renewals", "expected_agent": "renewal", "category": "normal"},
        {"id": 2, "query": "check my sleep", "expected_agent": "health", "category": "normal"},
        {"id": 3, "query": "buy 100 shares", "expected_agent": "finance", "category": "normal"},
        {"id": 4, "query": "search document", "expected_agent": "document", "category": "normal"},
        {"id": 5, "query": "what is the weather", "expected_agent": "unknown", "category": "normal"},
    ]
    cases_path = tmp_path / "cases.jsonl"
    write_cases(cases_path, cases)
    loaded, raw = evaluator.load_cases(cases_path)
    output = evaluator.run_keyword_only(loaded, raw, str(cases_path))
    assert output["mode"] == "keyword_only"
    assert output["n_cases"] == 5
    assert output["llm_classifier"] == {"status": "not_run"}
    assert output["supervisor"] == {"status": "not_run"}
    keyword = output["keyword"]
    assert keyword["n_scored"] == 5
    assert keyword["n_correct"] == 5
    assert keyword["accuracy"] == 1.0
    assert output["category_counts"] == {"normal": 5}
    assert output["expected_label_counts"] == {
        "renewal": 1,
        "health": 1,
        "finance": 1,
        "document": 1,
        "unknown": 1,
    }


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ({"id": 1, "query": "renewals", "expected_agent": "renewal", "category": "bad"}, "invalid category"),
        ({"id": 1, "query": "renewals", "expected_agent": "bank", "category": "normal"}, "invalid label"),
    ],
)
def test_invalid_category_or_label_rejected(tmp_path: Path, case: dict, message: str) -> None:
    cases_path = tmp_path / "cases.jsonl"
    write_cases(cases_path, [case])
    with pytest.raises(evaluator.CaseError) as exc:
        evaluator.load_cases(cases_path)
    assert message in str(exc.value)


def test_duplicate_id_malformed_missing_utf16_and_validate(tmp_path: Path, monkeypatch) -> None:
    duplicate = tmp_path / "duplicate.jsonl"
    write_cases(duplicate, [
        {"id": 1, "query": "renewals", "expected_agent": "renewal", "category": "normal"},
        {"id": 1, "query": "health", "expected_agent": "health", "category": "normal"},
    ])
    with pytest.raises(evaluator.CaseError, match="Duplicate id"):
        evaluator.load_cases(duplicate)

    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{bad json\n", encoding="utf-8")
    with pytest.raises(evaluator.CaseError, match="Malformed line 1"):
        evaluator.load_cases(malformed)

    missing = tmp_path / "missing.jsonl"
    with pytest.raises(FileNotFoundError):
        evaluator.load_cases(missing)

    utf16 = tmp_path / "utf16.jsonl"
    utf16.write_text(
        '{"id":1,"query":"renewals","expected_agent":"renewal","category":"normal"}\n',
        encoding="utf-16",
    )
    with pytest.raises(evaluator.CaseError, match="UTF-8"):
        evaluator.load_cases(utf16)

    validate_cases = tmp_path / "validate.jsonl"
    write_cases(validate_cases, [
        {"id": 1, "query": "renewals", "expected_agent": "renewal", "category": "normal"},
    ])
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval_routing.py", "--validate", "--cases", str(validate_cases)],
    )
    monkeypatch.setattr(evaluator, "ROOT", tmp_path)
    assert evaluator.main() == 0
    assert not (tmp_path / "results" / "routing_eval.json").exists()


def test_decide_valid_llm_and_invalid_fallback() -> None:
    valid = SupervisorRoutingService(llm_client=FakeLLMClient(
        {"agent": "renewal", "action": "read", "confidence": 0.9}
    ))
    validated, capability, routing_path, fallback_reason = valid.decide("show renewals", "eval")
    assert routing_path == "llm"
    assert fallback_reason is None
    assert validated.workflow is Intent.RENEWAL_QUERY

    invalid = SupervisorRoutingService(llm_client=FakeLLMClient("not-json"))
    validated, capability, routing_path, fallback_reason = invalid.decide("show renewals", "eval")
    assert routing_path == "fallback"
    assert fallback_reason in {"invalid_output", "error"}
