from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DEMO_PASSWORD", "test-demo-password")

from app.agents.classifier import classify
from app.agents.llm import get_llm_client
from app.config import get_settings
from app.routing.contracts import Intent
from app.routing.supervisor import SupervisorRoutingService
from app.routing.validator import RoutingValidator


LABELS = ("renewal", "health", "finance", "document", "unknown")
CATEGORIES = ("normal", "ambiguous", "multi_intent", "adversarial")


def intent_to_label(intent: Intent) -> str:
    if not isinstance(intent, Intent):
        raise ValueError("Unmapped Intent")
    if intent in (Intent.RENEWAL_QUERY, Intent.RENEWAL_MANAGEMENT):
        return "renewal"
    if intent in (Intent.HEALTH_QUERY, Intent.HEALTH_ANALYSIS):
        return "health"
    if intent in (
        Intent.STOCK_ANALYSIS,
        Intent.PORTFOLIO_ANALYSIS,
        Intent.INVESTMENT_PROPOSAL,
        Intent.INVESTMENT_EXECUTION,
    ):
        return "finance"
    if intent is Intent.DOCUMENT_SEARCH:
        return "document"
    if intent is Intent.GENERAL:
        return "unknown"
    raise ValueError(f"Unmapped Intent: {intent.value}")


class CaseError(ValueError):
    pass


def load_cases(path: str | Path) -> tuple[list[dict], bytes]:
    case_path = Path(path)
    if not case_path.exists():
        raise FileNotFoundError(f"Cases file missing: {case_path}")
    raw = case_path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw[:100]:
        raise CaseError("Re-save as UTF-8")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CaseError("Re-save as UTF-8") from exc

    cases: list[dict] = []
    seen_ids: set[int] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaseError(f"Malformed line {line_number}: {exc.msg}") from exc
        if not isinstance(case, dict):
            raise CaseError(f"Line {line_number}: case must be a JSON object")
        case_id = case.get("id")
        if not isinstance(case_id, int):
            raise CaseError(f"Line {line_number}: id for case must be an integer")
        if case_id in seen_ids:
            raise CaseError(f"Duplicate id {case_id} at line {line_number}")
        seen_ids.add(case_id)
        query = case.get("query")
        if not isinstance(query, str) or not query.strip():
            raise CaseError(f"Line {line_number}: id {case_id} has invalid query")
        expected = case.get("expected_agent")
        if expected not in LABELS:
            raise CaseError(f"Line {line_number}: id {case_id} has invalid label {expected!r}")
        category = case.get("category")
        if category not in CATEGORIES:
            raise CaseError(f"Line {line_number}: id {case_id} has invalid category {category!r}")
        cases.append({
            "id": case_id,
            "query": query,
            "expected_agent": expected,
            "category": category,
        })
    return cases, raw


def keyword_predictions(cases: list[dict]) -> tuple[list[str], list[dict]]:
    validator = RoutingValidator()
    predictions: list[str] = []
    rejected: list[dict] = []
    for case in cases:
        try:
            intent = validator.validate(case["query"]).workflow
            predictions.append(intent_to_label(intent))
        except ValueError:
            predictions.append("rejected")
            rejected.append({"id": case["id"], "query": case["query"], "category": case["category"]})
    return predictions, rejected


def _method_result(cases: list[dict], predictions: list[str]) -> dict:
    labels_by_category: dict[str, list[tuple[str, str]]] = {category: [] for category in CATEGORIES}
    confusion = {expected: {predicted: 0 for predicted in (*LABELS, "error", "rejected")} for expected in LABELS}
    misrouted: list[dict] = []
    n_correct = 0
    n_scored = 0
    for case, predicted in zip(cases, predictions):
        expected = case["expected_agent"]
        if predicted == "rejected":
            continue
        n_scored += 1
        labels_by_category[case["category"]].append((expected, predicted))
        confusion.setdefault(expected, {})
        confusion[expected][predicted] = confusion[expected].get(predicted, 0) + 1
        if predicted == expected:
            n_correct += 1
        else:
            misrouted.append({
                "id": case["id"],
                "query": case["query"],
                "category": case["category"],
                "expected": expected,
                "predicted": predicted,
            })
    accuracy_by_category: dict[str, float] = {}
    for category, pairs in labels_by_category.items():
        if pairs:
            accuracy_by_category[category] = sum(expected == predicted for expected, predicted in pairs) / len(pairs)
        else:
            accuracy_by_category[category] = 0.0
    return {
        "n_scored": n_scored,
        "n_correct": n_correct,
        "accuracy": n_correct / n_scored if n_scored else 0.0,
        "accuracy_by_category": accuracy_by_category,
        "confusion": confusion,
        "misrouted": misrouted,
    }


