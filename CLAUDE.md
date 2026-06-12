# CLAUDE.md — DS波段扫描系统（规格 + AI操作引导）

X-DeepSeek 波段验证系统，基于"价值波段 Value-Swing"方法论，每日尾盘扫描ETF池，生成四维评分报告并通过 Bark 推送（全文塞body），由 Cloudflare Worker 定时触发（交易日北京 14:49）。

> **方法论版本：** v2.6（2026-03-17）
> **系统版本：** ds_scanner v3.0
> **性质：** 与主体系完全隔离的影子交易实验系统
> 本文件 = 本系统唯一说明文档（原 SPEC.md 已并入，2026-06-11）。

---

## 🤖 AI操作引导（新会话先读这段）

- **影子系统边界**：不与主体系 0号/1号 的 PE 体系、铁律、持仓混同；本系统持仓/信号不写入主体系文档。
- **系统已全部线上运行**（GitHub Actions + Gist + Cloudflare Worker），本地不再跑扫描。
  本目录是落后的镜像副本，`data/etf_pool.json` / `data/holdings.json` 均为历史快照，
  **不可据此判断当前持仓或分数**；实时状态只在 Gist。
- 唯一仍需本地手动维护的是 `data/etf_base_config.json`（改分后 push 生效），评分方法见 `data/etf_base_config/GEMINI_UPDATE_GUIDE.md`（供 Gemini 使用，Claude 不主动改分）。
- `automation/ds_scanner.py` 依赖新浪行情 + AKShare，Cowork 沙箱不要尝试抓行情，只能对导出副本做离线分析。
- Cowork memory 不复制持仓/分数/现金等状态（避免双真理源）。
- 修订规则先改本文件再改代码。

---

## 架构

```
Cloudflare Worker（cron: 周一至五 北京14:49）
    │ workflow_dispatch 触发
    │ 备用：浏览器访问 Worker URL 带 ?key= 手动触发
    ▼
GitHub Actions（.github/workflows/scan.yml）
    │ 运行 automation/ds_scanner.py
    ├─ 读 GitHub Gist → etf_pool.json（上次policy分）
    ├─ 读 GitHub Gist → holdings.json（当前持仓）
    ├─ 拉取新浪实时行情 + AKShare历史K线
    ├─ 重算policy分 → 写回 Gist etf_pool.json
    └─ 生成 report.txt
    ▼
automation/send_report.py
    └─ Bark推送 report.txt 全文（body，POST JSON，badge红点+icon）
    ▼
DeepSeek / Gemini 四维评分分析
    └─ 人工决策 → 14:55-15:00 执行
```

---

## 文件说明

| 文件                                        | 说明                                                         | 维护方式                 |
| ------------------------------------------- | ------------------------------------------------------------ | ------------------------ |
| `automation/ds_scanner.py`                  | 主扫描脚本 v3.0                                              | 手动迭代                 |
| `automation/send_report.py`                 | Bark推送脚本（非交易日自动跳过，report.txt全文塞body，POST避免URL长度限制；APNs单条payload约4KB上限，超长可能截断——已知风险，按选择全文优先） | 手动迭代                 |
| `automation/cf_worker_trigger.js`           | Cloudflare Worker 定时触发器（部署在 CF，本文件为源码存档）  | 手动迭代                 |
| `data/etf_pool.json` / `data/holdings.json` | Gist 镜像的本地历史快照（不可据此判断当前状态）              | 脚本自动写回（线上跑）   |
| `data/etf_base_config.json`                 | 板块政策基础分（0-15分），低频手动维护                       | 手动，重大政策事件后更新 |
| `data/etf_base_config/`                     | base分评分指南与提示词（GEMINI_UPDATE_GUIDE / PROMPT_FOR_GEMINI） | 低频手动                 |
| `index.html`                                | 持仓管理网页，访问 stock.bailuzun.com                        | 手动迭代                 |
| `.github/workflows/scan.yml`                | Actions 工作流，仓库内位置同此                               | 手动迭代                 |
| `run_report.bat`                            | 本地手动跑扫描的批处理                                       | 手动迭代                 |
| `CLAUDE.md`                                 | 本文件：系统规格 + AI操作引导                                | 随系统演进               |
| `CNAME`                                     | 自定义域名 stock.bailuzun.com（仅仓库，本地镜像无）          | 固定不动                 |

