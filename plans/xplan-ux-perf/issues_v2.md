# issues_v2 ｜ handoff_v2 三批验收

验收人：High2。回执 `receipt_v2_b1/b2/b3` 已读。
确定性检查（前端测试 / 127 项 Python 测试 / compileall / diff check）采信执行方结果，未重跑。

## 总体结论

**块2 冻结项无违反**（含 `handoff_v1.md` 块2 全部继续生效的部分），**块1 完成条件 13 条全部满足**。

| 冻结项 | 结果 |
|---|---|
| 买入确认按钮不许"依据无效就常驻禁用" | ✅ `setBuyDrawerLoading` / `setBuyDrawerPending` 只在刷新在途、写入在途时禁用 |
| `addHolding()` 逐项校验一条不许删 | ✅ 代码/数量/100 份整数倍/成本/资金/日期/依据 七条全在，阈值未动 |
| 不动 `onSymbolInput()` / `selectSuggest()` / `fillReasonSelect()` | ✅ 未改 |
| 缓存键不许挂回业务源文件 | ✅ `observe.yml` 指向 `requirements-observe.txt` |
| `scan.yml` 一律不动 | ✅ 与 v1 状态一致，不在本批改动文件清单内 |
| 撤销索引复用只限 `loadInsightData()` | ✅ `loadData()` / `refreshScannerActions()` 未动 |
| `verifyEventWritten()` 判定标准不许放松 | ✅ 只改失败后的处置，判定本身未动 |
| 不许自动重试、不许静默修复 | ✅ 无重试、无自动拉取 |
| 不许在校验失败路径关窗 / 显示 ✅ / 设 ok 态 | ✅ 返回 `false`，调用方不会关；状态为 `warn` |
| 不做乐观 UI | ✅ 校验失败如实报告不确定，未归入成功或失败任一边 |
| 不升方法论版本 | ✅ `VERSION.json` / `X-Plan.md` / `Prompt.md` 未动 |

关键实现逐条核实：
- `openDrawer()`：`setBuyDrawerLoading(true)` → 打开抽屉 → `await refreshScannerActions()`，
  刷新失败被 catch 兜住，`fillReasonSelect` 放在 `try/finally` 里，**不会把入口锁死**。✅
- `addHolding()`：校验全部为同步操作，通过后立即 `setBuyDrawerPending(true)`，
  `finally` 恢复。校验失败时按钮不闪 pending，比弹窗那套更干净。✅
- `persistExecution()`：`patchSucceeded` / `verificationSucceeded` 两个标志分开，
  catch 里先判"PATCH 成功但校验失败"→ 不回滚、warn 状态、warn toast；
  否则才走原有回滚三件套。✅
- `loadInsightData()`：恢复每次 `index()`，并在代码注释与 `docs/03-实现约束.md` 双处写明
  刻意不复用的理由。✅

执行方两处判断，**均判定为合理**：
- 取消按钮在扫描器刷新期间保持可用（只在写入 pending 时才一并禁用）——与 v1 弹窗做法一致。
- observe 采用独立依赖清单 `requirements-observe.txt`，块4 明确授权。

---

## 问题清单

### 问题 1 · 校验失败后确认按钮被重新启用，买入抽屉可重复提交（中）

`persistExecution()` 走"PATCH 成功但校验失败"分支时返回 `false`，
调用方的 `finally` 随即执行 `setBuyDrawerPending(false)` / `setOperationDialogPending(false)`，
把确认按钮恢复成可点。而此路径下：

- `gistFileContents` 在 `saveData()` 成功时已同步为写入后的内容，
  所以再次提交时 `assertNoRemoteChange()` **比对通过、不会拦截**；
- 本地 `executionEvents` 与 `holdingsData` 按设计**没有回滚**。

后果分两种：

- **买入抽屉（`addHolding()`）：无任何拦截。** 再点一次「确认买入」会命中"已有持仓"确认框，
  然后**在已更新的持仓上再加一次份额**，并向 append-only 台账写入第二条 BUY/ADD 事件。
  这正是批3 设立的目的所要防止的结果。
- **操作弹窗（`confirmOperationDialog()`）：碰巧被拦住。** `validateOperationInput()` 会因
  "剩余份额必须小于当前持仓"或"加仓后总份额必须大于当前持仓"报错。
  但这是输入校验的副作用，不是设计出来的保护，不能当作已解决。

用户在这条路径上看到的是一句 2.5 秒的 ⚠️ 提示，而按钮就在眼前可点——
对一个被告知"校验未完成"的人来说，再点一次确认是很自然的反应。

- 涉及块1：批3 第 11 条
- 定性：**本该写进块1 却漏了**。该条规定了不回滚、不显示成功、不关闭入口、给出区分提示，
  但**没有规定这之后确认按钮该处于什么状态**。执行方按冻结项实现无误，块2 也未禁止恢复按钮。
- 参考修法（供下一轮规划参考，非本轮结论）：这条路径下弹窗/抽屉里已无任何合法操作可做——
  写入已落地、本地状态已正确——确认按钮保持禁用并提示刷新即可，取消仍可用，不会困住用户。

---

## 观察项（无需处理）

无。v1 遗留的观察项（校验失败误报"未写入"）已由本轮批3 解决。

---

## 处置建议

只有一个问题，且集中在一个函数的一条分支上。它触及块1 第 11 条的定义本身，
按流程需要 `handoff_v3` 增量，不能让执行方在 v2 边界内自行扩张。
当前工作区改动可保留，v3 在其基础上增量。

若判断该场景发生概率足够低、愿意先带着它上线，也可以直接进入提交环节——
但那意味着接受"网络抖动 + 用户重点一次"会在交易台账里留下重复事件的残余风险。
这是取舍，不是技术障碍，由用户裁决。
