import time
from datetime import datetime

import httpx

from ..models import Observation, ProviderBatch
from ..normalize import finite_number, normalize_period
from .yahoo import error


def parse_response(
    symbol: str,
    data: dict,
    now: datetime,
    currency: str = "",
    share_unit: str = "",
    period_metadata: dict | None = None,
) -> ProviderBatch:
    if not isinstance(data, dict):
        return ProviderBatch(errors=[error(symbol, "schema_unknown", "estimates", "alpha_vantage")])
    for key in ("Information", "Note", "Error Message"):
        if key in data:
            message = str(data[key]).lower()
            code = (
                "permission"
                if any(s in message for s in ("premium", "apikey", "api key"))
                else (
                    "quota"
                    if any(s in message for s in ("limit", "frequency", "rate", "day"))
                    else ("symbol_not_found" if key == "Error Message" else "permission")
                )
            )
            return ProviderBatch(errors=[error(symbol, code, "estimates", "alpha_vantage")])
    rows = data.get("estimates")
    if not isinstance(rows, list):
        return ProviderBatch(errors=[error(symbol, "schema_unknown", "estimates", "alpha_vantage")])
    batch = ProviderBatch(raw={"estimates": data})
    currency = data.get("currency", currency)
    for row in rows:
        if not isinstance(row, dict):
            batch.errors.append(error(symbol, "schema_unknown", "estimates", "alpha_vantage"))
            continue
        horizon = str(row.get("horizon", "")).lower()
        if horizon not in ("fiscal year", "fiscal quarter", "annual", "quarterly"):
            batch.errors.append(error(symbol, "period_unmapped", "estimates", "alpha_vantage"))
            continue
        period = normalize_period(
            {"endDate": row.get("date"), "period": horizon, "fiscalYear": row.get("fiscal_year")},
            period_metadata or {},
        )
        if period is None:
            batch.errors.append(error(symbol, "period_unmapped", "estimates", "alpha_vantage"))
            continue
        for metric, prefix in (("eps", "eps"), ("revenue", "revenue")):
            metric_currency = row.get(f"{prefix}_currency", currency)
            value = finite_number(row.get(f"{prefix}_estimate_average"))
            status, reason = ("ok", "") if value is not None else ("missing", "no_coverage")
            if not metric_currency or (
                metric == "eps" and share_unit not in ("common_share", "adr_share")
            ):
                value, status, reason = None, "missing", "currency_or_share_unit_unknown"
            elif period.period_type == "annual" and period.fiscal_year is None:
                status, reason = "unmapped", "fiscal_year_unmapped"
            batch.observations.append(
                Observation(
                    symbol,
                    metric,
                    value,
                    "alpha_vantage",
                    now,
                    currency=metric_currency,
                    unit=share_unit if metric == "eps" else "currency",
                    period_type=period.period_type,
                    fiscal_year=period.fiscal_year,
                    period_end=period.end,
                    kind="estimate",
                    basis=row.get("eps_basis", "undisclosed") if metric == "eps" else "reported",
                    estimate_date=row.get("estimate_date"),
                    status=status,
                    reason=reason,
                    meta={
                        "category": "estimates",
                        "period_evidence": period.evidence,
                        "analyst_count": row.get(f"{prefix}_estimate_analyst_count"),
                        "period_start": row.get("period_start"),
                    },
                )
            )
    if not rows:
        batch.errors.append(error(symbol, "no_coverage", "estimates", "alpha_vantage"))
    return batch


class AlphaVantageProvider:
    name = "alpha_vantage"
    categories = ("estimates",)

    def __init__(self, api_key: str, client=None, sleeper=time.sleep, metadata=None):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=20)
        self.sleeper = sleeper
        self.metadata = metadata or {}
        self.blocked = False
        self.blocked_code = "quota"
        self.reserve_attempt = lambda: True

    def fetch(self, symbol, report_year, now, categories=None):
        if not self.api_key:
            return ProviderBatch(errors=[error(symbol, "not_configured", "estimates", self.name)])
        if self.blocked:
            return ProviderBatch(errors=[error(symbol, self.blocked_code, "estimates", self.name)])
        for attempt in range(3):
            if not self.reserve_attempt():
                self.blocked, self.blocked_code = True, "quota"
                return ProviderBatch(errors=[error(symbol, "quota", "estimates", self.name)])
            try:
                response = self.client.get(
                    "https://www.alphavantage.co/query",
                    params={
                        "function": "EARNINGS_ESTIMATES",
                        "symbol": symbol,
                        "apikey": self.api_key,
                    },
                )
                if response.status_code in (401, 403, 429):
                    code = "quota" if response.status_code == 429 else "permission"
                    self.blocked = True
                    self.blocked_code = code
                    return ProviderBatch(errors=[error(symbol, code, "estimates", self.name)])
                if response.status_code in (400, 404):
                    return ProviderBatch(
                        errors=[error(symbol, "symbol_not_found", "estimates", self.name)]
                    )
                if 400 <= response.status_code < 500:
                    return ProviderBatch(
                        errors=[error(symbol, "permission", "estimates", self.name)]
                    )
                response.raise_for_status()
                meta = self.metadata.get(symbol, {})
                batch = parse_response(
                    symbol,
                    response.json(),
                    now,
                    meta.get("currency", ""),
                    meta.get("share_unit", ""),
                    meta,
                )
                if any(e["code"] in ("quota", "permission") for e in batch.errors):
                    self.blocked = True
                    self.blocked_code = next(
                        e["code"] for e in batch.errors if e["code"] in ("quota", "permission")
                    )
                return batch
            except (httpx.RequestError, httpx.HTTPStatusError):
                if attempt < 2:
                    self.sleeper(2**attempt)
            except ValueError:
                return ProviderBatch(
                    errors=[error(symbol, "schema_unknown", "estimates", self.name)]
                )
        return ProviderBatch(errors=[error(symbol, "network", "estimates", self.name)])
