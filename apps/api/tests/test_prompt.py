from datetime import date, datetime
from zoneinfo import ZoneInfo

from bi_agent_api.prompt import build_system_prompt


def test_prompt_contains_full_schema_runtime_date_and_result_rules() -> None:
    prompt = build_system_prompt(date(2031, 2, 3))

    expected_fragments = (
        "Fecha actual en America/Bogota: 2031-02-03",
        "idStore, idTicket, idProduct, year, month, day",
        "UnitValue, date,",
        "uniqueTicketPerStore, uniqueProductPerTicket",
        "idPartner, economicActivity_fix, stateName, cityName",
        "ZipCode, businessName, stratum, countryName, ImplementationDate",
        "productId, productName, barCode, manufacturerName, brandName",
        "categoryName, subCategoryName, lineName, flavor, unitMeasure, netQuantityValue",
        "últimos 13 meses",
        "SELECT MIN([date]) AS min_date, MAX([date]) AS max_date",
        "cero filas no demuestra que una métrica sea cero",
        "no se encontraron datos coincidentes",
    )
    for fragment in expected_fragments:
        assert fragment in prompt


def test_prompt_uses_current_date_in_bogota() -> None:
    bogota = ZoneInfo("America/Bogota")
    date_before_build = datetime.now(bogota).date().isoformat()
    prompt = build_system_prompt()
    date_after_build = datetime.now(bogota).date().isoformat()

    assert any(
        f"Fecha actual en America/Bogota: {current_date}" in prompt
        for current_date in {date_before_build, date_after_build}
    )
