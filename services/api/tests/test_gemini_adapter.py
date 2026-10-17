from collections import deque
from typing import Any

from find_my_next_book_api.agents.gemini import (
    GeminiRecommendationModel,
    _gemini_json_schema,
    _structured_method,
)
from find_my_next_book_api.recommendation.models import (
    CandidateExtractionResult,
    RequestedPublicationStatus,
    VerificationResult,
)


class TransientError(RuntimeError):
    code = 503
    status = "UNAVAILABLE"


class FakeStructuredClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = deque(responses)

    def invoke(self, messages: list[Any]) -> dict[str, Any]:
        result = self.responses.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class FakeGeminiClient:
    def __init__(self, responses: list[Any]) -> None:
        self.structured = FakeStructuredClient(responses)
        self.schema: Any = None
        self.method: str | None = None

    def with_structured_output(self, *, schema: Any, method: str) -> FakeStructuredClient:
        self.schema = schema
        self.method = method
        return self.structured


def profile_response() -> dict[str, Any]:
    return {
        "profile": {
            "genres": ["BL", "无限流"],
            "desired_traits": ["主角聪明"],
            "positive_aspects": ["副本设计烧脑", "群像写得好"],
            "hard_exclusions": ["感情线盖过剧情"],
            "publication_status": "any",
            "preferred_platforms": [],
            "reference_books": [
                {
                    "title": "我在无限游戏里封神",
                    "liked_aspects": ["副本设计烧脑", "群像"],
                }
            ],
            "already_read": ["地球上线"],
            "ranking_priorities": ["剧情", "感情线"],
        },
        "applied_feedback": [],
    }


def make_model(client: Any, **overrides: Any) -> GeminiRecommendationModel:
    return GeminiRecommendationModel(
        api_key="not-used",
        model="primary",
        fallback_model=overrides.get("fallback_model"),
        temperature=1.0,
        timeout_seconds=10,
        max_retries=overrides.get("max_retries", 0),
        retry_backoff_seconds=overrides.get("retry_backoff_seconds", 0.0),
        client=client,
        fallback_client=overrides.get("fallback_client"),
        sleeper=overrides.get("sleeper", lambda _delay: None),
    )


def test_profile_parsing_uses_native_structured_output() -> None:
    client = FakeGeminiClient([profile_response()])
    model = make_model(client)

    result = model.build_taste_profile(
        "我喜欢《我在无限游戏里封神》，想找烧脑BL无限流",
        None,
        None,
        ["地球上线"],
    )

    assert result.profile.genres == ["BL", "无限流"]
    assert result.profile.publication_status == RequestedPublicationStatus.ANY
    assert result.profile.reference_books[0].liked_aspects == ["副本设计烧脑", "群像"]
    assert client.method == "json_schema"
    assert client.schema is not None
    assert client.schema["title"] == "ProfileInterpretation"


def test_transient_503_retries_with_bounded_backoff() -> None:
    delays: list[float] = []
    client = FakeGeminiClient([TransientError("503 unavailable"), profile_response()])
    model = make_model(
        client,
        max_retries=2,
        retry_backoff_seconds=0.25,
        sleeper=delays.append,
    )

    result = model.build_taste_profile("想看无限流", None, None, [])

    assert result.profile.genres == ["BL", "无限流"]
    assert delays == [0.25]
    assert any("returned 503" in event for event in model.drain_events())


def test_fallback_model_is_used_after_primary_retries_exhausted() -> None:
    primary = FakeGeminiClient([TransientError("503"), TransientError("503")])
    fallback = FakeGeminiClient([profile_response()])
    model = make_model(
        primary,
        fallback_model="fallback",
        fallback_client=fallback,
        max_retries=1,
    )

    result = model.build_taste_profile("想看无限流", None, None, [])

    assert result.profile.reference_books[0].title == "我在无限游戏里封神"
    assert any("switching" in event for event in model.drain_events())


def test_llm_output_schemas_do_not_use_nullable_anyof() -> None:
    for schema_type in (CandidateExtractionResult, VerificationResult):
        schema = str(_gemini_json_schema(schema_type))
        assert "anyOf" not in schema
        assert "default" not in schema


def test_nested_outputs_use_supported_function_calling_mode() -> None:
    assert _structured_method(VerificationResult) == "function_calling"
    assert _structured_method(CandidateExtractionResult) == "function_calling"
