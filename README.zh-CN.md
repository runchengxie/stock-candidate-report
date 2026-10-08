# 候选股自动报告

从股票清单获取行情、财务和可用分析师预期，计算增长与估值，生成 Excel 和可追溯的 JSON。原 Excel 不会被覆盖。

## 使用

需要 Python 3.12+、uv、Node.js，以及可用的 `@oai/artifact-tool` 表格运行环境。当前机器已有该运行环境；换机器时必须单独配置，`uv sync` 不会安装它。

```powershell
uv sync --locked
uv run stock-report import-watchlist "C:/path/to/候选股.xlsx"
uv run stock-report generate --year 2026
uv run stock-report generate --year 2026 --refresh
uv run stock-report generate --year 2026 --offline
```

已导入清单时，直接运行 `generate`。清单可以在个人配置目录的 `watchlist.json` 中增删。导入命令拒绝覆盖现有清单，可用 `--output` 指定另一个文件。

项目读取机器的 `workspace.toml`。可通过 `--workspace-config` 或 `STOCK_REPORT_WORKSPACE_CONFIG` 显式指定。源码属于 CODE_ROOT；缓存、原始响应和报告属于 DATA_ROOT/stock-candidate-report；清单与 settings.toml 属于 CONFIG_ROOT/projects/stock-candidate-report。

输出在 `outputs/<运行ID>/`：Excel 第一张为“增长和估值”，第二张为“数据明细”。同名 JSON 保留输入 ID、来源、日期、计算依赖和失败原因。Excel 是运行快照，手工修改单元格不会更新 Python 计算结果。

## 数据与限制

- Yahoo 用于行情与财务；Alpha Vantage 预期接口是可选补充，通过本地配置或环境变量 `ALPHAVANTAGE_API_KEY` 设置密钥。程序不注册账号、不购买数据。
- 财年标签、预测币种和每股单位必须由来源或经核验的配置确定；无法确认时相应汇总字段留空。港股可以保留原表代码，通过 `yahoo_symbol` 映射数据源代码。ADR 不假设与普通股单位相同。
- SALES 汇总以百万原币显示，明细保留未缩放值。YTD 不含股息，并使用一致的拆股基准。
- NTM PE 使用未来四个尚未结束的连续财季 EPS 合计；缺少季度、口径冲突或合计非正时不计算，不用下一年 EPS 替代。
- EPS 的实际与预测口径未经核验时不计算两者增长率。亏损转盈利标为扭亏。财年变更产生的短年度不按正常年度增长计算。
- 缓存默认有效期：行情 1 小时、财务 1 天、预期 7 天。刷新缺少部分字段时保留旧字段及原时间，明确显示回退；离线模式不请求数据源。
- 本机真实连接测试遇到 Yahoo 拒绝访问，且未配置 Alpha Vantage 密钥。代码和离线流程通过测试，但这不能证明已获得实时数据或覆盖远期预期。完整覆盖需要数据源恢复访问并验证账户权限和返回格式。

退出码 0 表示至少一只股票有价格，仍须检查缺失字段；2 表示全部价格缺失，但诊断已导出；1 表示配置、导入或导出错误。

完整配置示例、外部表格运行环境和财年映射规则见 [英文 README](README.md)。
