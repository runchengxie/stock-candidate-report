import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

from .models import Observation, ProviderBatch


@dataclass(frozen=True)
class Period:
    fiscal_year: int | None
    end: date
    period_type: str
    evidence: str


def finite_number(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def normalize_period(raw: dict, metadata: dict) -> Period | None:
    end = raw.get("endDate") or raw.get("fiscalDateEnding")
    if not end:
        return None
    try:
        if isinstance(end, dict):
            end = end.get("raw") or end.get("fmt")
        if isinstance(end, (int, float)):
            end = datetime.fromtimestamp(end, UTC).date()
        elif not isinstance(end, date):
            end = date.fromisoformat(str(end)[:10])
        year = raw.get("fiscalYear") or metadata.get("fiscal_year_labels", {}).get(end.isoformat())
        label = "verified_fiscal_label" if year else "fiscal_year_unmapped"
        if year is None and metadata.get("fiscal_year_convention") == "end_year":
            year, label = end.year, "configured_end_year_convention"
        period_type = (
            "annual"
            if str(raw.get("period", "annual")).lower()
            in ("0y", "+1y", "annual", "yearly", "fiscal year")
            else "quarterly"
        )
        return Period(int(year) if year is not None else None, end, period_type, label)
    except (ValueError, TypeError, OSError):
        return None


def select_observations(batches: list[ProviderBatch]) -> list[Observation]:
    priority = {"yahoo": 0, "alpha_vantage": 1}
    selected = {}
    all_obs = [x for b in batches for x in b.observations]
    all_obs.sort(key=lambda x: (x.kind != "actual", x.value is None, priority.get(x.source, 99)))
    for obs in all_obs:
        key = (
            obs.symbol,
            obs.metric,
            obs.period_type,
            obs.fiscal_year,
            obs.period_end,
            obs.source if obs.period_type == "quarterly" else "",
        )
        selected.setdefault(key, obs)
    return list(selected.values())
