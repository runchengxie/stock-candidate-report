from datetime import UTC, date, datetime

from stock_candidate_report.providers.yahoo import parse_chart, parse_estimates, parse_financials

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def test_regular_price_and_split_adjusted_baseline():
    raw = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "regularMarketPrice": 60,
                        "regularMarketTime": 1791417600,
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
        "rows": [
            {"period": "0y", "endDate": "2026-06-30", "eps": 12, "revenue": 100},
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
            "rows": [{"endDate": "2025-12-31", "eps": 2, "revenue": 100_000_000}],
        },
        NOW,
    )
    assert [(x.metric, x.value, x.basis) for x in batch.observations] == [
        ("eps", 2, "GAAP"),
        ("revenue", 100_000_000, "reported"),
    ]
    assert batch.observations[0].period_end == date(2025, 12, 31)
