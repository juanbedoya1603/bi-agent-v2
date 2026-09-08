import json
from pathlib import Path
from typing import Any

import pytest
from agents import SQLiteSession
from agents.testing import ScriptedModel, assistant_message, function_call

from bi_agent_api.agent import answer_question, build_agent
from bi_agent_api.config import Settings


def make_settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="", openai_model="test-model")


def test_agent_disables_parallel_tool_calls_and_response_storage() -> None:
    agent = build_agent(make_settings(), model=ScriptedModel())

    assert agent.model_settings.parallel_tool_calls is False
    assert agent.model_settings.store is False


@pytest.mark.asyncio
async def test_runner_calls_tool_and_uses_its_output() -> None:
    sql = """SELECT SUM(s.totalSaleValue) AS sales
    FROM dbo.VW_SalesLast13Months s
    JOIN dbo.VW_Products p ON p.productId = s.idProduct
    JOIN dbo.VW_Stores st ON st.idPartner = s.idStore
    WHERE s.[date] >= '2026-08-01' AND s.[date] < '2026-09-01'
      AND p.brandName = 'COLGATE' AND st.cityName = 'BOGOTA'"""
    model = ScriptedModel(
        [
            [function_call("run_readonly_sql", {"sql": sql}, call_id="sql-1")],
            [assistant_message("Colgate vendió $1.234 en Bogotá en agosto de 2026.")],
        ]
    )
    executed: list[str] = []

    def executor(received_sql: str) -> dict[str, Any]:
        executed.append(received_sql)
        return {
            "ok": True,
            "columns": ["sales"],
            "rows": [[1234]],
            "row_count": 1,
            "truncated": False,
        }

    answer, context = await answer_question(
        "Ventas de Colgate en Bogotá en agosto de 2026",
        make_settings(),
        model=model,
        sql_executor=executor,
    )

    assert answer == "Colgate vendió $1.234 en Bogotá en agosto de 2026."
    assert executed == [sql]
    assert context.sql_attempts == 1
    assert context.sql_history == [
        {"sql": sql, "guard_passed": True, "result": context.latest_result}
    ]
    second_call_input = json.dumps(model.calls[1].input, default=str)
    assert "1234" in second_call_input
    model.assert_complete()


@pytest.mark.asyncio
async def test_tool_error_returns_to_model_and_sql_can_be_corrected() -> None:
    invalid_sql = "SELECT badColumn FROM dbo.VW_Products"
    corrected_sql = "SELECT TOP 1 productName FROM dbo.VW_Products"
    model = ScriptedModel(
        [
            [function_call("run_readonly_sql", {"sql": invalid_sql}, call_id="sql-1")],
            [function_call("run_readonly_sql", {"sql": corrected_sql}, call_id="sql-2")],
            [assistant_message("La consulta corregida devolvió Crema Dental Colgate.")],
        ]
    )
    attempts = 0

    def executor(sql: str) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if sql == invalid_sql:
            raise RuntimeError("Invalid column name 'badColumn'.")
        return {
            "ok": True,
            "columns": ["productName"],
            "rows": [["Crema Dental Colgate"]],
            "row_count": 1,
            "truncated": False,
        }

    answer, context = await answer_question(
        "Busca un producto Colgate",
        make_settings(),
        model=model,
        sql_executor=executor,
    )

    assert attempts == 2
    assert context.sql_attempts == 2
    assert "Crema Dental Colgate" in answer
    error_input = json.dumps(model.calls[1].input, default=str)
    assert "Invalid column name" in error_input
    model.assert_complete()


@pytest.mark.asyncio
async def test_guard_rejection_is_captured_without_reaching_executor() -> None:
    unsafe_sql = "DELETE FROM dbo.VW_Products"
    model = ScriptedModel(
        [
            [function_call("run_readonly_sql", {"sql": unsafe_sql}, call_id="sql-1")],
            [assistant_message("La consulta fue rechazada por el guard de solo lectura.")],
        ]
    )
    executions = 0

    def executor(_: str) -> dict[str, Any]:
        nonlocal executions
        executions += 1
        return {}

    _, context = await answer_question(
        "Intenta una consulta insegura",
        make_settings(),
        model=model,
        sql_executor=executor,
    )

    assert executions == 0
    assert context.sql_history[0]["sql"] == unsafe_sql
    assert context.sql_history[0]["guard_passed"] is False
    assert context.sql_history[0]["result"]["error"]["type"] == "sql_guard"


@pytest.mark.asyncio
async def test_tool_enforces_three_attempts_per_turn() -> None:
    sql = "SELECT productName FROM dbo.VW_Products"
    model = ScriptedModel(
        [
            [function_call("run_readonly_sql", {"sql": sql}, call_id=f"sql-{number}")]
            for number in range(1, 5)
        ]
        + [[assistant_message("No fue posible completar la consulta.")]]
    )
    executions = 0

    def executor(_: str) -> dict[str, Any]:
        nonlocal executions
        executions += 1
        raise RuntimeError("Transient SQL error")

    _, context = await answer_question(
        "Consulta con errores",
        make_settings(),
        model=model,
        sql_executor=executor,
    )

    assert context.sql_attempts == 4
    assert executions == 3
    limit_input = json.dumps(model.calls[4].input, default=str)
    assert "attempt_limit" in limit_input


@pytest.mark.asyncio
async def test_sqlite_session_keeps_context_between_messages(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            [assistant_message("Colgate vendió $1.234 en agosto.")],
            [assistant_message("En Medellín vendió $456.")],
        ]
    )
    session = SQLiteSession("conversation-1", tmp_path / "sessions.sqlite3")

    await answer_question(
        "Ventas de Colgate en agosto de 2026",
        make_settings(),
        model=model,
        sql_executor=lambda _: {},
        session=session,
    )
    await answer_question(
        "Ahora Medellín",
        make_settings(),
        model=model,
        sql_executor=lambda _: {},
        session=session,
    )

    second_call_input = json.dumps(model.calls[1].input, ensure_ascii=False, default=str)
    assert "Ventas de Colgate en agosto de 2026" in second_call_input
    assert "Colgate vendió $1.234 en agosto." in second_call_input
    assert "Ahora Medellín" in second_call_input
    session.close()
    model.assert_complete()


@pytest.mark.asyncio
async def test_new_sqlite_session_has_no_previous_context(tmp_path: Path) -> None:
    first_model = ScriptedModel([[assistant_message("Respuesta de la primera conversación.")]])
    second_model = ScriptedModel([[assistant_message("Respuesta independiente.")]])
    db_path = tmp_path / "sessions.sqlite3"
    first_session = SQLiteSession("conversation-1", db_path)
    second_session = SQLiteSession("conversation-2", db_path)

    await answer_question(
        "Pregunta privada de la primera conversación",
        make_settings(),
        model=first_model,
        sql_executor=lambda _: {},
        session=first_session,
    )
    await answer_question(
        "Pregunta nueva",
        make_settings(),
        model=second_model,
        sql_executor=lambda _: {},
        session=second_session,
    )

    second_input = json.dumps(second_model.calls[0].input, ensure_ascii=False, default=str)
    assert "Pregunta nueva" in second_input
    assert "Pregunta privada de la primera conversación" not in second_input
    first_session.close()
    second_session.close()
