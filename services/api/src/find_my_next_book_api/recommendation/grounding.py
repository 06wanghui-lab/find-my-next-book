import re
import unicodedata
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from opencc import OpenCC

from find_my_next_book_api.recommendation.models import (
    BookCandidate,
    CandidatePublicationStatus,
    EvaluationResult,
    EvidenceCitation,
    EvidenceRecord,
    EvidenceStage,
    RankingResult,
    ReaderTasteProfile,
    ReasonKind,
    Recommendation,
    RunMetrics,
    SearchExecution,
    VerificationResult,
    VerificationStatus,
    VerifiedBook,
)

PLATFORM_DOMAINS = {
    "jjwxc.net": "晋江文学城",
    "gongzicp.com": "长佩文学",
    "fanqienovel.com": "番茄小说",
    "qidian.com": "起点中文网",
}

COMPLETED_MARKERS = ("已完结", "完结", "全文完", "完本")
ONGOING_MARKERS = ("连载中", "连载", "更新中")
TRACKING_PARAMETERS = {"from", "source", "spm", "utm_campaign", "utm_medium", "utm_source"}
OFFICIAL_BOOK_PATTERNS = {
    "jjwxc.net": ("/onebook.php",),
    "gongzicp.com": ("/novel-", "/novel/"),
    "fanqienovel.com": ("/page/",),
    "qidian.com": ("/info/", "/book/"),
}
T2S_CONVERTER = OpenCC("t2s.json")


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(
        sorted(
            (key, value) for key, value in parse_qsl(parts.query) if key not in TRACKING_PARAMETERS
        )
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, "")
    )


def platform_for_url(url: str) -> str | None:
    hostname = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for domain, platform in PLATFORM_DOMAINS.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return platform
    return None


def is_official_book_url(url: str) -> bool:
    parts = urlsplit(url)
    hostname = (parts.hostname or "").lower().removeprefix("www.")
    for domain, path_markers in OFFICIAL_BOOK_PATTERNS.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            if domain == "jjwxc.net":
                return parts.path.endswith("onebook.php") and "novelid=" in parts.query
            return any(marker in parts.path.lower() for marker in path_markers)
    return False


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"[\s《》〈〉「」『』\-—_:：·,.，。!?！？()（）]", "", normalized).lower()


def normalize_title(value: str) -> str:
    value = re.sub(r"^(小说|网文|书名)[:：\s]*", "", value.strip())
    return _normalize_text(T2S_CONVERTER.convert(value))


def canonical_book_id(title: str, author: str | None = None) -> str:
    title_key = normalize_title(title)
    author_key = _normalize_text(author or "")
    return f"{title_key}::{author_key}" if author_key else title_key


def _claim_is_present(claim: str, evidence: EvidenceRecord) -> bool:
    normalized_claim = _normalize_text(claim)
    if not normalized_claim:
        return False
    evidence_text = _normalize_text(f"{evidence.title} {evidence.content}")
    return normalized_claim in evidence_text


def _supported_status(
    claimed_status: CandidatePublicationStatus,
    evidence: list[EvidenceRecord],
) -> CandidatePublicationStatus:
    combined = " ".join(f"{item.title} {item.content}" for item in evidence)
    if claimed_status == CandidatePublicationStatus.COMPLETED and any(
        marker in combined for marker in COMPLETED_MARKERS
    ):
        return CandidatePublicationStatus.COMPLETED
    if claimed_status == CandidatePublicationStatus.ONGOING and any(
        marker in combined for marker in ONGOING_MARKERS
    ):
        return CandidatePublicationStatus.ONGOING
    return CandidatePublicationStatus.UNKNOWN


