from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from bi_agent_api.auth import AuthStore, get_auth_store
from bi_agent_api.conversations import ConversationStore, get_conversation_store
from bi_agent_api.main import app


def authenticate(client: TestClient, store: ConversationStore) -> None:
    auth = AuthStore(store.engine)
    auth.create_user(
        "tester", "Tester", "test-password", is_admin=True, must_change_password=False
    )
    app.dependency_overrides[get_auth_store] = lambda: auth
    response = client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "test-password"}
    )
    assert response.status_code == 200


def test_create_list_and_open_conversation(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "sessions.sqlite3")
    app.dependency_overrides[get_conversation_store] = lambda: store
    try:
        with TestClient(app) as client:
            authenticate(client, store)
            created = client.post("/api/v1/conversations")
            conversation_id = created.json()["conversation_id"]
            listed = client.get("/api/v1/conversations")
            opened = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()[0]["conversation_id"] == conversation_id
    assert opened.status_code == 200
    assert opened.json()["messages"] == []


def test_conversation_chat_persists_visible_messages(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    store = ConversationStore(tmp_path / "sessions.sqlite3")

    async def fake_answer(question: str, _settings: Any, **kwargs: Any) -> tuple[str, Any]:
        session = kwargs["session"]
        await session.add_items(
            [
                {"role": "user", "content": question},
                {
                    "role": "assistant",
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": f"Resultado: {question}"}],
                },
            ]
        )
        data = {
            "ok": True,
            "columns": ["ventas"],
            "rows": [[1234]],
            "row_count": 1,
            "truncated": False,
        }
        return f"Resultado: {question}", SimpleNamespace(latest_result=data)

    monkeypatch.setattr("bi_agent_api.main.answer_question", fake_answer)
    app.dependency_overrides[get_conversation_store] = lambda: store
    try:
        with TestClient(app) as client:
            authenticate(client, store)
            created = client.post("/api/v1/conversations").json()
            conversation_id = created["conversation_id"]
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"message": "Ventas por marca"},
            )
            opened = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["columns"] == ["ventas"]
    messages = opened.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["data"]["rows"] == [[1234]]
    assert opened.json()["conversation"]["title"] == "Ventas por marca"


def test_unknown_conversation_returns_404(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "sessions.sqlite3")
    app.dependency_overrides[get_conversation_store] = lambda: store
    try:
        with TestClient(app) as client:
            authenticate(client, store)
            response = client.get("/api/v1/conversations/missing/messages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "La conversación no existe."
