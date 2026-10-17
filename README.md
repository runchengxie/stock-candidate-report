# Stock candidate report

[![CI](https://github.com/runchengxie/stock-candidate-report/actions/workflows/ci.yml/badge.svg)](https://github.com/runchengxie/stock-candidate-report/actions/workflows/ci.yml)

[中文使用说明](README.zh-CN.md)

Generate traceable candidate-stock growth and valuation JSON snapshots from a maintained watchlist. Excel is an optional additional output. The original input workbook is never modified. Every snapshot retains input observations, sources, timestamps, calculation dependencies and missing-data reasons.

## Install and run

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/). JSON output needs no Excel library, Node.js, Codex installation or private runtime.

```powershell
uv sync --locked
uv run stock-report import-watchlist "C:/path/to/候选股.xlsx" --workspace-config "C:/path/to/workspace.toml"
uv run stock-report generate --year 2026 --workspace-config "C:/path/to/workspace.toml"
uv run stock-report generate --year 2026 --refresh
uv run stock-report generate --year 2026 --offline
uv sync --extra excel
uv run --extra excel stock-report generate --year 2026 --excel
```

You can also create `watchlist.json` directly in your private configuration directory, without an Excel input. This synthetic example shows the format (AAA is a placeholder, not a recommendation):

```json
[{"symbol": "AAA", "name": "Synthetic company", "group": "Example"}]
```

After the first import, change `watchlist.json` to add/remove stocks or groups. Imports refuse to overwrite an existing watchlist; use `--output` to choose another filename. `generate --watchlist <file>` selects another JSON list. `--refresh` and `--offline` cannot be combined. Omit `--year` for the UTC runtime year; an explicit year only controls displayed columns and the year-end price baseline, **not** a historical point-in-time forecast reconstruction.

## Paths and personal configuration

Read the explicit machine-local workspace TOML, or set `STOCK_REPORT_WORKSPACE_CONFIG`:

```toml
code_root = "C:/path/to/code"
data_root = "D:/path/to/data"
config_root = "C:/path/to/private-config"
```

`CODE_ROOT`, `DATA_ROOT`, `CONFIG_ROOT` environment variables override the corresponding roots. Watchlists and `settings.toml` live under `CONFIG_ROOT/projects/stock-candidate-report/`. The SQLite cache, immutable responses and timestamped `outputs/<run_id>/` live under `DATA_ROOT/stock-candidate-report/`, including when running from a worktree. Keep all real data and keys outside Git.

Optional `settings.toml`:

```toml
[ttl_seconds]
prices = 3600
financials = 86400
estimates = 604800

[alpha_vantage]
daily_limit = 25
# api_key = "..."  # Prefer ALPHAVANTAGE_API_KEY in the environment.

[symbols.AAA]
# When independently verified, supply financial estimate currency and EPS share unit.
currency = "USD"
share_unit = "common_share"
# Set only after confirming the issuer labels fiscal years by their end year.
fiscal_year_convention = "end_year"
# For 52/53-week calendars or nonstandard labels, use explicit verified date mappings:
# fiscal_year_labels = { "2027-01-02" = 2026, "2027-12-31" = 2027 }

[symbols."700"]
yahoo_symbol = "0700.HK"
currency = "CNY"  # Financial estimate currency, not the HKD quote currency.
share_unit = "common_share"
```

Alpha Vantage is optional. Set `ALPHAVANTAGE_API_KEY` or `ALPHA_VANTAGE_API_KEY`; without one, the source is skipped and marked `not_configured`. No accounts or subscriptions are created. A persistent daily request budget is conservative and configurable; it does not guarantee the account's endpoint entitlement. Protect a settings file containing a key using OS permissions.

## Data and accounting conventions

- Yahoo regular-session price and market timestamp are separate from fetch time. Prior-year close is the last available trading date in that year. YTD uses split-adjusted, dividend-unadjusted Yahoo `Close`; the as-traded historical close is reconstructed from later split events and its baseline is separately displayed. Dividend total return is not calculated.
- Fiscal labels must come from the provider or independently verified per-symbol configuration (`fiscal_year_labels` or `fiscal_year_convention = "end_year"`). A date alone does **not** establish the issuer's FY label. Unmapped dates/values remain visible in detail and the raw archive, while FY summary columns remain blank. This is especially important for 52/53-week calendars. Fiscal transitions and annual end-date gaps outside 350–380 days are excluded from annual growth; known start dates also establish full-year duration.
- Revenue is displayed in **millions of the original currency** in the summary and unscaled in detail. Forecast currency is taken from metric-level source fields or verified per-symbol configuration; company financial currency is not automatically used for analyst forecasts. EPS/share units must be verified through configuration or source metadata; `EQUITY` alone is not proof of common shares. ADR ratios and currency conversions are not assumed. Yahoo EPS accounting basis is unverified unless supplied explicitly.
- Yahoo's public yfinance forecast tables retain `0y/+1y/0q/+1q` but discard end dates. If explicit dates cannot be obtained from Yahoo earningsTrend, those estimates are marked `period_unmapped`, not assigned from today's year. This can substantially reduce coverage even when Yahoo displays a forecast on its website.
- Alpha Vantage annual/quarterly estimates use explicit dates. The response parser is validated against synthetic structured fixtures; account-specific response schema, permission and future-year coverage need verification with a real key. Unexpected formats are reported as `schema_unknown`. The demo key is not a substitute for a real account.
- NTM PE here means price divided by the sum of the next four **not-yet-ended fiscal quarters**. It is a quarterly approximation, not precisely day-weighted twelve months. Missing/nonconsecutive quarters, currency/share-unit/basis conflicts, or nonpositive EPS produce a blank and a specific reason. Next-year EPS is never substituted. Undisclosed EPS basis is marked unverified.
- Annual growth requires a positive base and consecutive full fiscal years with compatible currency, units, basis and source. Negative EPS turning positive is marked `turnaround`, not a misleading growth percentage. Actual versus forecast EPS with undisclosed basis is not compared; verified GAAP and adjusted EPS cannot be mixed.
- Partial refreshes merge by observation identity and retain missing cached fields with original timestamps and response IDs. Freshness is evaluated per field; an incomplete refresh cannot renew old fields. Older concurrent writes cannot overwrite newer cache entries. Blank is missing/not applicable, never zero. Cache-only operation makes no provider requests. Aliases and normalization settings participate in cache identity.

Sources: [yfinance earnings estimates](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_earnings_estimate.html), [revenue estimates](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_revenue_estimate.html), [Alpha Vantage estimates](https://www.alphavantage.co/documentation/#earnings-estimates).

## Results and diagnostics

Each run creates `候选股-<run_id>.json`. With `--excel`, it also creates a same-named `.xlsx` containing summary and input-detail sheets. The JSON contains every chosen input, source identifier, calculation dependency and error. JSON is saved first; if the optional Excel dependency is missing or export fails, JSON diagnostics survive. Install the extra with `uv sync --extra excel` (or `pip install ".[excel]"`). CLI output includes `manifest`, `coverage` and `excel` (null unless requested). Output files are create-only.

Migration from the original local implementation: `--preview`, `[excel]` runtime settings, `STOCK_REPORT_ARTIFACT_MODULES`, and `STOCK_REPORT_NODE` have been removed. Excel now uses openpyxl; there is no Node/artifact-tool bridge. JSON structure and financial calculations are unchanged.

Exit codes: `0` at least one stock has a price (other missing fields remain visible); `2` no prices are available, but JSON diagnostics (and Excel if requested) are exported; `1` configuration/import/export error. A zero exit code does **not** mean all fields are filled. Inspect `coverage` and the detail sheet. Network denials or lack of forecast coverage are not reported as successful data acquisition.

## Development

```powershell
uv sync --locked
uv run ruff check .
uv run pytest -q
uv sync --locked --extra excel
uv run --extra excel pytest -q
uv build
```

When workspace settings are available, the test harness places temporary artifacts in a unique child of DATA_ROOT/stock-candidate-report/test-tmp, avoiding host Windows temp ACL issues. An explicit `--basetemp` takes precedence. CI without personal settings uses pytest's normal temp directory. Tests use synthetic data and disable network sockets through pytest-socket. Without the Excel extra, the two Excel integration modules and the Excel CLI case skip; all JSON, provider, cache and calculation tests run. With the extra installed, all tests run, including XLSX creation, typed-cell checks, formula safety, timestamp handling and end-to-end calculations. GitHub Actions covers JSON-only and Excel installs on Linux/Windows with Python 3.12, plus Excel on Python 3.14; it also runs Ruff and builds distributions. CI needs no credentials or live financial data. Live checks are manual and must not call paid services without configured authorization.

The first live check on 2026-10-08 found Yahoo returning HTTP 429/403 and no Alpha Vantage key configured. A diagnostics workbook can be produced, but that network check is not evidence of financial data coverage.

## License and data sources

Original project code is MIT licensed; see [LICENSE](LICENSE). Dependencies retain their own licenses. This license grants no rights to Yahoo, Alpha Vantage or other providers’ data, branding or services. Review each provider’s terms and your account permissions before retrieving, using or redistributing data. No provider data, private watchlists, credentials or generated reports are included. This tool does not provide investment recommendations.

The design and implementation records under `docs/superpowers/` describe the original local version; where they mention artifact-tool or mandatory Excel, the current README and CLI take precedence.
