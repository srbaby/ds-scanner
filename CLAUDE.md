# CLAUDE.md — DS波段扫描系统（规格 + AI操作引导）

X-DeepSeek 波段验证系统，基于"价值波段 Value-Swing"方法论，每日尾盘扫描ETF池，生成四维评分报告并通过 Bark 推送（全文塞body），由 Cloudflare Worker 定时触发（交易日北京 14:49）。

> **方法论版本：** 见 `X-Plan.md` 文档头（版本号不再在文件名/本文件维护，避免每次升级改多处）
> **性质：** 与主体系完全隔离的影子交易实验系统
> 本文件 = 本系统唯一说明文档（原 SPEC.md 已并入，2026-06-11）。

---

## 🤖 AI操作引导（新会话先读这段）

- **影子系统边界**：不与主体系 0号/1号 的 PE 体系、铁律、持仓混同；本系统持仓/信号不写入主体系文档。
- **方法论 canonical = 本目录 `X-Plan.md`**（完整版，含附录A扫描器policy分实现）。开仓/止损止盈/仓位/熔断等一切交易规则只看该文件，本文件不保留任何规则摘要，见下"交易规则速查索引"；`automation/ai_review.py` 运行时直接读取该文件全文作为system prompt，不在代码里重复抄写规则。
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
automation/generate_dashboard.py
    ├─ 调用 ai_review.py → Gemini API（system prompt=X-Plan.md全文，user输入=report.txt）
    └─ 写回 Gist dashboard.json（report原文 + Gemini分析 + 模型/时间/方法论版本；失败不阻塞后续步骤）
    ▼
automation/send_report.py
    └─ Bark推送 report.txt 全文（body，POST JSON，badge红点+icon，不变）
    ▼
index.html（GH Pages，stock.bailuzun.com，持仓管理+AI看板合一）
    ├─ 读 Gist holdings.json + dashboard.json：持仓管理置顶，
    │  AI分析（干货：标准回复格式全文）默认展开，report原文默认折叠
    │  （AI分析失败时自动展开作兜底）
    └─ 登记买卖/改资金 → 写回 Gist holdings.json + execution_events_<年>.jsonl
       + data_manifest.json（见下"Gist 数据源"）
    ▼
人工决策（必要时辅以DeepSeek/Gemini手动二次分析）
    └─ 14:55-15:00 执行
