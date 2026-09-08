from scripts.run_sql_live_smoke import live_smoke_enabled


def test_live_smoke_requires_explicit_opt_in() -> None:
    assert live_smoke_enabled({}) is False
    assert live_smoke_enabled({"RUN_SQL_LIVE_SMOKE": "0"}) is False
    assert live_smoke_enabled({"RUN_SQL_LIVE_SMOKE": "1"}) is True


def test_live_smoke_never_runs_from_pytest() -> None:
    environment = {
        "RUN_SQL_LIVE_SMOKE": "1",
        "PYTEST_CURRENT_TEST": "apps/api/tests/test_live_smoke.py::test",
    }

    assert live_smoke_enabled(environment) is False
