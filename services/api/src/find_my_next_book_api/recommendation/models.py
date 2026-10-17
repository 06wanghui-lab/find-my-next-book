from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class RequestedPublicationStatus(StrEnum):
    COMPLETED = "completed"
    ONGOING = "ongoing"
    ANY = "any"


class CandidatePublicationStatus(StrEnum):
    COMPLETED = "completed"
    ONGOING = "ongoing"
    UNKNOWN = "unknown"


class EvidenceStage(StrEnum):
    REFERENCE_VERIFICATION = "reference_verification"
    DISCOVERY = "discovery"
    CANDIDATE_VERIFICATION = "candidate_verification"


class VerificationStatus(StrEnum):
    OFFICIAL = "official"
    CORROBORATED = "corroborated"
    UNVERIFIED = "unverified"


class ReasonKind(StrEnum):
    VERIFIED_METADATA = "verified_metadata"
    ATTRIBUTED_READER_OPINION = "attributed_reader_opinion"
    PREFERENCE_INFERENCE = "preference_inference"


class PreferenceBrief(BaseModel):
    original_request: str = Field(min_length=1)
    genres: list[str] = Field(default_factory=list, max_length=8)
    themes: list[str] = Field(default_factory=list, max_length=12)
    excluded_elements: list[str] = Field(default_factory=list, max_length=12)
    publication_status: RequestedPublicationStatus = RequestedPublicationStatus.ANY
    preferred_platforms: list[str] = Field(default_factory=list, max_length=6)
    liked_books: list[str] = Field(default_factory=list, max_length=8)
    additional_constraints: list[str] = Field(default_factory=list, max_length=10)


