from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from bi_agent_api.main import app, app_db_is_available


def test_health() -> None:
    app.dependency_overrides[app_db_is_available] = lambda: True
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_degraded_when_app_db_is_unavailable() -> None:
    app.dependency_overrides[app_db_is_available] = lambda: False
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}


def test_existing_chat_endpoint_remains_available(monkeypatch: Any) -> None:
    async def fake_answer(message: str, _settings: Any) -> tuple[str, Any]:
        assert message == "Ventas del mes"
        data = {
            "ok": True,
            "columns": ["sales"],
            "rows": [[100]],
            "row_count": 1,
            "truncated": False,
        }
        return "Las ventas fueron 100.", SimpleNamespace(latest_result=data)

    monkeypatch.setattr("bi_agent_api.main.answer_question", fake_answer)
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "Ventas del mes"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Las ventas fueron 100."
    assert response.json()["data"]["rows"] == [[100]]
