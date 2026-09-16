from typing import Any

from bi_agent_api import database
from bi_agent_api.config import Settings
from bi_agent_api.database import execute_query


def db_settings(**overrides: Any) -> Settings:
    values = {
        "azure_storage_connection_string": "test-connection-string",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _local_views(connection: Any, _settings: Settings) -> None:
    connection.execute("CREATE SCHEMA dbo")
    connection.execute(
        """
        CREATE VIEW dbo.VW_Products AS
        SELECT * FROM (VALUES (1, 'one'), (2, 'two')) AS products(id, value)
        """
    )
    connection.execute(
        """
        CREATE VIEW dbo.VW_Stores AS
        SELECT * FROM (VALUES (10, 'BOGOTA')) AS stores(idPartner, cityName)
        """
    )
    connection.execute(
        """
        CREATE VIEW dbo.VW_SalesLast13Months AS
        SELECT * FROM (VALUES (10, 1, 125.50::DECIMAL(18, 2)))
            AS sales(idStore, idProduct, totalSaleValue)
        """
    )


def _use_local_views(monkeypatch: Any) -> None:
    monkeypatch.setattr(database, "_load_azure_extension", lambda _connection: None)
    monkeypatch.setattr(database, "_register_azure_secret", lambda *_args: None)
    monkeypatch.setattr(database, "_create_views", _local_views)


def test_execute_query_returns_contract_and_closes_connection(monkeypatch: Any) -> None:
    _use_local_views(monkeypatch)
    connections: list[Any] = []
    connect = database.duckdb.connect

    class TrackedConnection:
        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.closed = False

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

        def close(self) -> None:
            self.closed = True
            self.inner.close()

    def tracked_connect(*args: Any, **kwargs: Any) -> TrackedConnection:
        connection = TrackedConnection(connect(*args, **kwargs))
        connections.append(connection)
        return connection

    monkeypatch.setattr(database.duckdb, "connect", tracked_connect)

    result = execute_query(
        "SELECT id, value FROM dbo.VW_Products ORDER BY id",
        db_settings(),
    )

    assert result == {
        "ok": True,
        "columns": ["id", "value"],
        "rows": [[1, "one"], [2, "two"]],
        "row_count": 2,
        "truncated": False,
    }
    assert len(connections) == 1
    assert connections[0].closed is True


def test_execute_query_exposes_all_three_logical_views(monkeypatch: Any) -> None:
    _use_local_views(monkeypatch)

    queries = {
        "dbo.VW_Stores": ("SELECT idPartner FROM dbo.VW_Stores", 1),
        "dbo.VW_Products": ("SELECT id FROM dbo.VW_Products", 2),
        "dbo.VW_SalesLast13Months": ("SELECT totalSaleValue FROM dbo.VW_SalesLast13Months", 1),
    }

    for view, (sql, expected_row_count) in queries.items():
        result = execute_query(sql, db_settings())
        assert result["ok"] is True, view
        assert result["row_count"] == expected_row_count, view


def test_execute_query_fetches_201_and_returns_only_200(monkeypatch: Any) -> None:
    _use_local_views(monkeypatch)

    def local_many_views(connection: Any, _settings: Settings) -> None:
        connection.execute("CREATE SCHEMA dbo")
        connection.execute(
            """
            CREATE VIEW dbo.VW_Products AS
            SELECT range AS id, 'row-' || range::VARCHAR AS value FROM range(201)
            """
        )
        connection.execute("CREATE VIEW dbo.VW_Stores AS SELECT 1 AS idPartner")
        connection.execute("CREATE VIEW dbo.VW_SalesLast13Months AS SELECT 1 AS idStore")

    monkeypatch.setattr(database, "_create_views", local_many_views)

    result = execute_query(
        "SELECT id, value FROM dbo.VW_Products ORDER BY id",
        db_settings(max_result_rows=200),
    )

    assert result["row_count"] == 200
    assert result["truncated"] is True
    assert len(result["rows"]) == 200
    assert result["rows"][0] == [0, "row-0"]
    assert result["rows"][-1] == [199, "row-199"]


def test_execute_query_preserves_decimal_and_date_serialization(monkeypatch: Any) -> None:
    _use_local_views(monkeypatch)

    result = execute_query(
        "SELECT CAST(123.4500 AS DECIMAL(18, 4)) AS amount, DATE '2026-08-01' AS business_date",
        db_settings(),
    )

    assert result["rows"] == [["123.4500", "2026-08-01"]]


def test_sql_auth_connection_string() -> None:
    settings = Settings(
        _env_file=None,
        analytics_db_host="sql.internal",
        analytics_db_name="analytics",
        analytics_db_user="bi_reader",
        analytics_db_password="secret",
    )
    connection_string = settings.database_connection_string()

    assert "SERVER=sql.internal,1433" in connection_string
    assert "DATABASE=analytics" in connection_string
    assert "UID=bi_reader" in connection_string
    assert "PWD={secret}" in connection_string
    assert "Authentication=ActiveDirectoryInteractive" not in connection_string


def test_entra_interactive_connection_string() -> None:
    settings = Settings(
        _env_file=None,
        analytics_db_host="sql.internal",
        analytics_db_name="analytics",
        analytics_db_user="person@company.com",
        analytics_db_auth="entra_interactive",
    )
    connection_string = settings.database_connection_string()

    assert "UID=person@company.com" in connection_string
    assert "Authentication=ActiveDirectoryInteractive" in connection_string
    assert "Encrypt=yes" in connection_string
    assert "TrustServerCertificate=no" in connection_string


def test_entra_interactive_connection_string_does_not_include_password() -> None:
    settings = Settings(
        _env_file=None,
        analytics_db_host="sql.internal",
        analytics_db_name="analytics",
        analytics_db_user="bi_reader",
        analytics_db_auth="entra_interactive",
        analytics_db_password="should-not-be-used",
    )
    connection_string = settings.database_connection_string()

    assert "PWD=" not in connection_string
    assert "should-not-be-used" not in connection_string


def test_both_auth_modes_keep_application_intent_readonly() -> None:
    sql_settings = Settings(
        _env_file=None,
        analytics_db_host="sql.internal",
        analytics_db_name="analytics",
        analytics_db_user="bi_reader",
        analytics_db_password="secret",
    )
    entra_settings = Settings(
        _env_file=None,
        analytics_db_host="sql.internal",
        analytics_db_name="analytics",
        analytics_db_user="bi_reader",
        analytics_db_auth="entra_interactive",
    )

    assert "ApplicationIntent=ReadOnly" in sql_settings.database_connection_string()
    assert "ApplicationIntent=ReadOnly" in entra_settings.database_connection_string()
