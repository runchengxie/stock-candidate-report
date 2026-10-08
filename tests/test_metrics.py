from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from stock_candidate_report.metrics import calculate_row, forward_four_quarter_pe, growth
from stock_candidate_report.models import Observation, WatchItem

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def obs(metric, value, **kwargs):
    return Observation(
        "AAA",
        metric,
        value,
        "yahoo",
        NOW,
        currency="USD",
        unit="common_share" if metric == "eps" else "currency",
        **kwargs,
    )


def test_growth_and_turnaround():
    a = obs("revenue", 100, basis="reported", period_type="annual", fiscal_year=2025)
    b = replace(a, value=125, fiscal_year=2026)
    assert growth(a, b).value == 0.25
    a = obs("eps", -1, basis="GAAP", period_type="annual", fiscal_year=2025)
    b = replace(a, value=2, fiscal_year=2026)
    assert growth(a, b).value is None
    assert growth(a, b).status == "turnaround"
    assert growth(replace(a, value=0), b).value is None
    assert growth(replace(a, value=1), replace(b, currency="EUR")).value is None
    assert growth(replace(a, value=1), replace(b, basis="adjusted")).value is None


def test_split_consistent_ytd():
    observations = [obs("price", 60), obs("year_end_raw", 100), obs("year_end_baseline", 50)]
    row = calculate_row(WatchItem("AAA"), observations, 2026, NOW.date())
    assert row.values["year_end_raw"] == 100
    assert row.values["ytd"] == pytest.approx(0.2)
    assert calculate_row(WatchItem("AAA"), observations[:1], 2026, NOW.date()).values["ytd"] is None


def quarters():
    return [
        obs(
            "eps",
            v,
            period_type="quarterly",
            kind="estimate",
            basis="adjusted",
            period_end=d,
            meta={"quarter_id": q},
        )
        for v, d, q in [
            (1, date(2026, 12, 31), 8108),
            (2, date(2027, 3, 31), 8109),
            (3, date(2027, 6, 30), 8110),
            (4, date(2027, 9, 30), 8111),
        ]
    ]


def test_four_future_quarters_and_nonpositive():
    price = obs("price", 100, basis="regular_session")
    qs = quarters()
    assert forward_four_quarter_pe(price, qs, NOW.date()).value == 10
    assert forward_four_quarter_pe(price, qs[:3], NOW.date()).value is None
    assert forward_four_quarter_pe(price, [qs[0], qs[0], *qs[2:]], NOW.date()).value is None
    assert (
        forward_four_quarter_pe(price, [replace(qs[0], currency="EUR"), *qs[1:]], NOW.date()).value
        is None
    )
    assert (
        forward_four_quarter_pe(price, [replace(q, value=-1) for q in qs], NOW.date()).status
        == "not_applicable"
    )


def test_completed_and_skipped_quarter_rejected():
    price = obs("price", 100)
    qs = quarters()
    assert (
        forward_four_quarter_pe(
            price, [replace(qs[0], period_end=date(2026, 9, 30)), *qs[1:]], NOW.date()
        ).value
        is None
    )
    assert (
        forward_four_quarter_pe(
            price, [*qs[:3], replace(qs[3], period_end=date(2027, 12, 31))], NOW.date()
        ).value
        is None
    )


def test_53_week_calendar_supported():
    price = obs("price", 100)
    qs = quarters()
    dates = [date(2027, 1, 2), date(2027, 4, 3), date(2027, 7, 3), date(2027, 10, 2)]
    assert (
        forward_four_quarter_pe(
            price, [replace(q, period_end=d) for q, d in zip(qs, dates)], NOW.date()
        ).value
        == 10
    )
