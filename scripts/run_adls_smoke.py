"""Run a read-only connectivity and Parquet smoke test against ADLS Gen2.

The script deliberately keeps the current SQL Server/Fabric analytical path
untouched. Azure SDK calls are used for discovery, while DuckDB reads Parquet
remotely through its Azure extension using ``abfss://`` URLs.
"""

from __future__ import annotations

import gzip
import json
import platform
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import duckdb
import pyodbc
from azure.storage.filedatalake import DataLakeServiceClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from scripts.seed_adls_test_data import _columns_from_description  # noqa: E402

from bi_agent_api.config import Settings  # noqa: E402

CURRENT_CONTRACTS: dict[str, tuple[str, ...]] = {
    "Stores": (
        "idPartner",
        "economicActivity_fix",
        "coordenadas",
        "stateName",
        "cityName",
        "ZipCode",
        "businessName",
        "stratum",
        "countryName",
        "ImplementationDate",
        "idDeal",
        "macrozone",
    ),
    "Products": (
        "productId",
        "productName",
        "barCode",
        "manufacturerName",
        "brandName",
        "categoryName",
        "subCategoryName",
        "lineName",
        "flavor",
        "unitMeasure",
        "netQuantityValue",
    ),
    "Sales": (
        "idStore",
        "idTicket",
        "idProduct",
        "year",
        "month",
        "day",
        "tramo_horario",
        "totalSaleValue",
        "productQuantity",
        "UnitValue",
        "date",
        "uniqueTicketPerStore",
        "uniqueProductPerTicket",
    ),
}

VIEW_BY_DATASET = {
    "Stores": "dbo.VW_Stores",
    "Products": "dbo.VW_Products",
    "Sales": "dbo.VW_SalesLast13Months",
}


@dataclass(frozen=True)
class RemoteFile:
    path: str
    size_bytes: int | None


@dataclass(frozen=True)
class KnownRoute:
    name: str
    path: str
    dataset: str


def known_routes(base_path: str) -> tuple[KnownRoute, ...]:
    base = base_path.strip("/")
    return (
        KnownRoute("Stores", f"{base}/Stores", "Stores"),
        KnownRoute("Products", f"{base}/Products", "Products"),
        KnownRoute("Sales 2026/8", f"{base}/Sales/2026/8", "Sales"),
        KnownRoute("Sales 2026/9", f"{base}/Sales/2026/9", "Sales"),
    )


def _property_value(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def list_remote_files(filesystem: Any, path: str) -> list[RemoteFile]:
    """List files below a path without opening or downloading their contents."""

    files: list[RemoteFile] = []
    for item in filesystem.get_paths(path=path, recursive=True):
        item_name = _property_value(item, "name")
        if not item_name or _property_value(item, "is_directory"):
            continue
        content_length = _property_value(item, "content_length")
        files.append(
            RemoteFile(
                path=str(item_name),
                size_bytes=int(content_length) if content_length is not None else None,
            )
        )
    return sorted(files, key=lambda item: item.path.casefold())


def parquet_files(files: Sequence[RemoteFile]) -> list[RemoteFile]:
    return [item for item in files if item.path.casefold().endswith(".parquet")]


def parquet_uri(filesystem: str, path: str) -> str:
    return f"abfss://{filesystem.strip('/')}/{path.lstrip('/')}"


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parquet_source(filesystem: str, files: Sequence[RemoteFile]) -> str:
    """Build a DuckDB read-only table function over discovered files."""

    paths = parquet_files(files)
    if not paths:
        raise ValueError("No se encontraron archivos Parquet para consultar.")
    quoted_paths = ", ".join(
        _sql_string(parquet_uri(filesystem, item.path)) for item in paths
    )
    return f"read_parquet([{quoted_paths}], union_by_name=true)"


def compare_columns(found: Sequence[str], expected: Sequence[str]) -> dict[str, Any]:
    """Compare names while reporting missing, extra, and casing differences."""

    found_by_key = {name.casefold(): name for name in found}
    expected_by_key = {name.casefold(): name for name in expected}
    missing = [name for name in expected if name.casefold() not in found_by_key]
    extra = [name for name in found if name.casefold() not in expected_by_key]
    case_mismatches = [
        {"contract": name, "found": found_by_key[name.casefold()]}
        for name in expected
        if name.casefold() in found_by_key and found_by_key[name.casefold()] != name
    ]
    return {
        "matches": not missing and not extra and not case_mismatches,
        "missing": missing,
        "extra": extra,
        "case_mismatches": case_mismatches,
    }


def _schema(connection: Any, source: str) -> list[dict[str, str]]:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
    return [{"name": str(row[0]), "type": str(row[1])} for row in rows]


def _query_dataset(connection: Any, source: str) -> dict[str, Any]:
    count = connection.execute(f"SELECT COUNT(*) AS row_count FROM {source}").fetchone()[0]
    limited = connection.execute(f"SELECT * FROM {source} LIMIT 5")
    limit_rows = limited.fetchmany(5)
    return {
        "count": int(count),
        "limit": 5,
        "limit_rows_returned": len(limit_rows),
    }


def _safe_error(error: Exception, *secrets: str) -> str:
    message = str(error)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:1000]


