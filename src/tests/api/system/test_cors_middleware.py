from fastapi import FastAPI
from fastapi.testclient import TestClient

from ii_agent.app.middleware import configure_middleware
from ii_agent.core.config.settings import get_settings


def _build_test_app() -> FastAPI:
    app = FastAPI()
    configure_middleware(app, get_settings())

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_cors_get_request_echoes_allowed_origin():
    client = TestClient(_build_test_app())

    response = client.get("/health", headers={"Origin": "http://localhost:1420"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:1420"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_preflight_allows_frontend_auth_headers():
    client = TestClient(_build_test_app())

    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:1420"
    assert response.headers["access-control-allow-headers"] == "authorization,content-type"
