from collections import deque

from find_my_next_book_api.agents.workflow import (
    WorkflowLimits,
    build_recommendation_graph,
    initial_state,
)
from find_my_next_book_api.recommendation.models import (
    BookCandidate,
    CandidateExtractionResult,
    CandidatePublicationStatus,
    ProfileInterpretation,
    RankedBook,
    RankingReason,
    RankingResult,
    ReaderOpinion,
    ReaderTasteProfile,
    ReasonKind,
    ReferencePreference,
    RequestedPublicationStatus,
    SearchDocument,
    SearchPlan,
    SearchQuery,
    VerificationClaim,
    VerificationResult,
)


class FakeRecommendationModel:
    name = "Fake structured model"

    def __init__(self, extractions: list[CandidateExtractionResult]) -> None:
        self.extractions = deque(extractions)
        self.revise_calls = 0

    def drain_events(self) -> list[str]:
        return []

    def build_taste_profile(
        self, request: str, existing_profile, feedback, already_read: list[str]
    ) -> ProfileInterpretation:
        return ProfileInterpretation(
            profile=ReaderTasteProfile(
                genres=["古言"],
                desired_traits=["聪明女主", "权谋"],
                hard_exclusions=["虐文"],
                publication_status=RequestedPublicationStatus.COMPLETED,
                already_read=already_read,
            )
        )

    def plan_search(self, profile, references, max_queries: int) -> SearchPlan:
        return SearchPlan(
            queries=[SearchQuery(query="古言 权谋 聪明女主 完结", rationale="initial")]
        )

    def extract_candidates(self, profile, evidence) -> CandidateExtractionResult:
        return self.extractions.popleft()

    def verify_books(self, candidates, evidence) -> VerificationResult:
        claims = []
        for candidate in candidates:
            official = next(
                (
                    item
                    for item in evidence
                    if item.candidate_id == candidate.candidate_id and "onebook.php" in item.url
                ),
                None,
            )
            claims.append(
                VerificationClaim(
                    candidate_id=candidate.candidate_id,
                    official_title=candidate.title,
                    author=candidate.author_claim,
                    official_source_id=official.source_id if official else None,
                    metadata_source_ids=[official.source_id] if official else [],
                    genre_tags=["古言", "权谋"],
                    publication_status=CandidatePublicationStatus.COMPLETED,
                )
            )
        return VerificationResult(books=claims)

    def rank_candidates(
        self, profile, references, candidates, max_recommendations: int
    ) -> RankingResult:
        return RankingResult(
            books=[
                RankedBook(
                    candidate_id=item.candidate_id,
                    preference_fit_score=92,
                    reasons=[
                        RankingReason(
                            text="官方页面确认古言权谋且已完结",
                            kind=ReasonKind.VERIFIED_METADATA,
                            source_ids=item.metadata_source_ids,
                        ),
                        RankingReason(
                            text="推荐来源认为女主聪明且基调不虐",
                            kind=ReasonKind.ATTRIBUTED_READER_OPINION,
                            source_ids=item.discovery_source_ids,
                        ),
                    ],
                )
                for item in candidates
            ]
        )

    def revise_search(
        self, profile, references, evidence, previous_queries, retry_reason
    ) -> SearchQuery:
        self.revise_calls += 1
        return SearchQuery(query="古言 朝堂 女主谋略 完结", rationale="retry")


class FakeSearchProvider:
    name = "Fake search tool"

    def __init__(self, discovery_results: dict[str, list[SearchDocument]]) -> None:
        self.discovery_results = discovery_results
        self.calls: list[str] = []

    def search(self, request: SearchQuery) -> list[SearchDocument]:
        self.calls.append(request.query)
        if "作品信息" in request.query:
            title = request.query.split("《", 1)[1].split("》", 1)[0]
            return [official_document(title)]
        return self.discovery_results.get(request.query, [])


def discovery_document(title: str) -> SearchDocument:
    return SearchDocument(
        title=f"古言推荐：《{title}》",
        url=f"https://reviews.example/{len(title)}",
        content=f"《{title}》作者测试作者，读者认为女主聪明、权谋精彩且不虐。",
        score=0.8,
    )


def official_document(title: str) -> SearchDocument:
    return SearchDocument(
        title=f"《{title}》_测试作者_晋江文学城",
        url=f"https://www.jjwxc.net/onebook.php?novelid={len(title)}",
        content=f"《{title}》作者测试作者，古言、权谋，全文完结。",
        score=0.95,
    )


def extracted(title: str, source_id: str) -> CandidateExtractionResult:
    return CandidateExtractionResult(
        candidates=[
            BookCandidate(
                candidate_id="model-id",
                title=title,
                author_claim="测试作者",
                discovery_source_ids=[source_id],
                reader_opinions=[
                    ReaderOpinion(text="读者认为女主聪明且不虐", source_ids=[source_id])
                ],
            )
        ]
    )


def limits() -> WorkflowLimits:
    return WorkflowLimits(
        initial_query_count=1,
        min_candidates_for_verification=1,
        min_recommendations=1,
        max_verification_candidates=2,
    )


