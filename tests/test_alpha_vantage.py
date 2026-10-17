from datetime import UTC, datetime

import httpx

from stock_candidate_report.providers.alpha_vantage import AlphaVantageProvider, parse_response

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def test_estimate_coverage_and_unknown_schema():
    data = {
        "symbol": "AAA",
        "currency": "USD",
        "estimates": [
            {
                "date": "2027-12-31",
                "horizon": "fiscal year",
                "eps_estimate_average": "2",
                "revenue_estimate_average": "100",
                "eps_estimate_analyst_count": "8",
            },
            {"date": "2027-03-31", "horizon": "fiscal quarter", "eps_estimate_average": "0.5"},
        ],
    }
    batch = parse_response("AAA", data, NOW, "USD", "common_share")
    assert [(x.metric, x.period_type, x.value) for x in batch.observations] == [
        ("eps", "annual", 2),
        ("revenue", "annual", 100),
        ("eps", "quarterly", 0.5),
        ("revenue", "quarterly", None),
    ]
    assert parse_response("AAA", {"surprise": []}, NOW).errors[0]["code"] == "schema_unknown"


def test_alpha_errors_redacted_and_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"Information": "premium required secret-test"})

    p = AlphaVantageProvider(
        "secret-test", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    batch = p.fetch("AAA", 2026, NOW)
    assert batch.errors[0]["code"] == "permission"
    assert "secret-test" not in str(batch)
    assert len(calls) == 1


def test_rate_limit_and_no_key():
    assert (
        parse_response("AAA", {"Note": "API call frequency limit"}, NOW).errors[0]["code"]
        == "quota"
    )
    assert AlphaVantageProvider("").fetch("AAA", 2026, NOW).errors[0]["code"] == "not_configured"


def test_network_retry_is_bounded():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("secret-test", request=request)

    p = AlphaVantageProvider(
        "secret-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )
    batch = p.fetch("AAA", 2026, NOW)
    assert len(calls) == 3
    assert batch.errors[0]["code"] == "network"
    assert "secret-test" not in str(batch)