def ground_evaluation(
    evaluation: EvaluationResult,
    evidence: list[EvidenceRecord],
    *,
    max_recommendations: int,
) -> list[Recommendation]:
    """Turn model judgments into recommendations whose metadata is evidence-backed."""

    evidence_by_id = {item.source_id: item for item in evidence}
    grounded: list[Recommendation] = []

    for candidate in evaluation.candidates:
        cited = [
            evidence_by_id[source_id]
            for source_id in dict.fromkeys(candidate.source_ids)
            if source_id in evidence_by_id
        ]
        title_sources = [item for item in cited if _claim_is_present(candidate.title, item)]
        if not title_sources:
            continue

        uncertainties = list(dict.fromkeys(candidate.uncertainties))
        author = candidate.author
        if author and not any(_claim_is_present(author, item) for item in title_sources):
            author = None
            uncertainties.append("作者未在引用的检索证据中得到确认")

        platform = next(
            (platform_for_url(item.url) for item in title_sources if platform_for_url(item.url)),
            None,
        )
        if platform is None:
            uncertainties.append("引用页面不是已识别的官方平台页面，平台归属未确认")

        publication_status = _supported_status(
            candidate.claimed_publication_status,
            title_sources,
        )
        if (
            candidate.claimed_publication_status != CandidatePublicationStatus.UNKNOWN
            and publication_status == CandidatePublicationStatus.UNKNOWN
        ):
            uncertainties.append("连载状态未在引用的检索证据中得到确认")

        citations = [
            EvidenceCitation(
                source_id=item.source_id,
                title=item.title,
                url=item.url,
                excerpt=item.content[:500],
            )
            for item in title_sources
        ]
        grounded.append(
            Recommendation(
                rank=1,
                title=candidate.title,
                author=author,
                platform=platform,
                publication_status=publication_status,
                relevance_score=candidate.relevance_score,
                match_reasons=candidate.match_reasons,
                uncertainties=list(dict.fromkeys(uncertainties)),
                sources=citations,
            )
        )

    grounded.sort(key=lambda item: item.relevance_score, reverse=True)
    deduplicated: list[Recommendation] = []
    seen_titles: set[str] = set()
    for item in grounded:
        normalized_title = _normalize_text(item.title)
        if normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)
        item.rank = len(deduplicated) + 1
        deduplicated.append(item)
        if len(deduplicated) >= max_recommendations:
            break
    return deduplicated


def deduplicate_candidates(
    candidates: list[BookCandidate],
    evidence: list[EvidenceRecord],
    *,
    excluded_titles: list[str],
) -> list[BookCandidate]:
    """Reject uncited model output, normalize identity, and merge duplicate candidates."""

    evidence_by_id = {item.source_id: item for item in evidence}
    excluded = {normalize_title(title) for title in excluded_titles}
    merged: dict[str, BookCandidate] = {}

    for candidate in candidates:
        cited = [
            evidence_by_id[source_id]
            for source_id in dict.fromkeys(candidate.discovery_source_ids)
            if source_id in evidence_by_id
            and evidence_by_id[source_id].stage == EvidenceStage.DISCOVERY
        ]
        title_sources = [item for item in cited if _claim_is_present(candidate.title, item)]
        title_key = normalize_title(candidate.title)
        if not title_sources or title_key in excluded:
            continue

        supported_author = candidate.author_claim
        if supported_author and not any(
            _claim_is_present(supported_author, item) for item in title_sources
        ):
            supported_author = None

        identity = canonical_book_id(candidate.title, supported_author)
        source_ids = [item.source_id for item in title_sources]
        opinions = [
            opinion
            for opinion in candidate.reader_opinions
            if opinion.source_ids
            and all(source_id in source_ids for source_id in opinion.source_ids)
        ]
        if identity not in merged:
            merged[identity] = BookCandidate(
                candidate_id=identity,
                title=candidate.title.strip("《》 "),
                title_variants=list(dict.fromkeys([candidate.title, *candidate.title_variants])),
                author_claim=supported_author,
                discovery_source_ids=source_ids,
                reader_opinions=opinions,
            )
            continue

        current = merged[identity]
        current.title_variants = list(
            dict.fromkeys([*current.title_variants, candidate.title, *candidate.title_variants])
        )
        current.discovery_source_ids = list(
            dict.fromkeys([*current.discovery_source_ids, *source_ids])
        )
        known_opinions = {(item.text, tuple(item.source_ids)) for item in current.reader_opinions}
        current.reader_opinions.extend(
            item for item in opinions if (item.text, tuple(item.source_ids)) not in known_opinions
        )

    # A title-only candidate and the same title+author candidate should collapse.
    by_title: dict[str, list[BookCandidate]] = defaultdict(list)
    for candidate in merged.values():
        by_title[normalize_title(candidate.title)].append(candidate)

    collapsed: list[BookCandidate] = []
    for same_title in by_title.values():
        preferred = next((item for item in same_title if item.author_claim), same_title[0])
        for duplicate in same_title:
            if duplicate is preferred:
                continue
            preferred.title_variants = list(
                dict.fromkeys([*preferred.title_variants, *duplicate.title_variants])
            )
            preferred.discovery_source_ids = list(
                dict.fromkeys([*preferred.discovery_source_ids, *duplicate.discovery_source_ids])
            )
            preferred.reader_opinions.extend(duplicate.reader_opinions)
        preferred.candidate_id = canonical_book_id(preferred.title, preferred.author_claim)
        collapsed.append(preferred)
    return collapsed


