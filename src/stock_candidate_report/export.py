import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from .cache import clean_json
from .models import RunResult, json_value

REASONS = {
    "quota": "接口限流/配额用尽",
    "permission": "接口拒绝访问/缺少权限",
    "network": "网络请求失败",
    "no_coverage": "数据源无覆盖",
    "period_unmapped": "预期期间无法映射",
    "not_configured": "未配置密钥",
    "offline_cache_missing": "离线缓存缺失",
    "four_future_quarters_unavailable": "未来四季预期不足",
    "price_missing": "价格缺失",
    "nonpositive_base": "基数非正，增长率不适用",
    "incompatible_currency_unit_basis_or_source": "币种/单位/口径/来源不兼容",
    "schema_unknown": "供应商响应格式未验证",
    "stale": "过期缓存",
    "unverified_basis": "EPS口径未披露",
    "provider_failure": "供应商调用失败",
    "fiscal_year_unmapped": "财年标签未核验",
    "no_coverage_or_period_unmapped": "数据缺失或财年未映射",
    "price_or_year_end_missing": "价格或年末基准缺失",
    "incomparable_annual_periods": "财年变更/年度期间不可比",
    "annual_duration_unverified": "年度期间长度未核验",
    "actual_estimate_eps_basis_unverified": "实际与预期EPS口径未核验",
}


def display_reason(reason):
    for key in sorted(REASONS, key=len, reverse=True):
        reason = reason.replace(key, REASONS[key])
    return reason


def source_url(obs):
    if obs.source == "yahoo":
        section = "analysis/" if obs.kind == "estimate" else "financials/"
        if obs.metric in ("price", "year_end_raw", "year_end_baseline"):
            section = "history/"
        return (
            f"https://finance.yahoo.com/quote/{obs.meta.get('query_symbol', obs.symbol)}/{section}"
        )
    if obs.source == "alpha_vantage":
        return "https://www.alphavantage.co/documentation/#earnings-estimates"
    return ""


def sheet_payload(result: RunResult, year: int) -> dict:
    keys = ["year_end_raw", "price", "ytd", "ntm_pe"]
    keys += [f"eps_{fy}" for fy in range(year - 1, year + 3)]
    keys += [f"revenue_{fy}" for fy in range(year - 1, year + 3)]
    keys += [f"revenue_growth_{fy}" for fy in range(year, year + 3)]
    keys += [f"eps_growth_{fy}" for fy in range(year, year + 3)]
    headers = ["分组", "Symbol", "Name", f"{year - 1}年收盘价", "当前价格", "今年涨幅", "NTM PE"]
    headers += [f"FY{fy} EPS" for fy in range(year - 1, year + 3)]
    headers += [f"FY{fy} SALES" for fy in range(year - 1, year + 3)]
    headers += [f"FY{fy} SALES增长" for fy in range(year, year + 3)]
    headers += [f"FY{fy} EPS增长" for fy in range(year, year + 3)]
    headers += [
        "报价币种",
        "数据抓取时间 UTC",
        "数据状态",
        "财年结束日期/实际预期",
        "财务币种",
        "来源",
        "拆股后年末涨幅基准",
        "行情时间 UTC",
    ]
    rows = []
    for row in result.rows:
        obs = [o for o in result.observations if o.symbol == row.item.symbol]
        annual = [o for o in obs if o.period_type == "annual"]
        dates = sorted(
            {
                f"FY{o.fiscal_year or '未映射'}:{o.period_end} "
                f"{'实际' if o.kind == 'actual' else '预期'}"
                for o in annual
            }
        )
        missing = sum(s.value is None for s in row.statuses.values())
        stale = any(o.status == "stale" for o in obs)
        errors = sorted({e["code"] for e in result.errors if e["symbol"] == row.item.symbol})
        status = ("过期缓存；" if stale else "") + f"{missing}项缺失"
        if errors:
            status += "；" + display_reason(", ".join(errors))
        if any(s.status == "unverified_basis" for s in row.statuses.values()):
            status += "；EPS口径未披露"
        vals = [row.values.get(k) for k in keys]
        vals = [
            v / 1_000_000
            if k.startswith("revenue_") and "_growth_" not in k and v is not None
            else v
            for k, v in zip(keys, vals, strict=True)
        ]
        rows.append(
            [
                row.item.group,
                row.item.symbol,
                row.item.name,
                *vals,
                row.values.get("currency", ""),
                max((o.fetched_at.isoformat() for o in obs), default=""),
                status,
                "; ".join(dates),
                ",".join(sorted({o.currency for o in annual})),
                ",".join(sorted({o.source for o in obs})),
                row.values.get("year_end_baseline"),
                next((o.meta.get("price_time", "") for o in obs if o.metric == "price"), ""),
            ]
        )
    width = len(headers)

    def line(text):
        return [text] + [None] * (width - 1)

    summary = [
        line(""),
        line(f"候选股增长和估值（{year}）"),
        line("NTM PE：四个未来财季EPS合计的滚动近似；FY须经来源或配置核验；SALES：百万原币"),
        line(
            f"股票 {len(rows)}；价格可用 {result.coverage.get('prices_available', 0)}；"
            "空白表示缺失或不适用。逐项原因见数据明细。"
        ),
        headers,
        *rows,
    ]
    formats = {i: '#,##0.00;(#,##0.00);"–"' for i in range(3, 15)}
    formats.update({5: '0.0%;(0.0%);"–"', **{i: '0.0%;(0.0%);"–"' for i in range(15, 21)}})
    formats[6] = '0.0"x"'
    detail_headers = [
        "Symbol",
        "指标",
        "数值",
        "单位",
        "币种",
        "FY",
        "期间结束日期",
        "实际/预期",
        "EPS/财务口径",
        "来源",
        "抓取时间 UTC",
        "预期发布日",
        "数据状态",
        "原因",
        "来源网址",
        "数据ID",
        "原始响应ID",
        "行情时间 UTC",
    ]
    details = []
    for o in result.observations:
        details.append(
            [
                o.symbol,
                o.metric,
                o.value,
                o.unit,
                o.currency,
                o.fiscal_year,
                o.period_end.isoformat() if o.period_end else "",
                o.kind,
                o.basis,
                o.source,
                o.fetched_at.isoformat(),
                o.estimate_date or "",
                o.status,
                display_reason(o.reason),
                source_url(o),
                o.id,
                o.meta.get("cache_response_id", ""),
                o.meta.get("price_time", ""),
            ]
        )
    for row in result.rows:
        for key, metric in row.statuses.items():
            details.append(
                [
                    row.item.symbol,
                    key,
                    metric.value,
                    "calculated",
                    "",
                    None,
                    "",
                    "calculation",
                    "",
                    "Python",
                    "",
                    "",
                    metric.status,
                    display_reason(metric.reason),
                    "",
                    ",".join(metric.observation_ids),
                    "",
                    "",
                ]
            )
    dwidth = len(detail_headers)
    detail = [
        [t] + [None] * (dwidth - 1)
        for t in (
            "",
            "输入来源和计算明细",
            "日期与口径按供应商提供值保留；未披露EPS口径不代表已核验；计算值未缩放。",
            "原始响应和运行清单用于核对；过期缓存保留原抓取时间。",
        )
    ]
    detail += [detail_headers, *details]
    return {
        "sheets": [
            {
                "name": "增长和估值",
                "rows": summary,
                "formats": formats,
                "date_columns": [22, 28],
                "widths": {
                    0: 18,
                    1: 12,
                    2: 36,
                    21: 12,
                    22: 29,
                    23: 55,
                    24: 65,
                    25: 12,
                    26: 20,
                    27: 23,
                    28: 29,
                },
            },
            {
                "name": "数据明细",
                "rows": detail,
                "formats": {2: "#,##0.00", 5: "0"},
                "date_columns": [6, 10, 11, 17],
                "widths": {
                    0: 12,
                    1: 27,
                    3: 24,
                    6: 20,
                    8: 24,
                    9: 20,
                    10: 29,
                    11: 22,
                    12: 22,
                    13: 70,
                    14: 65,
                    15: 36,
                    16: 36,
                    17: 29,
                },
            },
        ]
    }


