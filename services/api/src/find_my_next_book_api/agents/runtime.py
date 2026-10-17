from dataclasses import dataclass
from typing import Any

from find_my_next_book_api.agents.gemini import GeminiRecommendationModel
from find_my_next_book_api.agents.workflow import WorkflowLimits, build_recommendation_graph
from find_my_next_book_api.core.settings import AgentSettings
from find_my_next_book_api.providers.tavily import TavilyBookSearchProvider


class AgentConfigurationError(RuntimeError):
    """Raised before external clients are built when credentials are incomplete."""


@dataclass(frozen=True)
class LiveWorkflow:
    graph: Any
    model_name: str
    search_provider_name: str


def create_live_workflow(settings: AgentSettings) -> LiveWorkflow:
    missing = settings.missing_credentials()
    if missing:
        names = ", ".join(missing)
        raise AgentConfigurationError(
            f"Missing required credentials: {names}. Add them to the environment or .env file."
        )

    assert settings.google_api_key is not None
    assert settings.tavily_api_key is not None
    model = GeminiRecommendationModel(
        api_key=settings.google_api_key.get_secret_value(),
        model=settings.agent_model,
        fallback_model=settings.agent_fallback_model,
        temperature=settings.agent_temperature,
        timeout_seconds=settings.agent_llm_timeout_seconds,
        max_retries=settings.agent_llm_max_retries,
        retry_backoff_seconds=settings.agent_llm_retry_backoff_seconds,
    )
    search_provider = TavilyBookSearchProvider(
        api_key=settings.tavily_api_key.get_secret_value(),
        max_results=settings.agent_search_max_results,
    )
    graph = build_recommendation_graph(
        model=model,
        search_provider=search_provider,
        limits=WorkflowLimits(
            initial_query_count=settings.agent_initial_query_count,
            max_search_attempts=settings.agent_max_search_attempts,
            max_search_calls=settings.agent_max_search_calls,
            min_candidates_for_verification=(settings.agent_min_candidates_for_verification),
            max_reference_books=settings.agent_max_reference_books,
            max_verification_candidates=settings.agent_max_verification_candidates,
            min_recommendations=settings.agent_min_recommendations,
            max_recommendations=settings.agent_max_recommendations,
        ),
    )
    return LiveWorkflow(
        graph=graph,
        model_name=model.name,
        search_provider_name=search_provider.name,
    )
