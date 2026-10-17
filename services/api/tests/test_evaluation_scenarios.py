from pathlib import Path

from find_my_next_book_api.evaluation import load_evaluation_scenarios
from find_my_next_book_api.recommendation.grounding import calculate_run_metrics
from find_my_next_book_api.recommendation.models import SearchExecution

SCENARIOS = Path(__file__).parents[1] / "evaluation" / "personalization_scenarios.json"


def test_same_reference_scenarios_encode_meaningfully_different_tastes() -> None:
    puzzle, relationship = load_evaluation_scenarios(SCENARIOS)

    assert puzzle.reference_title == relationship.reference_title
    assert set(puzzle.positive_aspects).isdisjoint(relationship.positive_aspects)
    assert puzzle.already_read != relationship.already_read
    assert "解谜" in puzzle.expected_ranking_signals
    assert "感情线" in relationship.expected_ranking_signals


def test_run_metrics_track_duplicate_and_api_failure_rates() -> None:
    metrics = calculate_run_metrics(
        [],
        [
            SearchExecution(query="one", result_count=2),
            SearchExecution(query="two", result_count=0, error="503"),
        ],
        raw_candidate_count=4,
        unique_candidate_count=3,
    )

    assert metrics.duplicate_rate == 0.25
    assert metrics.api_failures == 1
    assert metrics.raw_candidates == 4
    assert metrics.unique_candidates == 3
