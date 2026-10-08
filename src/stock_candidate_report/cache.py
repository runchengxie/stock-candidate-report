import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .models import Observation, ProviderBatch, json_value


def ttl_for(category: str, overrides=None) -> timedelta:
    seconds = (overrides or {}).get(
        category, {"prices": 3600, "financials": 86400, "estimates": 604800}[category]
    )
    return timedelta(seconds=max(0, float(seconds)))


def clean_json(value):
    if isinstance(value, dict):
        return {
            k: clean_json(v)
            for k, v in value.items()
            if not any(s in k.lower() for s in ("apikey", "api_key", "secret", "cookie", "crumb"))
        }
    if isinstance(value, (list, tuple)):
        return [clean_json(x) for x in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def decode_batch(payload: str) -> ProviderBatch:
    data = json.loads(payload)
    observations = []
    for row in data["observations"]:
        row["fetched_at"] = datetime.fromisoformat(row["fetched_at"])
        row["period_end"] = date.fromisoformat(row["period_end"]) if row["period_end"] else None
        observations.append(Observation(**row))
    return ProviderBatch(observations, data["errors"], data["raw"])


@dataclass
class CacheEntry:
    batch: ProviderBatch
    fresh: bool
    response_id: str


class Cache:
    def __init__(self, path: Path, ttl_overrides=None, av_daily_limit=25):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.ttl_overrides = ttl_overrides or {}
        self.av_daily_limit = av_daily_limit
        with self.connect() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS entries "
                "(key TEXT PRIMARY KEY, fetched_at TEXT, payload TEXT, response_id TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS budget "
                "(provider TEXT, day TEXT, count INTEGER, PRIMARY KEY(provider,day))"
            )

    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def get(self, key: str, now: datetime, ttl: timedelta) -> CacheEntry | None:
        with self.connect() as c:
            row = c.execute(
                "SELECT fetched_at,payload,response_id FROM entries WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        age = now - datetime.fromisoformat(row[0])
        return CacheEntry(decode_batch(row[1]), timedelta(0) <= age < ttl, row[2])

    def put(self, key: str, batch: ProviderBatch, fetched_at: datetime) -> None:
        response_id = uuid4().hex
        payload = json.dumps(
            clean_json(json_value(batch)), default=json_value, ensure_ascii=False, allow_nan=False
        )
        raw_dir = self.path.parent / "raw"
        raw_dir.mkdir(exist_ok=True)
        with (raw_dir / f"{response_id}.json").open("x", encoding="utf-8") as f:
            f.write(payload)
        with self.connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO entries VALUES(?,?,?,?)",
                (key, fetched_at.isoformat(), payload, response_id),
            )

    def reserve(self, provider: str, day: date, limit: int) -> bool:
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT count FROM budget WHERE provider=? AND day=?", (provider, day.isoformat())
            ).fetchone()
            count = row[0] if row else 0
            if count >= limit:
                return False
            c.execute(
                "INSERT OR REPLACE INTO budget VALUES(?,?,?)",
                (provider, day.isoformat(), count + 1),
            )
        return True
