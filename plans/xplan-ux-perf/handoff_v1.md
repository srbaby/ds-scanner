# handoff_v1 ｜ FROZEN ｜ X-Plan 交互反馈 · 政策可读性 · 链路效率 三批优化

> 接手你的人没有本次对话记忆。本包按 3 批交付，**批次之间有依赖顺序：批1 → 批2 → 批3**，
> 但每批可独立验收。每批交一次回执 `receipt_v1_b<M>.md`。

---

## 块1 · 交什么

产出物：仓库 `/Users/srbaby/Projects/XPlan` 上的代码改动 ＋ 每批一份回执。
给谁用：项目所有者本人（每日尾盘看板 + 手工登记交易的唯一使用者）。

### 批1 —— 交易登记的即时反馈与写入链路

1. 点击「加仓 / 减仓 / 清仓 / 更正依据」任一入口后，弹窗**不等待任何网络请求**即出现。
   `openOperationDialog` 中 `dialog.showModal()` 必须早于 `await refreshScannerActions()`。
2. `refreshScannerActions()` 未落地前，「确认登记」按钮处于 disabled，且
   `#operation-reason-status` 显示可见的进行中文案；落地后按结果启用，或沿用既有失败提示。
3. 点击「确认登记」后**立即**（不等网络）进入 pending 态：确认按钮 disabled 且文案变化，
   取消按钮同时 disabled。写入结束（成功或失败）两个按钮都恢复。
4. 重复提交不再产生"看起来像失败"的红色 toast。按钮 disabled 是第一道拦截；
   `operationSaveInFlight` 保留为兜底，但兜底分支不得再弹 `error` 级 toast。
5. 成功 toast **只在写后校验通过之后**弹一次。当前 `saveData()` 在 PATCH 成功时就弹
   `✅ 操作已登记`，而弹窗要再等一整轮 `verifyEventWritten()` 才关——这是"提示已出现却还得自己关窗"
   的直接原因。`saveData()` 只有 `persistExecution()` 一个调用方，成功提示移交调用方。
6. 写后校验优先复用 `patchFiles()` 的 PATCH 响应体（GitHub 返回更新后的 gist 对象，含文件内容），
   省掉一次 `index()+readFile()` 往返。**响应中该文件缺失或 `truncated` 为真时，必须回退到原来的
   重新读取校验**——拿不到内容一律视为校验未完成，不得跳过、不得当作通过。
7. 提交路径上的 GitHub API 往返数 ≤ 2（`assertNoRemoteChange` 1 次 + PATCH 1 次）；
   走 truncated 回退时 ≤ 3。回执里写明改动前后的实际调用次数。
8. 成功后弹窗自动关闭，用户无需手动关。
9. `npm run test:frontend` 全绿，并新增覆盖：pending 态的开启与恢复、校验回退分支。

### 批2 —— 政策观察的方向可读性与产品卡缺失

1. `build_policy_watchlist()` 目前只覆盖三种组合，另外两种被 `continue` 直接丢弃，
   必须补成独立分组（判定与顺序见下），这是"主题 chip 显示 +2 却一张产品卡都没有"的根因：

   | 条件 | 现状 | 要求 |
   |---|---|---|
   | 持仓 & delta<0 | `holdings_risk` | 不变 |
   | 持仓 & 等级降级 | `near_downgrades` | 不变 |
   | 非持仓 & delta>0 | `near_triggers` | 不变 |
   | **持仓 & delta>0** | **丢弃** | 新分组 `holdings_boost`，上限 5 |
   | **非持仓 & delta<0** | **丢弃** | 新分组 `pool_weakening`，上限 5 |

2. 两个新分组复用既有 `sort_key`，不得引入新排序口径。
3. `summary` 新增两个计数字段。既有字段名与含义一律不动，只准新增。
4. 前端 `renderPolicyWatch()` 渲染两个新分组，标题分别为「持仓政策转强」「池内政策转弱」。
5. **事件级方向文字化**：`policy_evidence()` 已经产出 `direction` 字段并写进 Gist，
   前端 `policyDeltaEvidence()` 完全没渲染它——这是"看不出正向反向"的根因。
   每条依据要显示中文方向词。取值域见 `score_policy_delta.py:45`：
   `positive` / `negative` / `mixed`。**缺失或取值不在域内时显示"方向未标注"，
   不得猜一个默认值、不得默认按正向渲染。**
6. 主题 chip 的方向同样要有文字标识，不能只靠颜色和正负号（暗色模式与色觉差异下不可读）。
7. `active_policy_deltas` 非空但五个分组全为空时，面板必须显式说明原因
   （例如"N 个主题有政策偏移，均未落到池内标的"），不得留白让人以为系统没跑。
