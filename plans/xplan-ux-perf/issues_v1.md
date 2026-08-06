# issues_v1 ｜ handoff_v1 三批验收

验收人：High2。回执 `receipt_v1_b1/b2/b3` 已读。
确定性检查（前端测试 / 127 项 Python 测试 / compileall / diff check）采信执行方结果，未重跑。

## 总体结论

**块2 冻结项无违反**，逐条核对如下：

| 冻结项 | 结果 |
|---|---|
| 不做乐观 UI，写入未确认前不关窗、不显示成功文案 | ✅ 成功 toast 移到 `verifyEventWritten()` 之后，弹窗仍在校验后才关 |
| 三处"拿不到数据"必须显式失败或标注 | ✅ 三处全部正确落地，见下 |
| `assertNoRemoteChange` 不删不弱化 | ✅ 未改 |
| 不加 `If-Match` 等条件请求头 | ✅ 未加 |
| 不改 `type="module"`、不引入构建步骤 | ✅ 未改 |
| `buildExecutionEvent` 字段、append-only 语义 | ✅ 未改 |
| 不碰评分链路 / `etf_base_config.json` | ✅ 未改 |
| 既有五个 watchlist 字段只增不改 | ✅ 只新增 `holdings_boost` / `pool_weakening` 及两个计数 |
| 不放宽 `active_policy_deltas` 过滤 | ✅ 未放宽，第 7 条按文案解释实现 |
| 不升方法论版本 | ✅ `VERSION.json` / `X-Plan.md` / `Prompt.md` 均未动 |
| 不拆并行 job、不动步骤顺序与 `continue-on-error` | ✅ 未动，compileall 仍在单测之前 |
| 测试不迁就实现 | ✅ 未见放宽断言或 skip |

三处"拿不到数据"分支单独核实：
- `verifyEventWritten()`：`patchedFile.truncated !== true && typeof content === 'string'` 双条件，
  任一不满足即回退重读，**没有跳过校验的路径**。✅
- `policyDirectionLabel()`：`positive/negative/mixed` 之外一律 "方向未标注"，未猜默认值、未默认按正向渲染。✅
- `loadInsightData()`：显式判非空对象，空则照常 `index()`。✅

执行方两处主动偏离，**均判定为合理**：
- 新分组测试放在 `automation/test_compare_policy_decision.py` 而非包里指定的
  `test_policy_research.py`。理由（该文件不能直接导入 compare）经核属实，且块4 允许自定测试组织方式。
- 依赖用 `>=` 下限而非精确钉版。块4 明确允许。

---

## 问题清单

**三条问题全部出在冻结包本身，不是执行偏差。** 执行方对其中两条已在回执中照实报告了取舍。

### 问题 1 · observe 工作流依赖膨胀（真实效率退步）

`observe.yml` 原本只装 `requests`，现改为 `pip install -r requirements.txt`，
连带装入 `pandas` / `akshare` / `lxml` / `beautifulsoup4`。
经核 `automation/observe.py` 顶层只依赖 `requests` 与本地 `versioning`，其余全是标准库。
夜间观察任务因此每次多装一批重依赖，**与批3「提效」的目的相反**。

- 涉及块1：批3 第 1 条
- 定性：**本该冻结却漏了**。该条同时写了"钉住 scan 链路依赖"和"两个 workflow 都指向该清单"，
  这两句自相矛盾；执行方按字面执行无误。

### 问题 2 · 买入建仓抽屉没有 pending 态

块1 批1 第 1 条只列了「加仓 / 减仓 / 清仓 / 更正依据」四个入口，这四个都走 `operation-dialog`。
买入建仓走的是抽屉（`submitNew` → `persistExecution` → `closeDrawer`），**未纳入范围**：
点确认后按钮无变化、不置灰，仍存在误点与重复点击的观感问题。
写入往返数已随 `verifyEventWritten` 优化而减少，但交互反馈没有。

- 涉及块1：批1 第 1、3 条（范围界定遗漏）
- 定性：**本该写进块1 却漏了**。执行方在 `receipt_v1_b1` 判断项里已照实声明该取舍。
- 备注：用户的原始诉求是"交易操作"，买入是其中最重要的一类，这个遗漏是我定范围时的失误。

### 问题 3 · 长开标签页首次进洞察页会读到过期快照（低）

`loadInsightData()` 改为复用 `gistIndex`。该函数只在 `!statsData` 时触发，即每次页面加载最多一次，
所以绝大多数情况下索引只有秒级到分钟级的年龄，无影响。
仅在「标签页开了很久、期间从未点过洞察页、其间 Actions 更新了 stats.json / report.txt」
这一窄场景下，会读到页面加载时的旧快照；旧代码每次 `index()` 可拿到新的。
已有 8 小时 stale-banner 部分兜底。

- 涉及块1：批3 第 3 条
- 定性：**本该写进块1 却漏了**——该条没有区分"省一次请求"与"洞察数据的新鲜度要求"。

---

## 观察项（非本次缺陷，不要求改）

`persistExecution()` 走 truncated 回退路径时，若 `verifyEventWritten()` 抛错，
PATCH 其实已经成功、远端已写入，但代码会回滚本地状态并提示"❌ 未写入"。
**这是改动前就存在的行为，本次既未引入也未修复**，且不在块1 范围内。
按红线 10 只记录、不擅自动。是否处理由用户裁决。

---

## 处置建议

问题 2 是用户原始诉求的一部分，建议补做。问题 1 修法简单（observe 独立依赖清单或恢复 `pip install requests`）。
问题 3 可暂不处理，留待观察。

三条都触及块1 完成条件的定义本身，按流程需要重新 `go规划` 出 `handoff_v2`，
不能让执行方在 v1 边界内自行扩张。当前工作区改动可保留，v2 在其基础上增量。
