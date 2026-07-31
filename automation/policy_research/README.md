# 政策事件流水线

> **状态：生产链路。** 本流水线在每日扫描器之前运行，产出的政策事件
> `active_delta` 会叠加到主题 `base_score`，并进入四维评分的政策催化位。
>
> 交易规则与作用边界以 `X-Plan.md` 模块 11 为唯一出处；系统位置、环境变量和
> Gist 契约见 `docs/02-系统架构.md`；反直觉实现与失败约束见
> `docs/03-实现约束.md`。

## 一、职责与边界

本组件负责：

1. 从 `data/policy_research/sources.json` 的白名单源采集政策与行业信息。
2. 用 DeepSeek 两趟归类筛选实质事件；不可用时整体退回关键词兜底。
3. 生成按主题聚合、自动衰减的 `active_delta`。
4. 将最新结果写入 `data/policy_research/snapshots/last_delta.json`，供
   `automation/ds_scanner.py` 在当日扫描前读取。
5. 生成政策影响对比与可穿透证据，供报告、Bark 和看板展示。

本组件不负责：

- 不覆盖 `data/etf_base_config.json` 的人工结构性基础分。
- 不修改扫描器产出的评分、信号或操作。
- 不让政策事件影响持仓逻辑 `policy` 总分或硬条件。
- 不把政策对比结果当成第二套权威决策。

## 二、固定执行顺序

```text
白名单采集
  → 粗筛
  → DeepSeek 第一趟选读
  → 抓取选中条目的正文
  → DeepSeek 第二趟判主题与方向
  → 事件提炼与去重
  → delta 评分和衰减
  → 政策影响对比
  → 主扫描器读取 last_delta.json
```

DeepSeek 两趟之间的先后关系不可并行或颠倒：第二趟必须使用第一趟选中的条目及其正文。
AI 未配置、调用失败或结果不可用时，整批归类显式退回关键词兜底，不混合两种判定口径。

## 三、有界并发与确定性

政策源采集和正文抓取是网络 I/O，可使用有界线程并发：

| 环境变量 | 默认值 | 含义 |
| --- | ---: | --- |
| `POLICY_HTTP_CONCURRENCY` | `8` | 全局 HTTP 工作线程上限 |
| `POLICY_HTTP_PER_DOMAIN_CONCURRENCY` | `2` | 同一注册域名的并发请求上限 |

两个值都必须是正整数，非法值会显式报错。域名上限用于避免对同一政务站点集中施压，
全局上限用于限制线程和连接资源。

工作线程只做请求与解析，不写文件。主线程按以下固定顺序合并：

- 源采集结果按 `sources.json` 顺序处理；
- 正文按 DeepSeek 第一趟返回的 `chosen` 顺序组装；
- 去重、错误归档、JSONL 和 snapshot 仅由主线程写入。

因此，网络请求完成顺序变化不会改变落盘顺序或第二趟输入。

## 四、输入与产物

### 手工维护输入

| 文件 | 用途 |
| --- | --- |
| `data/policy_research/sources.json` | 政策与行业来源白名单 |
| `data/policy_research/theme_keywords.json` | 关键词兜底与主题辅助映射 |
| `data/etf_base_config.json` | 主题结构性基础分；本组件只读 |

### 运行产物

| 路径 | 用途 |
| --- | --- |
| `data/policy_research/raw/YYYY-MM.jsonl` | 去重后的原始采集条目 |
| `data/policy_research/events/YYYY-MM.jsonl` | 结构化政策事件 |
| `data/policy_research/deltas/YYYY-MM-DD.json` | 当日主题 delta |
| `data/policy_research/reports/YYYY-MM-DD-*.md` | 人读的政策影响报告 |
| `data/policy_research/snapshots/last_collect.json` | 最近一次采集状态 |
| `data/policy_research/snapshots/last_extract.json` | 最近一次归类与提炼状态 |
| `data/policy_research/snapshots/last_delta.json` | 扫描器读取的最新政策输入 |
| `data/policy_research/snapshots/last_decision_compare.json` | 政策影响对比 |

GitHub Actions 中的事件与快照目录是一次性工作区，尚未持久化的限制记录在
`docs/05-未实现项.md`。

## 五、失败与可见性

- 全部政策源采集失败时，流程返回非零退出码，并在产物中写入
  `source_health.all_sources_failed`。
- `scan.yml` 对政策步骤使用 `continue-on-error`，因此退出码本身不会阻止扫描；
  扫描器会拒用不可信 delta，并由 Bark 显式报警。
- 部分源失败会保留错误明细；采集到 0 条新内容或提炼出 0 个事件不自动视为故障。
- AI 失败会在报告与 Bark 中标明关键词兜底，不能静默伪装成 AI 成功。
- delta 缺失或过期时，扫描器回到人工结构性基础分继续运行。

## 六、运行与验证

完整运行：

```bash
python3 automation/policy_research/run_policy_research.py
```

常用选项：

```bash
python3 automation/policy_research/run_policy_research.py --skip-collect
python3 automation/policy_research/run_policy_research.py --no-ai
python3 automation/policy_research/run_policy_research.py --days 7 --score-days 90
```

完整入口会输出六段耗时：

```text
collect / AI 第一趟 / 正文抓取 / AI 第二趟 / score / compare
```

回归测试与语法检查：

```bash
python3 -m unittest automation.policy_research.test_policy_research
python3 -m compileall -q automation
```

提交前仍须执行 `docs/04-开发纪律.md` 规定的完整门禁。
