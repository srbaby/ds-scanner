# CLAUDE.md — DS波段扫描系统（规格 + AI操作引导）

X-DeepSeek 波段验证系统，基于"价值波段 Value-Swing"方法论，每日尾盘扫描ETF池，生成四维评分报告并通过 Bark 推送（全文塞body），由 Cloudflare Worker 定时触发（交易日北京 14:49）。

> **方法论版本：** 见 `X-Plan.md` 文档头（版本号不再在文件名/本文件维护，避免每次升级改多处）
> **性质：** 与主体系完全隔离的影子交易实验系统
> 本文件 = 本系统唯一说明文档（原 SPEC.md 已并入，2026-06-11）。

---

## 🤖 AI操作引导（新会话先读这段）

- **判断"这段代码/这个数字是不是有意设计"，先读 [docs/01-业务意图.md](docs/01-业务意图.md)。** 它讲的是"为什么这么设计、每个数字回答什么问题、哪些看着像 bug 其实是刻意的"，不复述规则。规则永远看 `X-Plan.md`。**发现文档与代码冲突时，默认代码对、文档漏——先问，别按文档去"修正"代码。**
- **影子系统边界**：不与主体系 0号/1号 的 PE 体系、铁律、持仓混同；本系统持仓/信号不写入主体系文档。
- **方法论 canonical = 本目录 `X-Plan.md`**（完整版，扫描器 policy 分实现在模块11）。开仓/止损止盈/仓位/熔断等一切交易规则只看该文件，本文件不保留任何规则摘要、也不再维护规则索引（原因见下"交易规则去哪查"）；AI 审计模块运行时直接读取该文件全文作 system prompt，不在代码里重复抄写规则（该模块当前每日流程未启用，见架构图）。
- **系统已全部线上运行**（GitHub Actions + Gist + Cloudflare Worker），本地不再跑扫描。本目录是落后的镜像副本，`data/etf_pool.json` / `data/holdings.json` / `dashboard.json` 均为历史快照，**不可据此判断当前持仓或分数**；实时状态只在 Gist（见下"Gist 数据源"），可用已登录的 `gh` CLI（`gh api gists/<id>`）直接读，必要时也可直接 PATCH 写回，不必假设"只能离线分析"。
- 唯一仍需本地手动维护的是 `data/etf_base_config.json`（改分后 push 生效），评分方法见 `data/etf_base_config/GEMINI_UPDATE_GUIDE.md`（供 Gemini 使用，Claude 不主动改分）。
- `automation/ds_scanner.py` 依赖新浪行情 + AKShare，Cowork 沙箱不要尝试抓行情，只能对导出副本做离线分析。
- Cowork memory 不复制持仓/分数/现金/AI分析等状态（避免双真理源）。
- 修订规则先改本文件再改代码。

### ⚠️ 已知坑（改前端代码前必读）

