# handoff_v2 ｜ FROZEN ｜ 买入抽屉反馈 · observe 依赖回退 · 写后校验语义修正

> 接手你的人没有本次对话记忆。
> **本包是 `handoff_v1.md` 的增量**：v1 的三批已完成并通过验收，改动在工作区里（未提交）。
> 开工前必须读：同目录 `handoff_v1.md`（块2、块3 的约束**全部继续生效**）与 `issues_v1.md`（本包的由来）。
> 本包新增的约束写在下面；与 v1 冲突时以本包为准，但 v1 块2 的冻结项本包**没有任何一条解除**。
>
> 3 批，交 `receipt_v2_b<M>.md`。

---

## 块1 · 交什么

### 批1 —— 买入建仓抽屉的即时反馈

v1 只修了 `operation-dialog`（加仓/减仓/清仓/更正依据）。买入建仓走的是抽屉，
入口 `openDrawer()`、提交 `addHolding()`、确认按钮 `data-action="add-holding"`（`index.html:391-396`，无 id）。
它有和修复前的弹窗**完全相同**的两个毛病，本批按同一标准修掉：

1. `openDrawer()` 目前在 `js/app.js:1742` 于打开抽屉前 `await refreshScannerActions()`。
   改为**先打开抽屉、再异步刷新**，点击「买入」后抽屉不等待任何网络请求即出现。
2. 刷新在途期间「确认买入」按钮 disabled，并在 `#new-reason-status` 显示可见的加载中文案；
   刷新落地（成功或失败）后恢复可点。刷新失败不得让抽屉卡在永久禁用态。
3. 点击「确认买入」后**立即**（不等网络）进入 pending：确认按钮 disabled 且文案变化，
   取消按钮同时 disabled。写入结束（成功或失败）两者都恢复。
4. 成功后抽屉自动关闭（现有 `if (await persistExecution(...)) closeDrawer();` 行为保持）。
5. `npm run test:frontend` 绿，新增覆盖：抽屉开启顺序、刷新在途的禁用与恢复、提交 pending 与恢复。

### 批2 —— observe 依赖回退与洞察索引回退

6. `observe.yml` 只安装 `automation/observe.py` 真正需要的依赖。
   已核实：该文件顶层只依赖 `requests` 与本地 `automation/versioning.py`，其余均为标准库。
   现状是 v1 让它装了整份 `requirements.txt`（含 pandas / akshare / lxml / beautifulsoup4），
   夜间观察任务因此白装一批重依赖。
7. `observe.yml` 的 pip 缓存键**必须挂在依赖清单上，不得挂回 `automation/*.py` 或 `VERSION.json`**。
   挂业务源文件正是 v1 批3 要消灭的原始问题——改一行代码就丢缓存。
8. `scan.yml` 的依赖与缓存键保持 v1 现状不动。
9. `loadInsightData()` 恢复为每次调用都 `await gistClient.index()`，**撤销 v1 的索引复用**。
   理由：该函数受 `!statsData` 保护，每次页面加载最多执行一次，省下的是「一次会话一个请求」，
   收益可以忽略；代价是标签页长开时首次进洞察页会读到页面加载时的旧快照。不值得。
10. 在 `docs/03-实现约束.md` 里记一句「此处刻意不复用 `gistIndex`」及理由，
    防止以后再被当成冗余请求优化掉一次。

### 批3 —— 写后校验失败的语义修正

现状（`js/app.js` `persistExecution()` 的 catch 分支）：PATCH 成功之后 `verifyEventWritten()` 若抛错，
代码会**回滚本地状态并提示「❌ 未写入」**。但 PATCH 返回 200 意味着远端已经写入，
用户看到「未写入」很可能重新提交一次，在 append-only 交易台账里**写出重复事件**。
校验的回退分支要重新读取远端，正是最容易被网络抖动打中的地方。

