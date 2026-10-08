import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import yfinance as yf

from ..models import Observation, ProviderBatch
from ..normalize import finite_number, normalize_period


def error(symbol, code, category, source="yahoo"):
    return {"symbol": symbol, "source": source, "category": category, "code": code}


def response_error(status: int, envelope) -> str | None:
    if status in (401, 403):
        return "permission"
    if status == 429:
        return "quota"
    if status in (400, 404):
        return "symbol_not_found"
    if status >= 400:
        return "network"
    if envelope:
        message = str(envelope).lower()
        if "not found" in message or "no data found" in message:
            return "symbol_not_found"
        if "unauthorized" in message or "forbidden" in message or "crumb" in message:
            return "permission"
        if "limit" in message or "too many" in message:
            return "quota"
        return "provider_failure"
    return None


def parse_chart(symbol: str, raw: dict, report_year: int, now: datetime) -> ProviderBatch:
    batch = ProviderBatch(raw={"prices": raw})
    chart = raw.get("chart", {})
    issue = response_error(200, chart.get("error"))
    if issue:
        batch.errors.append(error(symbol, issue, "prices"))
        return batch
    results = chart.get("result") or []
    if not results:
        batch.errors.append(error(symbol, "no_coverage", "prices"))
        return batch
    result = results[0]
    meta = result.get("meta", {})
    currency = meta.get("currency", "")
    price = finite_number(meta.get("regularMarketPrice"))
    price_time = meta.get("regularMarketTime")
    observed = datetime.fromtimestamp(price_time, UTC).isoformat() if price_time else "unknown"
    if price is not None and price > 0:
        batch.observations.append(
            Observation(
                symbol,
                "price",
                price,
                "yahoo",
                now,
                currency=currency,
                unit="share_price",
                basis="regular_session",
                meta={"price_time": observed, "category": "prices"},
            )
        )
    try:
        tz = ZoneInfo(meta.get("exchangeTimezoneName", "America/New_York"))
    except (KeyError, ValueError):
        tz = UTC
    closes = ((result.get("indicators", {}).get("quote") or [{}])[0]).get("close", [])
    points = [
        (datetime.fromtimestamp(t, tz).date(), finite_number(v))
        for t, v in zip(result.get("timestamp", []), closes, strict=False)
    ]
    points = [(d, v) for d, v in points if v is not None and d.year == report_year - 1]
    if not points:
        return batch
    end, baseline = max(points)
    # Yahoo Close is split-adjusted but not dividend-adjusted (do not use Adj Close).
    factor = 1.0
    for split in result.get("events", {}).get("splits", {}).values():
        sd = datetime.fromtimestamp(split["date"], tz).date()
        if sd > end:
            denominator = finite_number(split.get("denominator"))
            numerator = finite_number(split.get("numerator"))
            if denominator and numerator:
                factor *= numerator / denominator
    for metric, value, basis in (
        ("year_end_raw", baseline * factor, "as_traded"),
        ("year_end_baseline", baseline, "split_adjusted_no_dividends"),
    ):
        batch.observations.append(
            Observation(
                symbol,
                metric,
                value,
                "yahoo",
                now,
                currency=currency,
                unit="share_price",
                period_end=end,
                basis=basis,
                meta={"category": "prices", "split_factor": factor},
            )
        )
    return batch