def source_view_schema(settings: Settings, view: str) -> list[dict[str, str]]:
    """Read source metadata only; no business rows are fetched."""

    connection = pyodbc.connect(settings.database_connection_string())
    cursor = connection.cursor()
    try:
        connection.timeout = settings.query_timeout_seconds
        cursor.execute(f"SELECT TOP (0) * FROM {view}")
        if cursor.description is None:
            raise RuntimeError(f"La view {view} no devolvió metadatos.")
        return [
            {"name": column.name, "type": column.duckdb_type}
            for column in _columns_from_description(cursor.description)
        ]
    finally:
        cursor.close()
        connection.close()


def compare_schema(
    found: Sequence[dict[str, str]], expected: Sequence[dict[str, str]]
) -> dict[str, Any]:
    column_comparison = compare_columns(
        [column["name"] for column in found], [column["name"] for column in expected]
    )
    found_by_name = {column["name"].casefold(): column for column in found}
    type_mismatches = [
        {
            "column": column["name"],
            "source_type": column["type"],
            "parquet_type": found_by_name[column["name"].casefold()]["type"],
        }
        for column in expected
        if column["name"].casefold() in found_by_name
        and column["type"].casefold()
        != found_by_name[column["name"].casefold()]["type"].casefold()
    ]
    return {
        **column_comparison,
        "type_matches": not type_mismatches,
        "type_mismatches": type_mismatches,
        "matches": column_comparison["matches"] and not type_mismatches,
    }


def _load_azure_extension(connection: Any) -> None:
    try:
        connection.execute("LOAD azure")
    except duckdb.Error:
        try:
            connection.execute("INSTALL azure")
            connection.execute("LOAD azure")
        except duckdb.Error:
            _load_azure_extension_from_https(connection)


def _duckdb_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows" and machine in {"amd64", "x86_64"}:
        return "windows_amd64"
    if system == "linux" and machine in {"amd64", "x86_64"}:
        return "linux_amd64"
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "osx_arm64"
    if system == "darwin" and machine in {"amd64", "x86_64"}:
        return "osx_amd64"
    raise RuntimeError(f"Plataforma no soportada para extensión DuckDB: {system}/{machine}")


def _load_azure_extension_from_https(connection: Any) -> None:
    """Fallback for environments where DuckDB's default HTTP fetch is blocked."""

    url = (
        f"https://extensions.duckdb.org/v{duckdb.__version__}/"
        f"{_duckdb_platform()}/azure.duckdb_extension.gz"
    )
    request = Request(url, headers={"User-Agent": "bi-agent-adls-smoke/1.0"})
    with tempfile.TemporaryDirectory(prefix="duckdb-adls-smoke-") as directory:
        extension_path = Path(directory) / "azure.duckdb_extension"
        with (
            urlopen(request, timeout=60) as response,
            gzip.GzipFile(fileobj=response) as compressed,
            extension_path.open("wb") as extension_file,
        ):
            shutil.copyfileobj(compressed, extension_file)
        connection.execute(f"INSTALL {_sql_string(str(extension_path))}")
        connection.execute("LOAD azure")


def _register_azure_secret(connection: Any, connection_string: str) -> None:
    connection.execute(
        """
        CREATE OR REPLACE SECRET adls_smoke_secret (
            TYPE azure,
            PROVIDER config,
            CONNECTION_STRING ?
        )
        """,
        [connection_string],
    )


def _empty_report(settings: Settings) -> dict[str, Any]:
    routes = {
        route.name: {"path": route.path, "files": [], "parquet_files": 0}
        for route in known_routes(settings.adls_base_path)
    }
    return {
        "status": "failed",
        "connection": {
            "status": "not_attempted",
            "filesystem": settings.adls_filesystem,
            "base_path": settings.adls_base_path,
        },
        "routes": routes,
        "schemas": {},
        "source_schemas": {},
        "queries": {},
        "differences": {},
        "blockers": [],
    }


