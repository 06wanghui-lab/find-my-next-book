from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from find_my_next_book_api.api.routes.health import router as health_router
from find_my_next_book_api.api.routes.recommend import router as recommend_router
from find_my_next_book_api.core.settings import get_settings

settings = get_settings()

app = FastAPI(
    title="Find My Next Book API",
    description="Grounded discovery and recommendation for Chinese web novels.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(recommend_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "name": "Find My Next Book API",
        "status": "recommendation-agent-ready",
        "docs": "/docs",
    }
