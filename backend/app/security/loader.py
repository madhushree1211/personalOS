from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .engine import Mitre


class DetectionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    event: str = Field(min_length=1)
    events: list[str] | None = None
    group_by: Literal["user_id", "ip"]
    threshold: int = Field(gt=0)
    window_seconds: int = Field(gt=0)
    severity: Literal["low", "medium", "high"]
    mitre: Mitre


def load_rules(directory: str | Path | None = None) -> list[DetectionRule]:
    rules_dir = Path(directory) if directory is not None else Path(__file__).parent / "rules"
    rules: list[DetectionRule] = []
    for path in sorted(rules_dir.glob("*.yml")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
            rules.append(DetectionRule.model_validate(data))
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in detection rule {path.name}: {exc}") from exc
        except ValidationError as exc:
            raise ValueError(f"Invalid detection rule {path.name}: {exc}") from exc
    return rules
