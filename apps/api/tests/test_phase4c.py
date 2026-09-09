from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agents.testing import ScriptedModel
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from bi_agent_api.agent import answer_question
from bi_agent_api.auth import AuthStore, get_auth_store
from bi_agent_api.config import Settings
from bi_agent_api.conversations import (
    ConversationStore,
    audit_turns,
    get_conversation_store,
    messages,
)
from bi_agent_api.main import app
from bi_agent_api.usage import AgentUsage, estimate_cost_usd


def usage() -> AgentUsage:
    return AgentUsage(
        requests=2,
        input_tokens=10_950,
        cached_input_tokens=3_120,
        output_tokens=1_890,
        reasoning_tokens=540,
        total_tokens=12_840,
    )


@pytest.mark.asyncio
async def test_answer_question_extracts_current_run_usage(monkeypatch: Any) -> None:
    reported_usage = SimpleNamespace(
        requests=2,
        input_tokens=10_950,
        input_tokens_details=SimpleNamespace(cached_tokens=3_120),
        output_tokens=1_890,
        output_tokens_details=SimpleNamespace(reasoning_tokens=540),
        total_tokens=12_840,
    )

    async def fake_run(*_: Any, **__: Any) -> Any:
        return SimpleNamespace(
            final_output="Respuesta",
            context_wrapper=SimpleNamespace(usage=reported_usage),
        )

    monkeypatch.setattr("bi_agent_api.agent.Runner.run", fake_run)
    _, context = await answer_question(
        "Pregunta",
        Settings(_env_file=None, openai_model="test-model"),
        model=ScriptedModel(),
        sql_executor=lambda _: {},
    )

    assert context.usage == usage()


def test_cost_uses_decimal_cached_tokens_and_does_not_charge_reasoning_twice() -> None:
    expected = Decimal("0.0058155")

    assert estimate_cost_usd("gpt-5-mini", usage()) == expected
    assert estimate_cost_usd(
        "gpt-5-mini",
        AgentUsage(**{**usage().__dict__, "reasoning_tokens": 999_999}),
    ) == expected
    assert estimate_cost_usd(
        "gpt-5-mini",
        AgentUsage(1, 100, 200, 0, 0, 100),
    ) == Decimal("0.000005")


def test_unknown_model_keeps_usage_but_has_no_estimated_cost() -> None:
    assert estimate_cost_usd("unpriced-model", usage()) is None


def test_audit_links_assistant_and_history_returns_usage_metadata(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")
    conversation = store.create_conversation(1)

    user_message, assistant_message = store.add_turn(
        conversation.conversation_id,
        1,
        "Pregunta",
        "Respuesta",
        None,
        duration_ms=6_420,
        sql_history=[],
        sql_durations_ms=[],
        model_name="gpt-5-mini",
        usage=usage(),
    )

    with store.engine.connect() as connection:
        audit = connection.execute(select(audit_turns)).one()
    assert audit.assistant_message_id == assistant_message.message_id
    assert audit.assistant_message_id != user_message.message_id
    assert audit.model_name == "gpt-5-mini"
    assert audit.llm_requests == 2
    assert audit.input_tokens == 10_950
    assert audit.cached_input_tokens == 3_120
    assert audit.output_tokens == 1_890
    assert audit.reasoning_tokens == 540
    assert audit.total_tokens == 12_840
    assert audit.estimated_cost_usd == Decimal("0.00581550")

    history = store.get_messages(conversation.conversation_id, 1)
    assert history[0].metadata is None
    assert history[1].metadata is not None
    assert history[1].metadata.duration_ms == 6_420
    assert history[1].metadata.llm_requests == 2
    assert history[1].metadata.cached_input_tokens == 3_120
    assert history[1].metadata.reasoning_tokens == 540
    assert history[1].metadata.estimated_cost_usd == Decimal("0.00581550")


def test_historical_assistant_without_linked_audit_has_null_metadata(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")
    conversation = store.create_conversation(1)
    timestamp = datetime.now(UTC)
    with store.engine.begin() as connection:
        connection.execute(
            insert(messages).values(
                conversation_id=conversation.conversation_id,
                role="assistant",
                content="Respuesta histórica",
                data_json=None,
                created_at=timestamp,
            )
        )

    history = store.get_messages(conversation.conversation_id, 1)

    assert len(history) == 1
    assert history[0].content == "Respuesta histórica"
    assert history[0].metadata is None


def test_failed_audit_has_no_assistant_message_id(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")
    conversation = store.create_conversation(1)

    store.add_failed_audit(
        conversation.conversation_id,
        1,
        duration_ms=12,
        error="agent_error",
    )

    with store.engine.connect() as connection:
        audit = connection.execute(select(audit_turns)).one()
    assert audit.assistant_message_id is None
    assert audit.model_name is None
    assert audit.total_tokens is None


def test_usage_history_remains_isolated_by_user_id(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3")
    auth = AuthStore(store.engine)
    first = auth.create_user("first", "First", "first-password", must_change_password=False)
    auth.create_user("second", "Second", "second-password", must_change_password=False)
    conversation = store.create_conversation(first.user_id)
    store.add_turn(
        conversation.conversation_id,
        first.user_id,
        "Pregunta",
        "Respuesta",
        None,
        duration_ms=1,
        sql_history=[],
        sql_durations_ms=[],
        model_name="gpt-5-mini",
        usage=usage(),
    )
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_auth_store] = lambda: auth
    try:
        with TestClient(app) as client:
            client.post(
                "/api/v1/auth/login",
                json={"username": "second", "password": "second-password"},
            )
            response = client.get(
                f"/api/v1/conversations/{conversation.conversation_id}/messages"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_back_to_login_calls_real_logout() -> None:
    source = Path("apps/web/components/auth-shell.tsx").read_text(encoding="utf-8")

    assert "onBackToLogin={() => void logout()}" in source
    assert "onBackToLogin={() => setUser(null)}" not in source


def test_migration_matches_applied_nullable_usage_schema() -> None:
    migration = Path("apps/api/migrations/003_phase4c_usage.sql").read_text(encoding="utf-8")

    assert "assistant_message_id bigint NULL" in migration
    assert "estimated_cost_usd decimal(19,8) NULL" in migration
    assert "FK_app_audit_turns_assistant_message" in migration
    assert "CREATE UNIQUE INDEX UX_app_audit_turns_assistant_message" in migration
    assert "WHERE assistant_message_id IS NOT NULL" in migration
    assert "CK_app_audit_turns_usage_nonnegative" in migration
    assert "app_conversations] WHERE user_id IS NULL" in migration
    assert "app_audit_turns] WHERE user_id IS NULL" in migration
    assert "ALTER COLUMN user_id" not in migration
