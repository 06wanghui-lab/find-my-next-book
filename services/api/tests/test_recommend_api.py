from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from find_my_next_book_api.agents.runtime import LiveWorkflow
from find_my_next_book_api.api.routes.recommend import get_recommendation_runtime
from find_my_next_book_api.main import app
from find_my_next_book_api.recommendation.models import (
    CandidatePublicationStatus,
    EvidenceCitation,
    ReaderTasteProfile,
    Recommendation,
    RunMetrics,
    VerificationStatus,
)


class FakeGraph:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def invoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((state, config))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture(autouse=True)
def clear_dependency_override() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def runtime_for(result: dict[str, Any] | Exception) -> tuple[LiveWorkflow, FakeGraph]:
    graph = FakeGraph(result)
    runtime = LiveWorkflow(
        graph=graph,
        model_name="Mock Gemini",
        search_provider_name="Mock Tavily",
    )
    app.dependency_overrides[get_recommendation_runtime] = lambda: runtime
    return runtime, graph


def successful_state(recommendations: list[Recommendation]) -> dict[str, Any]:
    return {
        "profile": ReaderTasteProfile(
            genres=["BL", "无限流"],
            positive_aspects=["副本烧脑"],
        ),
        "recommendations": recommendations,
        "metrics": RunMetrics(
            canonical_link_validity=1,
            metadata_verification_rate=1,
            hard_filter_compliance=1,
            duplicate_rate=0,
            api_failures=0,
            raw_candidates=1,
            unique_candidates=1,
        ),
        "errors": [],
        "fatal_error": None,
    }


def test_recommend_endpoint_runs_existing_graph_and_serializes_results() -> None:
    recommendation = Recommendation(
        rank=1,
        title="测试小说",
        author="测试作者",
        platform="晋江文学城",
        publication_status=CandidatePublicationStatus.COMPLETED,
        relevance_score=88,
        match_reasons=["已验证元数据：符合无限流偏好"],
        uncertainties=[],
        sources=[
            EvidenceCitation(
                source_id="S1",
                title="测试小说_晋江文学城",
                url="https://www.jjwxc.net/onebook.php?novelid=1",
                excerpt="测试证据",
            )
        ],
        official_url="https://www.jjwxc.net/onebook.php?novelid=1",
        verification_status=VerificationStatus.OFFICIAL,
    )
    _, graph = runtime_for(successful_state([recommendation]))
    client = TestClient(app)

    response = client.post("/api/recommend", json={"request": "想看烧脑BL无限流"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommendations"][0]["title"] == "测试小说"
    assert payload["recommendations"][0]["verification_status"] == "official"
    assert payload["providers"] == {"model": "Mock Gemini", "search": "Mock Tavily"}
    assert graph.calls[0][0]["request"] == "想看烧脑BL无限流"
    assert graph.calls[0][1] == {"recursion_limit": 24}


def test_recommend_endpoint_allows_grounded_empty_result() -> None:
    runtime_for(successful_state([]))
    client = TestClient(app)

    response = client.post("/api/recommend", json={"request": "非常冷门的小说要求"})

    assert response.status_code == 200
    assert response.json()["recommendations"] == []


def test_recommend_endpoint_maps_gemini_quota_to_429() -> None:
    state = successful_state([])
    state["fatal_error"] = "429 RESOURCE_EXHAUSTED: Gemini quota exceeded"
    runtime_for(state)
    client = TestClient(app)

    response = client.post("/api/recommend", json={"request": "想看无限流小说"})

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "model_quota_exceeded"


def test_recommend_endpoint_maps_unexpected_agent_failure_to_502() -> None:
    runtime_for(RuntimeError("provider disconnected"))
    client = TestClient(app)

    response = client.post("/api/recommend", json={"request": "想看无限流小说"})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "agent_unavailable"
