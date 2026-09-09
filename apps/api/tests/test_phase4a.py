import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agents import SQLiteSession
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects import mssql
from sqlalchemy.schema import CreateTable

from bi_agent_api.auth import AuthStore, User, get_auth_store
from bi_agent_api.config import Settings
from bi_agent_api.conversations import (
    ConversationStore,
    audit_sql_attempts,
    audit_turns,
    conversations,
    get_conversation_store,
    messages,
)
from bi_agent_api.main import app, current_user

OWNER_ID = 1


def authenticate(client: TestClient, store: ConversationStore) -> None:
    auth = AuthStore(store.engine)
    auth.create_user(
        "tester", "Tester", "test-password", is_admin=True, must_change_password=False
    )
    app.dependency_overrides[get_auth_store] = lambda: auth
    login = client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": "test-password"}
    )
    assert login.status_code == 200


def test_app_db_config_is_independent_from_analytics_credentials() -> None:
    settings = Settings(
        _env_file=None,
        analytics_db_host="analytics.internal",
        analytics_db_name="analytics",
        analytics_db_user="reader",
        analytics_db_password="analytics-secret",
        app_db_host="app.internal",
        app_db_name="bi_app",
        app_db_user="writer",
        app_db_password="app-secret",
    )

    app_connection = settings.app_database_connection_string()

    assert "SERVER=app.internal,1433" in app_connection
    assert "DATABASE=bi_app" in app_connection
    assert "UID=writer" in app_connection
    assert "PWD={app-secret}" in app_connection
    assert "analytics.internal" not in app_connection
    assert "analytics-secret" not in app_connection
    assert "ApplicationIntent=ReadOnly" not in app_connection


def test_app_db_config_reports_missing_values() -> None:
    with pytest.raises(ValueError, match="APP_DB_HOST"):
        Settings(_env_file=None).app_database_connection_string()


