from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from find_my_next_book_api.agents.model import RecommendationModel
from find_my_next_book_api.providers.base import BookSearchProvider, SearchProviderError
from find_my_next_book_api.recommendation.grounding import (
    calculate_run_metrics,
    canonical_book_id,
    canonicalize_url,
    deduplicate_candidates,
    finalize_ranking,
    ground_verification,
    platform_for_url,
)
from find_my_next_book_api.recommendation.models import (
    BookCandidate,
    EvidenceRecord,
    EvidenceStage,
    ReaderTasteProfile,
    Recommendation,
    RunMetrics,
    SearchExecution,
    SearchQuery,
    TraceEvent,
    VerifiedBook,
)

OFFICIAL_DOMAINS = ["jjwxc.net", "gongzicp.com", "fanqienovel.com", "qidian.com"]


@dataclass(frozen=True)
class WorkflowLimits:
    initial_query_count: int = 2
    max_search_attempts: int = 2
    max_search_calls: int = 3
    min_candidates_for_verification: int = 3
    max_reference_books: int = 3
    max_verification_candidates: int = 5
    min_recommendations: int = 3
    max_recommendations: int = 5


class RecommendationState(TypedDict):
    request: str
    existing_profile: ReaderTasteProfile | None
    feedback: str | None
    additional_already_read: list[str]
    profile: ReaderTasteProfile | None
    references: list[VerifiedBook]
    pending_queries: list[SearchQuery]
    executions: list[SearchExecution]
    evidence: list[EvidenceRecord]
    candidates: list[BookCandidate]
    verified_candidates: list[VerifiedBook]
    recommendations: list[Recommendation]
    metrics: RunMetrics | None
    raw_candidate_count: int
    search_attempts: int
    needs_retry: bool
    retry_reason: str | None
    errors: list[str]
    fatal_error: str | None
    trace: list[TraceEvent]


def initial_state(
    request: str,
    *,
    existing_profile: ReaderTasteProfile | None = None,
    feedback: str | None = None,
    already_read: list[str] | None = None,
) -> RecommendationState:
    return RecommendationState(
        request=request,
        existing_profile=existing_profile,
        feedback=feedback,
        additional_already_read=already_read or [],
        profile=None,
        references=[],
        pending_queries=[],
        executions=[],
        evidence=[],
        candidates=[],
        verified_candidates=[],
        recommendations=[],
        metrics=None,
        raw_candidate_count=0,
        search_attempts=0,
        needs_retry=False,
        retry_reason=None,
        errors=[],
        fatal_error=None,
        trace=[],
    )


