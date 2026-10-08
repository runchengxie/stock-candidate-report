from datetime import UTC, date, datetime

import openpyxl

from stock_candidate_report.cache import Cache
from stock_candidate_report.export import export_report
from stock_candidate_report.models import Observation, ProviderBatch, WatchItem
from stock_candidate_report.pipeline import run_report


def test_synthetic_report_reconciles_independent_numbers(tmp_path):
    now = datetime(2026, 10, 8, tzinfo=UTC)

    class Synthetic:
        name = "synthetic"
        categories = ("prices",)

        def fetch(self, symbol, report_year, now, categories=None):
            observations = [
                Observation("AAA", "price", 100, self.name, now, currency="USD"),
                Observation("AAA", "year_end_baseline", 80, self.name, now, currency="USD"),
            ]
            for fy, value in [(2025, 100), (2026, 125)]:
                observations.append(
                    Observation(
                        "AAA",
                        "revenue",
                        value * 1_000_000,
                        self.name,
                        now,
                        currency="USD",
                        unit="currency",
                        basis="reported",
                        period_type="annual",
                        fiscal_year=fy,
                        period_end=date(fy, 12, 31),
                    )
                )
            for value, end in [
                (1, date(2026, 12, 31)),
                (2, date(2027, 3, 31)),
                (3, date(2027, 6, 30)),
                (4, date(2027, 9, 30)),
            ]:
                observations.append(
                    Observation(
                        "AAA",
                        "eps",
                        value,
                        self.name,
                        now,
                        currency="USD",
                        unit="common_share",
                        basis="adjusted",
                        kind="estimate",
                        period_type="quarterly",
                        period_end=end,
                    )
                )
            return ProviderBatch(observations)

    result = run_report(
        [WatchItem("AAA")], 2026, now, False, False, [Synthetic()], Cache(tmp_path / "cache.sqlite")
    )
    assert result.rows[0].values["ntm_pe"] == 10
    assert result.rows[0].values["ytd"] == 0.25
    assert result.rows[0].values["revenue_growth_2026"] == 0.25
    output, _ = export_report(result, 2026, tmp_path)
    book = openpyxl.load_workbook(output, data_only=True)
    assert book["增长和估值"]["G6"].value == 10
    assert book["增长和估值"]["P6"].value == 0.25
    assert book["数据明细"].max_row >= 10
