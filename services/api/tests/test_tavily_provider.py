from typing import Any

from find_my_next_book_api.providers.tavily import TavilyBookSearchProvider
from find_my_next_book_api.recommendation.models import SearchQuery


class FakeTavilyTool:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.arguments: dict[str, Any] | None = None

    def invoke(self, arguments: dict[str, Any]) -> Any:
        self.arguments = arguments
        return self.response


def test_tavily_provider_preserves_real_urls_and_skips_invalid_rows() -> None:
    tool = FakeTavilyTool(
        {
            "results": [
                {
                    "title": "《测试书》官方页",
                    "url": "https://www.jjwxc.net/onebook.php?novelid=123",
                    "content": "作品信息，已完结。",
                    "score": 0.91,
                },
                {"title": "broken", "url": "javascript:alert(1)", "content": "bad"},
            ]
        }
    )
    provider = TavilyBookSearchProvider(api_key="unused", tool=tool)
    query = SearchQuery(
        query="古言 完结 site:jjwxc.net",
        rationale="寻找官方详情页",
        include_domains=["jjwxc.net"],
    )

    documents = provider.search(query)

    assert len(documents) == 1
    assert documents[0].url == "https://www.jjwxc.net/onebook.php?novelid=123"
    assert tool.arguments == {
        "query": "古言 完结 site:jjwxc.net",
        "include_domains": ["jjwxc.net"],
    }