---

## Gist 数据源

单个私有 Gist，Description: `ds_scanner`，包含两个文件：

| 文件            | 说明                                                    | 维护方式     |
| --------------- | ------------------------------------------------------- | ------------ |
| `etf_pool.json` | ETF池policy总分（base+tech+strength），每日跑完自动写回 | 脚本全自动   |
| `holdings.json` | 持仓数据（现金、代码、数量、成本、买入日期）            | 网页手动维护 |

脚本读取优先级：**Gist > 本地文件 > 硬编码兜底**。本地跑时不设环境变量自动降级本地文件，行为不变。

---

## 定时触发（Cloudflare Worker）

| 项       | 值                                                           |
| -------- | ------------------------------------------------------------ |
| Worker   | `ds-scan-trigger`（Cloudflare，源码存档 `automation/cf_worker_trigger.js`） |
| Cron     | `49 6 * * MON-FRI`（UTC）= 北京 14:49 周一至五。⚠️ CF cron 星期字段 1=周日，必须用英文缩写 |
| 变量     | `GH_REPO`=srbaby/ds-scanner（文本）、`GH_TOKEN`=fine-grained PAT（机密，仅 Actions 读写） |
| 手动备用 | 浏览器访问 Worker URL `?key=`（PAT 第12-19位）               |
| 准时性   | 实测分钟级（GitHub 自带 cron 延时数小时，已弃用）；iOS 快捷指令已退役（2026-06-11） |

---

## 环境变量（GitHub Actions Secrets）

| 变量名               | 说明                                                         |
| -------------------- | ------------------------------------------------------------ |
| `DS_SCANNER_GIST_ID` | Gist ID（32位）                                              |
| `GITHUB_TOKEN`       | 有 gist scope 的 PAT，Secret名为 `GH_PAT`                    |
| `BARK_KEY`           | Bark App 推送key（不带 `https://api.day.app/` 前缀，与fund-monitor同一套） |

---

## ETF 观察池（18只）

| 级别 | 代码     | 名称      | 板块     |
| ---- | -------- | --------- | -------- |
| S    | sh588000 | 科创50ETF | 科技成长 |
| S    | sh512480 | 半导体ETF | 半导体   |
| S    | sh515880 | 通信ETF   | 通信     |
| S    | sz159766 | 旅游ETF   | 旅游     |
| S    | sh515120 | 创新药ETF | 创新药   |
| A    | sz159851 | 金融科技  | 金融科技 |
| A    | sh512880 | 证券ETF   | 证券     |
| A    | sz159915 | 创业板ETF | 科技成长 |
| A    | sh515030 | 新能车ETF | 新能车   |
| A    | sz159755 | 电池ETF   | 电池     |
| B    | sh515220 | 煤炭ETF   | 煤炭     |
| B    | sh516150 | 稀土ETF   | 稀土     |
| B    | sh512400 | 有色ETF   | 有色     |
| B    | sh516020 | 化工ETF   | 化工     |
| -    | sh512690 | 酒ETF     | 酒       |
| -    | sh513180 | 恒生科技  | 港股科技 |
| 观   | sh515790 | 光伏ETF   | 光伏     |
| 观   | sh512660 | 军工ETF   | 国防安全 |

---

## Policy 评分体系

```
policy总分 = base分(0-15) + tech分(0-8) + strength分(0-7)，最高30分

base分：来自 data/etf_base_config.json，按板块政策倾向手动维护
tech分：价格/MA20位置(0-3) + RSI(0-3) + 量比(0-2)
strength分：ETF涨跌幅相对沪深300的超额强度(0-7)

逻辑止损阈值：policy总分 < 15 → 触发软止损
```