def export_report(
    result: RunResult,
    year: int,
    output_dir: Path,
    artifact_modules: Path | None = None,
    node_executable: str | None = None,
    preview: bool = False,
) -> tuple[Path, Path]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", result.run_id):
        raise ValueError("Invalid run_id")
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"候选股-{result.run_id}"
    xlsx, manifest = output_dir / f"{filename}.xlsx", output_dir / f"{filename}.json"
    if xlsx.exists() or manifest.exists():
        raise FileExistsError(filename)
    # Manifest is the first committed artifact: preserve diagnostics even if Excel export fails.
    data = clean_json(json_value(result))
    data["report_year"] = year
    payload = json.dumps(data, default=json_value, ensure_ascii=False, allow_nan=False, indent=2)
    temp_manifest = output_dir / f".{filename}-{uuid4().hex}.json.tmp"
    temp_manifest.write_text(payload, encoding="utf-8")
    try:
        os.link(temp_manifest, manifest)
    finally:
        temp_manifest.unlink(missing_ok=True)
    dependencies = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    modules = artifact_modules or Path(
        os.environ.get("STOCK_REPORT_ARTIFACT_MODULES", str(dependencies / "node_modules"))
    )
    node = node_executable or os.environ.get("STOCK_REPORT_NODE") or shutil.which("node")
    if not (modules / "@oai/artifact-tool").is_dir() or not node:
        raise RuntimeError(
            "Excel artifact runtime unavailable; set STOCK_REPORT_ARTIFACT_MODULES "
            "and STOCK_REPORT_NODE. JSON diagnostics were saved."
        )
    runtime = output_dir / ".export-runtime" / uuid4().hex
    runtime.mkdir(parents=True)
    link = runtime / "node_modules"
    if not link.exists():
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link.resolve()), str(modules.resolve())],
                check=True,
                capture_output=True,
            )
        else:
            link.symlink_to(modules.resolve(), target_is_directory=True)
    elif link.resolve() != modules.resolve():
        raise RuntimeError("Excel artifact runtime points to a different module directory")
    script = runtime / "export_workbook.mjs"
    shutil.copyfile(Path(__file__).with_name("export_workbook.mjs"), script)
    bridge = runtime / f"{result.run_id}.json"
    bridge.write_text(json.dumps(sheet_payload(result, year), ensure_ascii=False), encoding="utf-8")
    temp_xlsx = output_dir / f".{filename}-{uuid4().hex}.xlsx"
    proc = subprocess.run(
        [node, str(script), str(bridge), str(temp_xlsx), "preview" if preview else "no-preview"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if proc.returncode:
        log = output_dir / f"{filename}.export-error.txt"
        log.write_text(proc.stderr[-6000:], encoding="utf-8")
        raise RuntimeError(f"Excel artifact export failed; see {log}")
    os.link(temp_xlsx, xlsx)
    temp_xlsx.unlink()
    # Verification/render files remain supporting artifacts, never final workbook variants.
    for sidecar in output_dir.glob(temp_xlsx.name + ".*"):
        sidecar.rename(output_dir / (filename + sidecar.name[len(temp_xlsx.name) :]))
    return xlsx, manifest