11. 区分两种失败并给出不同处置：
    - **PATCH 本身失败**（`saveData()` 返回假值）：维持现有行为——回滚本地状态、提示未写入。
    - **PATCH 成功但写后校验未通过**：**不得回滚本地状态**（本地已与写入内容一致），
      **不得显示成功提示**，**不得关闭弹窗或抽屉**。必须给出一条与「未写入」明确区分的提示，
      内容要包含三件事：已提交、校验未完成、请刷新确认且不要重复提交。
      `setStatus()` 也要与「未写入」区分。
12. 这条语义写进 `docs/03-实现约束.md`。
13. 前端测试覆盖两条失败路径各自的状态与提示差异，断言「PATCH 成功 + 校验失败」时本地状态未被回滚。

### 每批共同的完成条件

```bash
npm run test:frontend
PYTHONPATH=automation python3 -m unittest discover -s automation -p 'test_*.py'
python3 -m compileall -q automation
git diff --check
```

四条全绿，结果贴进回执。不提交、不推送。

> 注：v1 执行方报告本机裸跑 `compileall` 会被 macOS 缓存目录权限拦截，
> 用 `PYTHONPYCACHEPREFIX` 指到临时目录可绕过。这是本机环境问题，不是代码问题，
> 沿用同样办法即可，但要在回执里照实写明用了什么命令。

---

## 块2 · 不许动什么

**`handoff_v1.md` 块2 的全部冻结项继续生效，本包不解除任何一条。** 尤其重申三条最容易在本包踩到的：

- **不做乐观 UI。** 批3 的核心就是「写入结果不确定时如实说不确定」，
  不许为了界面好看把它归成成功或失败中的任意一边（CLAUDE.md 红线 4）。
- **不许改 `buildExecutionEvent()` 的字段，不许破坏台账 append-only 语义**（红线 6）。
- **不升方法论版本**，不动 `VERSION.json` / `X-Plan.md` / `Prompt.md`（红线 2）。

本包新增：

### 批1

- **买入抽屉的确认按钮不许改成「依据无效就常驻禁用」。** 弹窗那边可以那样做，因为它的依据在打开时就定了；
  抽屉的依据随用户输入代码而变（`onSymbolInput()` → `fillReasonSelect()`），
  常驻禁用会变成一个没有解释的死按钮。禁用只用于两种在途状态：扫描器刷新中、写入中。
  `addHolding()` 现有的逐项校验 toast（代码/数量/成本/资金/日期/依据）**一条都不许删**。
- 不许改 `addHolding()` 的任何校验规则与阈值（含 100 份整数倍）。
- 不许动 `onSymbolInput()` / `selectSuggest()` / `fillReasonSelect()` 的既有行为。

### 批2

- **不许把缓存键挂回业务源文件。** 这是 v1 批3 修掉的原始问题，回退它等于白做。
- 不许改 `scan.yml`（依赖、缓存键、步骤顺序、`continue-on-error` 一律不动）。
- 不许拆并行 job，`compileall` 仍须在单测之前（红线 9 与 `scan.yml:43-45` 的事故注释）。
- 撤销索引复用**只撤销 `loadInsightData()` 这一处**。不许顺手改 `loadData()` 或 `refreshScannerActions()` 的取数方式。

### 批3

- `verifyEventWritten()` 的判定标准不许放松：拿不到内容 = 校验未通过。
  本批改的是**校验失败之后怎么处置**，不是校验本身。
- **不许自动重试写入，不许自动重新拉取后静默"修复"状态。** 这条路径下唯一正确的动作是
  如实告知并让用户刷新确认——自动重试可能在台账里写出第二条事件。
- 不许在这条路径上关闭弹窗/抽屉、不许显示 ✅、不许把 `setStatus()` 设成 ok 态。
- `assertNoRemoteChange()` 不许删不许弱化。

---

## 块3 · 材料在哪

仓库 `/Users/srbaby/Projects/XPlan`，分支 `main`。
**工作区带有 v1 的未提交改动，这是本包的起点，不要 stash、不要还原、不要 `git checkout`。**

### 先读

