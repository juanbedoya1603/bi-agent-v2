import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlglot import expressions as exp
from sqlglot import parse_one


@dataclass
class SyntheticSqlExecutor:
    """Returns configured rows in order and records only guard-approved SQL."""

    fake_results: list[dict[str, Any]]
    executed_sql: list[str] = field(default_factory=list)
    delivered_results: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, sql: str) -> dict[str, Any]:
        index = len(self.executed_sql)
        self.executed_sql.append(sql)
        if index >= len(self.fake_results):
            raise RuntimeError("No hay otro resultado sintético configurado para este caso.")
        configured = self.fake_results[index]
        result = {
            "ok": True,
            "columns": configured.get("columns", []),
            "rows": configured.get("rows", []),
            "row_count": configured.get("row_count", len(configured.get("rows", []))),
            "truncated": configured.get("truncated", False),
        }
        self.delivered_results.append(result)
        return result


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not 12 <= len(cases) <= 35:
        raise ValueError("El dataset debe contener entre 12 y 35 casos.")
    ids = [case.get("id") for case in cases]
    if any(not case_id for case_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("Cada caso debe tener un id único y no vacío.")
    return cases


def _normalize_sql(sql: str) -> str:
    try:
        return parse_one(sql, read="tsql").sql(dialect="tsql", pretty=False).upper()
    except Exception:
        return " ".join(sql.upper().split())


def _views(sql_calls: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for call in sql_calls:
        try:
            statement = parse_one(call["sql"], read="tsql")
        except Exception:
            continue
        for table in statement.find_all(exp.Table):
            if table.db.casefold() == "dbo":
                found.add(table.name.casefold())
    return found


def _compact(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.upper())
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.sub(r"[^A-Z0-9]+", "", without_marks)


def _has(compact_sql: str, expected: str) -> bool:
    canonical_expected = _canonical_sql(expected)
    return _compact(canonical_expected) in compact_sql


def _canonical_sql(value: str) -> str:
    value = value.upper().replace("[", "").replace("]", "")
    value = re.sub(r"\b(?:UPPER|LOWER)\((?:[A-Z_][A-Z0-9_]*\.)?([A-Z_][A-Z0-9_]*)\)", r"\1", value)
    return re.sub(r"\b(?!DBO\b)[A-Z_][A-Z0-9_]*\.", "", value)


def _parsed_statements(sql_history: list[dict[str, Any]]) -> list[exp.Expression]:
    statements = []
    for call in sql_history:
        try:
            statements.append(parse_one(call["sql"], read="tsql"))
        except Exception:
            continue
    return statements


def _division_parts(
    statements: list[exp.Expression],
) -> list[tuple[exp.Div, str, str]]:
    divisions = []
    for statement in statements:
        for division in statement.find_all(exp.Div):
            numerator = _compact(_canonical_sql(division.this.sql(dialect="tsql")))
            denominator = _compact(_canonical_sql(division.expression.sql(dialect="tsql")))
            divisions.append((division, numerator, denominator))
    return divisions


def _division_with_target(
    statements: list[exp.Expression], target: str
) -> tuple[exp.Div, str, str] | None:
    target_compact = _compact(target)
    for division, numerator, denominator in _division_parts(statements):
        if target_compact in numerator and "BRANDNAME" in numerator:
            return division, numerator, denominator
    return None


def _select_where(division: exp.Div) -> str:
    select = division.find_ancestor(exp.Select)
    where = select.args.get("where") if select else None
    return _compact(_canonical_sql(where.sql(dialect="tsql"))) if where else ""


def _semantic_check(
    specification: dict[str, Any], statements: list[exp.Expression], answer: str
) -> tuple[bool, str]:
    check_type = specification["type"]
    target = specification.get("target", "")
    division = _division_with_target(statements, target) if target else None

    if check_type in {"category_share", "dn", "penetration"}:
        if division is None:
            return False, "no se encontró una división cuyo numerador identifique la marca objetivo"
        expression, _, denominator = division
        if _compact(target) in denominator or "BRANDNAME" in denominator:
            return False, "el denominador de la división está restringido por marca"

        if check_type == "category_share":
            all_sql = _compact(_canonical_sql(" ".join(item.sql() for item in statements)))
            if "CATEGORYNAME" not in all_sql:
                return False, "el universo no identifica la categoría"
            return True, "marca solo en numerador y categoría presente en el universo"

        if "COUNTDISTINCTIDSTORE" not in denominator:
            return False, "el denominador no cuenta tiendas distintas"

        if check_type == "dn":
            all_sql = _compact(_canonical_sql(" ".join(item.sql() for item in statements)))
            if "CATEGORYNAME" not in all_sql:
                return False, "el denominador no deriva tiendas de categoría"
            return True, "denominador de tiendas distintas basado en categoría, sin marca"

        where = _select_where(expression)
        forbidden = ("BRANDNAME", "PRODUCTID", "CATEGORYNAME")
        if any(item in where for item in forbidden):
            return False, "el WHERE común restringe marca, producto o categoría"
        return True, "denominador de tiendas activas sin filtro de entidad"

    if check_type == "competitive_share":
        if division is None:
            return False, "no se encontró el cociente de share para la marca objetivo"
        brands = {_compact(brand) for brand in specification["brands"]}
        matching_universe = False
        for statement in statements:
            for in_expression in statement.find_all(exp.In):
                field = _compact(_canonical_sql(in_expression.this.sql()))
                values = {
                    _compact(str(item.this))
                    for item in in_expression.expressions
                    if isinstance(item, exp.Literal)
                }
                if "BRANDNAME" in field and brands <= values:
                    matching_universe = True
        if not matching_universe:
            return False, "no existe un IN común con todas las marcas del universo"
        presentation = specification.get("presentation")
        if presentation:
            found_global_filter = False
            for statement in statements:
                for where in statement.find_all(exp.Where):
                    text = _compact(_canonical_sql(where.sql()))
                    if "NETQUANTITYVALUE" in text and _compact(str(presentation)) in text:
                        found_global_filter = True
            if not found_global_filter:
                return False, "la presentación no está en un WHERE común al universo"
        return True, "universo competitivo y presentación aplicados globalmente"

    if check_type == "mom":
        previous_start = _compact(specification["previous_start"])
        current_start = _compact(specification["current_start"])
        current_end = _compact(specification["current_end"])
        for statement in statements:
            for subtraction in statement.find_all(exp.Sub):
                if not isinstance(subtraction.expression, exp.Literal):
                    continue
                if str(subtraction.expression.this) != "1" or not isinstance(
                    subtraction.this, exp.Div
                ):
                    continue
                numerator = _compact(subtraction.this.this.sql())
                denominator = _compact(subtraction.this.expression.sql())
                current_ok = current_start in numerator and current_end in numerator
                previous_ok = previous_start in denominator and current_start in denominator
                if current_ok and previous_ok:
                    return True, "fórmula current / previous - 1 con límites mensuales correctos"
        return False, "no se encontró current / previous - 1 con los períodos esperados"

    if check_type == "observable_causality":
        external = r"(?:promoci|campa(?:ñ|n)|clima|econom|competencia externa|precio de mercado)"
        causal = r"(?:se debi[oó]|debido a|causad[ao] por|por efecto de)"
        pattern = rf"{causal}.{{0,60}}{external}|{external}.{{0,60}}{causal}"
        invented = re.search(pattern, answer.casefold())
        return not invented, "no debe atribuir causalidad a factores externos no observables"

    if check_type == "geographic_context":
        required = [
            _compact(_canonical_sql(item)) for item in specification["filters"]
        ]
        for statement in statements:
            for where in statement.find_all(exp.Where):
                where_sql = _compact(_canonical_sql(where.sql(dialect="tsql")))
                if all(item in where_sql for item in required):
                    return True, "contexto geográfico completo aplicado en un WHERE común"
        return False, "stateName, cityName y macrozone no aparecen juntos en un WHERE común"

    return False, f"check semántico desconocido: {check_type}"


def score_case(
    case: dict[str, Any],
    answer: str,
    sql_history: list[dict[str, Any]],
    delivered_results: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = case["expected"]
    checks: list[dict[str, Any]] = []
    normalized = [_normalize_sql(call["sql"]) for call in sql_history]
    combined = " ".join(normalized)
    compact_sql = _compact(_canonical_sql(combined))
    answer_folded = answer.casefold()
    statements = _parsed_statements(sql_history)

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    calls = len(sql_history)
    minimum = expected.get("sql_calls_min", 0)
    maximum = expected.get("sql_calls_max", 3)
    check(
        "sql_calls",
        minimum <= calls <= maximum,
        f"esperado {minimum}..{maximum}; obtenido {calls}",
    )
    check(
        "guard",
        all(call.get("guard_passed") for call in sql_history),
        "todas las llamadas deben pasar el guard",
    )

    actual_views = _views(sql_history)
    for view in expected.get("views", []):
        check(f"view:{view}", view.casefold() in actual_views, f"views: {sorted(actual_views)}")
    for fragment in expected.get("contains", []):
        check(f"sql_contains:{fragment}", _has(compact_sql, fragment), fragment)
    for alternatives in expected.get("contains_any", []):
        passed = any(_has(compact_sql, item) for item in alternatives)
        check("sql_contains_any", passed, " | ".join(alternatives))
    for fragment in expected.get("not_contains", []):
        check(f"sql_not_contains:{fragment}", not _has(compact_sql, fragment), fragment)
    for fragment in expected.get("answer_contains", []):
        check(
            f"answer_contains:{fragment}",
            fragment.casefold() in answer_folded,
            fragment,
        )
    for alternatives in expected.get("answer_contains_any", []):
        passed = any(item.casefold() in answer_folded for item in alternatives)
        check("answer_contains_any", passed, " | ".join(alternatives))
    for fragment in expected.get("answer_not_contains", []):
        check(
            f"answer_not_contains:{fragment}",
            fragment.casefold() not in answer_folded,
            fragment,
        )
    for specification in expected.get("semantic_checks", []):
        passed, detail = _semantic_check(specification, statements, answer)
        check(f"semantic:{specification['type']}", passed, detail)
    if calls:
        check(
            "no_sql_in_answer",
            "select " not in answer_folded,
            "la respuesta no debe mostrar SQL",
        )

    return {
        "id": case["id"],
        "prompt": case["prompt"],
        "critical": case.get("critical", False),
        "manual_review_required": case.get("manual_review_required", False),
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "answer": answer,
        "sql_calls": sql_history,
        "fake_results": delivered_results,
    }


def build_report(results: list[dict[str, Any]], model: str) -> dict[str, Any]:
    passed = sum(result["passed"] for result in results)
    total = len(results)
    return {
        "model": model,
        "summary": {
            "cases": total,
            "passed": passed,
            "failed": total - passed,
            "accuracy": round(100 * passed / total, 1) if total else 0.0,
        },
        "manual_sql_review": [
            {
                "id": result["id"],
                "prompt": result["prompt"],
                "passed": result["passed"],
                "sql": [call["sql"] for call in result["sql_calls"]],
            }
            for result in results
            if result.get("manual_review_required")
        ],
        "results": results,
    }
