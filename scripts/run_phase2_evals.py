import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from bi_agent_api.agent import answer_question  # noqa: E402
from bi_agent_api.config import Settings  # noqa: E402
from bi_agent_api.phase2_evals import (  # noqa: E402
    SyntheticSqlExecutor,
    build_report,
    load_cases,
    score_case,
)


async def run(output: Path, cases_path: Path) -> int:
    if os.getenv("RUN_LIVE_EVALS") != "1":
        print("Live evals deshabilitados: define RUN_LIVE_EVALS=1 para consumir tokens.")
        return 2

    settings = Settings()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY no está configurada.")
        return 2

    results = []
    for case in load_cases(cases_path):
        executor = SyntheticSqlExecutor(case["fake_results"])
        try:
            answer, context = await answer_question(
                case["prompt"], settings, sql_executor=executor
            )
            result = score_case(
                case, answer, context.sql_history, executor.delivered_results
            )
        except Exception as error:
            result = {
                "id": case["id"],
                "prompt": case["prompt"],
                "critical": case.get("critical", False),
                "passed": False,
                "checks": [{"name": "runner", "passed": False, "detail": str(error)}],
                "answer": "",
                "sql_calls": [],
                "fake_results": executor.delivered_results,
            }
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} {case['id']}", flush=True)

    report = build_report(results, settings.openai_model)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(
        f"Cases: {summary['cases']} | Passed: {summary['passed']} | "
        f"Failed: {summary['failed']} | Accuracy: {summary['accuracy']}%",
        flush=True,
    )
    print(f"Reporte: {output}")
    return 0 if summary["failed"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Evals live de Calidad BI (Fase 2).")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=ROOT / "evals" / "cases.json")
    args = parser.parse_args()
    return asyncio.run(run(args.output, args.cases))


if __name__ == "__main__":
    raise SystemExit(main())
