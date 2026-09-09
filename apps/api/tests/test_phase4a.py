from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects import mssql
from sqlalchemy.schema import CreateTable

from bi_agent_api.config import Settings
from bi_agent_api.conversations import (
    ConversationStore,
    audit_sql_attempts,
    audit_turns,
    conversations,
    get_conversation_store,
    messages,
)
from bi_agent_api.main import app


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
    conversation = store.create_conversation()
    result = {
        "ok": True,
        "columns": ["sales"],
        "rows": [[123]],
        "row_count": 1,
        "truncated": False,
    }
    user_message, assistant_message = store.add_turn(
        conversation.conversation_id,
        "Ventas de septiembre",
        "Las ventas fueron 123.",
        result,
        duration_ms=25.5,
        sql_history=[{"sql": "SELECT 123", "guard_passed": True, "result": result}],
        sql_durations_ms=[7.25],
    )

    assert user_message.role == "user"
    assert assistant_message.data == result
    assert [item.role for item in store.get_messages(conversation.conversation_id)] == [
        "user",
        "assistant",
    ]
    renamed = store.rename_conversation(conversation.conversation_id, "Ventas septiembre")
    assert renamed.title == "Ventas septiembre"
    assert store.list_conversations("septiembre")[0].conversation_id == conversation.conversation_id
    assert store.list_conversations("sin coincidencias") == []

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

    store.delete_conversation(conversation.conversation_id)
    with store.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(messages)) == 0
        assert connection.scalar(select(func.count()).select_from(audit_turns)) == 0
        assert connection.scalar(select(func.count()).select_from(audit_sql_attempts)) == 0


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
    try:
        with TestClient(app) as client:
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


def test_excel_rejects_more_than_visible_limit() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/exports/excel",
            json={
                "columns": ["value"],
                "rows": [[number] for number in range(201)],
                "row_count": 200,
                "truncated": True,
            },
        )
    assert response.status_code == 422
