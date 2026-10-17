import os

import pytest

from find_my_next_book_api.agents.runtime import create_live_workflow
from find_my_next_book_api.agents.workflow import initial_state
from find_my_next_book_api.core.settings import AgentSettings


@pytest.mark.live
def test_live_gemini_and_tavily_smoke() -> None:
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_TESTS=1 to invoke paid external APIs")

    settings = AgentSettings()
    missing = settings.missing_credentials()
    assert not missing, f"Missing live-test credentials: {', '.join(missing)}"

    runtime = create_live_workflow(settings)
    result = runtime.graph.invoke(
        initial_state("推荐一些已完结的古言权谋小说，女主聪明，不要虐文"),
        config={"recursion_limit": 24},
    )

    assert result["fatal_error"] is None
    assert result["profile"] is not None
    assert result["executions"]
    for recommendation in result["recommendations"]:
        assert recommendation.sources
        assert all(
            source.url.startswith(("http://", "https://")) for source in recommendation.sources
        )