| 分数段        | 含义                                   |
| ------------- | -------------------------------------- |
| 12-15（base） | 国家战略级：半导体、AI算力、通信       |
| 9-12（base）  | 重点支持级：稀土、储能、国防、新能车   |
| 6-9（base）   | 稳增长级：电池、医药                   |
| 4-6（base）   | 中性周期级：大消费、酒、光伏、港股科技 |
| 2-4（base）   | 政策工具级：旅游、证券                 |
| 0-2（base）   | 政策限制级：银行                       |

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
14:49  Cloudflare Worker 自动触发 Actions（cron: 49 6 * * MON-FRI，UTC）
~14:53 收到Bark推送（带badge红点），长按通知复制全文发给 DeepSeek/Gemini
~14:55 AI输出持仓指令 + 新机会评分，人工决策确认
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
# 以下命令均在 X-Plan/ 根目录下执行

# 设置环境变量（可选，不设则降级本地文件）
export DS_SCANNER_GIST_ID=你的GistID
export GITHUB_TOKEN=你的PAT

# 运行
python3 automation/ds_scanner.py

# 强制刷新policy分
python3 automation/ds_scanner.py --refresh-policy
```

依赖：`pip install requests pandas akshare lxml beautifulsoup4`

---

## 熔断条件

| 条件     | 触发标准                          | 动作               |
| -------- | --------------------------------- | ------------------ |
| 绝对回撤 | 最大回撤 -25%                     | 立即清仓，停止操作 |
| 相对收益 | 连续4个月跑输沪深300且累计跑输>5% | 关闭实验           |
| 信号干旱 | 连续10交易日无有效信号            | 暂停2周            |
| 胜率熔断 | 连续20笔胜率<40%且盈亏比<1.2      | 暂停1个月          |

---

## 转实盘条件

- 连续3个月跑赢沪深300达5%，**或**
- 绝对收益达+15%且不跑输沪深300

满足任一 → 转实盘5,000元

---

## 版本记录

| 版本                 | 日期       | 核心变更                                                     |
| -------------------- | ---------- | ------------------------------------------------------------ |
| 通知方式v2           | 2026-06-12 | 邮件推送 → Bark推送（report.txt全文塞body，POST JSON，badge红点+icon）；移除EMAIL_*三个secrets，新增BARK_KEY；send_report.py改造，scan.yml同步更新 |
| 报告精简             | 2026-06-12 | 合并"🎯持仓波段管理卡"与"📦持仓状态"两个冗余区块（字段1:1对应），卡片标题加代码、当前盈亏行加现价；为Bark全文塞body的~4KB上限省空间，AI判断逻辑（波段管理卡字段）不受影响 |
| 目录重构             | 2026-06-12 | 本地镜像目录从 X_Python 改名为 X-Plan；scan.yml → .github/workflows/scan.yml（与真实仓库路径一致）；cf_worker_trigger.js → automation/cf_worker_trigger.js（命名习惯对齐基金看板项目）；二阶段：ds_scanner.py/send_report.py → automation/，etf_pool.json/holdings.json/etf_base_config.json/etf_base_config/ → data/（路径字面量已同步改写，Gist API文件名不受影响）；index.html/favicon.png 等保持根目录不动（GH Pages路径耦合） |
| 文档合并             | 2026-06-11 | SPEC.md 并入 CLAUDE.md，单文件维护                           |
| 触发方式v2           | 2026-06-11 | iOS快捷指令 → Cloudflare Worker 定时触发（北京14:49交易日），实测分钟级准时；手机端自动化已删除 |
| ds_scanner v3.0      | 2026-05    | 动态止盈拦截、is_reduced状态记忆、Gist持久化                 |
| 方法论 v2.6          | 2026-03-17 | 废除闪电战止损，重构为逻辑+价格+时间三道防线，时间止损延长至21天 |
| 方法论 v2.5          | 2026-03-02 | 量比定义统一，三方（Claude+Gemini+DeepSeek）审计定稿         |
| 方法论 v2.4          | 2026-02-24 | 废弃左轮，独尊右轮，新增三道金牌                             |
| etf_base_config v3.1 | 2026-05-13 | 政治局会议+中美峰会修正：通信/稀土/储能上调                  |
