# Stock Candidate Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 从候选清单生成可追溯的美股增长和估值 Excel。
**Architecture:** Python 数据适配器获取行情、财报和一致预期，标准化后存入 SQLite。纯计算模块生成报告快照，Excel 和 JSON 导出共享同一运行数据。
**Tech Stack:** Python 3.12+, uv, yfinance, httpx, SQLite, pytest, ruff；Excel 读写引擎在执行时按表格技能确认可用性，使用明确、可复现的依赖，不隐式依赖开发机器。
**Spec:** 2026-10-08-stock-candidate-report-design.md（同目录，已由用户批准）

## Global Constraints

- 独立 stock-candidate-report，不修改现有量化项目。
- Python 3.12+，uv 管理依赖；源码仅合成数据。
- 通过 workspace.toml 或显式环境配置解析根路径；数据在 DATA_ROOT/stock-candidate-report，个人配置在 CONFIG_ROOT/projects/stock-candidate-report。
- 免费优先，不购买数据、不注册账号；没有凭证时跳过相应适配器。
- 当前价格为常规时段；涨幅拆股一致且不含股息；财年、币种、实际与预期清楚标注。
- NTM 使用未来四个连续尚未结束财季，口径不兼容或数据不足时留空并解释。
- 价格 1 小时、预期 7 天、财务 1 天 TTL；有过期缓存时可回退并明确标记。
- Excel 是 Python 计算后的快照，原始输入不覆盖；报告和 JSON 使用时间戳及原子写入。

## Review Focus

1. 非十二月财年及 52/53 周财年不能按月份或运行年份强行贴标签：任务 2 测试。
2. 无效 Symbol、合并分组与尾注不能被错误请求或丢失：任务 1 测试。
3. API 在 HTTP 200 返回限流或权限错误仍需诊断，API key 不能泄漏：任务 3 测试。
4. 并发运行与同秒输出不得覆盖缓存或报告：任务 4、6 测试。
5. 离线或刷新失败不能把过期时间改成现在，也不能将缺失转零：任务 4、6 测试。

## 文件与接口

src/stock_candidate_report/{cli,config,watchlist,models,normalize,cache,metrics,pipeline,export}.py 各负责命令、路径、清单、记录、期间映射、缓存、计算、编排和输出。
providers/{base,yahoo,alpha_vantage}.py 负责供应商接口。tests/ 对应模块；README.md、AGENTS.md、pyproject.toml、uv.lock 和 docs/superpowers/{specs,plans}/ 为开发与交付契约。

共享不可变类型：WatchItem(symbol,name,group)、Observation(id,symbol,metric,value,currency,unit,period_type,fiscal_year,period_end,kind,basis,source,fetched_at,estimate_date,status,reason)、ProviderBatch(observations,errors,raw)、ReportRow(item,values,statuses)、RunResult(run_id,rows,observations,errors,coverage)。时间采用带时区 UTC，period_end 采用 date；value 为有限数值或 None。

### Task 1: 可安装项目、根配置与股票清单

**Files:** pyproject.toml, AGENTS.md, src/stock_candidate_report/{cli,config,watchlist,models}.py, tests/test_watchlist.py, tests/test_config.py。
**Interfaces:** load_roots(settings_path: Path | None, overrides: dict[str,str]) -> Roots；import_watchlist(path: Path) -> list[WatchItem]；save_watchlist(items: list[WatchItem], path: Path) -> None。

- [x] 在执行批准后创建独立 Git 仓库、任务分支与隔离 worktree；先归档批准的设计和计划，写 AGENTS.md，按共享标准维护源码/配置/数据边界。
- [x] 编写测试 test_import_groups_and_duplicates：合并组内两只股票继承分组；尾注与空行不入清单；重复 GOOG 抛出含两个行号的异常；输入文件字节保持不变。
- [x] 编写 test_roots_and_watchlist_paths：TOML 指定的数据路径正确；环境覆盖生效；缺失配置给出可操作错误，源码不得退回机器绝对路径。
- [x] 运行 uv run pytest tests/test_watchlist.py tests/test_config.py -q，确认因实现缺失失败。
- [x] 实现上述接口、CLI import-watchlist，股票 Symbol 字符集允许点和连字符，非法文本返回行级错误；清单保存到配置目录，不覆盖已有文件除非显式参数。
- [x] 同命令验证通过，uv run ruff check . 通过后提交 feat: import candidate watchlist and resolve workspace roots。

