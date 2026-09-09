import json
from pathlib import Path

import pytest

from bi_agent_api.phase2_evals import (
    SyntheticSqlExecutor,
    build_report,
    load_cases,
    score_case,
)

ROOT = Path(__file__).resolve().parents[3]


def test_loads_phase2_dataset() -> None:
    cases = load_cases(ROOT / "evals" / "cases.json")

    assert len(cases) == 30
    assert len({case["id"] for case in cases}) == 30


def test_loads_holdout_dataset() -> None:
    cases = load_cases(ROOT / "evals" / "holdout_cases.json")

    assert len(cases) == 14
    assert len({case["id"] for case in cases}) == 14
    assert all(case["prompt"] for case in cases)


def test_case_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"id": "same"}] * 20), encoding="utf-8")

    with pytest.raises(ValueError, match="id único"):
        load_cases(path)


def test_synthetic_executor_captures_sql_and_returns_sequence() -> None:
    executor = SyntheticSqlExecutor(
        [
            {"columns": ["sales"], "rows": [[1250000]]},
            {"columns": ["units"], "rows": [[25000]], "truncated": True},
        ]
    )

    first = executor("SELECT SUM(totalSaleValue) FROM dbo.VW_SalesLast13Months")
    second = executor("SELECT SUM(productQuantity) FROM dbo.VW_SalesLast13Months")

    assert executor.executed_sql == [
        "SELECT SUM(totalSaleValue) FROM dbo.VW_SalesLast13Months",
        "SELECT SUM(productQuantity) FROM dbo.VW_SalesLast13Months",
    ]
    assert first["row_count"] == 1
    assert second["truncated"] is True
    assert executor.delivered_results == [first, second]


def test_synthetic_executor_rejects_unconfigured_call() -> None:
    executor = SyntheticSqlExecutor([])

    with pytest.raises(RuntimeError, match="resultado sintético"):
        executor("SELECT productName FROM dbo.VW_Products")


def test_basic_scoring_and_report() -> None:
    case = {
        "id": "sales",
        "prompt": "Ventas",
        "expected": {
            "sql_calls_min": 1,
            "sql_calls_max": 1,
            "views": ["VW_SalesLast13Months"],
            "contains": ["SUM(totalSaleValue)"],
            "answer_contains": ["1.250.000"],
        },
    }
    history = [
        {
            "sql": "SELECT SUM(totalSaleValue) FROM dbo.VW_SalesLast13Months",
            "guard_passed": True,
            "result": {"ok": True},
        }
    ]

    result = score_case(case, "Ventas: 1.250.000", history, [{"rows": [[1250000]]}])
    report = build_report([result], "test-model")

    assert result["passed"] is True
    assert report["summary"] == {"cases": 1, "passed": 1, "failed": 0, "accuracy": 100.0}
    assert report["model"] == "test-model"


def _history(sql: str) -> list[dict[str, object]]:
    return [{"sql": sql, "guard_passed": True, "result": {"ok": True}}]


def test_category_share_rejects_brand_in_denominator() -> None:
    case = {
        "id": "share",
        "prompt": "share",
        "manual_review_required": True,
        "expected": {
            "sql_calls_min": 1,
            "semantic_checks": [{"type": "category_share", "target": "REXONA"}],
        },
    }
    sql = """SELECT SUM(CASE WHEN p.brandName='REXONA' THEN s.totalSaleValue END)
    / NULLIF(SUM(CASE WHEN p.brandName='REXONA' THEN s.totalSaleValue END),0)
    FROM dbo.VW_SalesLast13Months s JOIN dbo.VW_Products p ON p.productId=s.idProduct
    WHERE p.categoryName='CUIDADO PERSONAL'"""

    result = score_case(case, "37%", _history(sql), [])

    assert result["passed"] is False
    assert "restringido por marca" in result["checks"][-2]["detail"]


def test_penetration_rejects_brand_in_common_where() -> None:
    case = {
        "id": "penetration",
        "prompt": "penetration",
        "expected": {
            "sql_calls_min": 1,
            "semantic_checks": [{"type": "penetration", "target": "DOVE"}],
        },
    }
    sql = """SELECT COUNT(DISTINCT CASE WHEN p.brandName='DOVE' THEN s.idStore END)*1.0
    / NULLIF(COUNT(DISTINCT s.idStore),0)
    FROM dbo.VW_SalesLast13Months s JOIN dbo.VW_Products p ON p.productId=s.idProduct
    WHERE p.brandName='DOVE'"""

    result = score_case(case, "30%", _history(sql), [])

    assert result["passed"] is False
    assert "WHERE común" in result["checks"][-2]["detail"]


