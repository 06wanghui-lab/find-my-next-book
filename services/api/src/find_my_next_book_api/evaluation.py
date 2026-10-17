import json
from pathlib import Path

from pydantic import BaseModel, Field


class EvaluationScenario(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    request: str
    reference_title: str
    positive_aspects: list[str]
    hard_exclusions: list[str]
    already_read: list[str]
    expected_ranking_signals: list[str]


def load_evaluation_scenarios(path: Path) -> list[EvaluationScenario]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EvaluationScenario.model_validate(item) for item in payload]