def ground_verification(
    candidates: list[BookCandidate],
    evidence: list[EvidenceRecord],
    verification: VerificationResult,
) -> list[VerifiedBook]:
    evidence_by_id = {item.source_id: item for item in evidence}
    claims_by_id = {item.candidate_id: item for item in verification.books}
    verified: list[VerifiedBook] = []

    for candidate in candidates:
        claim = claims_by_id.get(candidate.candidate_id)
        candidate_evidence = [
            item
            for item in evidence
            if item.candidate_id == candidate.candidate_id
            or item.source_id in candidate.discovery_source_ids
        ]
        title_evidence = [
            item for item in candidate_evidence if _claim_is_present(candidate.title, item)
        ]
        identity_sources = [
            item for item in title_evidence if item.stage != EvidenceStage.DISCOVERY
        ]
        uncertainties: list[str] = []
        metadata_sources: list[EvidenceRecord] = []
        official_source: EvidenceRecord | None = None

        if claim:
            metadata_sources = [
                evidence_by_id[source_id]
                for source_id in dict.fromkeys(claim.metadata_source_ids)
                if source_id in evidence_by_id
                and evidence_by_id[source_id].stage
                in {
                    EvidenceStage.REFERENCE_VERIFICATION,
                    EvidenceStage.CANDIDATE_VERIFICATION,
                }
                and _claim_is_present(candidate.title, evidence_by_id[source_id])
            ]
            if claim.official_source_id:
                possible = evidence_by_id.get(claim.official_source_id)
                if (
                    possible
                    and is_official_book_url(possible.url)
                    and _claim_is_present(candidate.title, possible)
                ):
                    official_source = possible
                    if possible not in metadata_sources:
                        metadata_sources.append(possible)

        if official_source:
            verification_status = VerificationStatus.OFFICIAL
        else:
            independent_hosts = {
                (urlsplit(item.url).hostname or "").lower() for item in identity_sources
            }
            verification_status = (
                VerificationStatus.CORROBORATED
                if len(independent_hosts) >= 2
                else VerificationStatus.UNVERIFIED
            )

        title = candidate.title
        if (
            claim
            and claim.official_title
            and official_source
            and _claim_is_present(claim.official_title, official_source)
        ):
            title = claim.official_title.strip("《》 ")

        author = claim.author if claim else candidate.author_claim
        author_sources = metadata_sources
        if author and not any(_claim_is_present(author, item) for item in author_sources):
            author = None
            uncertainties.append("作者未在元数据证据中得到确认")

        genre_tags = []
        if claim:
            genre_tags = [
                tag
                for tag in claim.genre_tags
                if any(_claim_is_present(tag, item) for item in metadata_sources)
            ]

        publication_status = CandidatePublicationStatus.UNKNOWN
        if claim:
            publication_status = _supported_status(claim.publication_status, metadata_sources)
            if (
                claim.publication_status != CandidatePublicationStatus.UNKNOWN
                and publication_status == CandidatePublicationStatus.UNKNOWN
            ):
                uncertainties.append("连载状态未在元数据证据中得到确认")

        if verification_status == VerificationStatus.UNVERIFIED:
            uncertainties.append("未找到可确认身份的官方书籍页面或第二个独立来源")
        elif verification_status == VerificationStatus.CORROBORATED:
            uncertainties.append("书名得到多来源印证，但未找到可确认的官方书籍页面")

        verified.append(
            VerifiedBook(
                candidate_id=candidate.candidate_id,
                title=title,
                title_variants=candidate.title_variants,
                author=author,
                platform=platform_for_url(official_source.url) if official_source else None,
                official_url=official_source.url if official_source else None,
                genre_tags=list(dict.fromkeys(genre_tags)),
                publication_status=publication_status,
                verification_status=verification_status,
                discovery_source_ids=candidate.discovery_source_ids,
                identity_source_ids=[item.source_id for item in identity_sources],
                metadata_source_ids=[item.source_id for item in metadata_sources],
                reader_opinions=candidate.reader_opinions,
                uncertainties=uncertainties,
            )
        )
    return verified


