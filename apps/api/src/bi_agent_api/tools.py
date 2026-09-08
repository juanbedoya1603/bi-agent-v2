import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
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
    context.sql_attempts += 1
    if context.sql_attempts > context.settings.max_sql_attempts_per_turn:
        result = {
            "ok": False,
            "error": {
                "type": "attempt_limit",
                "message": "Se alcanzó el máximo de intentos SQL para este turno.",
            },
        }
        context.latest_result = result
        return result

    try:
        validated_sql = validate_readonly_sql(sql)
    except SqlGuardError as error:
        result = {
            "ok": False,
            "error": {"type": "sql_guard", "code": error.code, "message": error.message},
        }
        context.latest_result = result
        return result

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
    context.latest_result = result
    return result


run_readonly_sql = function_tool(
    _run_readonly_sql,
    name_override="run_readonly_sql",
    description_override=(
        "Valida y ejecuta una única consulta SELECT T-SQL sobre las views BI permitidas."
    ),
)