1. **前端脚本必须是普通 `<script>`，不能用 `type="module"`。** `js/api.js`/`js/decision.js`/`js/app.js` 按顺序加载、共享同一全局作用域（`app.js` 里直接用 `GistClient`/`parseJsonl`/`actionPriority` 等名字，不用 `import`）——这是故意的，为了 `file://` 双击打开也能测，不强依赖起服务器。2026-07-15 曾误改成 `type="module"`，`file://` 登录被 CORS 静默弄坏，好几天没人发现。
2. **改完登录/连接链路，必须用真实 token/gist 走一遍成功路径再算完成，不能只看"控制台无报错"或只测假 token。** 假 token 会在 401 那步提前 return，根本走不到后面真正出错的代码，会造成"看起来修好了"的假象——2026-07-19 那次 `parseJsonl` 命名冲突死循环爆栈就是这么漏测的（`app.js` 里一个同名本地函数覆盖了 `api.js` 的真实实现）。
3. **往 HTML 属性里塞 `JSON.stringify(...)` 时必须用 `escapeAttr`，不能用 `escapeHtml`。** `escapeHtml` 只转义 `& < >`，不转义双引号；`JSON.stringify` 全是双引号，用 `escapeHtml` 会在属性值里被提前截断，`JSON.parse` 静默炸掉、`catch` 成 `{}`。2026-07-19 发现 `js/app.js` 里 `data-reason="${escapeHtml(JSON.stringify(...))}"` 就是这样：下拉框选项看着完全正常（因为可见文字是单独转义的），但背后存的理由数据全烂了，导致所有登记不管有没有匹配上扫描器建议，最后都被兜底成 `rule_code: MANUAL_BACKFILL`——这个 bug 从功能上线起就一直存在，2026-07-10/07-13/07-14 三笔交易的"人工补录"标签都是被它污染的，已用 `CORRECT_REASON` 更正事件在 Gist 里改回来了（见下）。改任何 `data-*="${...}"` / `title="${...}"` 前，先确认塞进去的字符串里会不会有引号。
4. **改前端加载方式/接口形状，必须同步改 `js/test_app.js` / `js/test_api.js`，否则每日扫描会整个挂掉。** 这两个测试是 `scan.yml` 的**第一步**（`npm run test:frontend`），它一红，`ds_scanner.py` 根本跑不到，当天没 report、没 Bark、不写 Gist——但失败只体现在 Actions 历史里，不会主动通知任何人。2026-07-19 那次改回普通 script 后忘了改测试，连挂 3 次才被发现。两个测试现在都用 `vm` 把三个脚本按 `index.html` 的顺序丢进同一 context 加载（复刻浏览器共享全局作用域的行为），不走 ESM `import`——**这些文件没有任何 `export`，用 `import` 必然 `SyntaxError`**。另注意两点：① `test_app.js` 里那条 `type="module"` 的 guard 正则必须限定在 `<script` 标签内，因为 `index.html` 里解释"为什么不用 module"的注释本身就含这个字面量，全文搜会自己命中自己；② `vm` 是独立 realm，跨 realm 的对象/数组原型不同，结构比较要用宽松 `deepEqual`，`deepStrictEqual` 会误报。

### ⚠️ 已知坑（改行情/政策数据链路前必读）

这两条的共同教训：**"静默降级成看起来正常的值"比直接报错危险得多**，改数据链路时优先让异常可见，不要给一个"合理"的默认值。

1. **行情历史不复权，份额折算会污染 MA20，且 T-1 收盘校验查不出来。** `ak.fund_etf_hist_sina` 没有 adjust 参数，份额折算日收盘价会单日跳变几十个百分点；只要断层落进 MA20 窗口，MA20 就被永久拉偏。原本的 `close_gap_pct` 只比对最后一根 K 线与实时行情，**看不到窗口内部的断层**，而唯一的兜底是 `abs(MA20偏离) > 30` 这个拍脑袋阈值。2026-07-27 半导体ETF 偏离 -29.64% 差 0.36 个百分点漏网被判"有效"（同一现象的通信ETF -31.94% 被拦下），技术分被压到 4/25，且"现价>MA20"这条开仓硬条件永远不可能满足——一只政策分满分 30/30 的 S 级标的被静默除名。现由 `repair_price_discontinuity()` 前复权修正（单日跳变 >25% 即判定折算，A股ETF涨跌停上限20%，真实行情不可能到这个量级），价格与成交量反向缩放，结果记进 `data_quality.adjustments`（**不是 `issues`**——进 issues 会把标的直接判死）。
2. **政策研判必须跑在扫描器之前，否则等于没接。** `policy_research` 产出的主题 delta 是四维评分的输入（`ds_scanner.load_policy_deltas()` 读 `snapshots/last_delta.json`）。2026-07-27 之前 `scan.yml` 里政策步骤排在 `ds_scanner.py` **之后**，`ds_scanner.py` 里也没有任何一处引用政策数据——`score_policy_delta.py` 老老实实算出的 `effective_base` 没有任何人读，政策对每日操作建议**零影响**，只在看板上当摆设。改 workflow 顺序时注意别改回去。三条命名链必须严格同名才不会静默失效：`theme_keywords.json` 的主题名 → `etf_base_config.json` 的板块名 → `etf_pool.json` 的 `category`（当前 22/22 完全对齐，加新主题或新板块时要三处一起加）。
3. **政策事件的 `published_at` 必须来自源站，不能兜底成"今天"。** 采集端曾把 `published_at` 写死 `None`，抽取端再兜底成 `datetime.now()`；叠加 Actions 里 `data/policy_research/events/` 每次都是全新目录（既不提交也不从 Gist 恢复），等于每天把同一条事件重新标成"今天发布"——`age_days` 恒为 0、衰减权重恒为 1.0，`score_policy_delta.py` 里整套半衰期/过期逻辑全是死代码。2026-07-27 发现证券ETF那条"账户管理功能优化试点"从功能上线起就一直挂在满权重不动，`expires_at` 每天顺延（当天值 2026-09-25 = 当天 +60 天，正是这个 bug 的指纹）。现在采集端从列表页/URL 解析真实日期，取不到就留 `None` 并标记 `published_at_estimated`，该标记会把衰减权重压到最高 0.5，且透出到看板事件卡片上。**注意事件目录仍是一次性的**：真实日期解析失败的源站，事件依然不会随时间过期，要根治得把事件台账落到 Gist。