def test_graph_discovers_verifies_and_ranks_separately() -> None:
    model = FakeRecommendationModel([extracted("测试书", "S1")])
    search = FakeSearchProvider({"古言 权谋 聪明女主 完结": [discovery_document("测试书")]})
    graph = build_recommendation_graph(model=model, search_provider=search, limits=limits())

    result = graph.invoke(initial_state("推荐已完结古言权谋，女主聪明，不要虐文"))

    assert result["profile"].hard_exclusions == ["虐文"]
    assert [item.title for item in result["recommendations"]] == ["测试书"]
    assert result["recommendations"][0].official_url is not None
    assert result["metrics"].canonical_link_validity == 1.0
    assert [item.stage.value for item in result["executions"]] == [
        "discovery",
        "candidate_verification",
    ]


def test_graph_takes_only_one_discovery_retry() -> None:
    model = FakeRecommendationModel(
        [
            CandidateExtractionResult(
                candidates=[], needs_more_search=True, retry_reason="too generic"
            ),
            extracted("补充结果", "S2"),
        ]
    )
    search = FakeSearchProvider(
        {
            "古言 权谋 聪明女主 完结": [
                SearchDocument(
                    title="泛化推荐列表",
                    url="https://reviews.example/generic",
                    content="没有具体书名。",
                )
            ],
            "古言 朝堂 女主谋略 完结": [discovery_document("补充结果")],
        }
    )
    graph = build_recommendation_graph(model=model, search_provider=search, limits=limits())

    result = graph.invoke(initial_state("想看古言权谋"))

    assert result["search_attempts"] == 2
    assert model.revise_calls == 1
    assert [item.title for item in result["recommendations"]] == ["补充结果"]
    assert [event.node for event in result["trace"]].count("revise_search") == 1


def test_already_read_book_is_excluded_before_verification() -> None:
    model = FakeRecommendationModel([extracted("测试书", "S1"), extracted("测试书", "S1")])
    search = FakeSearchProvider({"古言 权谋 聪明女主 完结": [discovery_document("测试书")]})
    graph = build_recommendation_graph(model=model, search_provider=search, limits=limits())

    result = graph.invoke(initial_state("找古言", already_read=["《测试书》"]))

    assert result["candidates"] == []
    assert result["verified_candidates"] == []
    assert result["recommendations"] == []
    assert result["metrics"].hard_filter_compliance == 1.0


class ScenarioAwareModel(FakeRecommendationModel):
    def build_taste_profile(
        self, request: str, existing_profile, feedback, already_read: list[str]
    ) -> ProfileInterpretation:
        aspect = "副本设计烧脑" if "烧脑" in request else "角色羁绊"
        return ProfileInterpretation(
            profile=ReaderTasteProfile(
                genres=["BL", "无限流"],
                positive_aspects=[aspect],
                reference_books=[
                    ReferencePreference(title="我在无限游戏里封神", liked_aspects=[aspect])
                ],
            )
        )

    def rank_candidates(
        self, profile, references, candidates, max_recommendations: int
    ) -> RankingResult:
        puzzle_first = "副本设计烧脑" in profile.positive_aspects
        ordered = candidates if puzzle_first else list(reversed(candidates))
        return RankingResult(
            books=[
                RankedBook(
                    candidate_id=item.candidate_id,
                    preference_fit_score=95 - index * 20,
                    reasons=[
                        RankingReason(
                            text=f"与本次明确偏好 {profile.positive_aspects[0]} 匹配",
                            kind=ReasonKind.PREFERENCE_INFERENCE,
                            source_ids=[],
                        )
                    ],
                )
                for index, item in enumerate(ordered)
            ]
        )


def two_candidates() -> CandidateExtractionResult:
    return CandidateExtractionResult(
        candidates=[
            BookCandidate(
                candidate_id="puzzle",
                title="烧脑副本书",
                author_claim="测试作者",
                discovery_source_ids=["S2"],
            ),
            BookCandidate(
                candidate_id="bond",
                title="羁绊群像书",
                author_claim="测试作者",
                discovery_source_ids=["S2"],
            ),
        ]
    )


def test_same_reference_with_different_tastes_changes_ranking() -> None:
    model = ScenarioAwareModel([two_candidates(), two_candidates()])
    discovery = SearchDocument(
        title="BL无限流推荐：烧脑副本书与羁绊群像书",
        url="https://reviews.example/personalized",
        content=(
            "《烧脑副本书》作者测试作者，副本解谜烧脑。"
            "《羁绊群像书》作者测试作者，角色关系与团队羁绊突出。"
        ),
    )
    search = FakeSearchProvider({"古言 权谋 聪明女主 完结": [discovery]})
    graph = build_recommendation_graph(
        model=model,
        search_provider=search,
        limits=WorkflowLimits(
            initial_query_count=1,
            min_candidates_for_verification=2,
            max_verification_candidates=2,
            min_recommendations=1,
        ),
    )

    puzzle = graph.invoke(initial_state("喜欢烧脑副本和聪明主角"))
    relationship = graph.invoke(initial_state("喜欢角色羁绊和感情发展"))

    assert puzzle["profile"].reference_books[0].title == "我在无限游戏里封神"
    assert relationship["profile"].reference_books[0].title == "我在无限游戏里封神"
    assert puzzle["recommendations"][0].title == "烧脑副本书"
    assert relationship["recommendations"][0].title == "羁绊群像书"
