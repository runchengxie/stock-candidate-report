from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class WatchItem:
    symbol: str
    name: str = ""
    group: str = ""


@dataclass(frozen=True)
class Observation:
    symbol: str
    metric: str
    value: float | None
    source: str
    fetched_at: datetime
    currency: str = ""
    unit: str = ""
    period_type: str = "instant"
    fiscal_year: int | None = None
    period_end: date | None = None
    kind: str = "actual"
    basis: str = "undisclosed"
    estimate_date: str | None = None
    status: str = "ok"
    reason: str = ""
    meta: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class ProviderBatch:
    observations: list[Observation] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class MetricResult:
    value: float | None
    status: str = "ok"
    reason: str = ""
    observation_ids: list[str] = field(default_factory=list)


@dataclass
class ReportRow:
    item: WatchItem
    values: dict[str, float | str | None]
    statuses: dict[str, MetricResult]


@dataclass
class RunResult:
    run_id: str
    rows: list[ReportRow]
    observations: list[Observation]
    errors: list[dict]
    coverage: dict


def json_value(obj: Any):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    raise TypeError(type(obj).__name__)
