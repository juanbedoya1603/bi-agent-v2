from typing import Any

from bi_agent_api.config import Settings
from bi_agent_api.database import execute_query


class FakeCursor:
    description = [("id",), ("value",)]
    timeout = 0

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.sql = ""
        self.fetch_size = 0
        self.closed = False

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        self.fetch_size = size
        return self.rows[:size]

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


def db_settings(**overrides: Any) -> Settings:
    values = {
        "analytics_db_host": "sql.internal",
        "analytics_db_name": "analytics",
        "analytics_db_user": "bi_reader",
        "analytics_db_password": "secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_execute_query_returns_rows_and_closes_resources() -> None:
    cursor = FakeCursor([(1, "one"), (2, "two")])
    connection = FakeConnection(cursor)

    result = execute_query(
        "SELECT id, value FROM dbo.VW_Products",
        db_settings(),
        connect=lambda _: connection,
    )

    assert result == {
        "ok": True,
        "columns": ["id", "value"],
        "rows": [[1, "one"], [2, "two"]],
        "row_count": 2,
        "truncated": False,
    }
    assert cursor.timeout == 600
    assert cursor.closed and connection.closed


def test_execute_query_fetches_201_and_returns_only_200() -> None:
    cursor = FakeCursor([(number, f"row-{number}") for number in range(201)])
    connection = FakeConnection(cursor)

    result = execute_query(
        "SELECT id, value FROM dbo.VW_Products ORDER BY id",
        db_settings(max_result_rows=200),
        connect=lambda _: connection,
    )

    assert cursor.fetch_size == 201
    assert "TOP" not in cursor.sql.upper()
    assert result["row_count"] == 200
    assert result["truncated"] is True
    assert len(result["rows"]) == 200
