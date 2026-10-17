from datetime import UTC, datetime, timedelta

from stock_candidate_report.cache import Cache, ttl_for
from stock_candidate_report.models import Observation, ProviderBatch

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def test_ttl_boundaries_and_original_dates(tmp_path):
    c = Cache(tmp_path / "cache.sqlite")
    batch = ProviderBatch([Observation("AAA", "price", 10, "yahoo", NOW)])
    c.put("AAA:prices", batch, NOW)
    assert c.get("AAA:prices", NOW + timedelta(seconds=3599), ttl_for("prices")).fresh
    entry = c.get("AAA:prices", NOW + timedelta(seconds=3600), ttl_for("prices"))
    assert not entry.fresh
    assert entry.batch.observations[0].fetched_at == NOW
    assert ttl_for("estimates").total_seconds() == 604800
    assert ttl_for("financials").total_seconds() == 86400
    assert ttl_for("prices", {"prices": 5}).total_seconds() == 5
    assert not c.get("AAA:prices", NOW - timedelta(seconds=1), ttl_for("prices")).fresh


def test_cache_connections_and_persistent_daily_budget(tmp_path):
    p = tmp_path / "cache.sqlite"
    a, b = Cache(p), Cache(p)
    a.put("a", ProviderBatch(), NOW)
    b.put("b", ProviderBatch(), NOW)
    assert a.get("b", NOW, ttl_for("prices")) is not None
    assert a.reserve("av", NOW.date(), 1)
    assert not b.reserve("av", NOW.date(), 1)
    assert b.reserve("av", (NOW + timedelta(days=1)).date(), 1)
