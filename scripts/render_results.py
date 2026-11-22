import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "results" / "routing_eval.json"


def format_accuracy(value) -> str:
    if value is None:
        return "not run"
    return f"{float(value) * 100:.2f}%"


def format_categories(values) -> str:
    if not values:
        return "not run"
    return ", ".join(f"{category}: {format_accuracy(accuracy)}" for category, accuracy in values.items())


def main() -> None:
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    methods = [
        ("keyword", data.get("keyword")),
        ("llm_classifier", data.get("llm_classifier")),
        ("supervisor", data.get("supervisor")),
    ]

    print("| method | n_correct/n_scored | accuracy | per-category |")
    print("|---|---:|---:|---|")
    for method, result in methods:
        if not result or result.get("status") == "not_run":
            print(f"| {method} | not run | not run | not run |")
            continue
        n_correct = result.get("n_correct")
        n_scored = result.get("n_scored")
        accuracy = result.get("accuracy")
        per_category = result.get("accuracy_by_category", {})
        print(
            f"| {method} | {n_correct}/{n_scored} | {format_accuracy(accuracy)} | "
            f"{format_categories(per_category)} |"
        )


if __name__ == "__main__":
    main()
