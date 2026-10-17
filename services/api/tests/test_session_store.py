from find_my_next_book_api.persistence.session_store import SessionStore
from find_my_next_book_api.recommendation.models import (
    ReaderTasteProfile,
    ReferencePreference,
)


def test_session_store_round_trips_only_structured_taste_state(tmp_path) -> None:
    store = SessionStore(tmp_path)
    profile = ReaderTasteProfile(
        genres=["BL", "无限流"],
        positive_aspects=["烧脑副本"],
        reference_books=[ReferencePreference(title="我在无限游戏里封神", liked_aspects=["群像"])],
        already_read=["地球上线"],
    )

    store.save("reader-1", profile, ["死亡万花筒"])
    loaded = store.load("reader-1")

    assert loaded is not None
    assert loaded.profile == profile
    assert loaded.last_recommendation_titles == ["死亡万花筒"]
    serialized = (tmp_path / "reader-1.json").read_text(encoding="utf-8")
    assert "raw_chat" not in serialized
    assert "API_KEY" not in serialized