---

## 架构

```
Cloudflare Worker（cron: 周一至五 北京14:49）
    │ workflow_dispatch 触发
    │ 备用：浏览器访问 Worker URL 带 ?key= 手动触发
    ▼
GitHub Actions（.github/workflows/scan.yml）
    │ 先跑 automation/policy_research/run_policy_research.py
    │   └─ 抓政务源→抽事件→按发布日期衰减→主题delta(±2)→snapshots/last_delta.json
    │      ⚠️ 必须跑在扫描器之前，否则政策影响不了当天建议（2026-07-27 前就是如此）
    │ 再运行 automation/ds_scanner.py
    ├─ 读 last_delta.json → 政策delta叠加到base分（进四维政策催化位，见X-Plan模块11）
    ├─ 读 GitHub Gist → etf_pool.json（上次policy分）
    ├─ 读 GitHub Gist → holdings.json（当前持仓）
    ├─ 拉取新浪实时行情 + AKShare历史K线
    ├─ 重算policy分 → 写回 Gist etf_pool.json
    └─ 生成 report.txt
    ▼
automation/generate_dashboard.py
    └─ 写回 Gist dashboard.json（report原文 + decision + 政策旁路 + 时间/方法论版本）
       ⚠️ 每日流程不调用 AI：scan.yml 显式传 AI_PROVIDER=none，
          dashboard.ai/audit 恒为 {provider:"none", enabled:false}。
          ai_review.py(DeepSeek) / gemini_review.py(Gemini) 仅供手动调试，
          扫描器的 decision 是唯一权威。理由见 docs/01-业务意图.md 第四节第4条
    ▼
automation/send_report.py
    └─ Bark推送 report.txt 全文（body，POST JSON，badge红点+icon，不变）
    ▼
index.html（GH Pages，stock.bailuzun.com，持仓管理+看板合一）
    ├─ 读 Gist holdings.json + dashboard.json：持仓管理置顶；
    │  AI审计区因 enabled:false 显示"每日AI审计已停用"并折叠，
    │  操作看扫描器 decision（js/app.js 已正确处理，勿按旧文档"修正"）
    └─ 登记买卖/改资金 → 写回 Gist holdings.json + execution_events_<年>.jsonl
       + data_manifest.json（见下"Gist 数据源"）
    ▼
人工决策（必要时长按Bark复制report全文，手动喂给AI做二次分析）
    └─ 14:55-15:00 执行
```

---

## 文件说明