def run_smoke(settings: Settings) -> dict[str, Any]:
    report = _empty_report(settings)
    connection_string = settings.azure_storage_connection_string.get_secret_value()
    if not connection_string:
        report["status"] = "configuration_error"
        report["blockers"].append(
            "Falta AZURE_STORAGE_CONNECTION_STRING en la configuración local."
        )
        return report

    try:
        service = DataLakeServiceClient.from_connection_string(connection_string)
        filesystem = service.get_file_system_client(settings.adls_filesystem)
        filesystem.get_file_system_properties()
        report["connection"]["status"] = "ok"
    except Exception as error:
        report["connection"]["status"] = "fail"
        report["blockers"].append(
            f"No fue posible conectar con ADLS Gen2: {_safe_error(error, connection_string)}"
        )
        return report

    source_schemas: dict[str, list[dict[str, str]]] = {}
    for dataset, view in VIEW_BY_DATASET.items():
        try:
            source_schemas[dataset] = source_view_schema(settings, view)
            report["source_schemas"][dataset] = {
                "view": view,
                "columns": source_schemas[dataset],
            }
        except Exception as error:
            report["blockers"].append(
                f"No fue posible obtener el schema de {view}: "
                f"{_safe_error(error, connection_string, settings.analytics_db_password)}"
            )

    route_files: dict[str, list[RemoteFile]] = {}
    for route in known_routes(settings.adls_base_path):
        route_report = report["routes"][route.name]
        try:
            files = list_remote_files(filesystem, route.path)
        except Exception as error:
            route_files[route.name] = []
            route_report["error"] = _safe_error(error, connection_string)
            report["blockers"].append(
                f"No fue posible listar {route.path}: {route_report['error']}"
            )
            continue
        route_files[route.name] = files
        route_report["files"] = [
            {
                "path": item.path,
                "size_bytes": item.size_bytes,
                "parquet": item.path.casefold().endswith(".parquet"),
            }
            for item in files
        ]
        route_report["parquet_files"] = len(parquet_files(files))

    dataset_files: dict[str, list[RemoteFile]] = {
        "Stores": route_files.get("Stores", []),
        "Products": route_files.get("Products", []),
        "Sales": route_files.get("Sales 2026/8", []) + route_files.get("Sales 2026/9", []),
    }

    try:
        with duckdb.connect(database=":memory:") as connection:
            _load_azure_extension(connection)
            _register_azure_secret(connection, connection_string)
            for dataset, files in dataset_files.items():
                selected = parquet_files(files)
                if not selected:
                    report["blockers"].append(
                        f"No se encontró ningún Parquet para el dataset {dataset}."
                    )
                    continue

                sample = selected[0]
                sample_source = parquet_source(settings.adls_filesystem, [sample])
                all_source = parquet_source(settings.adls_filesystem, files)
                schema = _schema(connection, sample_source)
                report["schemas"][dataset] = {
                    "sample_file": sample.path,
                    "columns": schema,
                }
                report["queries"][dataset] = _query_dataset(connection, all_source)
                found_names = [column["name"] for column in schema]
                report["differences"][dataset] = {
                    "contract_view": VIEW_BY_DATASET[dataset],
                    "current_contract": compare_columns(
                        found_names, CURRENT_CONTRACTS[dataset]
                    ),
                    "source_view": (
                        compare_schema(schema, source_schemas[dataset])
                        if dataset in source_schemas
                        else {"matches": False, "error": "Schema de origen no disponible."}
                    ),
                }
                if not report["differences"][dataset]["source_view"]["matches"]:
                    report["blockers"].append(
                        f"El schema Parquet de {dataset} no coincide con "
                        f"{VIEW_BY_DATASET[dataset]}."
                    )

            if all(parquet_files(files) for files in dataset_files.values()):
                stores_source = parquet_source(
                    settings.adls_filesystem, dataset_files["Stores"]
                )
                products_source = parquet_source(
                    settings.adls_filesystem, dataset_files["Products"]
                )
                sales_source = parquet_source(settings.adls_filesystem, dataset_files["Sales"])
                join_row = connection.execute(
                    f"""
                    WITH
                    stores AS (
                        SELECT DISTINCT "idPartner" FROM {stores_source}
                    ),
                    products AS (
                        SELECT DISTINCT "productId" FROM {products_source}
                    )
                    SELECT
                        COUNT(*) AS sales_rows,
                        COUNT(*) FILTER (WHERE st."idPartner" IS NULL) AS sales_without_store,
                        COUNT(*) FILTER (WHERE p."productId" IS NULL) AS sales_without_product
                    FROM {sales_source} AS s
                    LEFT JOIN stores AS st ON s."idStore" = st."idPartner"
                    LEFT JOIN products AS p ON s."idProduct" = p."productId"
                    """
                ).fetchone()
                report["queries"]["joins"] = {
                    "sales_rows": int(join_row[0]),
                    "sales_without_store": int(join_row[1]),
                    "sales_without_product": int(join_row[2]),
                }
    except Exception as error:
        report["blockers"].append(
            f"Falló la lectura remota con DuckDB: {_safe_error(error, connection_string)}"
        )

    report["status"] = "passed" if not report["blockers"] else "failed"
    return report


def main() -> int:
    settings = Settings(_env_file=ROOT / ".env")
    report = run_smoke(settings)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
