from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd

from stock_candidate_report.cache import Cache, ttl_for
from stock_candidate_report.metrics import calculate_row, growth
from stock_candidate_report.models import Observation, ProviderBatch, WatchItem
from stock_candidate_report.normalize import normalize_period, select_observations
from stock_candidate_report.pipeline import run_report
from stock_candidate_report.providers.alpha_vantage import AlphaVantageProvider
from stock_candidate_report.providers.yahoo import (
    YahooProvider,
    parse_chart,
    parse_estimates,
    parse_financials,
)

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def observation(metric, value, **kwargs):
    if metric == "price":
        kwargs.setdefault("meta", {"share_unit": "common_share"})
    return Observation("AAA", metric, value, "yahoo", NOW, currency="USD", **kwargs)


def test_partial_refresh_keeps_cached_baseline_and_original_time(tmp_path):
    class Prices:
        name, categories = "yahoo", ("prices",)
        calls = 0

        def fetch(self, symbol, year, now, categories=None):
            self.calls += 1
            if self.calls == 1:
                return ProviderBatch(
                    [observation("price", 100), observation("year_end_baseline", 80)]
                )
            return ProviderBatch([replace(observation("price", 120), fetched_at=now)])

    p, c = Prices(), Cache(tmp_path / "cache.sqlite")
    items = [WatchItem("AAA")]
    run_report(items, 2026, NOW, False, False, [p], c)
    result = run_report(items, 2026, NOW + timedelta(days=1), True, False, [p], c)
    assert result.rows[0].values["ytd"] == 0.5
    base = next(o for o in result.observations if o.metric == "year_end_baseline")
    assert base.fetched_at == NOW
    assert base.status == "stale"
    offline = run_report(items, 2026, NOW + timedelta(days=1), False, True, [p], c)
    assert offline.rows[0].values["ytd"] == 0.5
    assert (
        next(o for o in offline.observations if o.metric == "year_end_baseline").status == "stale"
    )


def test_cache_response_id_and_older_write(tmp_path):
    path = tmp_path / "cache.sqlite"
    a, b = Cache(path), Cache(path)
    id_a = a.put("same", ProviderBatch([observation("price", 100)]), NOW)
    newer = NOW + timedelta(seconds=1)
    id_b = b.put(
        "same", ProviderBatch([replace(observation("price", 120), fetched_at=newer)]), newer
    )
    old_id = a.put("same", ProviderBatch([observation("price", 90)]), NOW)
    assert len({id_a, id_b, old_id}) == 3
    stored = a.get("same", newer, ttl_for("prices"))
    assert stored.response_id == id_b
    assert stored.batch.observations[0].value == 120


def test_stub_year_growth_rejected_and_53_week_allowed():
    a = observation(
        "revenue",
        100,
        unit="currency",
        basis="reported",
        period_type="annual",
        fiscal_year=2025,
        period_end=date(2025, 12, 31),
    )
    b = replace(a, value=60, fiscal_year=2026, period_end=date(2026, 6, 30))
    assert growth(a, b).value is None
    a = replace(a, period_end=date(2025, 12, 27))
    b = replace(b, value=110, period_end=date(2027, 1, 2))
    assert round(growth(a, b).value, 6) == 0.1


def test_noncalendar_fiscal_labels_require_verification():
    raw = {"endDate": "2027-01-02", "period": "annual"}
    p = normalize_period(raw, {})
    assert p.end == date(2027, 1, 2)
    assert p.fiscal_year is None
    p = normalize_period(raw, {"fiscal_year_labels": {"2027-01-02": 2026}})
    assert p.fiscal_year == 2026
    p = normalize_period(
        {"endDate": "2026-06-30", "period": "annual"}, {"fiscal_year_convention": "end_year"}
    )
    assert p.fiscal_year == 2026


def test_forecast_metric_currency_and_unknown_share_unit():
    batch = parse_estimates(
        "AAA",
        {
            "financialCurrency": "CNY",
            "quoteType": "EQUITY",
            "rows": [
                {
                    "endDate": "2026-12-31",
                    "fiscalYear": 2026,
                    "period": "annual",
                    "eps": 2,
                    "eps_currency": "USD",
                    "revenue": 100,
                    "revenue_currency": "CNY",
                }
            ],
        },
        NOW,
    )
    eps, revenue = batch.observations
    assert eps.currency == "USD"
    assert eps.value is None
    assert revenue.currency == "CNY"
    assert revenue.value == 100


def test_malformed_av_isolated_to_one_stock(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"estimates": [None]})

    provider = AlphaVantageProvider(
        "test-key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = run_report(
        [WatchItem("AAA"), WatchItem("BBB")],
        2026,
        NOW,
        False,
        False,
        [provider],
        Cache(tmp_path / "cache.sqlite"),
    )
    assert len(result.rows) == 2
    assert {e["code"] for e in result.errors} == {"schema_unknown"}