def build_recommendation_graph(
    *, model: RecommendationModel, search_provider: BookSearchProvider, limits: WorkflowLimits
):
    """Build a bounded graph that separates discovery from verification."""

    def build_taste_profile(state: RecommendationState) -> dict:
        try:
            interpretation = model.build_taste_profile(
                state["request"],
                state["existing_profile"],
                state["feedback"],
                state["additional_already_read"],
            )
            profile = interpretation.profile
            profile.reference_books = profile.reference_books[: limits.max_reference_books]
            return {
                "profile": profile,
                "trace": _model_trace(
                    state,
                    model,
                    "build_taste_profile",
                    f"{model.name} produced a structured taste profile",
                ),
            }
        except Exception as exc:
            return _fatal_update(state, model, "build_taste_profile", str(exc))

    def search_reference_records(state: RecommendationState) -> dict:
        profile = state["profile"]
        if profile is None:
            return _fatal_update(state, model, "search_reference_records", "Taste profile missing")
        requests = [
            (
                SearchQuery(
                    query=(
                        f"《{reference.title}》 "
                        f"{' '.join([*profile.genres[:2], *reference.liked_aspects[:2]])} "
                        "作者 作品信息 完结 连载 官方"
                    ),
                    rationale="解析参考小说并寻找原始平台记录",
                    include_domains=OFFICIAL_DOMAINS,
                ),
                EvidenceStage.REFERENCE_VERIFICATION,
                canonical_book_id(reference.title),
            )
            for reference in profile.reference_books
        ]
        if not requests:
            return {
                "trace": _append_trace(
                    state, "search_reference_records", "skip", "No reference novels supplied"
                )
            }
        return _search(state, requests, "search_reference_records")

    def verify_references(state: RecommendationState) -> dict:
        profile = state["profile"]
        if profile is None:
            return _fatal_update(state, model, "verify_references", "Taste profile missing")
        candidates = [
            BookCandidate(
                candidate_id=canonical_book_id(item.title),
                title=item.title,
                title_variants=[item.title],
            )
            for item in profile.reference_books
        ]
        if not candidates:
            return {
                "references": [],
                "trace": _append_trace(
                    state, "verify_references", "skip", "No reference novels to resolve"
                ),
            }
        reference_evidence = [
            item for item in state["evidence"] if item.stage == EvidenceStage.REFERENCE_VERIFICATION
        ]
        try:
            result = model.verify_books(candidates, reference_evidence)
            references = ground_verification(candidates, reference_evidence, result)
            return {
                "references": references,
                "trace": _model_trace(
                    state,
                    model,
                    "verify_references",
                    f"Resolved {len(references)} reference novel(s); "
                    "unverified status remains explicit",
                ),
            }
        except Exception as exc:
            return _fatal_update(state, model, "verify_references", str(exc))

    def plan_search(state: RecommendationState) -> dict:
        profile = state["profile"]
        if profile is None:
            return _fatal_update(state, model, "plan_search", "Taste profile missing")
        try:
            plan = model.plan_search(profile, state["references"], limits.initial_query_count)
            queries = plan.queries[: limits.initial_query_count]
            return {
                "pending_queries": queries,
                "trace": _model_trace(
                    state,
                    model,
                    "plan_search",
                    f"{model.name} planned {len(queries)} personalized discovery queries",
                ),
            }
        except Exception as exc:
            return _fatal_update(state, model, "plan_search", str(exc))

    def discover_candidates(state: RecommendationState) -> dict:
        discovery_calls = sum(item.stage == EvidenceStage.DISCOVERY for item in state["executions"])
        remaining = max(0, limits.max_search_calls - discovery_calls)
        queries = state["pending_queries"][:remaining]
        if not queries:
            return {
                "pending_queries": [],
                "search_attempts": state["search_attempts"] + 1,
                "errors": [*state["errors"], "No discovery search calls remain"],
                "trace": _append_trace(
                    state, "discover_candidates", "limit", "No discovery search calls remain"
                ),
            }
        update = _search(
            state,
            [(query, EvidenceStage.DISCOVERY, None) for query in queries],
            "discover_candidates",
        )
        update["pending_queries"] = []
        update["search_attempts"] = state["search_attempts"] + 1
        return update

    def extract_candidates(state: RecommendationState) -> dict:
        profile = state["profile"]
        if profile is None:
            return _fatal_update(state, model, "extract_candidates", "Taste profile missing")
        discovery_evidence = [
            item for item in state["evidence"] if item.stage == EvidenceStage.DISCOVERY
        ]
        if not discovery_evidence:
            return {
                "candidates": [],
                "raw_candidate_count": 0,
                "needs_retry": True,
                "retry_reason": "检索没有返回可提取的候选书籍",
                "trace": _append_trace(
                    state,
                    "extract_candidates",
                    "validation",
                    "No discovery evidence was available",
                ),
            }
        try:
            extraction = model.extract_candidates(profile, discovery_evidence)
            candidates = deduplicate_candidates(
                extraction.candidates,
                discovery_evidence,
                excluded_titles=[
                    *profile.already_read,
                    *(item.title for item in profile.reference_books),
                ],
            )
            needs_retry = extraction.needs_more_search or (
                len(candidates) < limits.min_candidates_for_verification
            )
            retry_reason = extraction.retry_reason
            if needs_retry and not retry_reason:
                retry_reason = f"仅提取到 {len(candidates)} 个唯一且有来源的候选"
            return {
                "candidates": candidates,
                "raw_candidate_count": len(extraction.candidates),
                "needs_retry": needs_retry,
                "retry_reason": retry_reason,
                "trace": _model_trace(
                    state,
                    model,
                    "extract_candidates",
                    f"Extracted {len(extraction.candidates)} raw candidates; "
                    f"retained {len(candidates)} canonical candidates",
                ),
            }
        except Exception as exc:
            return _fatal_update(state, model, "extract_candidates", str(exc))

    def revise_search(state: RecommendationState) -> dict:
        profile = state["profile"]
        if profile is None:
            return _fatal_update(state, model, "revise_search", "Taste profile missing")
        try:
            query = model.revise_search(
                profile,
                state["references"],
                [item for item in state["evidence"] if item.stage == EvidenceStage.DISCOVERY],
                [
                    item.query
                    for item in state["executions"]
                    if item.stage == EvidenceStage.DISCOVERY
                ],
                state["retry_reason"],
            )
            return {
                "pending_queries": [query],
                "needs_retry": False,
                "trace": _model_trace(
                    state,
                    model,
                    "revise_search",
                    f"{model.name} produced one bounded discovery retry",
                ),
            }
        except Exception as exc:
            return _fatal_update(state, model, "revise_search", str(exc))

    def search_candidate_records(state: RecommendationState) -> dict:
        requests = []
        for candidate in state["candidates"][: limits.max_verification_candidates]:
            author = f" {candidate.author_claim}" if candidate.author_claim else ""
            requests.append(
                (
                    SearchQuery(
                        query=f"《{candidate.title}》{author} 作者 作品信息 完结 连载 官方",
                        rationale="为候选书查找原始平台记录与客观元数据",
                        include_domains=OFFICIAL_DOMAINS,
                    ),
                    EvidenceStage.CANDIDATE_VERIFICATION,
                    candidate.candidate_id,
                )
            )
        if not requests:
            return {
                "trace": _append_trace(
                    state,
                    "search_candidate_records",
                    "skip",
                    "No candidates qualified for verification",
                )
            }
        return _search(state, requests, "search_candidate_records")

    def verify_candidates(state: RecommendationState) -> dict:
        candidates = state["candidates"][: limits.max_verification_candidates]
        if not candidates:
            return {
                "verified_candidates": [],
                "trace": _append_trace(
                    state, "verify_candidates", "skip", "No candidates to verify"
                ),
            }
        candidate_ids = {item.candidate_id for item in candidates}
        discovery_ids = {
            source_id for candidate in candidates for source_id in candidate.discovery_source_ids
        }
        relevant_evidence = [
            item
            for item in state["evidence"]
            if item.candidate_id in candidate_ids or item.source_id in discovery_ids
        ]
        try:
            result = model.verify_books(candidates, relevant_evidence)
            verified = ground_verification(candidates, relevant_evidence, result)
            return {
                "verified_candidates": verified,
                "trace": _model_trace(
                    state,
                    model,
                    "verify_candidates",
                    f"Verified {len(verified)} identities; "
                    f"{sum(item.official_url is not None for item in verified)} "
                    "official records found",
                ),
            }
        except Exception as exc:
            return _fatal_update(state, model, "verify_candidates", str(exc))

    def rank_candidates(state: RecommendationState) -> dict:
        profile = state["profile"]
        if profile is None:
            return _fatal_update(state, model, "rank_candidates", "Taste profile missing")
        if not state["verified_candidates"]:
            return {
                "recommendations": [],
                "metrics": calculate_run_metrics(
                    [],
                    state["executions"],
                    raw_candidate_count=state["raw_candidate_count"],
                    unique_candidate_count=len(state["candidates"]),
                    model_api_failures=_model_api_failure_count(state),
                ),
                "trace": _append_trace(
                    state,
                    "rank_candidates",
                    "validation",
                    "No verified candidates; returned fewer recommendations (zero)",
                ),
            }
        try:
            ranking = model.rank_candidates(
                profile,
                state["references"],
                state["verified_candidates"],
                limits.max_recommendations,
            )
            recommendations = finalize_ranking(
                profile,
                ranking,
                state["verified_candidates"],
                state["evidence"],
                max_recommendations=limits.max_recommendations,
            )
            trace = _model_trace(
                state,
                model,
                "rank_candidates",
                f"Evidence validation retained {len(recommendations)} "
                "recommendation(s); fewer are allowed",
            )
            return {
                "recommendations": recommendations,
                "metrics": calculate_run_metrics(
                    recommendations,
                    state["executions"],
                    raw_candidate_count=state["raw_candidate_count"],
                    unique_candidate_count=len(state["candidates"]),
                    model_api_failures=sum(
                        item.action == "retry/fallback" and "returned 503" in item.detail
                        for item in trace
                    ),
                ),
                "trace": trace,
            }
        except Exception as exc:
            return _fatal_update(state, model, "rank_candidates", str(exc))

    def _search(
        state: RecommendationState,
        requests: list[tuple[SearchQuery, EvidenceStage, str | None]],
        node: str,
    ) -> dict:
        evidence = list(state["evidence"])
        executions = list(state["executions"])
        errors = list(state["errors"])
        trace = list(state["trace"])
        for query, stage, candidate_id in requests:
            trace.append(
                TraceEvent(
                    node=node,
                    action="tool_call",
                    detail=f"{search_provider.name}: {query.query}",
                )
            )
            try:
                documents = search_provider.search(query)
                documents.sort(
                    key=lambda item: (
                        platform_for_url(item.url) is None,
                        -(item.score or 0.0),
                    )
                )
                known_urls = {
                    canonicalize_url(item.url)
                    for item in evidence
                    if item.stage == stage and item.candidate_id == candidate_id
                }
                added = 0
                for document in documents:
                    canonical_url = canonicalize_url(document.url)
                    if canonical_url in known_urls:
                        continue
                    known_urls.add(canonical_url)
                    evidence.append(
                        EvidenceRecord(
                            source_id=f"S{len(evidence) + 1}",
                            query=query.query,
                            stage=stage,
                            candidate_id=candidate_id,
                            **document.model_dump(),
                        )
                    )
                    added += 1
                executions.append(
                    SearchExecution(
                        query=query.query,
                        include_domains=query.include_domains,
                        result_count=added,
                        stage=stage,
                        candidate_id=candidate_id,
                    )
                )
            except SearchProviderError as exc:
                message = str(exc)
                errors.append(message)
                executions.append(
                    SearchExecution(
                        query=query.query,
                        include_domains=query.include_domains,
                        result_count=0,
                        error=message,
                        stage=stage,
                        candidate_id=candidate_id,
                    )
                )
        return {
            "evidence": evidence,
            "executions": executions,
            "errors": errors,
            "trace": trace,
        }

    def continue_or_stop(state: RecommendationState) -> Literal["continue", "stop"]:
        return "stop" if state["fatal_error"] else "continue"

    def after_profile(state: RecommendationState) -> Literal["references", "plan", "stop"]:
        if state["fatal_error"]:
            return "stop"
        profile = state["profile"]
        return "references" if profile and profile.reference_books else "plan"

    def retry_or_verify(state: RecommendationState) -> Literal["retry", "verify", "stop"]:
        if state["fatal_error"]:
            return "stop"
        discovery_calls = sum(item.stage == EvidenceStage.DISCOVERY for item in state["executions"])
        if (
            state["needs_retry"]
            and state["search_attempts"] < limits.max_search_attempts
            and discovery_calls < limits.max_search_calls
        ):
            return "retry"
        return "verify"

    builder = StateGraph(RecommendationState)
    builder.add_node("build_taste_profile", build_taste_profile)
    builder.add_node("search_reference_records", search_reference_records)
    builder.add_node("verify_references", verify_references)
    builder.add_node("plan_search", plan_search)
    builder.add_node("discover_candidates", discover_candidates)
    builder.add_node("extract_candidates", extract_candidates)
    builder.add_node("revise_search", revise_search)
    builder.add_node("search_candidate_records", search_candidate_records)
    builder.add_node("verify_candidates", verify_candidates)
    builder.add_node("rank_candidates", rank_candidates)
    builder.add_edge(START, "build_taste_profile")
    builder.add_conditional_edges(
        "build_taste_profile",
        after_profile,
        {"references": "search_reference_records", "plan": "plan_search", "stop": END},
    )
    builder.add_edge("search_reference_records", "verify_references")
    builder.add_conditional_edges(
        "verify_references", continue_or_stop, {"continue": "plan_search", "stop": END}
    )
    builder.add_conditional_edges(
        "plan_search", continue_or_stop, {"continue": "discover_candidates", "stop": END}
    )
    builder.add_edge("discover_candidates", "extract_candidates")
    builder.add_conditional_edges(
        "extract_candidates",
        retry_or_verify,
        {"retry": "revise_search", "verify": "search_candidate_records", "stop": END},
    )
    builder.add_conditional_edges(
        "revise_search", continue_or_stop, {"continue": "discover_candidates", "stop": END}
    )
    builder.add_edge("search_candidate_records", "verify_candidates")
    builder.add_conditional_edges(
        "verify_candidates", continue_or_stop, {"continue": "rank_candidates", "stop": END}
    )
    builder.add_edge("rank_candidates", END)
    return builder.compile()


def _append_trace(
    state: RecommendationState, node: str, action: str, detail: str
) -> list[TraceEvent]:
    return [*state["trace"], TraceEvent(node=node, action=action, detail=detail)]


def _model_api_failure_count(state: RecommendationState) -> int:
    return sum(
        event.action == "retry/fallback" and "returned 503" in event.detail
        for event in state["trace"]
    )


def _model_trace(
    state: RecommendationState,
    model: RecommendationModel,
    node: str,
    detail: str,
) -> list[TraceEvent]:
    trace = list(state["trace"])
    for event in model.drain_events():
        trace.append(TraceEvent(node=node, action="retry/fallback", detail=event))
    trace.append(TraceEvent(node=node, action="model_call", detail=detail))
    return trace


def _fatal_update(
    state: RecommendationState,
    model: RecommendationModel,
    node: str,
    message: str,
) -> dict:
    trace = list(state["trace"])
    for event in model.drain_events():
        trace.append(TraceEvent(node=node, action="retry/fallback", detail=event))
    trace.append(TraceEvent(node=node, action="error", detail=message))
    return {
        "fatal_error": message,
        "errors": [*state["errors"], message],
        "trace": trace,
    }
