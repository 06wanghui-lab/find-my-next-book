from typing import Protocol

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


class ModelProviderError(RuntimeError):
    """Raised when the configured LLM cannot complete a structured task."""


class RecommendationModel(Protocol):
    name: str

    def build_taste_profile(
        self,
        request: str,
        existing_profile: ReaderTasteProfile | None,
        feedback: str | None,
        already_read: list[str],
    ) -> ProfileInterpretation: ...

    def plan_search(
        self,
        profile: ReaderTasteProfile,
        references: list[VerifiedBook],
        max_queries: int,
    ) -> SearchPlan: ...

    def extract_candidates(
        self,
        profile: ReaderTasteProfile,
        evidence: list[EvidenceRecord],
    ) -> CandidateExtractionResult: ...

    def verify_books(
        self,
        candidates: list[BookCandidate],
        evidence: list[EvidenceRecord],
    ) -> VerificationResult: ...

    def rank_candidates(
        self,
        profile: ReaderTasteProfile,
        references: list[VerifiedBook],
        candidates: list[VerifiedBook],
        max_recommendations: int,
    ) -> RankingResult: ...

    def revise_search(
        self,
        profile: ReaderTasteProfile,
        references: list[VerifiedBook],
        evidence: list[EvidenceRecord],
        previous_queries: list[str],
        retry_reason: str | None,
    ) -> SearchQuery: ...

    def drain_events(self) -> list[str]: ...