### Task 2: 标准化财年与供应商契约

**Files:** models.py, normalize.py, providers/base.py, tests/test_normalize.py。
**Interfaces:** Provider.fetch(symbol: str, report_year: int, now: datetime) -> ProviderBatch；normalize_period(raw: dict, metadata: dict) -> Period | None；select_observations(batches: list[ProviderBatch]) -> list[Observation]。

- [x] 编写 test_fiscal_period_mapping：明确结束日期的六月 FY2026 正确映射；0y 缺少实际财年锚点时返回 None；52/53 周的明确 FY 标签被保留；推断字段标明依据。
- [x] 编写 test_source_and_units：有限数值保留，NaN/Inf 变为 missing；实际优先覆盖同期间预期，来源选择固定；不同 EPS basis 不伪装相同；货币和 ADR 单位未知时记录原因。
- [x] uv run pytest tests/test_normalize.py -q，确认失败。
- [x] 实现共享类型和期间映射，保留原始提供值及映射证据；不给缺失日期编造日期。
- [x] 同命令及 ruff 验证通过，提交 feat: normalize fiscal observations and provenance。

### Task 3: Yahoo 与可选 Alpha Vantage 数据适配器

**Files:** providers/{yahoo,alpha_vantage}.py, tests/test_yahoo.py, tests/test_alpha_vantage.py。
**Interfaces:** YahooProvider.fetch 和 AlphaVantageProvider.fetch 遵守 Task 2 契约；构造参数接受可替换 transport/client、超时和配额；所有 API key 只从配置加载。

- [x] 测试 test_yahoo_regular_price_and_estimates：盘后价格不能替代常规报价；历史价区分原始与拆股一致序列；年度/季度预期使用明确期间日期；缺字段不崩溃。
- [x] 测试 test_alpha_response_errors：HTTP 200 的 Information/Note/Error Message 分类为权限、配额或代码错误；权限不重试，可重试网络失败最多三次；异常和存档中不出现测试 secret。
- [x] 测试 test_estimate_coverage：合成年度和季度响应均保留来源、analyst count 等可用元数据；无 key 时跳过；不因为端点存在就宣称 2028 有覆盖。
- [x] uv run pytest tests/test_yahoo.py tests/test_alpha_vantage.py -q，确认失败。
- [x] 先阅读当前官方 yfinance 和 Alpha Vantage 字段定义，以无凭证 Yahoo 小样本验证真实格式；实现适配器，原始响应存档剔除敏感字段。Yahoo 自身异常仅输出清洗过的结构化信息。
- [x] 同命令及 ruff 验证通过，提交 feat: fetch market data and optional analyst estimates。

### Task 4: SQLite 缓存与运行编排

**Files:** cache.py, pipeline.py, tests/test_cache.py, tests/test_pipeline.py。
**Interfaces:** Cache.get(key: str, now: datetime, ttl: timedelta) -> CacheEntry | None；Cache.put(key: str, batch: ProviderBatch) -> None；run_report(items: list[WatchItem], year: int, now: datetime, refresh: bool, offline: bool, providers: list[Provider], cache: Cache) -> RunResult。

- [x] test_ttl_boundaries：3600 秒价格到期；604800 秒预期到期；86400 秒财务到期；允许配置覆盖。
- [x] test_offline_and_fallback：offline 不触发网络；刷新失败回退缓存并保留原 fetched_at、stale、失败原因；没有缓存产生 missing；一股失败其他股继续。
- [x] test_cache_concurrency_and_quota：两个独立数据库连接写入不会损坏，超过供应商配额不继续请求；同日预算跨运行保存；未来 fetched_at 标记异常而非永久有效。
- [x] uv run pytest tests/test_cache.py tests/test_pipeline.py -q，确认失败。
- [x] 使用事务、busy timeout 和稳定缓存键，分别缓存行情/财务/预期，运行 ID 使用 UTC 加随机后缀；不可变响应与 observation ID 进入清单。网络日志不输出完整带凭证 URL。
- [x] 同命令及 ruff 验证通过，提交 feat: cache observations and preserve refresh diagnostics。

