from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Protocol

import pyodbc

from .config import Settings


class Cursor(Protocol):
    description: Any

    def execute(self, sql: str) -> Any: ...

    def fetchmany(self, size: int) -> list[Any]: ...

    def close(self) -> None: ...


class Connection(Protocol):
    timeout: int

    def cursor(self) -> Cursor: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[str], Connection]


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def execute_query(
    sql: str,
    settings: Settings,
    *,
    connect: ConnectionFactory = pyodbc.connect,
) -> dict[str, Any]:
    """Ejecuta SQL ya validado y retorna como máximo MAX_RESULT_ROWS."""
    connection: Connection | None = None
    cursor: Cursor | None = None
    try:
        connection = connect(settings.database_connection_string())
        connection.timeout = settings.query_timeout_seconds
        cursor = connection.cursor()
        cursor.execute(sql)

        columns = [str(column[0]) for column in cursor.description]
        fetched = cursor.fetchmany(settings.max_result_rows + 1)
        truncated = len(fetched) > settings.max_result_rows
        rows = [
            [_json_value(value) for value in row] for row in fetched[: settings.max_result_rows]
        ]
        return {
            "ok": True,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
