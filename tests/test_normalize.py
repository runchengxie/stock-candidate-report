from datetime import UTC, date, datetime

from stock_candidate_report.models import Observation, ProviderBatch
from stock_candidate_report.normalize import finite_number, normalize_period, select_observations


def test_fiscal_period_mapping():
    p = normalize_period({"endDate": "2026-06-30", "fiscalYear": 2026, "period": "0y"}, {})
    assert (p.fiscal_year, p.end) == (2026, date(2026, 6, 30))
    assert normalize_period({"period": "0y"}, {"report_year": 2026}) is None
    p = normalize_period({"endDate": "2027-01-02", "fiscalYear": 2026, "period": "0y"}, {})
    assert p.fiscal_year == 2026


def test_source_and_units():
    assert finite_number(float("nan")) is None
    assert finite_number(float("inf")) is None
    assert finite_number("0") == 0
    now = datetime(2026, 10, 8, tzinfo=UTC)
    actual = Observation(
        "AAA",
        "eps",
        1,
        "yahoo",
        now,
        period_type="annual",
        fiscal_year=2025,
        period_end=date(2025, 12, 31),
    )
    estimate = Observation(
        "AAA",
        "eps",
        2,
        "alpha_vantage",
        now,
        period_type="annual",
        fiscal_year=2025,
        period_end=date(2025, 12, 31),
        kind="estimate",
    )
    assert select_observations([ProviderBatch([estimate]), ProviderBatch([actual])]) == [actual]