def finalize_ranking(
    profile: ReaderTasteProfile,
    ranking: RankingResult,
    books: list[VerifiedBook],
    evidence: list[EvidenceRecord],
    *,
    max_recommendations: int,
) -> list[Recommendation]:
    books_by_id = {item.candidate_id: item for item in books}
    evidence_by_id = {item.source_id: item for item in evidence}
    excluded_titles = {
        normalize_title(title)
        for title in [
            *profile.already_read,
            *(reference.title for reference in profile.reference_books),
        ]
    }
    recommendations: list[Recommendation] = []

    for ranked in ranking.books:
        book = books_by_id.get(ranked.candidate_id)
        if book is None or ranked.hard_constraint_violations:
            continue
        if normalize_title(book.title) in excluded_titles:
            continue
        if (
            profile.publication_status.value in {"completed", "ongoing"}
            and book.publication_status.value != profile.publication_status.value
        ):
            continue

        valid_reasons = []
        for reason in ranked.reasons:
            valid_ids = [
                source_id for source_id in reason.source_ids if source_id in evidence_by_id
            ]
            if reason.kind == ReasonKind.VERIFIED_METADATA:
                valid_ids = [
                    source_id for source_id in valid_ids if source_id in book.metadata_source_ids
                ]
                if not valid_ids:
                    continue
            elif reason.kind == ReasonKind.ATTRIBUTED_READER_OPINION:
                valid_ids = [
                    source_id for source_id in valid_ids if source_id in book.discovery_source_ids
                ]
                if not valid_ids:
                    continue
            valid_reasons.append(reason.model_copy(update={"source_ids": valid_ids}))
        if not valid_reasons:
            continue

        quality_multiplier = {
            VerificationStatus.OFFICIAL: 1.0,
            VerificationStatus.CORROBORATED: 0.85,
            VerificationStatus.UNVERIFIED: 0.6,
        }[book.verification_status]
        preference_score = ranked.preference_fit_score
        if 0 < preference_score <= 1:
            preference_score *= 100
        final_score = round(preference_score * quality_multiplier, 1)
        cited_ids = list(
            dict.fromkeys(
                [
                    *book.identity_source_ids,
                    *book.metadata_source_ids,
                    *(source_id for reason in valid_reasons for source_id in reason.source_ids),
                ]
            )
        )
        if not cited_ids:
            cited_ids = book.discovery_source_ids
        citations = [
            EvidenceCitation(
                source_id=source_id,
                title=evidence_by_id[source_id].title,
                url=evidence_by_id[source_id].url,
                excerpt=evidence_by_id[source_id].content[:500],
            )
            for source_id in cited_ids
            if source_id in evidence_by_id
        ]
        if not citations:
            continue

        labels = {
            ReasonKind.VERIFIED_METADATA: "已验证元数据",
            ReasonKind.ATTRIBUTED_READER_OPINION: "读者来源观点",
            ReasonKind.PREFERENCE_INFERENCE: "偏好匹配推断",
        }
        recommendations.append(
            Recommendation(
                rank=1,
                title=book.title,
                author=book.author,
                platform=book.platform,
                publication_status=book.publication_status,
                relevance_score=final_score,
                match_reasons=[f"{labels[item.kind]}：{item.text}" for item in valid_reasons],
                uncertainties=book.uncertainties,
                sources=citations,
                canonical_id=book.candidate_id,
                official_url=book.official_url,
                verification_status=book.verification_status,
                genre_tags=book.genre_tags,
                reasons=valid_reasons,
                hard_constraint_violations=[],
            )
        )

    recommendations.sort(key=lambda item: item.relevance_score, reverse=True)
    final: list[Recommendation] = []
    seen: set[str] = set()
    for recommendation in recommendations:
        key = normalize_title(recommendation.title)
        if key in seen:
            continue
        seen.add(key)
        recommendation.rank = len(final) + 1
        final.append(recommendation)
        if len(final) >= max_recommendations:
            break
    return final


def calculate_run_metrics(
    recommendations: list[Recommendation],
    executions: list[SearchExecution],
    *,
    raw_candidate_count: int,
    unique_candidate_count: int,
    model_api_failures: int = 0,
) -> RunMetrics:
    total = len(recommendations)
    valid_links = sum(
        1
        for item in recommendations
        if item.official_url and is_official_book_url(item.official_url)
    )
    verified = sum(
        1 for item in recommendations if item.verification_status != VerificationStatus.UNVERIFIED
    )
    compliant = sum(1 for item in recommendations if not item.hard_constraint_violations)
    duplicate_count = max(0, raw_candidate_count - unique_candidate_count)
    return RunMetrics(
        canonical_link_validity=valid_links / total if total else 0.0,
        metadata_verification_rate=verified / total if total else 0.0,
        hard_filter_compliance=compliant / total if total else 1.0,
        duplicate_rate=duplicate_count / raw_candidate_count if raw_candidate_count else 0.0,
        api_failures=sum(1 for item in executions if item.error) + model_api_failures,
        raw_candidates=raw_candidate_count,
        unique_candidates=unique_candidate_count,
    )
