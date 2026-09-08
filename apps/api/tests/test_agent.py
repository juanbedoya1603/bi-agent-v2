import json
from typing import Any

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from bi_agent_api.agent import answer_question
from bi_agent_api.config import Settings


def make_settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="", openai_model="test-model")


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
