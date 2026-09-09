import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from agents import RunContextWrapper, function_tool

from .config import Settings
from .sql_guard import SqlGuardError, validate_readonly_sql

SqlExecutor = Callable[[str], dict[str, Any]]


@dataclass
class BiAgentContext:
    settings: Settings
    sql_executor: SqlExecutor
    sql_attempts: int = 0
    latest_result: dict[str, Any] | None = field(default=None)
    sql_history: list[dict[str, Any]] = field(default_factory=list)
    sql_durations_ms: list[float] = field(default_factory=list)


def _safe_error_message(error: Exception, settings: Settings) -> str:
    message = " ".join(str(part) for part in getattr(error, "args", ()) if part)
    if not message:
        message = str(error) or "Error desconocido de SQL Server."
    for secret in (
        settings.analytics_db_password,
        settings.analytics_db_user,
        settings.analytics_db_host,
    ):
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"(?i)(pwd|password)\s*=\s*[^;\s]+", r"\1=[REDACTED]", message)
    return message[:1000]


async def _run_readonly_sql(wrapper: RunContextWrapper[BiAgentContext], sql: str) -> dict[str, Any]:
    """Ejecuta una consulta T-SQL de solo lectura sobre las tres views autorizadas."""
    context = wrapper.context
    started_at = perf_counter()
    context.sql_attempts += 1
    history_entry: dict[str, Any] = {"sql": sql, "guard_passed": False, "result": None}
    context.sql_history.append(history_entry)
    if context.sql_attempts > context.settings.max_sql_attempts_per_turn:
        result = {
            "ok": False,
            "error": {
                "type": "attempt_limit",
                "message": "Se alcanzó el máximo de intentos SQL para este turno.",
            },
        }
        history_entry["result"] = result
        context.latest_result = result
        context.sql_durations_ms.append((perf_counter() - started_at) * 1000)
        return result

    try:
        validated_sql = validate_readonly_sql(sql)
    except SqlGuardError as error:
        result = {
            "ok": False,
            "error": {"type": "sql_guard", "code": error.code, "message": error.message},
        }
        history_entry["result"] = result
        context.latest_result = result
        context.sql_durations_ms.append((perf_counter() - started_at) * 1000)
        return result

    history_entry["guard_passed"] = True
    try:
        result = await asyncio.to_thread(context.sql_executor, validated_sql)
    except Exception as error:  # La tool convierte errores DB en observaciones corregibles.
        result = {
            "ok": False,
            "error": {
                "type": "sql_error",
                "message": _safe_error_message(error, context.settings),
            },
        }
    history_entry["result"] = result
    context.latest_result = result
    context.sql_durations_ms.append((perf_counter() - started_at) * 1000)
    return result


run_readonly_sql = function_tool(
    _run_readonly_sql,
    name_override="run_readonly_sql",
    description_override=(
        "Valida y ejecuta una única consulta SELECT T-SQL sobre las views BI permitidas."
    ),
)