def test_each_retry_reserves_budget_and_bad_requests_do_not_retry(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("failed", request=request)

    provider = AlphaVantageProvider(
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )
    run_report(
        [WatchItem("AAA")],
        2026,
        NOW,
        False,
        False,
        [provider],
        Cache(tmp_path / "cache.sqlite", av_daily_limit=1),
    )
    assert len(calls) == 1
    calls.clear()

    def bad_request(request):
        calls.append(request)
        return httpx.Response(400)

    provider = AlphaVantageProvider(
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(bad_request)),
        sleeper=lambda _: None,
    )
    assert provider.fetch("AAA", 2026, NOW).errors[0]["code"] == "symbol_not_found"
    assert len(calls) == 1


def test_yahoo_error_envelope_is_classified():
    raw = {
        "chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}
    }
    assert parse_chart("AAA", raw, 2026, NOW).errors[0]["code"] == "symbol_not_found"


def test_failed_acquisitions_have_immutable_archives(tmp_path):
    class Failing:
        name, categories = "yahoo", ("prices",)

        def fetch(self, *args):
            return ProviderBatch(
                errors=[
                    {"symbol": "AAA", "source": "yahoo", "category": "prices", "code": "network"}
                ],
                raw={"diagnostic": "safe"},
            )

    c = Cache(tmp_path / "cache.sqlite")
    result = run_report([WatchItem("AAA")], 2026, NOW, False, False, [Failing()], c)
    assert len(list((tmp_path / "raw").glob("*.json"))) == 1
    assert result.errors[0]["response_id"]


def test_complete_estimate_cohort_survives_source_selection():
    qs = [
        observation(
            "eps",
            v,
            unit="common_share",
            basis="adjusted",
            kind="estimate",
            period_type="quarterly",
            period_end=end,
        )
        for v, end in [
            (1, date(2026, 12, 31)),
            (2, date(2027, 3, 31)),
            (3, date(2027, 6, 30)),
            (4, date(2027, 9, 30)),
        ]
    ]
    av = [replace(q, source="alpha_vantage", id=f"av{i}") for i, q in enumerate(qs)]
    chosen = select_observations([ProviderBatch(qs[:2]), ProviderBatch(av)])
    row = calculate_row(WatchItem("AAA"), [observation("price", 100), *chosen], 2026, NOW.date())
    assert row.values["ntm_pe"] == 10
    assert all(x.startswith("av") for x in row.statuses["ntm_pe"].observation_ids[1:])


def test_quote_summary_denial_classification_and_blocking():
    class Ticker:
        def get_info(self):
            return {"financialCurrency": "USD", "quoteType": "EQUITY"}

        def get_earnings_estimate(self):
            return pd.DataFrame({"avg": [1]}, index=["0y"])

        def get_revenue_estimate(self):
            return pd.DataFrame({"avg": [100]}, index=["0y"])

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    provider = YahooProvider(
        ticker_factory=lambda _: Ticker(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    batch = provider.fetch("AAA", 2026, NOW, ("estimates",))
    assert any(e["code"] == "quota" for e in batch.errors)
    provider.fetch("BBB", 2026, NOW, ("estimates",))
    assert len(calls) == 1


def test_actual_eps_basis_is_not_asserted_gaap():
    batch = parse_financials(
        "AAA",
        {
            "financialCurrency": "USD",
            "quoteType": "EQUITY",
            "shareUnit": "common_share",
            "rows": [{"fiscalYear": 2025, "endDate": "2025-12-31", "eps": 2, "revenue": 100}],
        },
        NOW,
    )
    assert batch.observations[0].basis == "undisclosed"


def test_alias_changes_invalidate_normalized_cache(tmp_path):
    class Provider:
        name, categories = "yahoo", ("prices",)
        symbol_metadata = {"AAA": {"yahoo_symbol": "FIRST"}}
        calls = 0

        def fetch(self, symbol, year, now, categories=None):
            self.calls += 1
            value = 100 if self.symbol_metadata["AAA"]["yahoo_symbol"] == "FIRST" else 200
            return ProviderBatch([observation("price", value)])

    provider = Provider()
    cache = Cache(tmp_path / "cache.sqlite")
    run_report([WatchItem("AAA")], 2026, NOW, False, False, [provider], cache)
    provider.symbol_metadata = {"AAA": {"yahoo_symbol": "SECOND"}}
    result = run_report([WatchItem("AAA")], 2026, NOW, False, False, [provider], cache)
    assert result.rows[0].values["price"] == 200
    assert provider.calls == 2


def test_unknown_actual_vs_forecast_eps_basis_not_compared():
    actual = observation(
        "eps",
        2,
        unit="common_share",
        basis="undisclosed",
        period_type="annual",
        fiscal_year=2025,
        period_end=date(2025, 12, 31),
    )
    forecast = replace(
        actual, value=3, kind="estimate", fiscal_year=2026, period_end=date(2026, 12, 31)
    )
    assert growth(actual, forecast).value is None
