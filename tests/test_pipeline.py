from datetime import UTC, datetime, timedelta

from stock_candidate_report.cache import Cache
from stock_candidate_report.models import Observation, ProviderBatch, WatchItem
from stock_candidate_report.pipeline import run_report

NOW = datetime(2026, 10, 8, tzinfo=UTC)


class Prices:
    name = "yahoo"
    categories = ("prices",)

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def fetch(self, symbol, report_year, now, categories=None):
        self.calls += 1
        if self.fail:
            return ProviderBatch(
                errors=[
                    {"symbol": symbol, "category": "prices", "source": self.name, "code": "network"}
                ]
            )
        return ProviderBatch(
            [Observation(symbol, "price", 100, self.name, now, currency="USD", unit="share_price")]
        )


def test_offline_and_failed_refresh_keep_original_time(tmp_path):
    c = Cache(tmp_path / "cache.sqlite")
    items = [WatchItem("AAA")]
    p = Prices()
    run_report(items, 2026, NOW, False, False, [p], c)
    failing = Prices(True)
    result = run_report(items, 2026, NOW + timedelta(days=1), True, False, [failing], c)
    assert result.rows[0].values["price"] == 100
    obs = result.observations[0]
    assert obs.fetched_at == NOW
    assert obs.status == "stale"
    assert "network" in obs.reason
    offline = Prices()
    result = run_report(items, 2026, NOW + timedelta(days=2), False, True, [offline], c)
    assert offline.calls == 0
    assert result.observations[0].status == "stale"


def test_partial_failure_does_not_stop_other_stock(tmp_path):
    class Partial(Prices):
        def fetch(self, symbol, report_year, now, categories=None):
            self.fail = symbol == "AAA"
            return super().fetch(symbol, report_year, now, categories)

    result = run_report(
        [WatchItem("AAA"), WatchItem("BBB")],
        2026,
        NOW,
        False,
        False,
        [Partial()],
        Cache(tmp_path / "cache.sqlite"),
    )
    assert result.rows[0].values["price"] is None
    assert result.rows[1].values["price"] == 100
    assert result.coverage["prices_available"] == 1


def test_all_prices_missing_is_not_success(tmp_path):
    result = run_report(
        [WatchItem("AAA")], 2026, NOW, False, True, [Prices()], Cache(tmp_path / "cache.sqlite")
    )
    assert result.coverage["prices_available"] == 0
    assert result.coverage["missing_fields"] > 0