def build_keyword_result(cases: list[dict]) -> dict:
    predictions, rejected = keyword_predictions(cases)
    result = _method_result(cases, predictions)
    result["rejected"] = rejected
    return result


def run_keyword_only(cases: list[dict], raw: bytes, cases_path: str) -> dict:
    keyword = build_keyword_result(cases)
    category_counts = dict(Counter(case["category"] for case in cases))
    expected_counts = dict(Counter(case["expected_agent"] for case in cases))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "keyword_only",
        "provider": None,
        "model": None,
        "cases_file": cases_path,
        "cases_sha256": hashlib.sha256(raw).hexdigest(),
        "n_cases": len(cases),
        "category_counts": category_counts,
        "expected_label_counts": expected_counts,
        "keyword": keyword,
        "llm_classifier": {"status": "not_run"},
        "supervisor": {"status": "not_run"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cases", default="data/routing_eval.jsonl")
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    cases_path = Path(args.cases)
    try:
        cases, raw = load_cases(cases_path)
    except FileNotFoundError as exc:
        print(str(exc))
        return 2
    except CaseError as exc:
        print(str(exc))
        return 2

    category_counts = dict(Counter(case["category"] for case in cases))
    expected_counts = dict(Counter(case["expected_agent"] for case in cases))
    if args.validate:
        print(f"n_cases={len(cases)}")
        print("category_counts=" + json.dumps(category_counts, sort_keys=True))
        print("expected_agent_counts=" + json.dumps(expected_counts, sort_keys=True))
        return 0
    if args.live:
        settings = get_settings()
        client = get_llm_client(settings)
        if client is None:
            print("LLM client is unavailable: configure a provider and API key.")
            return 2
        provider = str(getattr(settings, "llm_provider", "none"))
        model = getattr(settings, "llm_model", None)
    else:
        client = None
        provider = None
        model = None

    keyword = build_keyword_result(cases)
    llm_result = {"status": "not_run"}
    supervisor_result = {"status": "not_run"}

    if args.live:
        llm_predictions: list[str] = []
        supervisor_predictions: list[str] = []
        routing_paths: Counter[str] = Counter()
        fallback_reasons: Counter[str] = Counter()
        supervisor_rejected: list[dict] = []
        service = SupervisorRoutingService(llm_client=client)
        for index, case in enumerate(cases):
            try:
                decision = classify(case["query"], client)
                llm_predictions.append(decision.agent if decision.agent in LABELS else "unknown")
            except Exception:
                llm_predictions.append("error")
            try:
                validated, capability, routing_path, fallback_reason = service.decide(case["query"], "eval")
                supervisor_predictions.append(intent_to_label(validated.workflow))
                routing_paths[routing_path] += 1
                if fallback_reason is not None:
                    fallback_reasons[fallback_reason] += 1
            except ValueError:
                supervisor_predictions.append("rejected")
                supervisor_rejected.append({"id": case["id"], "query": case["query"], "category": case["category"]})
            except Exception:
                supervisor_predictions.append("error")
            if args.sleep > 0 and index + 1 < len(cases):
                time.sleep(args.sleep)

        llm_result = _method_result(cases, llm_predictions)
        llm_result["rejected"] = []
        supervisor_result = _method_result(cases, supervisor_predictions)
        supervisor_result["rejected"] = supervisor_rejected
        supervisor_result["routing_path_counts"] = dict(routing_paths)
        supervisor_result["fallback_reason_counts"] = dict(fallback_reasons)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if args.live else "keyword_only",
        "provider": provider,
        "model": model,
        "cases_file": str(cases_path),
        "cases_sha256": hashlib.sha256(raw).hexdigest(),
        "n_cases": len(cases),
        "category_counts": category_counts,
        "expected_label_counts": expected_counts,
        "keyword": keyword,
        "llm_classifier": llm_result,
        "supervisor": supervisor_result,
    }
    results_dir = ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "routing_eval.json").write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print("method n_correct/n_scored accuracy")
    for name, result in (
        ("keyword", keyword),
        ("llm_classifier", llm_result),
        ("supervisor", supervisor_result),
    ):
        if result.get("status") == "not_run":
            print(f"{name} not_run")
        else:
            print(f"{name} {result['n_correct']}/{result['n_scored']} {result['accuracy']:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
