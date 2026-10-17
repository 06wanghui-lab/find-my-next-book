import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from find_my_next_book_api.recommendation.models import ReaderTasteProfile

SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class SessionRecord(BaseModel):
    session_id: str
    profile: ReaderTasteProfile
    last_recommendation_titles: list[str] = Field(default_factory=list, max_length=20)
    updated_at: datetime


class SessionStore:
    """JSON persistence for structured taste state, never raw chat history or keys."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load(self, session_id: str) -> SessionRecord | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        return SessionRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(
        self,
        session_id: str,
        profile: ReaderTasteProfile,
        recommendation_titles: list[str],
    ) -> SessionRecord:
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = SessionRecord(
            session_id=session_id,
            profile=profile,
            last_recommendation_titles=recommendation_titles,
            updated_at=datetime.now(UTC),
        )
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
        return record

    def _path(self, session_id: str) -> Path:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError(
                "Session ID must be 1-64 characters using letters, numbers, '_' or '-'"
            )
        return self.directory / f"{session_id}.json"
