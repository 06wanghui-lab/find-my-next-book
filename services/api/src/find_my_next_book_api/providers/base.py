from typing import Protocol

from find_my_next_book_api.recommendation.models import SearchDocument, SearchQuery


class SearchProviderError(RuntimeError):
    """Raised when an external search provider cannot complete a request."""


class BookSearchProvider(Protocol):
    name: str

    def search(self, request: SearchQuery) -> list[SearchDocument]: ...