def test_app_db_healthcheck_executes_select_one(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")

    store.check_app_db()


def test_sql_server_statements_use_explicit_biagent_schema() -> None:
    dialect = mssql.dialect()
    app_tables = (conversations, messages, audit_turns, audit_sql_attempts)

    select_statements = [str(select(table).compile(dialect=dialect)) for table in app_tables]
    insert_sql = str(insert(conversations).compile(dialect=dialect))
    update_sql = str(update(conversations).compile(dialect=dialect))
    delete_sql = str(delete(conversations).compile(dialect=dialect))
    messages_ddl = str(CreateTable(messages).compile(dialect=dialect))

    assert all(table.schema == "biAgent" for table in app_tables)
    assert all("[biAgent].app_" in statement for statement in select_statements)
    assert "INSERT INTO [biAgent].app_conversations" in insert_sql
    assert "UPDATE [biAgent].app_conversations" in update_sql
    assert "DELETE FROM [biAgent].app_conversations" in delete_sql
    assert "REFERENCES [biAgent].app_conversations" in messages_ddl


def test_persistence_rename_search_audit_and_delete(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")
    conversation = store.create_conversation(OWNER_ID)
    result = {
        "ok": True,
        "columns": ["sales"],
        "rows": [[123]],
        "row_count": 1,
        "truncated": False,
    }
    user_message, assistant_message = store.add_turn(
        conversation.conversation_id,
        OWNER_ID,
        "Ventas de septiembre",
        "Las ventas fueron 123.",
        result,
        duration_ms=25.5,
        sql_history=[{"sql": "SELECT 123", "guard_passed": True, "result": result}],
        sql_durations_ms=[7.25],
    )

    assert user_message.role == "user"
    assert assistant_message.data == result
    assert [item.role for item in store.get_messages(conversation.conversation_id, OWNER_ID)] == [
        "user",
        "assistant",
    ]
    renamed = store.rename_conversation(
        conversation.conversation_id, OWNER_ID, "Ventas septiembre"
    )
    assert renamed.title == "Ventas septiembre"
    assert (
        store.list_conversations(OWNER_ID, "septiembre")[0].conversation_id
        == conversation.conversation_id
    )
    assert store.list_conversations(OWNER_ID, "sin coincidencias") == []

    with store.engine.connect() as connection:
        turn = connection.execute(select(audit_turns)).one()
        attempt = connection.execute(select(audit_sql_attempts)).one()
    assert turn.sql_attempt_count == 1
    assert turn.duration_ms == 25.5
    assert turn.success is True
    assert attempt.sql_text == "SELECT 123"
    assert attempt.guard_passed is True
    assert attempt.duration_ms == 7.25
    assert attempt.row_count == 1
    assert attempt.truncated is False

    store.delete_conversation(conversation.conversation_id, OWNER_ID)
    with store.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(messages)) == 0
        assert connection.scalar(select(func.count()).select_from(audit_turns)) == 0
        assert connection.scalar(select(func.count()).select_from(audit_sql_attempts)) == 0


@pytest.mark.asyncio
async def test_delete_clears_only_matching_sdk_session(tmp_path: Path) -> None:
    app_db_path = tmp_path / "app.sqlite3"
    session_db_path = tmp_path / "sessions.sqlite3"
    store = ConversationStore(app_db_path, session_db_path)
    first = store.create_conversation(OWNER_ID)
    second = store.create_conversation(OWNER_ID)
    first_session = SQLiteSession(first.conversation_id, session_db_path)
    second_session = SQLiteSession(second.conversation_id, session_db_path)
    await first_session.add_items([{"role": "user", "content": "Primera"}])
    await second_session.add_items([{"role": "user", "content": "Segunda"}])
    first_session.close()
    second_session.close()

    await store.delete_conversation_with_session(first.conversation_id, OWNER_ID)

    deleted_session = SQLiteSession(first.conversation_id, session_db_path)
    retained_session = SQLiteSession(second.conversation_id, session_db_path)
    assert await deleted_session.get_items() == []
    assert await retained_session.get_items() == [{"role": "user", "content": "Segunda"}]
    deleted_session.close()
    retained_session.close()


def test_new_conversation_endpoints_and_excel_export(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")

    def unexpected_call(*_: Any, **__: Any) -> None:
        raise AssertionError("Excel export must not call OpenAI or analytics SQL Server")

    monkeypatch.setattr("bi_agent_api.main.answer_question", unexpected_call)
    monkeypatch.setattr("bi_agent_api.database.execute_query", unexpected_call)
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: User(
        user_id=OWNER_ID,
        username="tester",
        display_name="Tester",
        is_admin=False,
        is_active=True,
        must_change_password=False,
    )
    try:
        with TestClient(app) as client:
            authenticate(client, store)
            created = client.post("/api/v1/conversations").json()
            conversation_id = created["conversation_id"]
            renamed = client.patch(
                f"/api/v1/conversations/{conversation_id}",
                json={"title": "Análisis marcas"},
            )
            found = client.get("/api/v1/conversations", params={"search": "marcas"})
            not_found = client.get("/api/v1/conversations", params={"search": "tiendas"})
            exported = client.post(
                "/api/v1/exports/excel",
                json={
                    "ok": True,
                    "columns": ["brandName", "sales"],
                    "rows": [["COLGATE", 1234.5]],
                    "row_count": 1,
                    "truncated": False,
                },
            )
            deleted = client.delete(f"/api/v1/conversations/{conversation_id}")
    finally:
        app.dependency_overrides.clear()

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Análisis marcas"
    assert len(found.json()) == 1
    assert not_found.json() == []
    assert deleted.status_code == 204
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    workbook = load_workbook(BytesIO(exported.content), read_only=True)
    sheet = workbook["Datos"]
    assert list(sheet.values) == [("Marca", "Ventas"), ("COLGATE", 1234.5)]
    workbook.close()


def test_failed_turn_does_not_leave_visible_message(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")

    async def fail_answer(*_: Any, **__: Any) -> tuple[str, Any]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("bi_agent_api.main.answer_question", fail_answer)
    app.dependency_overrides[get_conversation_store] = lambda: store
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            authenticate(client, store)
            conversation_id = client.post("/api/v1/conversations").json()["conversation_id"]
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"message": "Ventas"},
            )
            history = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert history.json()["messages"] == []
    with store.engine.connect() as connection:
        audit = connection.execute(select(audit_turns)).one()
    assert audit.success is False
    assert audit.error == "agent_error"
    assert audit.sql_attempt_count == 0


@pytest.mark.parametrize("failed_audit", [False, True], ids=["audit-ok", "audit-fails"])
def test_app_db_failure_rolls_back_only_current_sdk_session_items(
    tmp_path: Path,
    monkeypatch: Any,
    failed_audit: bool,
) -> None:
    session_db_path = tmp_path / "sessions.sqlite3"
    store = ConversationStore(tmp_path / "app.sqlite3", session_db_path)
    conversation = store.create_conversation(OWNER_ID)
    previous_items = [
        {"role": "user", "content": "Pregunta anterior"},
        {
            "role": "assistant",
            "type": "message",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Respuesta anterior"}],
        },
    ]

    async def seed_session() -> None:
        session = SQLiteSession(conversation.conversation_id, session_db_path)
        await session.add_items(previous_items)
        session.close()

    async def fake_answer(_: str, __: Any, **kwargs: Any) -> tuple[str, Any]:
        await kwargs["session"].add_items(
            [
                {"role": "user", "content": "Pregunta nueva"},
                {
                    "role": "assistant",
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Respuesta nueva"}],
                },
            ]
        )
        return "Respuesta nueva", SimpleNamespace(
            latest_result=None,
            sql_history=[],
            sql_durations_ms=[],
        )

    def fail_persistence(*_: Any, **__: Any) -> None:
        raise RuntimeError("App DB write failed")

    asyncio.run(seed_session())
    monkeypatch.setattr("bi_agent_api.main.answer_question", fake_answer)
    monkeypatch.setattr(store, "add_turn", fail_persistence)
    if failed_audit:
        monkeypatch.setattr(store, "add_failed_audit", fail_persistence)
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: User(
        user_id=OWNER_ID,
        username="tester",
        display_name="Tester",
        is_admin=False,
        is_active=True,
        must_change_password=False,
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/conversations/{conversation.conversation_id}/messages",
                json={"message": "Pregunta nueva"},
            )
    finally:
        app.dependency_overrides.clear()

    async def read_session() -> list[Any]:
        session = SQLiteSession(conversation.conversation_id, session_db_path)
        items = await session.get_items()
        session.close()
        return items

    assert response.status_code == 502
    assert asyncio.run(read_session()) == previous_items
    assert store.get_messages(conversation.conversation_id, OWNER_ID) == []


def test_excel_rejects_more_than_visible_limit(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")
    app.dependency_overrides[get_conversation_store] = lambda: store
    with TestClient(app) as client:
        authenticate(client, store)
        response = client.post(
            "/api/v1/exports/excel",
            json={
                "columns": ["value"],
                "rows": [[number] for number in range(201)],
                "row_count": 200,
                "truncated": True,
            },
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
