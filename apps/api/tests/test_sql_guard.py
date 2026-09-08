import pytest

from bi_agent_api.sql_guard import SqlGuardError, validate_readonly_sql


def test_allows_valid_select() -> None:
    sql = "SELECT SUM(totalSaleValue) FROM dbo.VW_SalesLast13Months"
    assert validate_readonly_sql(sql) == sql


def test_allows_valid_cte() -> None:
    sql = """
    WITH sales AS (
        SELECT idProduct, SUM(totalSaleValue) AS value
        FROM dbo.VW_SalesLast13Months
        GROUP BY idProduct
    )
    SELECT p.productName, sales.value
    FROM sales
    JOIN dbo.VW_Products p ON p.productId = sales.idProduct
    """
    assert validate_readonly_sql(sql) == sql.strip()


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("UPDATE dbo.VW_Products SET productName = 'x'", "not_select"),
        ("DROP VIEW dbo.VW_Products", "not_select"),
        ("SELECT * INTO #copy FROM dbo.VW_Products", "select_into"),
        ("SELECT * FROM dbo.Users", "table_not_allowed"),
        (
            "SELECT * FROM dbo.VW_Products; SELECT * FROM dbo.VW_Stores",
            "multiple_statements",
        ),
    ],
)
def test_rejects_unsafe_sql(sql: str, code: str) -> None:
    with pytest.raises(SqlGuardError) as caught:
        validate_readonly_sql(sql)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM analytics.dbo.VW_Products",
        "SELECT * FROM remote.analytics.dbo.VW_Products",
        "SELECT * FROM other.VW_Products",
        "SELECT * FROM VW_Products",
    ],
)
def test_rejects_cross_database_linked_server_or_missing_schema(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_readonly_sql(sql)
