import json
from collections.abc import Mapping
from typing import Any

from langchain_tavily import TavilySearch

from find_my_next_book_api.providers.base import SearchProviderError
from find_my_next_book_api.recommendation.models import SearchDocument, SearchQuery


class TavilyBookSearchProvider:
    name = "TavilySearch"

    def __init__(
        self,
        *,
        api_key: str,
        max_results: int = 5,
        search_depth: str = "basic",
        tool: Any | None = None,
    ) -> None:
        self._tool = tool or TavilySearch(
            api_wrapper={"tavily_api_key": api_key},
            max_results=max_results,
            topic="general",
            include_answer=False,
            include_raw_content=False,
            include_images=False,
            search_depth=search_depth,
        )

    def search(self, request: SearchQuery) -> list[SearchDocument]:
        arguments: dict[str, Any] = {"query": request.query}
        if request.include_domains:
            arguments["include_domains"] = request.include_domains

        try:
            response = self._tool.invoke(arguments)
            payload = self._coerce_payload(response)
        except Exception as exc:  # provider exceptions vary across SDK releases
            raise SearchProviderError(f"Tavily search failed: {exc}") from exc

        documents: list[SearchDocument] = []
        for result in payload.get("results", []):
            if not isinstance(result, Mapping):
                continue
            try:
                documents.append(
                    SearchDocument(
                        title=str(result.get("title") or "").strip(),
                        url=str(result.get("url") or "").strip(),
                        content=str(result.get("content") or "").strip()[:1800],
                        score=_optional_float(result.get("score")),
                    )
                )
            except (TypeError, ValueError):
                continue
        return documents

    @staticmethod
    def _coerce_payload(response: Any) -> Mapping[str, Any]:
        if isinstance(response, Mapping):
            return response
        content = getattr(response, "content", response)
        if isinstance(content, str):
            parsed = json.loads(content)
            if isinstance(parsed, Mapping):
                return parsed
        raise SearchProviderError("Tavily returned an unexpected response shape")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
