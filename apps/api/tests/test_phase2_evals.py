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

    assert len(cases) == 24
    assert len({case["id"] for case in cases}) == 24


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
