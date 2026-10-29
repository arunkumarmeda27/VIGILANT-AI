import asyncio

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException, Request
from app.main import app
from app.api.routes.health import database_ready

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "vigilant-ai-api"


def test_global_exception_response_does_not_expose_exception_details():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
        }
    )
    response = asyncio.run(
        app.exception_handlers[Exception](
            request, RuntimeError("private database connection details")
        )
    )

    assert response.status_code == 500
    assert response.body == b'{"detail":"Internal Server Error"}'
    assert b"private database connection details" not in response.body


def test_database_readiness_response_does_not_expose_database_error():
    class FailingDatabase:
        def execute(self, statement):
            raise RuntimeError("private database connection details")

    with pytest.raises(HTTPException) as error:
        asyncio.run(database_ready(db=FailingDatabase()))

    assert error.value.status_code == 503
    assert error.value.detail == "Database unavailable"
    assert "private database connection details" not in error.value.detail