def _parse_rows(symbol, payload, now, kind):
    batch = ProviderBatch(raw={kind: payload})
    currency = payload.get("financialCurrency", "")
    unit = payload.get("shareUnit") or "unknown_share_unit"
    for row in payload.get("rows", []):
        period = normalize_period(row, payload)
        if not period:
            batch.errors.append(error(symbol, "period_unmapped", "estimates"))
            continue
        for metric in ("eps", "revenue"):
            metric_currency = row.get(f"{metric}_currency") or (
                currency if kind == "actual" else payload.get("estimate_currency", "")
            )
            value = finite_number(row.get(metric))
            basis = (
                row.get("eps_basis", row.get("basis", "undisclosed"))
                if metric == "eps"
                else "reported"
            )
            status, reason = "ok", ""
            if value is None:
                status, reason = "missing", "no_coverage"
            if not metric_currency or (
                metric == "eps" and unit not in ("common_share", "adr_share")
            ):
                value, status, reason = None, "missing", "currency_or_share_unit_unknown"
            elif period.period_type == "annual" and period.fiscal_year is None:
                status, reason = "unmapped", "fiscal_year_unmapped"
            batch.observations.append(
                Observation(
                    symbol,
                    metric,
                    value,
                    "yahoo",
                    now,
                    currency=metric_currency,
                    unit=unit if metric == "eps" else "currency",
                    period_type=period.period_type,
                    fiscal_year=period.fiscal_year,
                    period_end=period.end,
                    kind=kind,
                    basis=basis,
                    status=status,
                    reason=reason,
                    meta={
                        "category": "financials" if kind == "actual" else "estimates",
                        "period_evidence": period.evidence,
                        "analyst_count": row.get("analyst_count"),
                        "period_start": row.get("period_start"),
                    },
                )
            )
    return batch


def parse_estimates(symbol: str, payload: dict, now: datetime) -> ProviderBatch:
    return _parse_rows(symbol, payload, now, "estimate")


def parse_financials(symbol: str, payload: dict, now: datetime) -> ProviderBatch:
    return _parse_rows(symbol, payload, now, "actual")


def _unwrap(value):
    return value.get("raw") if isinstance(value, dict) else value


