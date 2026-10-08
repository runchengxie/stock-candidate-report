# Stock candidate report

Generate a new candidate-stock growth and valuation Excel from a maintained watchlist. The original workbook is never modified. Outputs are Python-calculated snapshots with a source sheet and a JSON run manifest.

## Install and run

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js and an available `@oai/artifact-tool` runtime. The installed Codex spreadsheet runtime is detected by default; on another machine, configure `STOCK_REPORT_ARTIFACT_MODULES` (the directory containing `@oai/artifact-tool`) and `STOCK_REPORT_NODE` (Node executable). This dependency is external and is **not installed by `uv sync`**. Openpyxl is used only to read and verify files, not to generate workbooks.

```powershell
uv sync --locked
uv run stock-report import-watchlist "C:/path/to/候选股.xlsx" --workspace-config "C:/path/to/workspace.toml"
uv run stock-report generate --year 2026 --workspace-config "C:/path/to/workspace.toml"
uv run stock-report generate --year 2026 --refresh
uv run stock-report generate --year 2026 --offline
uv run stock-report generate --year 2026 --preview
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

[excel]
# artifact_modules = "C:/path/to/runtime/node_modules"
# node_executable = "C:/path/to/node.exe"

[symbols.AAA]
# When independently verified, supply financial estimate currency and EPS share unit.
currency = "USD"
share_unit = "common_share"

[symbols."700"]
yahoo_symbol = "0700.HK"
currency = "CNY"  # Financial estimate currency, not the HKD quote currency.
share_unit = "common_share"
```

Alpha Vantage is optional. Set `ALPHAVANTAGE_API_KEY` or `ALPHA_VANTAGE_API_KEY`; without one, the source is skipped and marked `not_configured`. No accounts or subscriptions are created. A persistent daily request budget is conservative and configurable; it does not guarantee the account's endpoint entitlement. Protect a settings file containing a key using OS permissions.

## Data and accounting conventions

- Yahoo regular-session price and market timestamp are separate from fetch time. Prior-year close is the last available trading date in that year. YTD uses split-adjusted, dividend-unadjusted Yahoo `Close`; the as-traded historical close is reconstructed from later split events and its baseline is separately displayed. Dividend total return is not calculated.
- Fiscal years are labelled by the year of the explicit period end, except an explicit provider fiscal-year label takes precedence. This is not a natural/calendar-year comparison. The detail sheet preserves the period end and actual/estimate status. Fiscal transitions with conflicting annual periods are not silently combined.
- Revenue is displayed in **millions of the original currency** in the summary and unscaled in detail. EPS remains per share in its original currency. ADR share units and currency conversions are not assumed.
- Yahoo's public yfinance forecast tables retain `0y/+1y/0q/+1q` but discard end dates. If explicit dates cannot be obtained from Yahoo earningsTrend, those estimates are marked `period_unmapped`, not assigned from today's year. This can substantially reduce coverage even when Yahoo displays a forecast on its website.
- Alpha Vantage annual/quarterly estimates use explicit dates. The response parser is validated against synthetic structured fixtures; account-specific response schema, permission and future-year coverage need verification with a real key. Unexpected formats are reported as `schema_unknown`. The demo key is not a substitute for a real account.
- NTM PE here means price divided by the sum of the next four **not-yet-ended fiscal quarters**. It is a quarterly approximation, not precisely day-weighted twelve months. Missing/nonconsecutive quarters, currency/share-unit/basis conflicts, or nonpositive EPS produce a blank and a specific reason. Next-year EPS is never substituted. Undisclosed EPS basis is marked unverified.
- Annual growth requires a positive base and consecutive fiscal years with compatible currency, units, basis and source. Negative EPS turning positive is marked `turnaround`, not a misleading growth percentage. GAAP actuals and adjusted/undisclosed estimates do not automatically form compatible EPS growth.
- Refresh failures may fall back to expired cache while retaining the original fetch time and failure reason. Blank is missing/not applicable, never zero. Cache-only operation makes no provider requests.

Sources: [yfinance earnings estimates](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_earnings_estimate.html), [revenue estimates](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_revenue_estimate.html), [Alpha Vantage estimates](https://www.alphavantage.co/documentation/#earnings-estimates).

## Results and diagnostics

Each run creates one `候选股-<run_id>.xlsx` (summary and input detail) and one same-named `.json`. The JSON contains every chosen input, source identifier, calculation dependency and error. Rendering and verification files are supporting outputs only. The JSON is saved before Excel export; if the external Excel runtime is missing, diagnostics survive.

Exit codes: `0` at least one stock has a price (other missing fields remain visible); `2` no prices are available, but the report and diagnostics are exported; `1` configuration/import/export error. A zero exit code does **not** mean all fields are filled. Inspect `coverage` and the detail sheet. Network denials or lack of forecast coverage are not reported as successful data acquisition.

## Development

```powershell
uv sync --locked
uv run ruff check .
uv run pytest -q
```

On hosts whose default Windows temp directory has restrictive ACLs, first create a dedicated parent under DATA_ROOT and use `--basetemp <new-child-directory>` for pytest. Tests use synthetic data, including the real export engine. Live checks are manual and must not call paid services without configured authorization.

The first live check on 2026-10-08 found Yahoo returning HTTP 429/403 and no Alpha Vantage key configured. A diagnostics workbook can be produced, but that network check is not evidence of financial data coverage.
