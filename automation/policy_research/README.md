# AI 政策基础分研究备忘

> 状态：研究旁路，不接入真实交易，不覆盖 `data/etf_base_config.json`。
>
> 当前生产规则：扫描器继续读取人工基准分；政策/新闻系统只生成旁路 delta、激进度报告和月度慢调建议。
>
> （2026-07-10 从根目录 `AI-Policy-Score-Research.md` 迁移至此，与实现代码同目录，避免设计文档和代码分家。）

## 研究目标

政策基础分（0-15）不再依赖一次性 AI 脑拍，而改为无人值守的政策事件系统：

```text
当日有效政策分 = 结构性 base + 自动政策事件 active_delta
```

- `base`：长期政策地位，来自现有 `data/etf_base_config.json`，只允许月度慢调建议。
- `active_delta`：政策/新闻事件触发的临时偏移，自动衰减，合计封顶 -2 到 +2。
- 系统无人工复核环节；用机器激进度闸门替代人工确认。

## 文件布局

```text
automation/policy_research/
  collect_policy_news.py        # 白名单采集
  extract_policy_events.py      # 事件提炼，不直接打分
  score_policy_delta.py         # 规则评分、衰减、月度慢调建议
  compare_policy_decision.py    # 与原规则对比，量化激进度
  run_policy_research.py        # 总入口

data/policy_research/
  sources.json                  # 采集源白名单
  theme_keywords.json           # 主题映射与关键词
  raw/YYYY-MM.jsonl             # 原始采集项
  events/YYYY-MM.jsonl          # 结构化政策事件
  deltas/YYYY-MM-DD.json        # 当日 policy delta
  reports/YYYY-MM-DD-*.md       # 研究报告
  snapshots/                    # 最近一次运行快照
```

正式文件不动：

```text
automation/ds_scanner.py
data/etf_base_config.json
data/etf_pool.json
```

## 数据采集范围

不采全网，只采白名单。

### S 级：直接政策源

中国政府网、国务院/部委政策库、发改委、工信部、财政部、央行、证监会等。S 级来源可以直接参与 `active_delta`。

### A 级：主管机构与海外政策源

交易所、国家能源局、商务部、科技部、国家数据局，美国白宫、BIS、USTR、OFAC、欧盟委员会等。A 级来源可以影响受海外政策冲击明显的主题，例如半导体、AI算力、稀土、港股科技、出口链、国防安全。

### B 级：权威新闻确认

新华社、证券时报、中证报、上证报、财联社、第一财经、路透、彭博等。B 级只能作为确认或补充；单条 B 级新闻不直接改分。

### C 级：市场线索源

东方财富、同花顺、雪球、券商研报摘要、行业媒体。C 级只作为线索，第一阶段不参与自动 delta。

## 新闻与政策怎么用

流程固定：

```text
采集 -> 去重 -> 主题映射 -> 事件提炼 -> 规则评分 -> 自动衰减 -> 决策影响对比
```

结构化事件契约：

```json
{
  "event_id": "...",
  "published_at": "2026-07-10",
  "title": "...",
  "themes": ["半导体", "AI算力"],
  "direction": "positive",
  "policy_action": "funding_or_tax",
  "evidence_strength": 4,
  "confidence": "high",
  "decay_mode": "national_60d",
  "half_life_days": 20,
  "expires_at": "2026-09-08",
  "sources": [
    {"source": "工信部", "source_rank": "S", "url": "https://...", "title": "..."}
  ]
}
```

去重规则：

- 同 URL 直接去重。
- 标题高相似且主题/方向相同，合并为一个事件。
- 同一政策被媒体转载，保留最高等级来源，其他来源进入 `sources`。
- 同一主题同方向事件可以累计证据，但 `active_delta` 封顶。

## Delta 规则

```text
S级官方 + 强政策动作：±2
S/A级官方 + 明确方向：±1
B级新闻 + 至少两个独立来源确认：±1观察
C级市场线索：0，只记录
```

强政策动作包括：财政补贴、税收优惠、政府采购、重大工程、准入标准、出口管制、制裁、关税、明确限制、去产能、强监管。

每日限制：

```text
单事件最大 ±2
同主题 active_delta 合计封顶 ±2
最终 effective_base 限制在 0-15
```

## 自动消退与回归

没有政策/新闻时，分数回归结构性 base，不能无限累计。

```text
普通新闻/市场解读：3-7日内失效
部委/监管/交易所政策：10日半衰，20日失效或降权
国家级/重大海外政策：20日半衰，60日失效或降权
明确负面限制：保留到到期或出现反向事件，但仍不永久写 base
```

月度慢调 base：

```text
过去30天主题净政策事件分 >= +6 -> 建议 base +1
过去30天主题净政策事件分 <= -6 -> 建议 base -1
单月最多 ±1
连续同方向才允许后续继续调整
```

第一阶段只生成建议，不自动写 `etf_base_config.json`。

## 无人值守激进度闸门

不设人工复核，用机器闸门：

```text
新增 BUY/ADD 过多 -> delta 降权或只进报告
新增 RISK_STOP -> 负向 delta 不参与真实止损，只参与评分降级
aggression_index > 7 -> 过激，只报告不执行旁路裁决
```

第一阶段政策 delta 只影响四维评分中的政策催化，不允许直接改 `policy < 15` 逻辑止损。

## 验证方案

每天同时保存两套结果：

```text
baseline：当前人工 base
policy_shadow：人工 base + active_delta
```

量化指标：

```text
score_delta_total
signal_grade 升级/降级次数
operation_changes
new_buy_count
new_add_count
new_sell_count
new_risk_stop_count
target_position_delta_pct
aggression_index
```

激进度指数：

```text
aggression_index =
  新增BUY * 3
+ 新增ADD * 2
+ 信号升级次数 * 1
+ 目标仓位增加百分比 / 5
- 新增SELL * 2
- 新增RISK_STOP * 4
```

分档：

```text
-4以下：过度防守
-3到+3：可接受
+4到+7：偏激进，可观察
+8以上：过激，自动降权或只进报告
```

事后验证：

```text
政策事件触发后 3/5/10/21 个交易日：
- 主题 ETF 是否跑赢沪深300
- 因政策 delta 升级的 BUY/ADD 是否贡献正收益
- 因政策 delta 降级的主题是否避免回撤
```

## 安全底线

政策研究系统不可成为每日扫描单点故障。采集失败、事件为空、评分失败、输出异常时，生产系统继续使用当前 `data/etf_base_config.json`。