class ReferencePreference(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    liked_aspects: list[str] = Field(default_factory=list, max_length=10)


class ReaderTasteProfile(BaseModel):
    """Session-level taste state; intentionally separate from raw chat history."""

    genres: list[str] = Field(default_factory=list, max_length=10)
    desired_traits: list[str] = Field(default_factory=list, max_length=16)
    positive_aspects: list[str] = Field(default_factory=list, max_length=16)
    hard_exclusions: list[str] = Field(default_factory=list, max_length=16)
    publication_status: RequestedPublicationStatus = RequestedPublicationStatus.ANY
    preferred_platforms: list[str] = Field(default_factory=list, max_length=6)
    reference_books: list[ReferencePreference] = Field(default_factory=list, max_length=6)
    already_read: list[str] = Field(default_factory=list, max_length=50)
    ranking_priorities: list[str] = Field(default_factory=list, max_length=10)


class ProfileInterpretation(BaseModel):
    profile: ReaderTasteProfile
    applied_feedback: list[str] = Field(default_factory=list, max_length=10)


class SearchQuery(BaseModel):
    query: str = Field(min_length=2, max_length=240)
    rationale: str = Field(min_length=1, max_length=300)
    include_domains: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("include_domains")
    @classmethod
    def normalize_domains(cls, domains: list[str]) -> list[str]:
        normalized: list[str] = []
        for domain in domains:
            value = domain.strip().lower().removeprefix("www.")
            if value and "/" not in value and value not in normalized:
                normalized.append(value)
        return normalized


class SearchPlan(BaseModel):
    queries: list[SearchQuery] = Field(min_length=1, max_length=3)


class SearchDocument(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    url: str
    content: str = Field(default="", max_length=1800)
    score: float | None = None

    @field_validator("url")
    @classmethod
    def require_http_url(cls, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("search result URL must use http or https")
        return url


class EvidenceRecord(SearchDocument):
    source_id: str = Field(pattern=r"^S\d+$")
    query: str
    stage: EvidenceStage = EvidenceStage.DISCOVERY
    candidate_id: str | None = None


class SearchExecution(BaseModel):
    query: str
    include_domains: list[str] = Field(default_factory=list)
    result_count: int = Field(ge=0)
    error: str | None = None
    stage: EvidenceStage = EvidenceStage.DISCOVERY
    candidate_id: str | None = None


class ReaderOpinion(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    source_ids: list[str] = Field(min_length=1, max_length=6)


class BookCandidate(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    title_variants: list[str] = Field(default_factory=list, max_length=8)
    # Empty string means absent. Gemini native structured output rejects nullable
    # fields for some schemas, so LLM-facing models avoid Optional values.
    author_claim: str = Field(default="", max_length=100)
    discovery_source_ids: list[str] = Field(default_factory=list, max_length=10)
    reader_opinions: list[ReaderOpinion] = Field(default_factory=list, max_length=10)


class CandidateExtractionResult(BaseModel):
    candidates: list[BookCandidate] = Field(max_length=20)
    needs_more_search: bool = False
    retry_reason: str = Field(default="", max_length=400)


class VerificationClaim(BaseModel):
    candidate_id: str
    official_title: str = Field(default="", max_length=200)
    author: str = Field(default="", max_length=100)
    official_source_id: str = ""
    metadata_source_ids: list[str] = Field(default_factory=list, max_length=8)
    genre_tags: list[str] = Field(default_factory=list, max_length=10)
    publication_status: CandidatePublicationStatus = CandidatePublicationStatus.UNKNOWN


class VerificationResult(BaseModel):
    books: list[VerificationClaim] = Field(max_length=20)


class VerifiedBook(BaseModel):
    candidate_id: str
    title: str
    title_variants: list[str] = Field(default_factory=list)
    author: str | None = None
    platform: str | None = None
    official_url: str | None = None
    genre_tags: list[str] = Field(default_factory=list)
    publication_status: CandidatePublicationStatus = CandidatePublicationStatus.UNKNOWN
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    discovery_source_ids: list[str] = Field(default_factory=list)
    identity_source_ids: list[str] = Field(default_factory=list)
    metadata_source_ids: list[str] = Field(default_factory=list)
    reader_opinions: list[ReaderOpinion] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class RankingReason(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    kind: ReasonKind
    source_ids: list[str] = Field(default_factory=list, max_length=6)


class RankedBook(BaseModel):
    candidate_id: str
    preference_fit_score: float = Field(ge=0, le=100)
    reasons: list[RankingReason] = Field(min_length=1, max_length=8)
    hard_constraint_violations: list[str] = Field(default_factory=list, max_length=8)


class RankingResult(BaseModel):
    books: list[RankedBook] = Field(max_length=20)


class EvaluationCandidate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str | None = Field(default=None, max_length=100)
    source_ids: list[str] = Field(min_length=1, max_length=6)
    claimed_platform: str | None = Field(default=None, max_length=60)
    claimed_publication_status: CandidatePublicationStatus = CandidatePublicationStatus.UNKNOWN
    relevance_score: float = Field(ge=0, le=100)
    match_reasons: list[str] = Field(min_length=1, max_length=5)
    uncertainties: list[str] = Field(default_factory=list, max_length=6)


class EvaluationResult(BaseModel):
    candidates: list[EvaluationCandidate] = Field(default_factory=list, max_length=10)
    needs_more_search: bool = False
    retry_reason: str | None = Field(default=None, max_length=400)


class EvidenceCitation(BaseModel):
    source_id: str
    title: str
    url: str
    excerpt: str


class Recommendation(BaseModel):
    rank: int = Field(ge=1)
    title: str
    author: str | None = None
    platform: str | None = None
    publication_status: CandidatePublicationStatus
    relevance_score: float = Field(ge=0, le=100)
    match_reasons: list[str]
    uncertainties: list[str]
    sources: list[EvidenceCitation] = Field(min_length=1)
    canonical_id: str | None = None
    official_url: str | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    genre_tags: list[str] = Field(default_factory=list)
    reasons: list[RankingReason] = Field(default_factory=list)
    hard_constraint_violations: list[str] = Field(default_factory=list)


class RunMetrics(BaseModel):
    canonical_link_validity: float = Field(ge=0, le=1)
    metadata_verification_rate: float = Field(ge=0, le=1)
    hard_filter_compliance: float = Field(ge=0, le=1)
    duplicate_rate: float = Field(ge=0, le=1)
    api_failures: int = Field(ge=0)
    raw_candidates: int = Field(ge=0)
    unique_candidates: int = Field(ge=0)


class TraceEvent(BaseModel):
    node: str
    action: str
    detail: str
