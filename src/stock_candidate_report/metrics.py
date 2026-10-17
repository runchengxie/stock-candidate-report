from datetime import date

from .models import MetricResult, Observation, ReportRow, WatchItem


def missing(reason: str) -> MetricResult:
    return MetricResult(None, "missing", reason)


def growth(previous: Observation, current: Observation) -> MetricResult:
    if previous.value is None or current.value is None:
        return missing("no_coverage")
    if (
        current.metric == "eps"
        and previous.kind != current.kind
        and (previous.basis == "undisclosed" or current.basis == "undisclosed")
    ):
        return missing("actual_estimate_eps_basis_unverified")
    if (previous.currency, previous.unit, previous.basis, previous.source) != (
        current.currency,
        current.unit,
        current.basis,
        current.source,
    ):
        return missing("incompatible_currency_unit_basis_or_source")
    if previous.period_type != "annual" or current.period_type != "annual":
        return missing("not_annual")
    if previous.fiscal_year is None or current.fiscal_year != previous.fiscal_year + 1:
        return missing("nonconsecutive_fiscal_year")
    if not previous.period_end or not current.period_end:
        return missing("annual_duration_unverified")
    if not 350 <= (current.period_end - previous.period_end).days <= 380:
        return missing("incomparable_annual_periods")
    for o in (previous, current):
        start = o.meta.get("period_start")
        if start and not 350 <= (o.period_end - date.fromisoformat(start)).days + 1 <= 380:
            return missing("incomparable_annual_periods")
    if previous.value <= 0:
        return MetricResult(
            None,
            "turnaround" if previous.value < 0 < current.value else "not_applicable",
            "nonpositive_base",
        )
    return MetricResult(
        current.value / previous.value - 1,
        "unverified_basis" if current.basis == "undisclosed" else "ok",
        "basis_undisclosed" if current.basis == "undisclosed" else "",
        [previous.id, current.id],
    )


def forward_four_quarter_pe(
    price: Observation, quarters: list[Observation], as_of: date
) -> MetricResult:
    if price.value is None or price.value <= 0:
        return missing("price_missing")
    qs = sorted(
        (
            q
            for q in quarters
            if q.period_end
            and q.period_end > as_of
            and q.kind == "estimate"
            and q.period_type == "quarterly"
        ),
        key=lambda q: q.period_end,
    )
    qs = qs[:4]
    if len(qs) != 4 or any(q.value is None for q in qs):
        return missing("four_future_quarters_unavailable")
    if len({q.period_end for q in qs}) != 4:
        return missing("duplicate_quarter")
    if not 1 <= (qs[0].period_end - as_of).days <= 105:
        return missing("first_future_quarter_missing")
    for a, b in zip(qs, qs[1:], strict=False):
        if not 70 <= (b.period_end - a.period_end).days <= 105:
            return missing("nonconsecutive_quarters")
        if a.meta.get("quarter_id") is not None and b.meta.get("quarter_id") is not None:
            if b.meta["quarter_id"] != a.meta["quarter_id"] + 1:
                return missing("nonconsecutive_quarters")
    signature = {(q.currency, q.unit, q.basis, q.source) for q in qs}
    if len(signature) != 1 or not qs[0].currency or qs[0].currency != price.currency:
        return missing("incompatible_currency_unit_basis_or_source")
    if qs[0].unit not in ("common_share", "adr_share"):
        return missing("share_unit_unknown")
    price_unit = price.meta.get("share_unit") or (
        price.unit if price.unit in ("common_share", "adr_share") else "unknown_share_unit"
    )
    if price_unit != qs[0].unit:
        return missing("share_unit_mismatch")
    total = sum(q.value for q in qs)
    ids = [price.id, *(q.id for q in qs)]
    if total <= 0:
        return MetricResult(None, "not_applicable", "nonpositive_forward_eps", ids)
    return MetricResult(
        price.value / total,
        "unverified_basis" if qs[0].basis == "undisclosed" else "ok",
        "basis_undisclosed" if qs[0].basis == "undisclosed" else "",
        ids,
    )


def calculate_row(
    item: WatchItem, observations: list[Observation], year: int, as_of: date
) -> ReportRow:
    obs = [o for o in observations if o.symbol == item.symbol]
    statuses = {}
    values = {}

    def assign(key, result):
        statuses[key] = result
        values[key] = result.value

    def get(metric, fy=None):
        matches = [
            o
            for o in obs
            if o.metric == metric
            and (fy is None or (o.period_type == "annual" and o.fiscal_year == fy))
        ]
        if fy is not None and len({o.period_end for o in matches}) > 1:
            return None  # A fiscal transition can produce two periods in the same end-year.
        return next((o for o in matches if o.value is not None), None)

    for key in ("price", "year_end_raw", "year_end_baseline"):
        o = get(key)
        assign(
            key, MetricResult(o.value, o.status, o.reason, [o.id]) if o else missing("no_coverage")
        )
    price, baseline = get("price"), get("year_end_baseline")
    if price and baseline and price.currency == baseline.currency and baseline.value > 0:
        assign(
            "ytd",
            MetricResult(price.value / baseline.value - 1, observation_ids=[price.id, baseline.id]),
        )
    else:
        assign("ytd", missing("price_or_year_end_missing"))
    for metric in ("eps", "revenue"):
        for fy in range(year - 1, year + 3):
            o = get(metric, fy)
            assign(
                f"{metric}_{fy}",
                MetricResult(o.value, o.status, o.reason, [o.id])
                if o
                else missing("no_coverage_or_period_unmapped"),
            )
        for fy in range(year, year + 3):
            a, b = get(metric, fy - 1), get(metric, fy)
            assign(f"{metric}_growth_{fy}", growth(a, b) if a and b else missing("no_coverage"))
    qs = [o for o in obs if o.metric == "eps" and o.period_type == "quarterly"]
    valuation = (
        missing("price_missing") if not price else missing("four_future_quarters_unavailable")
    )
    if price:
        sources = sorted(
            {q.source for q in qs}, key=lambda s: {"yahoo": 0, "alpha_vantage": 1}.get(s, 99)
        )
        for source in sources:
            candidate = forward_four_quarter_pe(price, [q for q in qs if q.source == source], as_of)
            if candidate.value is not None or candidate.status == "not_applicable":
                valuation = candidate
                break
            valuation = candidate
    assign("ntm_pe", valuation)
    values["currency"] = price.currency if price else ""
    return ReportRow(item, values, statuses)
