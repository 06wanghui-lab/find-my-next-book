from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from find_my_next_book_api.agents.runtime import (
    AgentConfigurationError,
    LiveWorkflow,
    create_live_workflow,
)
from find_my_next_book_api.agents.workflow import initial_state
from find_my_next_book_api.core.settings import get_agent_settings
from find_my_next_book_api.recommendation.models import (
    ReaderTasteProfile,
    Recommendation,
    RunMetrics,
)

router = APIRouter(prefix="/api", tags=["recommendations"])


class RecommendationRequest(BaseModel):
    request: str = Field(min_length=3, max_length=2_000)


class ProviderSummary(BaseModel):
    model: str
    search: str


class RecommendationResponse(BaseModel):
    profile: ReaderTasteProfile
    recommendations: list[Recommendation]
    metrics: RunMetrics | None = None
    warnings: list[str] = Field(default_factory=list)
    providers: ProviderSummary


def get_recommendation_runtime() -> LiveWorkflow:
    try:
        return create_live_workflow(get_agent_settings())
    except AgentConfigurationError as exc:
        raise _configuration_error(exc) from exc


@router.post("/recommend", response_model=RecommendationResponse)
async def recommend(
    payload: RecommendationRequest,
    runtime: Annotated[LiveWorkflow, Depends(get_recommendation_runtime)],
) -> RecommendationResponse:
    """Run the existing compiled LangGraph without exposing provider credentials."""
    try:
        state = await run_in_threadpool(
            runtime.graph.invoke,
            initial_state(payload.request),
            {"recursion_limit": 24},
        )
    except AgentConfigurationError as exc:
        raise _configuration_error(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "agent_unavailable",
                "message": "推荐服务暂时不可用，请稍后再试。",
            },
        ) from exc

    fatal_error = state.get("fatal_error")
    if fatal_error:
        raise _agent_http_error(fatal_error)

    profile = state.get("profile")
    if profile is None:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_agent_result",
                "message": "推荐服务没有返回有效的读者画像，请重试。",
            },
        )

    return RecommendationResponse(
        profile=profile,
        recommendations=state["recommendations"],
        metrics=state.get("metrics"),
        warnings=(
            ["部分检索或验证调用失败，因此返回的结果可能较少。"]
            if state.get("errors")
            else []
        ),
        providers=ProviderSummary(
            model=runtime.model_name,
            search=runtime.search_provider_name,
        ),
    )


def _agent_http_error(message: str) -> HTTPException:
    normalized = message.upper()
    if "RESOURCE_EXHAUSTED" in normalized or "429" in normalized or "QUOTA" in normalized:
        return HTTPException(
            status_code=429,
            detail={
                "code": "model_quota_exceeded",
                "message": "AI 推荐额度暂时用完了，请稍后再试或配置可用的备用模型。",
            },
        )
    return HTTPException(
        status_code=502,
        detail={
            "code": "agent_failed",
            "message": "检索或推荐流程没有完成，请稍后重试。",
        },
    )


def _configuration_error(_exc: AgentConfigurationError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "provider_not_configured",
            "message": "推荐服务尚未配置完整的模型和搜索凭据。",
        },
    )
