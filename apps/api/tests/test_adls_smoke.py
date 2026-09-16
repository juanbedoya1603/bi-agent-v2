from scripts.run_adls_smoke import (
    CURRENT_CONTRACTS,
    RemoteFile,
    compare_columns,
    compare_schema,
    parquet_source,
    parquet_uri,
)


def test_adls_defaults_are_safe_and_do_not_require_a_secret() -> None:
    from bi_agent_api.config import Settings

    settings = Settings(_env_file=None)

    assert settings.azure_storage_connection_string.get_secret_value() == ""
    assert settings.adls_filesystem == "agentbi"
    assert settings.adls_base_path == "TiendasOn"


def test_parquet_uri_and_source_contain_no_credentials() -> None:
    files = [RemoteFile("TiendasOn/Stores/store-1.parquet", 123)]

    uri = parquet_uri("agentbi", files[0].path)
    source = parquet_source("agentbi", files)

    assert uri == "abfss://agentbi/TiendasOn/Stores/store-1.parquet"
    assert "read_parquet" in source
    assert "union_by_name=true" in source
    assert "AccountKey" not in source


def test_compare_columns_reports_missing_extra_and_case_differences() -> None:
    result = compare_columns(
        ["idPartner", "cityname", "newColumn"],
        ["idPartner", "cityName", "stateName"],
    )

    assert result["matches"] is False
    assert result["missing"] == ["stateName"]
    assert result["extra"] == ["newColumn"]
    assert result["case_mismatches"] == [{"contract": "cityName", "found": "cityname"}]


def test_current_contracts_include_the_three_analytical_views() -> None:
    assert set(CURRENT_CONTRACTS) == {"Stores", "Products", "Sales"}


def test_compare_schema_reports_type_differences() -> None:
    result = compare_schema(
        [{"name": "idPartner", "type": "VARCHAR"}],
        [{"name": "idPartner", "type": "BIGINT"}],
    )

    assert result["matches"] is False
    assert result["type_matches"] is False
    assert result["type_mismatches"] == [
        {"column": "idPartner", "source_type": "BIGINT", "parquet_type": "VARCHAR"}
    ]
