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
    "sql",
    [
        "INSERT INTO dbo.VW_Products (productId) VALUES (1)",
        "UPDATE dbo.VW_Products SET productName = 'x'",
        "DELETE FROM dbo.VW_Products WHERE productId = 1",
        """MERGE dbo.VW_Products AS target
        USING dbo.VW_Products AS source ON target.productId = source.productId
        WHEN MATCHED THEN UPDATE SET target.productName = source.productName""",
        "DROP VIEW dbo.VW_Products",
        "ALTER VIEW dbo.VW_Products AS SELECT 1 AS productId",
        "CREATE VIEW dbo.unsafe AS SELECT * FROM dbo.VW_Products",
        "TRUNCATE TABLE dbo.VW_Products",
        "EXEC sys.sp_who",
        "EXECUTE sys.sp_who",
        "USE analytics",
        "BEGIN TRANSACTION",
        "COMMIT TRANSACTION",
        "ROLLBACK TRANSACTION",
        "SELECT * INTO #copy FROM dbo.VW_Products",
    ],
)
def test_rejects_write_ddl_exec_use_and_transactions(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_readonly_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        """SELECT * FROM OPENROWSET(
            'MSOLEDBSQL', 'Server=external;Trusted_Connection=yes;', 'SELECT 1'
        ) AS external_rows""",
        "SELECT * FROM OPENQUERY(remote_server, 'SELECT 1')",
        """SELECT * FROM OPENDATASOURCE(
            'MSOLEDBSQL', 'Data Source=external;Integrated Security=SSPI'
        ).analytics.dbo.VW_Products""",
    ],
)
def test_rejects_openrowset_openquery_and_opendatasource(sql: str) -> None:
    with pytest.raises(SqlGuardError) as caught:
        validate_readonly_sql(sql)
    assert caught.value.code in {"table_not_allowed", "cross_database"}


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
