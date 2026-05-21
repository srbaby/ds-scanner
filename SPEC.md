# DS波段扫描系统

X-DeepSeek 波段验证系统，基于"价值波段 Value-Swing"方法论，每日尾盘扫描ETF池，生成四维评分报告并推送至邮件，由 iOS 快捷指令触发。

> **方法论版本：** v2.6（2026-03-17）  
> **系统版本：** ds_scanner v3.0  
> **性质：** 与主体系完全隔离的影子交易实验系统  

---

## 架构

```
iOS 快捷指令
    │ workflow_dispatch 触发
    ▼
GitHub Actions（scan.yml）
    │ 运行 ds_scanner.py
    ├─ 读 GitHub Gist → etf_pool.json（上次policy分）
    ├─ 读 GitHub Gist → holdings.json（当前持仓）
    ├─ 拉取新浪实时行情 + AKShare历史K线
    ├─ 重算policy分 → 写回 Gist etf_pool.json
    └─ 生成 report.txt
    ▼
send_report.py
    └─ 邮件推送 report.txt 附件
    ▼
DeepSeek / Gemini 四维评分分析
    └─ 人工决策 → 14:55-15:00 执行
```

---

## 文件说明

| 文件 | 说明 | 维护方式 |
|---|---|---|
| `ds_scanner.py` | 主扫描脚本 v3.0 | 手动迭代 |
| `send_report.py` | 邮件推送脚本 | 手动迭代 |
| `etf_base_config.json` | 板块政策基础分（0-15分），低频手动维护 | 手动，重大政策事件后更新 |
| `index.html` | 持仓管理网页，访问 stock.bailuzun.com | 手动迭代 |
| `.github/workflows/scan.yml` | Actions 工作流 | 手动迭代 |
| `CNAME` | 自定义域名 stock.bailuzun.com | 固定不动 |

---

## Gist 数据源

单个私有 Gist，Description: `ds_scanner`，包含两个文件：

| 文件 | 说明 | 维护方式 |
|---|---|---|
| `etf_pool.json` | ETF池policy总分（base+tech+strength），每日跑完自动写回 | 脚本全自动 |
| `holdings.json` | 持仓数据（现金、代码、数量、成本、买入日期） | 网页手动维护 |

脚本读取优先级：**Gist > 本地文件 > 硬编码兜底**。本地跑时不设环境变量自动降级本地文件，行为不变。

---

## 环境变量

| 变量名 | 说明 | 配置位置 |
|---|---|---|
| `DS_SCANNER_GIST_ID` | Gist ID（32位） | Actions Secrets |
| `GITHUB_TOKEN` | 有 gist scope 的 PAT，Secret名为 `GH_PAT` | Actions Secrets |
| `EMAIL_USER` | 发件邮箱（126.com） | Actions Secrets |
| `EMAIL_PASS` | 邮箱授权码 | Actions Secrets |
| `EMAIL_TO` | 收件邮箱 | Actions Secrets |

---

## ETF 观察池（18只）

| 级别 | 代码 | 名称 | 板块 |
|---|---|---|---|
| S | sh588000 | 科创50ETF | 科技成长 |
| S | sh512480 | 半导体ETF | 半导体 |
| S | sh515880 | 通信ETF | 通信 |
| S | sz159766 | 旅游ETF | 旅游 |
| S | sh515120 | 创新药ETF | 创新药 |
| A | sz159851 | 金融科技 | 金融科技 |
| A | sh512880 | 证券ETF | 证券 |
| A | sz159915 | 创业板ETF | 科技成长 |
| A | sh515030 | 新能车ETF | 新能车 |
| A | sz159755 | 电池ETF | 电池 |
| B | sh515220 | 煤炭ETF | 煤炭 |
| B | sh516150 | 稀土ETF | 稀土 |
| B | sh512400 | 有色ETF | 有色 |
| B | sh516020 | 化工ETF | 化工 |
| - | sh512690 | 酒ETF | 酒 |
| - | sh513180 | 恒生科技 | 港股科技 |
| 观 | sh515790 | 光伏ETF | 光伏 |
| 观 | sh512660 | 军工ETF | 国防安全 |

---

## Policy 评分体系

```
policy总分 = base分(0-15) + tech分(0-8) + strength分(0-7)，最高30分

base分：来自 etf_base_config.json，按板块政策倾向手动维护
tech分：价格/MA20位置(0-3) + RSI(0-3) + 量比(0-2)
strength分：ETF涨跌幅相对沪深300的超额强度(0-7)

逻辑止损阈值：policy总分 < 15 → 触发软止损
```

