# 候选股自动报告

从股票清单获取行情、财务和可用分析师预期，计算增长与估值，默认生成可追溯的 JSON，可选额外导出 Excel。原 Excel 不会被覆盖。

## 使用

只需 Python 3.12+ 和 uv。默认 JSON 输出不依赖 Excel 库、Node.js 或 Codex 私有运行环境。Excel 是可选依赖，使用 openpyxl。

```powershell
uv sync --locked
uv run stock-report import-watchlist "C:/path/to/候选股.xlsx"
uv run stock-report generate --year 2026
uv run stock-report generate --year 2026 --refresh
uv run stock-report generate --year 2026 --offline
# 可选 Excel 输出
uv sync --extra excel
uv run --extra excel stock-report generate --year 2026 --excel
```

也可直接在个人配置目录创建 `watchlist.json`，例如 `[{"symbol":"AAA","name":"合成示例","group":"示例"}]`，无需先导入 Excel。AAA 是占位示例，不代表投资建议。

已导入清单时，直接运行 `generate`。清单可以在个人配置目录的 `watchlist.json` 中增删。导入命令拒绝覆盖现有清单，可用 `--output` 指定另一个文件。

项目读取机器的 `workspace.toml`。可通过 `--workspace-config` 或 `STOCK_REPORT_WORKSPACE_CONFIG` 显式指定。源码属于 CODE_ROOT；缓存、原始响应和报告属于 DATA_ROOT/stock-candidate-report；清单与 settings.toml 属于 CONFIG_ROOT/projects/stock-candidate-report。

输出在数据目录的 `outputs/<运行ID>/`。默认只有 JSON，保留输入 ID、来源、日期、计算依赖和失败原因。加 `--excel` 后额外生成 XLSX，第一张为“增长和估值”，第二张为“数据明细”。Excel 是运行快照，手工修改单元格不会更新 Python 计算结果。Excel 依赖缺失或导出失败时，已生成的 JSON 仍保留。

旧版 `--preview`、`[excel]` 运行环境配置及 Node/artifact-tool 桥接已移除；财务计算和 JSON 结构不变。

## 数据与限制

- Yahoo 用于行情与财务；Alpha Vantage 预期接口是可选补充，通过本地配置或环境变量 `ALPHAVANTAGE_API_KEY` 设置密钥。程序不注册账号、不购买数据。
- 财年标签、预测币种和每股单位必须由来源或经核验的配置确定；无法确认时相应汇总字段留空。港股可以保留原表代码，通过 `yahoo_symbol` 映射数据源代码。ADR 不假设与普通股单位相同。
- SALES 汇总以百万原币显示，明细保留未缩放值。YTD 不含股息，并使用一致的拆股基准。
- NTM PE 使用未来四个尚未结束的连续财季 EPS 合计；缺少季度、口径冲突或合计非正时不计算，不用下一年 EPS 替代。
- EPS 的实际与预测口径未经核验时不计算两者增长率。亏损转盈利标为扭亏。财年变更产生的短年度不按正常年度增长计算。
- 缓存默认有效期：行情 1 小时、财务 1 天、预期 7 天。刷新缺少部分字段时保留旧字段及原时间，明确显示回退；离线模式不请求数据源。
- 本机真实连接测试遇到 Yahoo 拒绝访问，且未配置 Alpha Vantage 密钥。代码和离线流程通过测试，但这不能证明已获得实时数据或覆盖远期预期。完整覆盖需要数据源恢复访问并验证账户权限和返回格式。

退出码 0 表示至少一只股票有价格，仍须检查缺失字段；2 表示全部价格缺失，但诊断已导出；1 表示配置、导入或导出错误。

完整配置示例和财年映射规则见 [英文 README](README.md)。

## 开发与开源

```powershell
uv sync --locked
uv run ruff check .
uv run pytest -q
uv sync --locked --extra excel
uv run --extra excel pytest -q
uv build
```

测试使用合成数据并禁用网络连接。基础安装跳过 Excel 专项测试；安装 excel extra 后运行全部测试。CI 覆盖 Linux/Windows、纯 JSON 和含 Excel 的安装，并执行代码检查、测试与打包，无需 API 密钥。

原创代码采用 MIT 许可证，见 [LICENSE](LICENSE)。许可证不授予第三方金融数据的使用或再分发权，数据使用需遵守供应商条款。真实候选清单、密钥、缓存和报告应保留在仓库外。历史设计文档描述旧实现，当前行为以 README 和 CLI 为准。