| 文件                                        | 说明                                                         | 维护方式                 |
| ------------------------------------------- | ------------------------------------------------------------ | ------------------------ |
| `X-Plan.md`                                 | **方法论正文（canonical）**，唯一规则源；AI 审计模块运行时读取全文作 system prompt（当前每日流程未启用） | 演化走流程               |
| `automation/ds_scanner.py`                  | 主扫描脚本                                                    | 手动迭代                 |
| `automation/ai_review.py`                   | AI审计模块（DeepSeek）+ 输出契约校验 `validate_ai_output`。**每日流程不调用**，仅供手动调试 | 手动迭代                 |
| `automation/generate_dashboard.py`          | 把 report + decision + 政策旁路 + 元信息写入 Gist `dashboard.json`；`AI_PROVIDER` 默认 `none`，不调 AI | 手动迭代                 |
| `automation/send_report.py`                 | Bark推送脚本（非交易日自动跳过，report.txt全文塞body，POST避免URL长度限制；APNs单条payload约4KB上限，超长可能截断——已知风险，按选择全文优先） | 手动迭代                 |
| `workers/ds-scan-trigger/src/index.js`（2026-07-20 前：`automation/cf_worker_trigger.js`） | Cloudflare Worker 定时触发器（部署在 CF，本文件为源码存档；2026-07-20 起接入 Workers Builds Git 自动部署） | 手动迭代 |
| `data/etf_pool.json` / `data/holdings.json` | Gist 镜像的本地历史快照（不可据此判断当前状态）              | 脚本自动写回（线上跑）   |
| `data/etf_base_config.json`                 | 板块政策基础分（0-15分），低频手动维护                       | 手动，重大政策事件后更新 |
| `data/etf_base_config/`                     | base分评分指南与提示词（GEMINI_UPDATE_GUIDE / PROMPT_FOR_GEMINI） | 低频手动                 |
| `index.html`                                | 持仓管理 + 看板（合一），访问 stock.bailuzun.com。壳页面，逻辑都在 `js/` | 手动迭代                 |
| `js/api.js`                                 | Gist 读写封装（`GistClient`/`GistApiError`/`parseJson`/`parseJsonl`），不碰 DOM | 手动迭代                 |
| `js/decision.js`                            | 纯函数：动作优先级排序、dashboard 新鲜度判断                 | 手动迭代                 |
| `js/app.js`                                 | 主逻辑：渲染、持仓登记、扫描器建议匹配（三态）、执行事件构建与写回。~2400行，DOM/状态/业务规则都在这一个文件里 | 手动迭代                 |
| `js/test_app.js` / `js/test_api.js`         | 前端回归测试（`npm run test:frontend`），`scan.yml` 的第一道门禁——挂了当天整个扫描不跑。改前端必须同步改，见上"已知坑"第4条 | 手动迭代                 |
| `css/style.css`                             | 全部样式，含桌面表格布局的 grid-template-columns（按实测内容宽度定宽，改前先用浏览器量实际字符宽度，别拍脑袋） | 手动迭代                 |
| `.github/workflows/scan.yml`                | Actions 工作流，仓库内位置同此                               | 手动迭代                 |
| `run_report.bat`                            | 本地手动跑扫描的批处理                                       | 手动迭代                 |
| `CLAUDE.md`                                 | 本文件：系统规格 + AI操作引导                                | 随系统演进               |
| `CNAME`                                     | 自定义域名 stock.bailuzun.com（仅仓库，本地镜像无）          | 固定不动                 |

---

## Gist 数据源

单个私有 Gist（Description: `ds_scanner`）。可用 `gh api gists/<id>` 直接读，`gh api --method PATCH gists/<id> --input body.json` 直接写（`gh` 已用仓库owner账号登录，带 `gist` scope）。

**当前使用中的文件：**