8. `automation/policy_research/test_policy_research.py` 与 `js/test_app.js` 同步补测：
   两个新分组的进桶判定、`direction` 的三种取值与缺失时的渲染。全部 Python 测试与前端测试绿。

### 批3 —— 链路效率

1. 新增 `requirements.txt` 钉住 scan 链路实际依赖（`requests pandas akshare lxml beautifulsoup4`）。
   `scan.yml` 与 `observe.yml` 的 `cache-dependency-path` 改为指向依赖清单，
   安装改为 `pip install -r requirements.txt`。
   现状问题：缓存键挂在 `automation/*.py` 等业务源文件上，**改一行扫描器代码就丢掉整个 pip 缓存**，
   而 akshare + pandas 是重装依赖。
2. 回执中说明并验证：改扫描器代码不再使 pip 缓存失效。
3. `loadInsightData()` 复用已有的 `gistIndex`，不再额外发一次 `index()`。
   但 `gistIndex` 为空时必须照常拉取，不得静默用空对象顶替。
4. 回执给出改动前后 scan 工作流各步骤耗时对照（最近一次 Actions 运行 vs 改动后一次）。
   **拿不到就写"拿不到"，不要估算、不要编数字。**

### 每批共同的完成条件

```bash
npm run test:frontend
PYTHONPATH=automation python3 -m unittest discover -s automation -p 'test_*.py'
python3 -m compileall -q automation
git diff --check
```

四条全绿，结果贴进回执。不提交、不推送——改动留在工作区等验收。

---

## 块2 · 不许动什么

### 全局（三批都适用）

- **不做乐观 UI。** 写入未经校验确认前，不得关闭弹窗、不得显示成功文案、不得把
  `holdingsData` 视为已更新。即时反馈靠 pending 态，不靠假装成功。
  （CLAUDE.md 红线 4：静默降级是头号事故源。）
- **任何"拿不到数据"的分支都必须显式失败或显式标注**，不得返回一个看起来合理的默认值。
  本包里出现三次：批1 第 6 条、批2 第 5 条、批3 第 3 条——三处都不许图省事。
- **测试不许迁就实现。** 断言变红时改实现，不是改断言、不是放宽阈值、不是加 skip。
  确实是断言写错了，停手报告，不要自行改。
- 不许提交、推送、建分支、建 PR。
- 不许把 Token、Gist ID 或任何实时账户数据写进仓库、文档、日志或回执（红线 12）。
- 不许擅自补包里没写的功能，不许删除任何代码或文件（红线 10）。看到该删的，写进回执让人裁决。

### 批1

- `assertNoRemoteChange()` 不许删、不许改成"失败就继续"。它是唯一的跨设备并发保护。
- `verifyEventWritten()` 的语义不许弱化：拿不到内容 = 校验未通过。
- **不许给 PATCH 加 `If-Match` 或任何条件请求头。** Gist 接口不支持，加了会让所有写入
  100% 失败——`js/app.js:234` 的注释记录了这次事故。
- 三个 `<script>` 不许改成 `type="module"`（红线 7）。`file://` 双击打开必须仍可用。
- 不许引入构建步骤、打包器、npm 运行时依赖。
- `buildExecutionEvent()` 产出的字段一个都不许改；execution_events 的 append-only 语义不许改（红线 6）。

### 批2

- **不许碰评分链路。** 不改 `ds_scanner.py`，不改 `score_policy_delta.py` 的聚合/衰减/夹紧逻辑，
  不改 `data/etf_base_config.json`。政策只进四维评分的政策催化位，不碰 `policy` 总分、
  不触发也不压制 `RISK_STOP`、不绕开量比与 MA20 硬条件（红线 5，X-Plan.md 模块 11）。
- `compact_watch_row()` 与 `signal_gap()` 的字段和阈值不许改。
- 既有输出字段 `holdings_risk` / `near_triggers` / `near_downgrades` /
  `active_policy_deltas` / `summary` 的判定条件与含义不许改，**只准新增**。
- **不许放宽 `active_policy_deltas` 的过滤**——`delta == 0` 的主题不进这个列表，
  那会改变"生效"的定义。第 7 条要的是一句解释文案，不是放宽过滤。
- **本批不升方法论版本。** 判断依据：watchlist 是观察展示层，X-Plan.md 未规定其分桶口径，
  评分、等级、操作、仓位一律未动。**不许改 `VERSION.json` / `X-Plan.md` / `Prompt.md`。**
  若你认为必须升版本才能自洽——停手报告，不要自行改（红线 2：不许代码先行、文档追认）。

### 批3

- **不许拆并行 job，不许调整步骤顺序。** 回归测试是"红了后面全不跑"的门禁；
  政策步骤必须排在 `ds_scanner.py` 之前，否则政策永远影响不了当天建议（红线 9）。
- `python -m compileall -q automation/` 必须保留在单测之前，不许合并、不许省略。
  理由写在 `scan.yml:43-45`：单测只覆盖被 import 到的模块，没被导入的文件语法错了单测照样全绿。