class YahooProvider:
    name = "yahoo"
    categories = ("prices", "financials", "estimates")

    def __init__(self, ticker_factory=None, client=None, symbol_metadata=None):
        self.ticker_factory = ticker_factory or yf.Ticker
        self.client = client or httpx.Client(
            timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
        )
        self.blocked = False
        self.blocked_code = "quota"
        self.symbol_metadata = symbol_metadata or {}

    def fetch(self, symbol, report_year, now, categories=None):
        wanted = categories if categories is not None else self.categories
        batch = ProviderBatch()
        if self.blocked:
            batch.errors.extend(error(symbol, self.blocked_code, c) for c in wanted)
            return batch
        symbol_info = self.symbol_metadata.get(symbol, {})
        query_symbol = symbol_info.get("yahoo_symbol", symbol)
        ticker = self.ticker_factory(query_symbol)
        info = {}
        # Each category is isolated so one unavailable endpoint cannot hide other data.
        for category in wanted:
            try:
                if category == "prices":
                    start = int(datetime(report_year - 1, 12, 15, tzinfo=UTC).timestamp())
                    stop = int((now + timedelta(days=1)).timestamp())
                    response = self.client.get(
                        f"https://query1.finance.yahoo.com/v8/finance/chart/{query_symbol}",
                        params={
                            "period1": start,
                            "period2": stop,
                            "interval": "1d",
                            "events": "splits",
                            "includeAdjustedClose": "false",
                        },
                    )
                    if response.status_code in (401, 403, 429):
                        self.blocked = True
                        self.blocked_code = "quota" if response.status_code == 429 else "permission"
                    response.raise_for_status()
                    part = parse_chart(symbol, response.json(), report_year, now)
                    part.observations = [
                        replace(
                            o,
                            meta={
                                **o.meta,
                                "query_symbol": query_symbol,
                                "share_unit": symbol_info.get("share_unit", "unknown_share_unit"),
                            },
                        )
                        for o in part.observations
                    ]
                else:
                    if not info:
                        info = ticker.get_info()
                    base = {
                        "financialCurrency": info.get("financialCurrency", ""),
                        "quoteType": info.get("quoteType", ""),
                        "shareUnit": symbol_info.get("share_unit", ""),
                        "estimate_currency": symbol_info.get("currency", ""),
                        "fiscal_year_convention": symbol_info.get("fiscal_year_convention"),
                        "fiscal_year_labels": symbol_info.get("fiscal_year_labels", {}),
                        "rows": [],
                    }
                    # Yahoo's quote unit can be an ADR; do not infer conversion ratios.
                    if info.get("underlyingSymbol") or "ADR" in str(info.get("longName", "")):
                        base["quoteType"] = "UNKNOWN_ADR"
                    if category == "financials":
                        table = ticker.get_income_stmt()
                        for end in table.columns:
                            row = {"endDate": str(end.date()), "period": "annual"}
                            for metric, key in (("eps", "DilutedEPS"), ("revenue", "TotalRevenue")):
                                row[metric] = table.loc[key, end] if key in table.index else None
                            base["rows"].append(row)
                        part = parse_financials(symbol, base, now)
                    else:
                        # Public yfinance tables discard endDate. Never map 0y by runtime year.
                        eps = ticker.get_earnings_estimate()
                        rev = ticker.get_revenue_estimate()
                        for period in set(eps.index) | set(rev.index):
                            base["rows"].append(
                                {
                                    "period": period,
                                    "eps": finite_number(eps.loc[period, "avg"])
                                    if period in eps.index
                                    else None,
                                    "revenue": finite_number(rev.loc[period, "avg"])
                                    if period in rev.index
                                    else None,
                                }
                            )
                        # Preserve explicit dates when the Yahoo quoteSummary endpoint is available.
                        trend = self.client.get(
                            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{query_symbol}",
                            params={"modules": "earningsTrend"},
                        )
                        response_data = trend.json() if trend.status_code == 200 else {}
                        envelope = response_data.get("quoteSummary", {}).get("error")
                        issue = response_error(trend.status_code, envelope)
                        if issue:
                            batch.errors.append(error(symbol, issue, "estimates"))
                            if issue in ("quota", "permission"):
                                self.blocked, self.blocked_code = True, issue
                        if trend.status_code == 200 and not issue:
                            data = response_data.get("quoteSummary", {}).get("result") or []
                            if data:
                                base["rows"] = [
                                    {
                                        "period": x.get("period"),
                                        "endDate": _unwrap(x.get("endDate")),
                                        "fiscalYear": _unwrap(x.get("fiscalYear")),
                                        "eps": _unwrap(x.get("earningsEstimate", {}).get("avg")),
                                        "revenue": _unwrap(x.get("revenueEstimate", {}).get("avg")),
                                        "eps_currency": x.get("earningsEstimate", {}).get(
                                            "currency"
                                        ),
                                        "revenue_currency": x.get("revenueEstimate", {}).get(
                                            "currency"
                                        ),
                                        "analyst_count": _unwrap(
                                            x.get("earningsEstimate", {}).get("numberOfAnalysts")
                                        ),
                                    }
                                    for x in data[0].get("earningsTrend", {}).get("trend", [])
                                ]
                        part = parse_estimates(symbol, base, now)
                    # Save only safe business metadata, never cookie/crumb/session state.
                    part.raw["company"] = {
                        k: info.get(k)
                        for k in ("longName", "currency", "financialCurrency", "lastFiscalYearEnd")
                    }
                batch.observations.extend(part.observations)
                batch.errors.extend(part.errors)
                # Roundtrip removes numpy scalars/NaN before immutable raw storage.
                batch.raw.update(json.loads(json.dumps(part.raw, default=str)))
            except Exception as exc:
                is_quota = "RateLimit" in type(exc).__name__
                if is_quota:
                    self.blocked = True
                    self.blocked_code = "quota"
                code = self.blocked_code if self.blocked else "network"
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                    code = "symbol_not_found"
                batch.errors.append(error(symbol, code, category))
                logging.getLogger(__name__).debug("%s %s %s", symbol, category, code)
            if self.blocked:
                for pending in wanted[wanted.index(category) + 1 :]:
                    batch.errors.append(error(symbol, self.blocked_code, pending))
                break
        return batch
