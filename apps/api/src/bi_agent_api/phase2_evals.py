import json
import re
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
    if not isinstance(cases, list) or not 20 <= len(cases) <= 25:
        raise ValueError("El dataset de Fase 2 debe contener entre 20 y 25 casos.")
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
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def _has(compact_sql: str, expected: str) -> bool:
    canonical_expected = _canonical_sql(expected)
    return _compact(canonical_expected) in compact_sql


def _canonical_sql(value: str) -> str:
    value = value.upper().replace("[", "").replace("]", "")
    value = re.sub(r"\b(?:UPPER|LOWER)\((?:[A-Z_][A-Z0-9_]*\.)?([A-Z_][A-Z0-9_]*)\)", r"\1", value)
    return re.sub(r"\b(?!DBO\b)[A-Z_][A-Z0-9_]*\.", "", value)


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
        "results": results,
    }