### Task 5: 涨幅、年度增长及未来四财季 PE

**Files:** metrics.py, tests/test_metrics.py。
**Interfaces:** calculate_row(item: WatchItem, observations: list[Observation], year: int, as_of: date) -> ReportRow；growth(previous: Observation, current: Observation) -> MetricResult；forward_four_quarter_pe(price: Observation, quarters: list[Observation], as_of: date) -> MetricResult。

- [x] test_growth_and_turnaround：营收 100→125 等于 .25；EPS -1→2 结果百分比 None 且状态 turnaround；零基数不除零；币种或 basis 冲突返回 missing。
- [x] test_split_consistent_ytd：原始上年价 100、2:1 拆股后基准 50、当前价 60 得 .20；展示原始上年价仍为 100；无 IPO 前价格则涨幅缺失。
- [x] test_four_future_quarters：四个连续未来季度 EPS 1+2+3+4、价格 100 得 PE 10；少季、重复、跳季、已结束财季、不同币种或 basis 均不得得到 PE；非正 EPS 标 not_applicable。季度校验支持明确的 52/53 周日历，不仅判断固定 90 天。
- [x] uv run pytest tests/test_metrics.py -q，确认失败。
- [x] 实现纯函数和字段状态，不外推缺失季度，不混合年预测替代 NTM；同源未披露口径仍明确标注未核验。
- [x] 同命令及 ruff 验证通过，提交 feat: calculate growth and rolling four-quarter valuation。

### Task 6: Excel 快照、CLI 与真实运行交付

**Files:** export.py, cli.py, README.md, tests/test_export.py, tests/test_cli.py, tests/test_end_to_end.py。
**Interfaces:** export_report(result: RunResult, year: int, output_dir: Path) -> tuple[Path,Path]；CLI generate --year --refresh --offline --workspace-config --watchlist；缺少所有价格退出 2，成功或部分成功退出 0。

- [x] test_export_snapshot：两张表名为“增长和估值”“数据明细”；随报告年生成表头；数值为数值，缺失为空而不是零；来源/实际预期/期间日期/币种/过期状态可核对，四财季近似说明可见；JSON 与 Excel 使用相同 run_id 和 observation IDs。
- [x] test_atomic_and_collision：写入失败不产生完整成品，同秒运行输出不同文件；输入绝不覆盖；用户提供名称或分组以 = 开头也不变成 Excel 公式。
- [x] test_cli_and_end_to_end：合成行情、财报、四季预测生成 PE 10 和增长 .25；offline 为零网络请求；全部价格缺失仍输出 JSON 诊断并退出 2。
- [x] uv run pytest tests/test_export.py tests/test_cli.py tests/test_end_to_end.py -q，确认失败。
- [x] 根据表格技能支持的引擎实现导出，冻结表头、筛选、百分比格式和合理列宽；README 写完整安装、导入、生成、刷新、离线、配置密钥与缺失诊断命令；库依赖写入 uv.lock。
- [x] uv sync --locked；uv run ruff check .；uv run pytest -q，全部通过。运行 --help 与实际命令检查用户入口。
- [x] 导入真实候选表到个人配置目录，免费接口运行一次到数据目录；按成功/缺失/失败/缓存统计覆盖，选不同财年代表股票独立核对，检查 Excel 可读性；无 key 的接口明确跳过。
- [x] 提交 feat: export candidate report and document reproducible workflow；对整个分支做独立审阅，修复实质问题并复验。依共享工作区流程验证远端归属，若有对应用户仓库走 PR；新项目无远端时保留已提交本地仓库并明确报告，不编造 PR。

## 自审与执行交接

设计的输入、口径、缓存、诊断、输出和真实运行分别由任务 1–6 覆盖；Review Focus 均有具体测试。新仓库目前未建立，计划与设计暂存在 DATA_ROOT 的 design 目录，执行后归档到 docs/superpowers/plans/2026-10-08-stock-candidate-report.md。

推荐 Native：由主 agent 在本会话按顺序实现六个任务，完成后进行一次独立审阅。模块依赖紧密且必须先验证免费数据覆盖，逐任务完整分派增加协调成本。实施前请用户审阅计划并选择 Native 或 Subagent-driven。

