"""Seed a small, read-only Fabric/SQL Server snapshot into ADLS Gen2.

This script is intentionally independent from the application query path.  It
only reads the three approved views, writes temporary Parquet files below
``tmp/``, and overwrites the four explicitly configured ADLS test files.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pyodbc
from azure.storage.filedatalake import DataLakeServiceClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from bi_agent_api.config import Settings  # noqa: E402

DEFAULT_SALES_LIMIT = 100_000
DEFAULT_CHUNK_SIZE = 10_000


@dataclass(frozen=True)
class ExportTarget:
    name: str
    view: str
    adls_path: str
    query: str
    parameters: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Column:
    name: str
    duckdb_type: str


def _arrow_type(raw: Sequence[Any]) -> pa.DataType:
    _, type_code, _, _, precision, scale, _ = raw
    if type_code is bool:
        return pa.bool_()
    if type_code is int:
        return pa.int64()
    if type_code is float:
        return pa.float64()
    if type_code is Decimal:
        decimal_precision = min(max(int(precision or 38), 1), 38)
        decimal_scale = min(max(int(scale or 0), 0), decimal_precision)
        return pa.decimal128(decimal_precision, decimal_scale)
    if type_code is datetime:
        return pa.timestamp("us")
    if type_code is date:
        return pa.date32()
    if type_code is time:
        return pa.time64("us")
    if type_code is bytes:
        return pa.binary()
    return pa.string()


def _arrow_schema(description: Sequence[Sequence[Any]]) -> pa.Schema:
    return pa.schema(
        [pa.field(str(column[0]), _arrow_type(column), nullable=True) for column in description]
    )


def _columns_from_description(description: Sequence[Sequence[Any]]) -> list[Column]:
    """Map pyodbc's Python types to the equivalent DuckDB/Parquet types."""

    columns: list[Column] = []
    for raw in description:
        name, type_code, _, _, precision, scale, _ = raw
        if type_code is bool:
            duckdb_type = "BOOLEAN"
        elif type_code is int:
            duckdb_type = "BIGINT"
        elif type_code is float:
            duckdb_type = "DOUBLE"
        elif type_code is Decimal:
            decimal_precision = min(max(int(precision or 38), 1), 38)
            decimal_scale = min(max(int(scale or 0), 0), decimal_precision)
            duckdb_type = f"DECIMAL({decimal_precision}, {decimal_scale})"
        elif type_code is datetime:
            duckdb_type = "TIMESTAMP"
        elif type_code is date:
            duckdb_type = "DATE"
        elif type_code is time:
            duckdb_type = "TIME"
        elif type_code is bytes:
            duckdb_type = "BLOB"
        else:
            duckdb_type = "VARCHAR"
        columns.append(Column(name=str(name), duckdb_type=duckdb_type))
    return columns


def targets(sales_limit: int) -> tuple[ExportTarget, ...]:
    sales_query = """
        SELECT TOP (?) *
        FROM dbo.VW_SalesLast13Months
        WHERE [year] = ? AND [month] = ?
        ORDER BY [date], idStore, idTicket, idProduct
    """
    return (
        ExportTarget(
            "Stores",
            "dbo.VW_Stores",
            "TiendasOn/Stores/stores.parquet",
            "SELECT * FROM dbo.VW_Stores",
        ),
        ExportTarget(
            "Products",
            "dbo.VW_Products",
            "TiendasOn/Products/products.parquet",
            "SELECT * FROM dbo.VW_Products",
        ),
        ExportTarget(
            "Sales 2026/8",
            "dbo.VW_SalesLast13Months",
            "TiendasOn/Sales/2026/8/sales.parquet",
            sales_query,
            (sales_limit, 2026, 8),
        ),
        ExportTarget(
            "Sales 2026/9",
            "dbo.VW_SalesLast13Months",
            "TiendasOn/Sales/2026/9/sales.parquet",
            sales_query,
            (sales_limit, 2026, 9),
        ),
    )


