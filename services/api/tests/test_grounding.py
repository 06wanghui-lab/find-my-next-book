from find_my_next_book_api.recommendation.grounding import (
    deduplicate_candidates,
    finalize_ranking,
    ground_verification,
    normalize_title,
)
from find_my_next_book_api.recommendation.models import (
    BookCandidate,
    CandidatePublicationStatus,
    EvidenceRecord,
    EvidenceStage,
    RankedBook,
    RankingReason,
    RankingResult,
    ReaderOpinion,
    ReaderTasteProfile,
    ReasonKind,
    RequestedPublicationStatus,
    VerificationClaim,
    VerificationResult,
    VerificationStatus,
)


def evidence(
    source_id: str,
    title: str,
    content: str,
    url: str,
    *,
    stage: EvidenceStage = EvidenceStage.DISCOVERY,
    candidate_id: str | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        source_id=source_id,
        query="test",
        title=title,
        content=content,
        url=url,
        score=0.8,
        stage=stage,
        candidate_id=candidate_id,
    )


def test_candidate_normalization_deduplicates_and_excludes_read_titles() -> None:
    records = [
        evidence(
            "S1",
            "无限流小说推荐：《死亡万花筒》《地球上线》",
            "《死亡万花筒》作者西子绪，读者认为副本悬疑；《地球上线》也很烧脑。",
            "https://reviews.example/list",
        )
    ]
    candidates = [
        BookCandidate(
            candidate_id="model-1",
            title="《死亡万花筒》",
            author_claim="西子绪",
            discovery_source_ids=["S1"],
        ),
        BookCandidate(
            candidate_id="model-2",
            title="死亡万花筒",
            author_claim="西子绪",
            discovery_source_ids=["S1"],
        ),
        BookCandidate(
            candidate_id="model-3",
            title="地球上线",
            discovery_source_ids=["S1"],
        ),
        BookCandidate(
            candidate_id="invented",
            title="不存在的书",
            discovery_source_ids=["S1"],
        ),
    ]

    result = deduplicate_candidates(candidates, records, excluded_titles=["《地球上线》"])

    assert len(result) == 1
    assert normalize_title(result[0].title) == normalize_title("死亡万花筒")
    assert result[0].author_claim == "西子绪"


def test_title_normalization_collapses_traditional_and_simplified_variants() -> None:
    assert normalize_title("《死亡萬花筒》") == normalize_title("死亡万花筒")
    assert normalize_title("我在無限遊戲裡封神") == normalize_title("《我在无限游戏里封神》")


def test_official_verification_preserves_objective_metadata() -> None:
    candidate = BookCandidate(
        candidate_id="死亡万花筒::西子绪",
        title="死亡万花筒",
        author_claim="西子绪",
        discovery_source_ids=["S1"],
        reader_opinions=[ReaderOpinion(text="副本氛围悬疑", source_ids=["S1"])],
    )
    records = [
        evidence(
            "S1",
            "无限流书单：死亡万花筒",
            "读者认为《死亡万花筒》副本氛围悬疑。",
            "https://reviews.example/list",
        ),
        evidence(
            "S2",
            "《死亡万花筒》西子绪_晋江文学城",
            "《死亡万花筒》作者西子绪，纯爱、无限流，全文完结。",
            "https://www.jjwxc.net/onebook.php?novelid=123",
            stage=EvidenceStage.CANDIDATE_VERIFICATION,
            candidate_id=candidate.candidate_id,
        ),
    ]
    claim = VerificationClaim(
        candidate_id=candidate.candidate_id,
        official_title="死亡万花筒",
        author="西子绪",
        official_source_id="S2",
        metadata_source_ids=["S2"],
        genre_tags=["纯爱", "无限流"],
        publication_status=CandidatePublicationStatus.COMPLETED,
    )

    book = ground_verification([candidate], records, VerificationResult(books=[claim]))[0]

    assert book.verification_status == VerificationStatus.OFFICIAL
    assert book.official_url == "https://www.jjwxc.net/onebook.php?novelid=123"
    assert book.author == "西子绪"
    assert book.genre_tags == ["纯爱", "无限流"]
    assert book.publication_status == CandidatePublicationStatus.COMPLETED
    assert book.reader_opinions[0].text == "副本氛围悬疑"


def test_ranking_separates_metadata_from_opinion_and_enforces_hard_status() -> None:
    candidate = BookCandidate(
        candidate_id="候选::作者",
        title="候选",
        author_claim="作者",
        discovery_source_ids=["S1"],
        reader_opinions=[ReaderOpinion(text="读者认为很烧脑", source_ids=["S1"])],
    )
    records = [
        evidence(
            "S1",
            "候选评价",
            "《候选》读者认为副本很烧脑。",
            "https://reviews.example/candidate",
        ),
        evidence(
            "S2",
            "《候选》作者_晋江文学城",
            "《候选》作者作者，无限流，全文完结。",
            "https://www.jjwxc.net/onebook.php?novelid=88",
            stage=EvidenceStage.CANDIDATE_VERIFICATION,
            candidate_id=candidate.candidate_id,
        ),
    ]
    book = ground_verification(
        [candidate],
        records,
        VerificationResult(
            books=[
                VerificationClaim(
                    candidate_id=candidate.candidate_id,
                    official_title="候选",
                    author="作者",
                    official_source_id="S2",
                    metadata_source_ids=["S2"],
                    genre_tags=["无限流"],
                    publication_status=CandidatePublicationStatus.COMPLETED,
                )
            ]
        ),
    )[0]
    ranking = RankingResult(
        books=[
            RankedBook(
                candidate_id=candidate.candidate_id,
                preference_fit_score=90,
                reasons=[
                    RankingReason(
                        text="官方标签含无限流",
                        kind=ReasonKind.VERIFIED_METADATA,
                        source_ids=["S2"],
                    ),
                    RankingReason(
                        text="该书被读者描述为烧脑",
                        kind=ReasonKind.ATTRIBUTED_READER_OPINION,
                        source_ids=["S1"],
                    ),
                ],
            )
        ]
    )
    completed_profile = ReaderTasteProfile(publication_status=RequestedPublicationStatus.COMPLETED)

    recommendations = finalize_ranking(
        completed_profile, ranking, [book], records, max_recommendations=5
    )

    assert len(recommendations) == 1
    assert recommendations[0].match_reasons == [
        "已验证元数据：官方标签含无限流",
        "读者来源观点：该书被读者描述为烧脑",
    ]

    ongoing_profile = ReaderTasteProfile(publication_status=RequestedPublicationStatus.ONGOING)
    assert finalize_ranking(ongoing_profile, ranking, [book], records, max_recommendations=5) == []


def test_fractional_model_score_is_normalized_to_100_point_scale() -> None:
    candidate = BookCandidate(
        candidate_id="测试",
        title="测试",
        discovery_source_ids=["S1"],
    )
    record = evidence(
        "S1",
        "《测试》评价",
        "《测试》读者认为烧脑。",
        "https://reviews.example/test",
    )
    book = ground_verification([candidate], [record], VerificationResult(books=[]))[0]
    ranking = RankingResult(
        books=[
            RankedBook(
                candidate_id="测试",
                preference_fit_score=0.9,
                reasons=[
                    RankingReason(
                        text="读者认为烧脑",
                        kind=ReasonKind.ATTRIBUTED_READER_OPINION,
                        source_ids=["S1"],
                    )
                ],
            )
        ]
    )

    result = finalize_ranking(
        ReaderTasteProfile(), ranking, [book], [record], max_recommendations=1
    )

    assert result[0].relevance_score == 54.0