- 各 `continue-on-error` 步骤的存在与位置不许改。
- 不许删除任何测试文件，不许从门禁列表里摘掉测试。
- 不许改 Cloudflare Worker 与触发方式（排班由独立私有仓库维护，本仓库只定义被唤醒后的行为）。

---

## 块3 · 材料在哪

仓库：`/Users/srbaby/Projects/XPlan`，分支 `main`，起始状态干净。

### 先读

| 文件 | 什么时候 |
|---|---|
| `CLAUDE.md` | 开工前，红线共 12 条 |
| `docs/03-实现约束.md` | 改任何代码前 |
| `docs/04-开发纪律.md` | 每批交付前 |
| `X-Plan.md` 模块 11（约 528–600 行） | 批2 开工前，政策边界 |

### 已核实的根因锚点（不必重新定位，但要自己确认没被改动过）

批1：
- `js/app.js:1924-1946` `openOperationDialog` —— `await refreshScannerActions()` 在 `showModal()` 之前
- `js/app.js:396-401` `assertNoRemoteChange` —— index + 读 2 文件
- `js/app.js:403-410` `verifyEventWritten` —— 又一次 index + 重读事件文件
- `js/app.js:412-455` `persistExecution` —— 串行编排，`operationSaveInFlight` 在此
- `js/app.js:230-255` `saveData` —— 成功 toast 位置错误，唯一调用方是 `persistExecution`
- `js/app.js:2061-2109` `confirmOperationDialog` —— 提交入口，无 pending 态
- `index.html:408-442` 弹窗 DOM，确认按钮 `data-action="confirm-operation"`

批2：
- `automation/policy_research/compare_policy_decision.py:241-259` —— 分桶，两类被 `continue` 丢弃
- 同文件 `:212-228` `policy_evidence` —— `direction` 在这里产出
- 同文件 `:280-299` —— watchlist 输出形状
- `js/app.js:1031-1073` `renderPolicyWatch`
- `js/app.js:1075-1099` `policyDeltaEvidence` —— `direction` 在这里被丢掉
- `js/app.js:1101-1118` `policyWatchRows`
- `automation/policy_research/score_policy_delta.py:40-47` —— `direction` 取值域

批3：
- `.github/workflows/scan.yml:18-39`、`.github/workflows/observe.yml:18-30` —— 缓存键与安装
- `js/app.js:184-197` `loadInsightData` —— 多余的第二次 `index()`

### 使用限制

- `data/*.json` 是历史快照，**不是实时状态**。实时状态只在 Gist。
- **真实 Gist 只读核验，未经明确授权不得写入**（红线 11）。批1 不要拿真实 Gist 做写入验证——
  用测试替身。
- `data/policy_research/{raw,events,deltas,reports,snapshots}` 已 gitignore，本地大概率不存在。
  批2 的测试自己造夹具，不要依赖真实运行产物。
- 前端测试用 `node:vm` 把 `api.js` / `decision.js` / `app.js` 按 index.html 的顺序注入同一全局作用域
  （见 `js/test_app.js:20-47`）。新增的 DOM 依赖要在那个 `context.document` 桩里能跑通，
  否则测试会以 `getElementById: () => null` 的形式静默走空分支。

---

## 块4 · 可以自己定什么

- CSS 类名、所有用户可见文案的措辞、pending 态的具体视觉。
- 两个新分组的实现方式（复用 `compact_watch_row` 还是抽公共函数）。
- `requirements.txt` 的版本钉法（`==` 还是 `>=`），只要缓存能稳定命中且 scan 能跑。
- 测试的组织方式与用例命名。
- `index.html` 末尾三个 `?v=` 查询串的新值——改了 `js/*.js` 就该递增（用途见 `index.html:444-448`）。
- 批内的实现顺序。

**块2 没写到的，一律你自己定。** 上面只列容易误判的地方，不是穷举。

---

## 块5 · 什么时候停手

出现以下任一情况，停下来写进回执，不要自行决定：

1. 要改 `VERSION.json` / `X-Plan.md` / `Prompt.md` 才能继续。
2. 要改 `ds_scanner.py` 的评分逻辑、或要回写 `etf_base_config.json` 才能继续。
3. 要写真实 Gist 才能验证。
4. 要引入构建步骤、打包器或 npm 运行时依赖才能继续。
5. 门禁测试无法在不放宽断言的前提下变绿。
6. 发现某条完成条件与块2 的冻结项或 CLAUDE.md 红线冲突。
7. 做某一批时发现另一批的前提被推翻（例如批1 的改动使批2 的锚点失效）。
8. 块3 列的某个锚点与实际代码对不上——说明仓库已变化，先报告再动。

停手时保留已完成的部分，不要回滚。
