import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.main import CORSFastAPI, app, global_exception_handler


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "http://127.0.0.1:5173"],
)
def test_local_frontend_origin_receives_cors_headers_on_protected_endpoint(origin):
    response = TestClient(app).get(
        "/api/applications/1/consistency-runs",
        headers={"Origin": origin},
    )

    # CORS must not bypass the endpoint's authentication requirement.
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "origin" in response.headers.get("vary", "").lower()


def test_local_frontend_preflight_allows_authorization_header():
    response = TestClient(app).options(
        "/api/applications/1/consistency-runs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_local_frontend_origin_receives_cors_headers_on_server_error():
    test_app = CORSFastAPI()
    test_app.add_exception_handler(Exception, global_exception_handler)

    @test_app.get("/test-server-error")
    async def server_error(_request: Request):
        raise RuntimeError("synthetic test error")

    response = TestClient(test_app, raise_server_exceptions=False).get(
        "/test-server-error",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