| 文件 | 何时 |
|---|---|
| 同目录 `handoff_v1.md` | 开工前，块2/块3 全部继续生效 |
| 同目录 `issues_v1.md` | 开工前，本包三批的由来 |
| `CLAUDE.md` | 开工前，12 条红线 |
| `docs/03-实现约束.md` | 改代码前；批2、批3 都要往里写 |
| `docs/04-开发纪律.md` | 每批交付前 |

### 已核实的锚点

批1：
- `js/app.js:1741-1756` `openDrawer()` —— 第 1742 行 `await refreshScannerActions()` 在打开抽屉之前
- `js/app.js:1802` 起 `addHolding()` —— 提交入口，逐项校验 toast 在开头
- `index.html:390-403` 抽屉按钮，**两个按钮都还没有 id**
- 可直接参考 v1 已完成的同类实现：`js/app.js` 的 `setOperationDialogLoading()` /
  `setOperationDialogPending()` / `updateOperationDialogConfirmState()`，
  但**注意上面块2 说的差异**，不要照抄 `hasValidReason` 那条门禁

批2：
- `.github/workflows/observe.yml` —— v1 改成了 `pip install -r requirements.txt`
- `automation/observe.py:22-35` —— 全部 import，可自行复核只需 `requests`
- `js/app.js:184-190` `loadInsightData()` —— v1 加的 `hasGistIndex` 复用逻辑在此
- `js/app.js:2372-2375` —— `!statsData` 守卫，说明该函数每次页面加载最多跑一次

批3：
- `js/app.js` `persistExecution()` —— `saveData()` 返回值判定、`verifyEventWritten()` 调用、
  catch 里的回滚三件套（`holdingsData` / `executionEvents` / `dataManifest`）与 finally
- `js/app.js` `saveData()` —— 成功返回 PATCH 后的 gist 对象，失败返回假值

### 使用限制

- `data/*.json` 是历史快照，实时状态只在 Gist。
- **真实 Gist 只读核验，未经明确授权不得写入**（红线 11）。批1、批3 用前端测试替身验证，
  不要拿真实 Gist 做写入实验——批3 恰恰是"写坏了会在台账里留下重复事件"的路径。
- 不许把 Token、Gist ID 或实时账户数据写进仓库、日志或回执（红线 12）。
- 前端测试用 `node:vm` 按 `index.html` 顺序注入 `api.js` / `decision.js` / `app.js` 到同一全局作用域
  （`js/test_app.js` 开头）。新增 DOM 依赖要能在那个 `document` 桩里跑通，
  否则会以 `getElementById: () => null` 静默走空分支——测试绿了但什么都没测到。

---

## 块4 · 可以自己定什么

- 所有 CSS 类名、用户可见文案的措辞、pending 态与加载态的视觉。
- 批2 中 observe 依赖清单的组织方式（独立文件、命名、放哪），只要满足第 6、7 条。
- 批3 中「区分 PATCH 失败与校验失败」的实现机制（标志位、自定义错误类型、拆 try 块等随你）。
- 新增 DOM id 的命名。
- 测试的组织方式与用例命名。
- `index.html` 末尾 `?v=` 查询串的新值（改了 `js/*.js` 就该递增）。
- 批内实现顺序。

**块2 没写到的一律你自己定。** 上面只列容易误判处，不是穷举。

---

## 块5 · 什么时候停手

1. 要改 `VERSION.json` / `X-Plan.md` / `Prompt.md` 才能继续。
2. 要改 `ds_scanner.py` 评分逻辑或回写 `etf_base_config.json` 才能继续。
3. 要写真实 Gist 才能验证。
4. 要引入构建步骤、打包器或 npm 运行时依赖才能继续。
5. 门禁测试无法在不放宽断言的前提下变绿。
6. 发现某条完成条件与本包块2、`handoff_v1.md` 块2 或 CLAUDE.md 红线冲突。
7. 块3 列的锚点与实际代码对不上——说明工作区已变化，先报告再动。
8. 发现 v1 的改动本身有错，需要改它才能完成本包——**报告，不要顺手改**。
   v1 已通过验收，推翻它要走新一轮规划。

停手时保留已完成的部分，不要回滚。
