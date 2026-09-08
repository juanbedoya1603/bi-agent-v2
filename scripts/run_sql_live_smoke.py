import asyncio
import json
import os
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from bi_agent_api.agent import answer_question  # noqa: E402
from bi_agent_api.config import Settings  # noqa: E402
from bi_agent_api.database import execute_query  # noqa: E402
from bi_agent_api.sql_guard import validate_readonly_sql  # noqa: E402

OUTPUT = ROOT / "tmp" / "sql-live-smoke.json"


def live_smoke_enabled(environ: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    return values.get("RUN_SQL_LIVE_SMOKE") == "1" and "PYTEST_CURRENT_TEST" not in values


def _redact(message: str, settings: Settings) -> str:
    redacted = message
    for secret in (
        settings.openai_api_key,
        settings.analytics_db_password,
        settings.analytics_db_user,
        settings.analytics_db_host,
    ):
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted[:1000]


class TimedSqlExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls: list[dict[str, Any]] = []

    def __call__(self, sql: str) -> dict[str, Any]:
        started = perf_counter()
        try:
            result = execute_query(sql, self.settings)
        except Exception as error:
            self.calls.append(
                {
                    "sql": sql,
                    "duration_seconds": round(perf_counter() - started, 3),
                    "error": _redact(str(error), self.settings),
                }
            )
            raise
        self.calls.append(
            {
                "sql": sql,
                "duration_seconds": round(perf_counter() - started, 3),
                "error": None,
            }
        )
        return result


def _successful_result(sql_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(sql_history):
        result = entry.get("result")
        if isinstance(result, dict) and result.get("ok") is True:
            return result
    return None


def _case_report(
    case_id: str,
    kind: str,
    prompt: str,
    answer: str,
    sql_history: list[dict[str, Any]],
    timed_calls: list[dict[str, Any]],
    total_duration: float,
    outer_error: str | None = None,
) -> dict[str, Any]:
    durations = iter(timed_calls)
    attempts = []
    for entry in sql_history:
        timed = next(durations, None) if entry.get("guard_passed") else None
        result = entry.get("result") or {}
        attempts.append(
            {
                "sql": entry.get("sql", ""),
                "guard_passed": bool(entry.get("guard_passed")),
                "duration_sql_seconds": timed.get("duration_seconds") if timed else None,
                "row_count": result.get("row_count"),
                "truncated": result.get("truncated"),
                "error": result.get("error"),
            }
        )

    successful = _successful_result(sql_history)
    errors = [attempt["error"] for attempt in attempts if attempt["error"]]
    error: Any = outer_error or (errors[-1] if successful is None and errors else None)
    return {
        "id": case_id,
        "kind": kind,
        "prompt": prompt,
        "sql_generated": [attempt["sql"] for attempt in attempts],
        "guard_passed": bool(attempts) and all(
            attempt["guard_passed"] for attempt in attempts
        ),
        "duration_sql_seconds": round(
            sum(call["duration_seconds"] for call in timed_calls), 3
        ),
        "duration_total_seconds": round(total_duration, 3),
        "row_count": successful.get("row_count") if successful else None,
        "truncated": successful.get("truncated") if successful else None,
        "final_answer": answer,
        "error": error,
        "attempts": attempts,
    }


async def _run_case(
    case_id: str, kind: str, prompt: str, settings: Settings
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    executor = TimedSqlExecutor(settings)
    started = perf_counter()
    try:
        answer, context = await answer_question(prompt, settings, sql_executor=executor)
        report = _case_report(
            case_id,
            kind,
            prompt,
            answer,
            context.sql_history,
            executor.calls,
            perf_counter() - started,
        )
        successful = _successful_result(context.sql_history)
    except Exception as error:
        executed_history = [
            {
                "sql": call["sql"],
                "guard_passed": True,
                "result": {
                    "ok": False,
                    "error": {"type": "runner_error", "message": call["error"]},
                },
            }
            for call in executor.calls
        ]
        report = _case_report(
            case_id,
            kind,
            prompt,
            "",
            executed_history,
            executor.calls,
            perf_counter() - started,
            _redact(str(error), settings),
        )
        successful = None
    print(f"{case_id}: {'OK' if report['error'] is None else 'ERROR'}", flush=True)
    return report, successful


def _rows_as_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
    columns = [str(column).lower() for column in result.get("columns", [])]
    return [dict(zip(columns, row, strict=False)) for row in result.get("rows", [])]


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _availability(result: dict[str, Any]) -> tuple[date, date]:
    rows = _rows_as_dicts(result)
    if not rows:
        raise ValueError("La consulta de disponibilidad no devolvió filas.")
    row = rows[0]
    values = list(row.values())
    minimum = row.get("min_date", values[0] if values else None)
    maximum = row.get("max_date", values[1] if len(values) > 1 else None)
    return _parse_date(minimum), _parse_date(maximum)


def _brand_category(result: dict[str, Any]) -> tuple[str, str]:
    for row in _rows_as_dicts(result):
        brand = row.get("brandname") or row.get("brand_name")
        category = row.get("categoryname") or row.get("category_name")
        if brand and category:
            return str(brand), str(category)
    raise ValueError("No se encontró una pareja real de marca y categoría.")


def _city(result: dict[str, Any]) -> str:
    for row in _rows_as_dicts(result):
        value = row.get("cityname") or row.get("city_name")
        if value:
            return str(value)
    raise ValueError("No se encontró una ciudad real.")


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _previous_month(value: date) -> date:
    year = value.year - (value.month == 1)
    month = 12 if value.month == 1 else value.month - 1
    return date(year, month, 1)


def _build_analytic_cases(
    brand: str,
    category: str,
    city: str,
    previous_start: date,
    recent_start: date,
    recent_end: date,
) -> list[tuple[str, str]]:
    previous = previous_start.isoformat()
    recent = recent_start.isoformat()
    end = recent_end.isoformat()
    return [
        (
            "brand_sales_by_month",
            f"Ventas de la marca {brand} por mes entre {previous} y antes de {end}.",
        ),
        (
            "brand_units",
            f"Unidades vendidas de la marca {brand} desde {recent} y antes de {end}.",
        ),
        (
            "category_tickets",
            f"Tickets de la categoría {category} desde {recent} y antes de {end}.",
        ),
        (
            "top_products",
            f"Top 10 productos por ventas de la categoría {category} desde {recent} "
            f"y antes de {end}.",
        ),
        (
            "average_price",
            f"Precio medio de la marca {brand} desde {recent} y antes de {end}.",
        ),
        (
            "brand_share",
            f"Share de ventas de la marca {brand} dentro de la categoría {category} "
            f"desde {recent} y antes de {end}.",
        ),
        (
            "dn",
            f"DN de la marca {brand} en la categoría {category} desde {recent} "
            f"y antes de {end}.",
        ),
        (
            "penetration",
            f"Penetración de la marca {brand} en la ciudad {city} desde {recent} "
            f"y antes de {end}.",
        ),
        (
            "mom",
            f"Variación MoM de ventas de la marca {brand}: compara el período "
            f"{previous} a antes de {recent} contra {recent} a antes de {end}.",
        ),
    ]


def _write_report(report: dict[str, Any]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _guard_accepts(sql: str) -> bool:
    try:
        validate_readonly_sql(sql)
    except Exception:
        return False
    return True


async def run() -> int:
    if not live_smoke_enabled():
        print("Smoke SQL live deshabilitado: define RUN_SQL_LIVE_SMOKE=1.")
        return 2

    settings = Settings()
    started_at = datetime.now().astimezone()
    report: dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "model": settings.openai_model,
        "database_auth": settings.analytics_db_auth,
        "analytic_case_count": 10,
        "cases": [],
    }
    try:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY no está configurada.")
        settings.database_connection_string()
    except Exception as error:
        report["status"] = "configuration_error"
        report["error"] = _redact(str(error), settings)
        report["finished_at"] = datetime.now().astimezone().isoformat()
        _write_report(report)
        print(f"Configuración incompleta. Reporte: {OUTPUT}")
        return 2

    availability_prompt = (
        "Consulta la disponibilidad temporal real de ventas y devuelve MIN([date]) "
        "como min_date y MAX([date]) como max_date."
    )
    availability_report, availability_result = await _run_case(
        "availability", "analytic", availability_prompt, settings
    )
    report["cases"].append(availability_report)
    if availability_result is None:
        report["status"] = "failed"
        report["error"] = "No fue posible determinar la disponibilidad temporal."
        report["finished_at"] = datetime.now().astimezone().isoformat()
        _write_report(report)
        return 1

    try:
        minimum_date, maximum_date = _availability(availability_result)
        recent_end = _month_start(maximum_date)
        recent_start = _previous_month(recent_end)
        previous_start = _previous_month(recent_start)

        discovery_brand_prompt = (
            "Explora valores reales: devuelve TOP 5 brandName y categoryName con ventas, "
            f"usando datos desde {recent_start.isoformat()} y antes de "
            f"{recent_end.isoformat()}, ordenados por ventas descendentes."
        )
        brand_report, brand_result = await _run_case(
            "discover_brand_category", "discovery", discovery_brand_prompt, settings
        )
        report["cases"].append(brand_report)
        if brand_result is None:
            raise ValueError("Falló la exploración de marca y categoría.")
        brand, category = _brand_category(brand_result)

        discovery_city_prompt = (
            "Explora valores reales: devuelve TOP 5 cityName con ventas, "
            f"usando datos desde {recent_start.isoformat()} y antes de "
            f"{recent_end.isoformat()}, ordenados por ventas descendentes."
        )
        city_report, city_result = await _run_case(
            "discover_city", "discovery", discovery_city_prompt, settings
        )
        report["cases"].append(city_report)
        if city_result is None:
            raise ValueError("Falló la exploración de ciudad.")
        city = _city(city_result)
    except Exception as error:
        report["status"] = "failed"
        report["error"] = _redact(str(error), settings)
        report["finished_at"] = datetime.now().astimezone().isoformat()
        _write_report(report)
        return 1

    for case_id, prompt in _build_analytic_cases(
        brand, category, city, previous_start, recent_start, recent_end
    ):
        case_report, _ = await _run_case(case_id, "analytic", prompt, settings)
        report["cases"].append(case_report)

    executed_sql = [
        sql
        for case in report["cases"]
        for attempt in case["attempts"]
        if attempt["guard_passed"]
        for sql in [attempt["sql"]]
    ]
    all_readonly = all(_guard_accepts(sql) for sql in executed_sql)
    analytic_cases = [case for case in report["cases"] if case["kind"] == "analytic"]
    succeeded = sum(case["error"] is None for case in analytic_cases)
    report["summary"] = {
        "total_prompts": len(report["cases"]),
        "analytic_cases": len(analytic_cases),
        "analytic_succeeded": succeeded,
        "analytic_failed": len(analytic_cases) - succeeded,
        "sql_executions": len(executed_sql),
        "all_executed_sql_guard_validated": all_readonly,
        "duration_seconds": round(
            (datetime.now().astimezone() - started_at).total_seconds(), 3
        ),
        "available_from": minimum_date.isoformat(),
        "available_to": maximum_date.isoformat(),
    }
    report["status"] = "passed" if succeeded == len(analytic_cases) else "failed"
    report["finished_at"] = datetime.now().astimezone().isoformat()
    _write_report(report)
    print(
        f"Analíticos: {succeeded}/{len(analytic_cases)} | SQL: {len(executed_sql)} | "
        f"Reporte: {OUTPUT}",
        flush=True,
    )
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