| 文件                             | 说明                                                         | 维护方式                    |
| -------------------------------- | ------------------------------------------------------------ | --------------------------- |
| `etf_pool.json`                  | ETF池policy总分（base+tech+strength），每日跑完自动写回      | 脚本全自动                  |
| `holdings.json`                  | 当前持仓（现金、代码、数量、成本、买入日期）                 | 网页手动维护                |
| `dashboard.json`                 | 看板数据：report原文 + `ai`/`audit`（当前 enabled:false） + `decision.operations`（扫描器权威操作清单，结构化字段，前端靠这个做"三态"匹配，不是解析 report 里的 markdown 表格） + 生成时间/模型/方法论版本 | generate_dashboard.py全自动 |
| `execution_events_<年>.jsonl`    | 买卖/改资金/更正 的完整台账，append-only，一行一个 JSON 事件。`event_type` 有 `BUY`/`ADD`/`REDUCE`/`SELL`/`CASH_UPDATE`/`CORRECT_REASON`/`REVERSE_EVENT`。**从不原地改历史记录**——纠错是追加一条 `CORRECT_REASON` 事件（带 `target_event_id`/`previous_rule_code`），展示层再把最新更正结果盖在原记录上；撤销同理，追加 `REVERSE_EVENT` | 网页写（`js/app.js` 的 `buildExecutionEvent`/`persistExecution`） |
| `data_manifest.json`             | 上面几个 jsonl 文件的元信息（row_count/content_bytes/content_sha256/last_event_id），每次写 execution_events 时同步重算 | 网页自动同步写             |
| `stats.json` / `observer_state.json` | 方法论有效性统计 / 观察器状态                             | 自动化脚本写                |

**遗留/归档（只读，不再写入）：** `trades.jsonl`、`portfolio_snapshots.jsonl`——已分别迁移到 `trades_<年>.jsonl`、`portfolio_snapshots_<年>.jsonl`，`data_manifest.json.legacy_files` 里标了 `migrated_to`。`report.txt` 是当次 `report` 字段的纯文本副本，给 Bark 推送用。

脚本（Python 侧）读取优先级：**Gist > 本地文件 > 硬编码兜底**。本地跑时不设环境变量自动降级本地文件，行为不变。

### 持仓登记的"三态"匹配（`js/app.js`，容易踩坑的地方）

网页登记买卖时，会把当日 `dashboard.json.decision.operations` 里的扫描器建议和用户输入的代码/动作做匹配，三种结果：

1. **数据是今日的且匹配上** → 正常放行，理由标签用扫描器的 `rule_code`/`ai_action_id`，`data_confidence: scanner_authoritative`。
2. **数据是今日的但确无该代码/动作** → 允许人工补录（点"转人工补录"，`confirm()` 二次确认），`rule_code: MANUAL_BACKFILL`，`data_confidence: manual`。
3. **数据没刷新成功/不是今日的** → 拦截，下拉框禁用，不能让用户在这种状态下被当成"确认无信号"而人工补录，同样要求先刷新重试或显式覆盖确认。

`lastScanStatus`（`{ok, fresh, reason, generatedDate}`）只在浏览器内存里，不落盘、不进 Gist，出问题时无法事后反查，只能看当时下拉框旁边那行状态小字。

---

## 定时触发（Cloudflare Worker）

| 项       | 值                                                           |
| -------- | ------------------------------------------------------------ |
| Worker   | `ds-scan-trigger`（Cloudflare，源码存档 `workers/ds-scan-trigger/src/index.js`，2026-07-20 前路径 `automation/cf_worker_trigger.js`） |
| 排班     | **不在本 Worker 上**。自身公网 Cron 已随中控化删除（配额还给中控），改由 `master-scheduler` 经 Service Binding 内网唤醒：北京 12:00 / 14:49 发 `scan`，20:30 发 `observe`，周一至五 |
| 变量     | `GH_REPO`=srbaby/ds-scanner（文本）、`GH_TOKEN`=fine-grained PAT（机密，仅 Actions 读写）、`CRON_TOKEN`（机密，中控内网唤醒的暗号） |
| 手动备用 | 浏览器访问 Worker URL `?key=`（PAT 第12-19位）               |
| 准时性   | 实测分钟级（GitHub 自带 cron 延时数小时，已弃用）；iOS 快捷指令已退役（2026-06-11） |

