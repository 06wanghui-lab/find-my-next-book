from fastapi.testclient import TestClient

from find_my_next_book_api.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "find-my-next-book-api",
    }


def test_root_exposes_agent_status() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "recommendation-agent-ready"


def test_local_react_origin_can_preflight_recommendation_post() -> None:
    response = client.options(
        "/api/recommend",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