def test_cross_year_mom_requires_december_as_previous_month() -> None:
    case = {
        "id": "mom",
        "prompt": "mom",
        "expected": {
            "sql_calls_min": 1,
            "semantic_checks": [
                {
                    "type": "mom",
                    "previous_start": "2025-12-01",
                    "current_start": "2026-01-01",
                    "current_end": "2026-02-01",
                }
            ],
        },
    }
    sql = """SELECT SUM(CASE WHEN s.date>='2026-01-01' AND s.date<'2026-02-01'
    THEN s.totalSaleValue END) / NULLIF(SUM(CASE WHEN s.date>='2025-12-01'
    AND s.date<'2026-01-01' THEN s.totalSaleValue END),0) - 1 AS growth
    FROM dbo.VW_SalesLast13Months s"""

    result = score_case(case, "20%", _history(sql), [])
    report = build_report([result], "test-model")

    assert result["passed"] is True
    assert report["manual_sql_review"] == []


def test_competitive_share_requires_presentation_in_common_where() -> None:
    case = {
        "id": "competitive",
        "prompt": "competitive",
        "expected": {
            "sql_calls_min": 1,
            "semantic_checks": [
                {
                    "type": "competitive_share",
                    "target": "DORIA",
                    "brands": ["DORIA", "LA MUÑECA", "MONTICELLO"],
                    "presentation": 1000,
                }
            ],
        },
    }
    sql = """SELECT SUM(CASE WHEN p.brandName='DORIA' AND p.netQuantityValue=1000
    THEN s.totalSaleValue ELSE 0 END)*1.0 / NULLIF(SUM(s.totalSaleValue),0)
    FROM dbo.VW_SalesLast13Months s JOIN dbo.VW_Products p ON p.productId=s.idProduct
    WHERE p.brandName IN ('DORIA','LA MUÑECA','MONTICELLO')"""

    result = score_case(case, "45%", _history(sql), [])

    assert result["passed"] is False
    assert "WHERE común" in result["checks"][-2]["detail"]


def test_dn_rejects_denominator_restricted_to_brand() -> None:
    case = {
        "id": "dn",
        "prompt": "dn",
        "expected": {
            "sql_calls_min": 1,
            "semantic_checks": [{"type": "dn", "target": "ALPINA"}],
        },
    }
    sql = """SELECT COUNT(DISTINCT CASE WHEN p.brandName='ALPINA' THEN s.idStore END)*1.0
    / NULLIF(COUNT(DISTINCT CASE WHEN p.brandName='ALPINA' THEN s.idStore END),0)
    FROM dbo.VW_SalesLast13Months s JOIN dbo.VW_Products p ON p.productId=s.idProduct
    WHERE p.categoryName='LECHES'"""

    result = score_case(case, "60%", _history(sql), [])

    assert result["passed"] is False
    assert "restringido por marca" in result["checks"][-2]["detail"]


def test_why_check_rejects_invented_external_causality() -> None:
    case = {
        "id": "why",
        "prompt": "why",
        "expected": {
            "sql_calls_min": 0,
            "semantic_checks": [{"type": "observable_causality"}],
        },
    }

    result = score_case(case, "La caída se debió a promociones de la competencia.", [], [])

    assert result["passed"] is False
    assert "factores externos" in result["checks"][-1]["detail"]


def test_regression_no_data_uses_null_aggregate() -> None:
    cases = load_cases(ROOT / "evals" / "cases.json")
    case = next(item for item in cases if item["id"] == "no_matching_rows")

    assert case["fake_results"][0]["rows"] == [[None]]


def test_geographic_context_requires_all_filters_in_same_where() -> None:
    case = {
        "id": "macrozone_penetration",
        "prompt": "penetration",
        "expected": {
            "sql_calls_min": 1,
            "semantic_checks": [
                {
                    "type": "geographic_context",
                    "filters": [
                        "stateName='VALLE DEL CAUCA'",
                        "cityName='SANTIAGO DE CALI'",
                        "macrozone='Centro'",
                    ],
                }
            ],
        },
    }
    sql = """SELECT COUNT(DISTINCT s.idStore)
    FROM dbo.VW_SalesLast13Months s
    JOIN dbo.VW_Stores st ON st.idPartner=s.idStore
    WHERE st.stateName='VALLE DEL CAUCA'
      AND st.cityName='SANTIAGO DE CALI'
      AND st.macrozone='Centro'"""

    assert score_case(case, "25%", _history(sql), [])["passed"] is True

    incomplete_sql = sql.replace("AND st.macrozone='Centro'", "")
    assert score_case(case, "25%", _history(incomplete_sql), [])["passed"] is False