| 分数段 | 含义 |
|---|---|
| 12-15（base） | 国家战略级：半导体、AI算力、通信 |
| 9-12（base） | 重点支持级：稀土、储能、国防、新能车 |
| 6-9（base） | 稳增长级：电池、医药 |
| 4-6（base） | 中性周期级：大消费、酒、光伏、港股科技 |
| 2-4（base） | 政策工具级：旅游、证券 |
| 0-2（base） | 政策限制级：银行 |

---

## 开仓规则（三道金牌 + 四维评分）

```
三道金牌（串联，缺一否决）：
  第一道 量能关：量比 ≥ 1.20（以14:55尾盘为准）
  第二道 趋势关：现价 > MA20 + 同板块≥2只ETF涨幅>1%
  第三道 数据关：|现价/MA20 - 1| < 30%，人工复核

四维评分（通过三道金牌后）：
  政策催化  30分
  技术面    25分
  市场情绪  20分
  风险收益比 25分
  总分≥75分方可开仓

仓位对应：
  75-79分 → 10%标准仓
  80-84分 → 15%重仓
  ≥85分   → 20-30%强势仓（需人工复核）
```

---

## 止损止盈体系（v2.6三道防线）

```
止损优先级（高→低）：
  1. 价格止损（-8%硬止损）：盘中可触发，不等14:55
  2. 逻辑止损（policy总分<15）：尾盘14:55清仓
  3. 时间止损（持仓满21天）：强制换股

止盈梯度：
  浮盈+8%  → 首次减仓50%，标记 is_reduced: true
  浮盈+12% → 全部清仓
  动态止盈  → 减仓后从最高点回撤3%，全部清仓
```

---

## 仓位约束

```
单只持仓上限：50%
总持仓上限：60%（留40%现金）
单板块上限：30%
单日开仓上限：30%
```

---

## 每日流程

```
14:30  iOS快捷指令触发 Actions
14:35  收到邮件报告，复制附件内容发给 DeepSeek/Gemini
14:45  AI输出持仓指令 + 新机会评分
14:55  人工决策确认
14:55-15:00  尾盘执行
收盘后  更新 holdings.json（stock.bailuzun.com）
```

---

## 持仓管理网页

地址：`stock.bailuzun.com`（即 `index.html`）

功能：
- 查看可用资金和持仓列表
- 买入建仓（代码自动联想补全池内ETF）
- 减仓（自动标记 `is_reduced: true`）
- 清仓（删除记录）
- 修改数量/成本/买入日期
- 所有操作实时写回 Gist

首次打开需输入 GitHub Token 和 Gist ID，保存在浏览器本地，后续免登录。

---

## 本地运行

```bash
# 设置环境变量（可选，不设则降级本地文件）
export DS_SCANNER_GIST_ID=你的GistID
export GITHUB_TOKEN=你的PAT

# 运行
python3 ds_scanner.py

# 强制刷新policy分
python3 ds_scanner.py --refresh-policy
```

依赖：`pip install requests pandas akshare lxml beautifulsoup4`

---

## 熔断条件

| 条件 | 触发标准 | 动作 |
|---|---|---|
| 绝对回撤 | 最大回撤 -25% | 立即清仓，停止操作 |
| 相对收益 | 连续4个月跑输沪深300且累计跑输>5% | 关闭实验 |
| 信号干旱 | 连续10交易日无有效信号 | 暂停2周 |
| 胜率熔断 | 连续20笔胜率<40%且盈亏比<1.2 | 暂停1个月 |

---

## 转实盘条件

- 连续3个月跑赢沪深300达5%，**或**
- 绝对收益达+15%且不跑输沪深300

满足任一 → 转实盘5,000元

---

## 版本记录

| 版本 | 日期 | 核心变更 |
|---|---|---|
| ds_scanner v3.0 | 2026-05 | 动态止盈拦截、is_reduced状态记忆、Gist持久化 |
| 方法论 v2.6 | 2026-03-17 | 废除闪电战止损，重构为逻辑+价格+时间三道防线，时间止损延长至21天 |
| 方法论 v2.5 | 2026-03-02 | 量比定义统一，三方（Claude+Gemini+DeepSeek）审计定稿 |
| 方法论 v2.4 | 2026-02-24 | 废弃左轮，独尊右轮，新增三道金牌 |
| etf_base_config v3.1 | 2026-05-13 | 政治局会议+中美峰会修正：通信/稀土/储能上调 |
