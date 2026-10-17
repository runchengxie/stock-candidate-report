import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from .cache import Cache, ttl_for
from .metrics import calculate_row
from .models import ProviderBatch, RunResult, WatchItem
from .normalize import select_observations


def identity(o):
    return o.symbol, o.metric, o.period_type, o.fiscal_year, o.period_end, o.kind


def cached_observations(entry, now, ttl, reason=""):
    result = []
    for o in entry.batch.observations:
        age = now - o.fetched_at
        stale = bool(reason) or not timedelta(0) <= age < ttl
        result.append(
            replace(
                o,
                status="stale" if stale else o.status,
                reason=reason or ("expired_offline_cache" if stale else o.reason),
                meta={
                    **o.meta,
                    "cache_response_id": o.meta.get("cache_response_id", entry.response_id),
                    "used_cache": True,
                },
            )
        )
    return result


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
            settings = getattr(provider, "symbol_metadata", getattr(provider, "metadata", {})).get(
                item.symbol, {}
            )
            fingerprint = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[
                :16
            ]
            for category in provider.categories:
                key = f"v2:{provider.name}:{item.symbol}:{year}:{category}:{fingerprint}"
                ttl = ttl_for(category, cache.ttl_overrides)
                entry = cache.get(key, now, ttl)
                if entry and (offline or (entry.fresh and not refresh)):
                    batch = ProviderBatch(
                        cached_observations(entry, now, ttl), entry.batch.errors, entry.batch.raw
                    )
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
                    provider.reserve_attempt = lambda: cache.reserve(
                        provider.name, now.date(), cache.av_daily_limit
                    )
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
                response_id = cache.archive(batch)
                batch.errors = [{**e, "response_id": response_id} for e in batch.errors]
                batch.observations = [
                    replace(
                        o, meta={**o.meta, "cache_response_id": response_id, "used_cache": False}
                    )
                    for o in batch.observations
                ]
                if entry:
                    good = {identity(o) for o in batch.observations if o.value is not None}
                    failed = ",".join(e["code"] for e in batch.errors) or "partial_response"
                    retained = [
                        o
                        for o in cached_observations(entry, now, ttl, f"refresh_failed:{failed}")
                        if o.value is not None and identity(o) not in good
                    ]
                    if retained:
                        identities = {identity(o) for o in retained}
                        batch.observations = [
                            o for o in batch.observations if identity(o) not in identities
                        ]
                        batch.observations.extend(retained)
                        cached_count += 1
                if any(o.value is not None for o in batch.observations):
                    cache.put(key, batch, now, response_id=response_id)
                batches.append(batch)
        observations.extend(select_observations(batches))
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
    return RunResult(
        now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:10],
        rows,
        observations,
        errors,
        {
            "stocks": len(items),
            "prices_available": sum(r.values["price"] is not None for r in rows),
            "missing_fields": sum(s.value is None for r in rows for s in r.statuses.values()),
            "cache_batches": cached_count,
            "provider_calls": requests,
            "fields_available": sum(s.value is not None for r in rows for s in r.statuses.values()),
        },
    )
