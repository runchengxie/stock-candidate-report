from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from .cache import Cache, ttl_for
from .metrics import calculate_row
from .models import ProviderBatch, RunResult, WatchItem
from .normalize import select_observations


def run_report(
    items: list[WatchItem],
    year: int,
    now: datetime,
    refresh: bool,
    offline: bool,
    providers: list,
    cache: Cache,
    progress=None,
) -> RunResult:
    observations, errors = [], []
    cached_count, requests = 0, 0
    for i, item in enumerate(items):
        batches = []
        for provider in providers:
            for category in provider.categories:
                key = f"v1:{provider.name}:{item.symbol}:{year}:{category}"
                entry = cache.get(key, now, ttl_for(category, cache.ttl_overrides))
                if entry and (offline or (entry.fresh and not refresh)):
                    batch = entry.batch
                    if not entry.fresh:
                        batch.observations = [
                            replace(o, status="stale", reason="expired_offline_cache")
                            for o in batch.observations
                        ]
                    batch.observations = [
                        replace(
                            o,
                            meta={
                                **o.meta,
                                "cache_response_id": entry.response_id,
                                "used_cache": True,
                            },
                        )
                        for o in batch.observations
                    ]
                    batches.append(batch)
                    cached_count += 1
                    continue
                if offline:
                    batches.append(
                        ProviderBatch(
                            errors=[
                                {
                                    "symbol": item.symbol,
                                    "source": provider.name,
                                    "category": category,
                                    "code": "offline_cache_missing",
                                }
                            ]
                        )
                    )
                    continue
                if provider.name == "alpha_vantage":
                    if not getattr(provider, "api_key", ""):
                        batches.append(provider.fetch(item.symbol, year, now, (category,)))
                        continue
                    if not cache.reserve(provider.name, now.date(), cache.av_daily_limit):
                        batch = ProviderBatch(
                            errors=[
                                {
                                    "symbol": item.symbol,
                                    "source": provider.name,
                                    "category": category,
                                    "code": "quota",
                                }
                            ]
                        )
                    else:
                        requests += 1
                        batch = provider.fetch(item.symbol, year, now, (category,))
                else:
                    requests += 1
                    try:
                        batch = provider.fetch(item.symbol, year, now, (category,))
                    except Exception:
                        batch = ProviderBatch(
                            errors=[
                                {
                                    "symbol": item.symbol,
                                    "source": provider.name,
                                    "category": category,
                                    "code": "provider_failure",
                                }
                            ]
                        )
                valid = any(o.value is not None for o in batch.observations)
                if valid:
                    cache.put(key, batch, now)
                    stored = cache.get(key, now, ttl_for(category, cache.ttl_overrides))
                    batch.observations = [
                        replace(
                            o,
                            meta={
                                **o.meta,
                                "cache_response_id": stored.response_id,
                                "used_cache": False,
                            },
                        )
                        for o in batch.observations
                    ]
                elif entry:
                    reason = ",".join(e["code"] for e in batch.errors) or "no_coverage"
                    old = [
                        replace(
                            o,
                            status="stale",
                            reason=f"refresh_failed:{reason}",
                            meta={
                                **o.meta,
                                "cache_response_id": entry.response_id,
                                "used_cache": True,
                            },
                        )
                        for o in entry.batch.observations
                    ]
                    batch.observations.extend(old)
                    cached_count += 1
                batches.append(batch)
        selected = select_observations(batches)
        observations.extend(selected)
        errors.extend(e for b in batches for e in b.errors)
        if progress:
            progress(i + 1, len(items), item.symbol)
    rows = [calculate_row(item, observations, year, now.date()) for item in items]
    for row in rows:
        reasons = sorted({e["code"] for e in errors if e["symbol"] == row.item.symbol})
        if reasons:
            for status in row.statuses.values():
                if status.value is None:
                    status.reason += "; " + ", ".join(reasons)
    missing_count = sum(s.value is None for r in rows for s in r.statuses.values())
    return RunResult(
        now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:10],
        rows,
        observations,
        errors,
        {
            "stocks": len(items),
            "prices_available": sum(r.values["price"] is not None for r in rows),
            "missing_fields": missing_count,
            "cache_batches": cached_count,
            "provider_calls": requests,
            "fields_available": sum(s.value is not None for r in rows for s in r.statuses.values()),
        },
    )