> **排班归中控管，不在本仓库。** 几点唤醒、唤醒哪个 action，全在 `srbaby/Master-Scheduler`——
> 那是**独立的私有仓库**（本地 `~/Projects/Master-Scheduler`），账户级基础设施，同时服务本项目与基金看板。
> 本仓库只管收到唤醒之后做什么。**要改时间点去那个仓库改并重新部署，别在这里找。**
>
> 该仓库私有是有原因的：它的 README 含 CF 绑定清单与 `/test` 后门地址，而 `ds-scanner` 与 `fund-monitor`
> 都是公开仓库。

---

## 环境变量（GitHub Actions Secrets）

| 变量名                          | 说明                                                         |
| ------------------------------- | ------------------------------------------------------------ |
| `DS_SCANNER_GIST_ID`            | Gist ID（32位）                                              |
| `GITHUB_TOKEN`                  | 有 gist scope 的 PAT，Secret名为 `GH_PAT`                    |
| `BARK_KEY`                      | Bark App 推送key（不带 `https://api.day.app/` 前缀，与fund-monitor同一套） |
| `AI_PROVIDER`（可选）           | `none`（默认，`scan.yml` 显式传入）/ `gemini` / `deepseek`。**每日流程恒为 none**，下面几个 AI 变量因此当前都不生效，仅手动调试时才需要 |
| `GEMINI_API_KEY`                | Google AI Studio 免费API Key；仅 `AI_PROVIDER=gemini` 时使用 |
| `GEMINI_MODEL`（可选）          | 默认`gemini-3.5-flash`（免费层可用）；用于切换模型对比质量   |
| `GEMINI_THINKING_LEVEL`（可选） | 默认`high`（minimal/low/medium/high，控制推理深度/成本）；仅3.x系列支持，切回2.x模型需清空 |

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

## 交易规则去哪查

**规则一律读 `X-Plan.md`，它自己的章节标题就是索引，本文件不再维护第二份。**

> **这里曾有一张「交易规则速查索引」表，2026-07-27 删除。** 它是 v2.x 的化石：
> v3.0 重写方法论（2026-07-09）时没同步，实测表里 10 个概念有 9 个
> （三道金牌／三道防线／冲突矩阵／异常情况SOP／白名单／黑名单／附录A／毕业／熔断）
> 在 `X-Plan.md` 里**零命中**，模块号也几乎全错——索引说"止损止盈→模块3"，
> 实际模块3是「B/A/S 信号分级」；说"熔断与转实盘→模块9"，实际模块9是「输出与数据契约」。
>
> **教训**：给规则造第二个出处，它一定会烂，而烂索引比没索引更坏——它会把人导向错的地方
> 却看不出错。旧表内容在 git 历史里，需要考古用
> `git log -- CLAUDE.md` 找到删除前那次提交。

---

## 归档层的处置（`plans/`，待拍板）

参照 `fund-monitor` 的文档纪律：**归档层本身也需要维护，否则它会烂，而它烂掉的方式是看不出来的。**
那个项目已于 2026-07-26 删掉自己的 `docs/archive/` 与 `DECISIONS.md`，历史全部交给 git。

本仓库 `plans/` 现状（2026-07-27 逐份复核）：

| 文件 | 是什么 | 复核状态 | 建议 |
| --- | --- | --- | --- |
| `action-1-fail-loud.md` | "让系统会喊疼"执行指导书 | 已完成上线 | 删（git 里有） |
| `dead-code-candidates-2026-07-10.md` | 死代码扫描结果 | **6条已烂5条**，已加过期标记 | 处理完唯一存活项后删 |
| `gemini-api-shadow-archive.md` | Gemini 转正方案 | 已放弃；且内容已过期（写着"正式 provider 是 DeepSeek"，实际是 `none`） | 删 |
| `review-prompt-full-system-audit.md` | 可复用的全系统审查 meta-prompt | **是活工具，不是归档** | 留，但不该放 `plans/` |
| `version-history-archive.md` | 本文件 changelog 的归档 | 在用（本文件版本记录只留最近2条） | 留 or 交给 git，待定 |

