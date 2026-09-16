from datetime import date
from decimal import Decimal

from scripts.seed_adls_test_data import _columns_from_description, targets


def test_seed_targets_are_limited_to_the_four_test_files() -> None:
    seed_targets = targets(123)

    assert [target.adls_path for target in seed_targets] == [
        "TiendasOn/Stores/stores.parquet",
        "TiendasOn/Products/products.parquet",
        "TiendasOn/Sales/2026/8/sales.parquet",
        "TiendasOn/Sales/2026/9/sales.parquet",
    ]
    assert seed_targets[2].parameters == (123, 2026, 8)
    assert seed_targets[3].parameters == (123, 2026, 9)


def test_odbc_types_are_mapped_to_parquet_compatible_duckdb_types() -> None:
    description = [
        ("numeric_value", Decimal, None, None, 18, 4, True),
        ("business_date", date, None, None, None, None, True),
        ("description", str, None, None, None, None, True),
    ]

    columns = _columns_from_description(description)

    assert [(column.name, column.duckdb_type) for column in columns] == [
        ("numeric_value", "DECIMAL(18, 4)"),
        ("business_date", "DATE"),
        ("description", "VARCHAR"),
    ]
