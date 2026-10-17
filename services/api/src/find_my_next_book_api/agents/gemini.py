import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from find_my_next_book_api.agents.model import ModelProviderError
from find_my_next_book_api.agents.prompts import (
    CANDIDATE_EXTRACTION_SYSTEM_PROMPT,
    PROFILE_SYSTEM_PROMPT,
    RANKING_SYSTEM_PROMPT,
    REVISE_SEARCH_SYSTEM_PROMPT,
    SEARCH_PLAN_SYSTEM_PROMPT,
    VERIFICATION_SYSTEM_PROMPT,
)
from find_my_next_book_api.recommendation.models import (
    BookCandidate,
    CandidateExtractionResult,
    EvidenceRecord,
    ProfileInterpretation,
    RankingResult,
    ReaderTasteProfile,
    SearchPlan,
    SearchQuery,
    VerificationResult,
    VerifiedBook,
)

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


@dataclass(frozen=True)
class _Endpoint:
    model_name: str
    client: Any


class GeminiRecommendationModel:
    """Gemini adapter with explicit 503 retry/backoff and optional model fallback."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        fallback_model: str | None,
        temperature: float,
        timeout_seconds: int,
        max_retries: int,
        retry_backoff_seconds: float,
        client: Any | None = None,
        fallback_client: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        primary = client or self._create_client(
            api_key=api_key,
            model=model,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
        self._endpoints = [_Endpoint(model_name=model, client=primary)]
        if fallback_model:
            fallback = fallback_client or self._create_client(
                api_key=api_key,
                model=fallback_model,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
            )
            self._endpoints.append(_Endpoint(model_name=fallback_model, client=fallback))
        self.name = "Gemini (" + " → ".join(item.model_name for item in self._endpoints) + ")"
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleeper
        self._events: list[str] = []

    @staticmethod
    def _create_client(
        *,
        api_key: str,
        model: str,
        temperature: float,
        timeout_seconds: int,
    ) -> ChatGoogleGenerativeAI:
        # SDK retries are disabled so retry count/backoff remain observable and bounded here.
        return ChatGoogleGenerativeAI(
            model=model,
            api_key=api_key,
            temperature=temperature,
            request_timeout=timeout_seconds,
            retries=0,
        )

    def build_taste_profile(
        self,
        request: str,
        existing_profile: ReaderTasteProfile | None,
        feedback: str | None,
        already_read: list[str],
    ) -> ProfileInterpretation:
        payload = {
            "current_request": request,
            "existing_structured_profile": (
                existing_profile.model_dump(mode="json") if existing_profile else None
            ),
            "new_feedback": feedback,
            "additional_already_read": already_read,
        }
        return self._invoke_structured(
            ProfileInterpretation,
            PROFILE_SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
            operation="taste profile interpretation",
        )

    def plan_search(
        self,
        profile: ReaderTasteProfile,
        references: list[VerifiedBook],
        max_queries: int,
    ) -> SearchPlan:
        payload = {
            "maximum_queries": max_queries,
            "taste_profile": profile.model_dump(mode="json"),
            "resolved_reference_books": [item.model_dump(mode="json") for item in references],
        }
        return self._invoke_structured(
            SearchPlan,
            SEARCH_PLAN_SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
            operation="personalized search planning",
        )

    def extract_candidates(
        self,
        profile: ReaderTasteProfile,
        evidence: list[EvidenceRecord],
    ) -> CandidateExtractionResult:
        payload = {
            "taste_profile": profile.model_dump(mode="json"),
            "discovery_evidence": [item.model_dump(mode="json") for item in evidence],
        }
        return self._invoke_structured(
            CandidateExtractionResult,
            CANDIDATE_EXTRACTION_SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
            operation="candidate extraction",
        )

    def verify_books(
        self,
        candidates: list[BookCandidate],
        evidence: list[EvidenceRecord],
    ) -> VerificationResult:
        payload = {
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "verification_evidence": [item.model_dump(mode="json") for item in evidence],
        }
        return self._invoke_structured(
            VerificationResult,
            VERIFICATION_SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
            operation="book metadata verification",
        )

    def rank_candidates(
        self,
        profile: ReaderTasteProfile,
        references: list[VerifiedBook],
        candidates: list[VerifiedBook],
        max_recommendations: int,
    ) -> RankingResult:
        payload = {
            "maximum_recommendations": max_recommendations,
            "taste_profile": profile.model_dump(mode="json"),
            "resolved_references": [item.model_dump(mode="json") for item in references],
            "verified_candidates": [item.model_dump(mode="json") for item in candidates],
        }
        return self._invoke_structured(
            RankingResult,
            RANKING_SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
            operation="personalized candidate ranking",
        )

    def revise_search(
        self,
        profile: ReaderTasteProfile,
        references: list[VerifiedBook],
        evidence: list[EvidenceRecord],
        previous_queries: list[str],
        retry_reason: str | None,
    ) -> SearchQuery:
        payload = {
            "taste_profile": profile.model_dump(mode="json"),
            "resolved_references": [item.model_dump(mode="json") for item in references],
            "previous_queries": previous_queries,
            "retry_reason": retry_reason,
            "existing_result_titles": [item.title for item in evidence],
        }
        return self._invoke_structured(
            SearchQuery,
            REVISE_SEARCH_SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
            operation="search revision",
        )

    def drain_events(self) -> list[str]:
        events = self._events
        self._events = []
        return events

    def _invoke_structured(
        self,
        schema: type[StructuredOutput],
        system_prompt: str,
        user_content: str,
        *,
        operation: str,
    ) -> StructuredOutput:
        last_error: Exception | None = None
        for endpoint_index, endpoint in enumerate(self._endpoints):
            for attempt in range(self._max_retries + 1):
                try:
                    method = _structured_method(schema)
                    structured_client = endpoint.client.with_structured_output(
                        schema=(
                            schema if method == "function_calling" else _gemini_json_schema(schema)
                        ),
                        method=method,
                    )
                    response = structured_client.invoke(
                        [("system", system_prompt), ("human", user_content)]
                    )
                    if attempt or endpoint_index:
                        self._events.append(
                            f"{operation} succeeded with {endpoint.model_name} "
                            f"after attempt {attempt + 1}"
                        )
                    return schema.model_validate(response)
                except Exception as exc:  # SDK error classes vary across releases
                    last_error = exc
                    transient = _is_transient_503(exc)
                    if transient and attempt < self._max_retries:
                        delay = self._retry_backoff_seconds * (2**attempt)
                        self._events.append(
                            f"{operation}: {endpoint.model_name} returned 503; "
                            f"retrying in {delay:g}s ({attempt + 1}/{self._max_retries})"
                        )
                        if delay:
                            self._sleep(delay)
                        continue
                    break

            if endpoint_index + 1 < len(self._endpoints):
                next_model = self._endpoints[endpoint_index + 1].model_name
                self._events.append(
                    f"{operation}: switching from {endpoint.model_name} to fallback {next_model}"
                )

        assert last_error is not None
        raise ModelProviderError(f"Gemini {operation} failed: {last_error}") from last_error


def _is_transient_503(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    status = str(getattr(exc, "status", "")).upper()
    message = str(exc).upper()
    return (
        code == 503
        or status == "UNAVAILABLE"
        or ("503" in message and ("UNAVAILABLE" in message or "SERVICE" in message))
    )


def _gemini_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Keep runtime defaults while removing defaults rejected by Gemini schemas."""
    result = schema.model_json_schema()

    def strip_defaults(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            for child in value.values():
                strip_defaults(child)
        elif isinstance(value, list):
            for child in value:
                strip_defaults(child)

    strip_defaults(result)
    return result


def _structured_method(schema: type[BaseModel]) -> str:
    """Use tool calling for nested schemas rejected by Gemini JSON-schema mode."""
    if schema in {CandidateExtractionResult, VerificationResult, RankingResult}:
        return "function_calling"
    return "json_schema"