```

---

## 文件说明

| 文件                                        | 说明                                                         | 维护方式                 |
| ------------------------------------------- | ------------------------------------------------------------ | ------------------------ |
| `X-Plan.md`                                 | **方法论正文（canonical）**，`ai_review.py`运行时读取全文作为system prompt | 演化走流程               |
| `automation/ds_scanner.py`                  | 主扫描脚本                                                    | 手动迭代                 |
| `automation/ai_review.py`                   | Gemini API调用模块：读`X-Plan.md`+report.txt，输出四维评分分析文本 | 手动迭代                 |
| `automation/generate_dashboard.py`          | 调用ai_review，把report+Gemini分析+元信息写入Gist `dashboard.json` | 手动迭代                 |
| `automation/send_report.py`                 | Bark推送脚本（非交易日自动跳过，report.txt全文塞body，POST避免URL长度限制；APNs单条payload约4KB上限，超长可能截断——已知风险，按选择全文优先） | 手动迭代                 |
| `workers/ds-scan-trigger/src/index.js`（2026-07-20 前：`automation/cf_worker_trigger.js`） | Cloudflare Worker 定时触发器（部署在 CF，本文件为源码存档；2026-07-20 起接入 Workers Builds Git 自动部署） | 手动迭代 |
| `data/etf_pool.json` / `data/holdings.json` | Gist 镜像的本地历史快照（不可据此判断当前状态）              | 脚本自动写回（线上跑）   |
| `data/etf_base_config.json`                 | 板块政策基础分（0-15分），低频手动维护                       | 手动，重大政策事件后更新 |
| `data/etf_base_config/`                     | base分评分指南与提示词（GEMINI_UPDATE_GUIDE / PROMPT_FOR_GEMINI） | 低频手动                 |
| `index.html`                                | 持仓管理 + AI分析看板（合一），访问 stock.bailuzun.com。壳页面，逻辑都在 `js/` | 手动迭代                 |
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
| `dashboard.json`                 | AI看板：report原文 + Gemini分析 + `decision.operations`（扫描器权威操作清单，结构化字段，前端靠这个做"三态"匹配，不是解析 report 里的 markdown 表格） + 生成时间/模型/方法论版本 | generate_dashboard.py全自动 |
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
> 那是**独立的私有仓库**（本地 `D:\Projects\Master-Scheduler`），账户级基础设施，同时服务本项目与基金看板。
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
| `GEMINI_API_KEY`                | Google AI Studio 免费API Key，`generate_dashboard.py`用      |
| `GEMINI_MODEL`（可选）          | 默认`gemini-3.5-flash`（免费层可用）；不配置则用默认值，用于后续切换模型对比质量 |
| `GEMINI_THINKING_LEVEL`（可选） | 默认`high`（minimal/low/medium/high，控制推理深度/成本，high=免费层最高等级）；仅3.x系列支持，切回2.x模型需清空 |

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

## 交易规则速查索引（规则一律读 X-Plan.md，本文件不展开）

| 规则                                                 | 位置（X-Plan.md） |
| ---------------------------------------------------- | ----------------- |
| 开仓：三道金牌 + 四维评分 + 仓位对应                 | 模块2 / 模块7     |
| 止损止盈：三道防线 + 梯度/动态止盈                   | 模块3             |
| 持仓-新信号冲突矩阵                                  | 模块4             |
| 异常情况SOP                                          | 模块5             |
| 资金/仓位硬约束、加仓管理                            | 模块6             |
| 选品白/黑名单、爆发力评级                            | 模块8             |
| 熔断与转实盘（毕业）条件                             | 模块9             |
| 扫描器policy分实现（base/tech/strength、软止损阈值） | 附录A             |

---

## 每日流程

```
14:49  Cloudflare Worker 自动触发 Actions（cron: 49 6 * * MON-FRI，UTC）
~14:51 Gemini自动分析完成，写入Gist dashboard.json
~14:53 收到Bark推送（带badge红点），打开 index.html 查看AI分析（干货，默认展开）
~14:55 人工决策确认（Gemini分析失败时，仍可长按Bark通知复制report全文发给DeepSeek/Gemini手动分析）
14:55-15:00  尾盘执行
收盘后  更新 holdings.json（stock.bailuzun.com）
```

---

## 前端页面（GH Pages，stock.bailuzun.com）

单页 `index.html`（持仓管理 + AI看板合一），自上而下：

| 区块                       | 功能                                                         |
| -------------------------- | ------------------------------------------------------------ |
| 持仓管理（置顶）           | 可用资金/持仓列表，买入建仓（代码自动联想补全池内ETF）/ 减仓（自动标记`is_reduced: true`）/ 清仓（删除记录）/ 修改数量、成本、买入日期，所有操作实时写回Gist `holdings.json` + `execution_events_<年>.jsonl`（见上"三态"匹配） |
| 🤖 今日AI分析（默认展开）   | Gemini回复全文（标准回复格式=持仓指令/新机会/执行窗口，即"干货"），含止损/开仓信号高亮徽章 |
| 📡 原始扫描数据（默认折叠） | report.txt原文；AI分析失败时自动展开作人工兜底               |

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
| 前端测试修复（扫描恢复） | 2026-07-20 | 07-19 改回普通 script 后未同步改前端测试，`scan.yml` 第一步回归测试必挂，扫描自 07-19 起连续失败 3 次（含 07-20 午间）。修复：`test_app.js` 把"断言必须是 module"反转为"出现 module 即失败"的 guard；两个测试改用 `vm` 共享 context 按序加载三个脚本，不再走 ESM `import`；结构比较改宽松 `deepEqual` 避开跨 realm 原型误报。详见上"已知坑"第4条 |
| file:// 本地测试修复 + 数据修正 | 2026-07-19 | ① `js/api.js`/`js/decision.js` 从 ES module 改回普通 script（修复 07-15 引入的 file:// CORS 登录失败）；② 修复 `data-reason` 属性用 `escapeHtml` 未转义引号导致的 JSON 静默损坏（详见上"已知坑"第3条），这是 07-10/07-13/07-14 三笔交易被误标 `MANUAL_BACKFILL` 的真实根因；③ 用 `CORRECT_REASON` 事件在 Gist 里补上这三笔的正确归因；④ 修桌面表格"实仓→目标"列宽不够导致换行/撑高卡片的问题 |
