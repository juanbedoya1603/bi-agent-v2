from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

ALLOWED_VIEWS = frozenset(
    {
        ("dbo", "vw_saleslast13months"),
        ("dbo", "vw_stores"),
        ("dbo", "vw_products"),
    }
)


@dataclass(frozen=True)
class SqlGuardError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def validate_readonly_sql(sql: str) -> str:
    """Valida una única consulta SELECT T-SQL contra la whitelist."""
    if not sql.strip():
        raise SqlGuardError("empty_sql", "La consulta SQL está vacía.")

    try:
        statements = parse(sql, read="tsql")
    except ParseError as exc:
        raise SqlGuardError("parse_error", "La consulta no es T-SQL válido.") from exc

    if len(statements) != 1:
        raise SqlGuardError("multiple_statements", "Solo se permite una sentencia SQL.")

    statement = statements[0]
    if not isinstance(statement, exp.Select):
        raise SqlGuardError("not_select", "Solo se permiten consultas SELECT.")

    if statement.find(exp.Into):
        raise SqlGuardError("select_into", "SELECT INTO no está permitido.")

    cte_names = {
        cte.alias_or_name.casefold() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
    }

    tables = list(statement.find_all(exp.Table))
    if not tables:
        raise SqlGuardError("missing_table", "La consulta debe leer una view permitida.")

    for table in tables:
        name = table.name.casefold()
        schema = table.db.casefold() if table.db else ""
        catalog = table.catalog.casefold() if table.catalog else ""

        if not schema and not catalog and name in cte_names:
            continue
        if catalog:
            raise SqlGuardError(
                "cross_database",
                "No se permiten otras bases de datos ni linked servers.",
            )
        if (schema, name) not in ALLOWED_VIEWS:
            raise SqlGuardError(
                "table_not_allowed",
                f"La tabla o view {table.sql(dialect='tsql')} no está permitida.",
            )

    return sql.strip()