def _batches(cursor: Any, chunk_size: int) -> Iterator[list[Any]]:
    while rows := cursor.fetchmany(chunk_size):
        yield rows


def _record_batch(rows: Sequence[Any], schema: pa.Schema) -> pa.RecordBatch:
    arrays = [
        pa.array([row[index] for row in rows], type=field.type)
        for index, field in enumerate(schema)
    ]
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


def _export_target(
    connection: Any,
    target: ExportTarget,
    output_path: Path,
    *,
    chunk_size: int,
) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        cursor.execute(target.query, *target.parameters)
        if cursor.description is None:
            raise RuntimeError(
                f"La consulta de {target.name} no devolvió un conjunto de resultados."
            )
        schema = _arrow_schema(cursor.description)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        row_count = 0
        with pq.ParquetWriter(output_path, schema, compression="zstd") as writer:
            for rows in _batches(cursor, chunk_size):
                writer.write_batch(_record_batch(rows, schema))
                row_count += len(rows)
        with duckdb.connect(database=":memory:") as export:
            quoted_output = str(output_path).replace("'", "''")
            parquet_schema = [
                {"name": str(row[0]), "type": str(row[1])}
                for row in export.execute(
                    f"DESCRIBE SELECT * FROM read_parquet('{quoted_output}')"
                ).fetchall()
            ]
        return {
            "view": target.view,
            "local_file": str(output_path.relative_to(ROOT)),
            "adls_path": target.adls_path,
            "rows": row_count,
            "columns": parquet_schema,
            "size_bytes": output_path.stat().st_size,
        }
    finally:
        cursor.close()


def _upload_file(filesystem: Any, local_path: Path, remote_path: str) -> None:
    """Overwrite this single file only; no directory or filesystem deletion occurs."""

    file_client = filesystem.get_file_client(remote_path)
    with local_path.open("rb") as stream:
        file_client.upload_data(stream, overwrite=True)


def seed(
    settings: Settings,
    *,
    sales_limit: int = DEFAULT_SALES_LIMIT,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict[str, Any]:
    if sales_limit < 1:
        raise ValueError("sales_limit debe ser mayor que cero.")
    if chunk_size < 1:
        raise ValueError("chunk_size debe ser mayor que cero.")

    connection_string = settings.azure_storage_connection_string.get_secret_value()
    if not connection_string:
        raise ValueError("Falta AZURE_STORAGE_CONNECTION_STRING.")

    report: dict[str, Any] = {
        "status": "running",
        "filesystem": settings.adls_filesystem,
        "sales_limit_per_month": sales_limit,
        "chunk_size": chunk_size,
        "exports": [],
    }
    sql_connection = pyodbc.connect(settings.database_connection_string())
    sql_connection.timeout = settings.query_timeout_seconds
    try:
        service = DataLakeServiceClient.from_connection_string(connection_string)
        filesystem = service.get_file_system_client(settings.adls_filesystem)
        filesystem.get_file_system_properties()
        with tempfile.TemporaryDirectory(prefix="adls-seed-", dir=ROOT / "tmp") as directory:
            temporary_directory = Path(directory)
            for target in targets(sales_limit):
                local_path = temporary_directory / Path(target.adls_path).name
                export_report = _export_target(
                    sql_connection,
                    target,
                    local_path,
                    chunk_size=chunk_size,
                )
                _upload_file(filesystem, local_path, target.adls_path)
                export_report["uploaded"] = True
                report["exports"].append(export_report)
    finally:
        sql_connection.close()

    report["status"] = "passed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sales-limit", type=int, default=DEFAULT_SALES_LIMIT)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    arguments = parser.parse_args()
    settings = Settings(_env_file=ROOT / ".env")
    report = seed(
        settings,
        sales_limit=arguments.sales_limit,
        chunk_size=arguments.chunk_size,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
