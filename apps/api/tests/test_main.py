from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from bi_agent_api.auth import AuthStore, get_auth_store
from bi_agent_api.conversations import ConversationStore, get_conversation_store
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


def test_existing_chat_endpoint_requires_auth_and_remains_available(
    monkeypatch: Any, tmp_path: Any
) -> None:
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
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")
    auth = AuthStore(store.engine)
    auth.create_user("tester", "Tester", "test-password")
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_auth_store] = lambda: auth
    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/chat", json={"message": "Ventas del mes"})
        client.post(
            "/api/v1/auth/login", json={"username": "tester", "password": "test-password"}
        )
        client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "test-password", "new_password": "new-test-password"},
        )
        response = client.post("/api/v1/chat", json={"message": "Ventas del mes"})
    app.dependency_overrides.clear()

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["answer"] == "Las ventas fueron 100."
    assert response.json()["data"]["rows"] == [[100]]
