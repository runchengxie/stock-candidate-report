from datetime import UTC, date, datetime

import httpx

from stock_candidate_report.providers.yahoo import (
    YahooProvider,
    parse_chart,
    parse_estimates,
    parse_financials,
)

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def test_regular_price_and_split_adjusted_baseline():
    raw = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "regularMarketPrice": 60,
                        "regularMarketTime": 1791403200,
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": [1767196800, 1767283200],
                    "indicators": {"quote": [{"close": [50, 52]}]},
                    "events": {
                        "splits": {"x": {"date": 1770000000, "numerator": 2, "denominator": 1}}
                    },
                }
            ],
            "error": None,
        }
    }
    obs = parse_chart("AAA", raw, 2026, NOW).observations
    values = {x.metric: x.value for x in obs}
    assert values["price"] == 60
    assert values["year_end_raw"] == 100
    assert values["year_end_baseline"] == 50
    assert next(x for x in obs if x.metric == "price").meta["price_time"] != NOW.isoformat()


def test_estimates_require_explicit_period_dates():
    payload = {
        "financialCurrency": "USD",
        "quoteType": "EQUITY",
        "shareUnit": "common_share",
        "estimate_currency": "USD",
        "rows": [
            {
                "period": "0y",
                "endDate": "2026-06-30",
                "fiscalYear": 2026,
                "eps": 12,
                "revenue": 100,
            },
            {"period": "+1y", "eps": 13, "revenue": 120},
        ],
    }
    batch = parse_estimates("AAA", payload, NOW)
    assert [(x.fiscal_year, x.value) for x in batch.observations] == [(2026, 12), (2026, 100)]
    assert any(x["code"] == "period_unmapped" for x in batch.errors)


def test_historical_financial_currency():
    batch = parse_financials(
        "AAA",
        {
            "financialCurrency": "USD",
            "quoteType": "EQUITY",
            "shareUnit": "common_share",
            "rows": [
                {
                    "endDate": "2025-12-31",
                    "fiscalYear": 2025,
                    "eps": 2,
                    "eps_basis": "GAAP",
                    "revenue": 100_000_000,
                }
            ],
        },
        NOW,
    )
    assert [(x.metric, x.value, x.basis) for x in batch.observations] == [
        ("eps", 2, "GAAP"),
        ("revenue", 100_000_000, "reported"),
    ]
    assert batch.observations[0].period_end == date(2025, 12, 31)


def test_configured_exchange_alias_preserves_original_symbol():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 500,
                                "currency": "HKD",
                                "exchangeTimezoneName": "Asia/Hong_Kong",
                            },
                            "timestamp": [],
                            "indicators": {"quote": [{"close": []}]},
                        }
                    ]
                }
            },
        )

    provider = YahooProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        symbol_metadata={"700": {"yahoo_symbol": "0700.HK"}},
    )
    batch = provider.fetch("700", 2026, NOW, ("prices",))
    assert requests[0].url.path.endswith("/0700.HK")
    assert batch.observations[0].symbol == "700"
    assert batch.observations[0].currency == "HKD"


def test_permission_denial_stops_further_requests():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403)

    provider = YahooProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    first = provider.fetch("AAA", 2026, NOW, ("prices",))
    second = provider.fetch("BBB", 2026, NOW, ("prices",))
    assert first.errors[0]["code"] == "permission"
    assert second.errors[0]["code"] == "permission"
    assert len(calls) == 1
