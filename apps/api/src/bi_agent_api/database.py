from datetime import date, datetime, time
from decimal import Decimal
from threading import Timer
from typing import Any

import duckdb

from .config import Settings

_VIEW_SOURCES = {
    "dbo.VW_Stores": "Stores/*.parquet",
    "dbo.VW_Products": "Products/*.parquet",
    # DuckDB's abfss reader accepts recursive lookups only when the pattern
    # ends in **; the Sales dataset contains only Parquet files.
    "dbo.VW_SalesLast13Months": "Sales/**",
}


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


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parquet_uri(settings: Settings, relative_glob: str) -> str:
    filesystem = settings.adls_filesystem.strip("/")
    base_path = settings.adls_base_path.strip("/")
    if not filesystem or not base_path:
        raise ValueError("ADLS_FILESYSTEM y ADLS_BASE_PATH son obligatorios.")
    return f"abfss://{filesystem}/{base_path}/{relative_glob}"


def _load_azure_extension(connection: Any) -> None:
    try:
        connection.execute("LOAD azure")
    except duckdb.Error:
        connection.execute("INSTALL azure")
        connection.execute("LOAD azure")


def _register_azure_secret(connection: Any, connection_string: str) -> None:
    connection.execute(
        """
        CREATE OR REPLACE SECRET adls_query_secret (
            TYPE azure,
            PROVIDER config,
            CONNECTION_STRING ?
        )
        """,
        [connection_string],
    )


def _validate_parquet_schema(connection: Any, source: str, view: str) -> None:
    rows = connection.execute(
        """
        SELECT file_name, name, duckdb_type, column_id
        FROM parquet_schema(?::VARCHAR)
        WHERE name <> 'schema' AND column_id IS NOT NULL
        ORDER BY file_name, column_id
        """,
        [source],
    ).fetchall()
    schemas: dict[str, list[tuple[str, str]]] = {}
    for file_name, name, duckdb_type, _column_id in rows:
        schemas.setdefault(str(file_name), []).append((str(name), str(duckdb_type)))

    if not schemas:
        raise RuntimeError(f"No se encontraron archivos Parquet para {view}.")

    reference_file, reference_schema = next(iter(schemas.items()))
    for file_name, schema in schemas.items():
        if schema != reference_schema:
            raise RuntimeError(
                f"Schema drift detectado para {view}: {file_name} no coincide con "
                f"{reference_file}. Esperado {reference_schema!r}; encontrado {schema!r}."
            )


def _create_views(connection: Any, settings: Settings) -> None:
    connection.execute("CREATE SCHEMA dbo")
    for view, relative_glob in _VIEW_SOURCES.items():
        source = _parquet_uri(settings, relative_glob)
        _validate_parquet_schema(connection, source, view)
        connection.execute(
            f"CREATE VIEW {view} AS SELECT * FROM read_parquet({_sql_literal(source)})"
        )


def _execute_with_timeout(connection: Any, sql: str, timeout_seconds: int) -> Any:
    timer = Timer(timeout_seconds, connection.interrupt)
    timer.daemon = True
    timer.start()
    try:
        return connection.execute(sql)
    finally:
        timer.cancel()


def execute_query(sql: str, settings: Settings) -> dict[str, Any]:
    """Ejecuta SQL DuckDB y retorna como mÃ¡ximo MAX_RESULT_ROWS."""
    connection_string = settings.azure_storage_connection_string.get_secret_value()
    if not connection_string:
        raise ValueError("Falta AZURE_STORAGE_CONNECTION_STRING.")

    connection = duckdb.connect(database=":memory:")
    try:
        _load_azure_extension(connection)
        _register_azure_secret(connection, connection_string)
        connection.execute("SET default_collation = 'NOCASE.NOACCENT'")
        _create_views(connection, settings)

        cursor = _execute_with_timeout(connection, sql, settings.query_timeout_seconds)
        if cursor.description is None:
            raise RuntimeError("La consulta no devolviÃ³ un conjunto de resultados.")

        columns = [str(column[0]) for column in cursor.description]
        fetched = cursor.fetchmany(settings.max_result_rows + 1)
        truncated = len(fetched) > settings.max_result_rows
        rows = [
            [_json_value(value) for value in row]
            for row in fetched[: settings.max_result_rows]
        ]
        return {
            "ok": True,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }
    finally:
        connection.close()