唯一存活的死代码：`automation/gemini_reliability_check.py`（无任何引用，`scan.yml` 不调用，
`AI_PROVIDER` 默认 `none` 连日常 AI 审计都没启用）。建议删除，理由与依据见该清单文件末尾。

**以上均未擅自执行**——本仓库约定文件/代码删除由大亨拍板。删除后要取回：

```bash
git log --diff-filter=D --format='%h %ad' --date=short -1 -- plans/xxx.md
```

拿到 hash 后 `git show <hash>^:plans/xxx.md` 即全文。

---

## 每日流程

```
14:49  Cloudflare Worker 自动触发 Actions（cron: 49 6 * * MON-FRI，UTC）
~14:51 generate_dashboard.py 写回 Gist dashboard.json（不调用AI）
~14:53 收到Bark推送（带badge红点），打开 index.html 看扫描器操作清单
~14:55 人工决策确认（需要二次分析时，长按Bark通知复制report全文手动喂给AI）
14:55-15:00  尾盘执行
收盘后  更新 holdings.json（stock.bailuzun.com）
```

---

## 前端页面（GH Pages，stock.bailuzun.com）

单页 `index.html`（持仓管理 + 看板合一），自上而下：

| 区块                       | 功能                                                         |
| -------------------------- | ------------------------------------------------------------ |
| 持仓管理（置顶）           | 可用资金/持仓列表，买入建仓（代码自动联想补全池内ETF）/ 减仓（自动标记`is_reduced: true`）/ 清仓（删除记录）/ 修改数量、成本、买入日期，所有操作实时写回Gist `holdings.json` + `execution_events_<年>.jsonl`（见上"三态"匹配） |
| 🤖 今日AI审计（当前停用）   | `AI_PROVIDER=none` 时显示"每日AI审计已停用／操作清单由扫描器确定性生成"并折叠。启用时才渲染审计全文 |
| 📡 原始扫描数据（默认折叠） | report.txt原文；无 decision 或 AI 异常时自动展开作人工兜底   |

GitHub Token + Gist ID 存浏览器localStorage，登录一次后自动读取。

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

前端本地测试直接双击 `index.html`（`file://` 协议，见上"已知坑"第1条），不用起服务器。

---

## 版本记录（只留关键节点，不逐次记流水账）

| 版本                    | 日期       | 核心变更                                                     |
| ----------------------- | ---------- | ------------------------------------------------------------ |
| **v3.2 政策入评分 + 两处静默降级修复** | 2026-07-27 | **① 政策事件正式成为四维评分输入（方法论升 v3.2）**：此前 `policy_research` 在 `scan.yml` 里排在扫描器之后、`ds_scanner.py` 也从不读它，政策对操作建议零影响、纯看板摆设。现调整 workflow 顺序（政策先跑），`ds_scanner.load_policy_deltas()` 读 `last_delta.json` 把主题 delta（±2）叠加到 base 分，报告新增「政策事件调整」段落显示动了谁。边界见 X-Plan 模块11。② MA20 份额折算断层修正（半导体ETF -29.64% 差 0.36 个百分点绕过 `abs>30` 阈值被判"有效"，政策满分标的被静默除名）。③ 政策事件 `published_at` 不再兜底成当天（衰减机制此前是死代码）。三项均补回归测试，详见上"已知坑（改行情/政策数据链路前必读）" |
| master-scheduler 补静默日志 | 2026-07-27 | 07-27 中午12:00那次 scan 漏触发（GitHub Actions 与 Gist 均无对应记录），排查发现 `master-scheduler`（独立仓库，见下"排班归中控管"）的 `scheduled()` 从不打日志，即使漏调用也无法事后回溯；14:49 现场蹲守确认链路本身健康（`wrangler tail` 抓到 `dispatch -> 204 OK`）。修复：仅在实际命中 5 个排班点时 `console.log` 结果（不刷屏 idle tick），并把 `wrangler.toml` 里占位的 `compatibility_date` 换成经 Cloudflare API 核对过的线上真实值 `2026-06-24`。改动在 `Master-Scheduler` 仓库，已部署 |
