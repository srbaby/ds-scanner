# receipt_v3_b1 ｜ issues_v2 问题1 ｜ 直接修复回执

执行方：High（用户指示"你自己搞定"，未另出 handoff_v3——交接包的作用是把上下文交给没有记忆的执行者，
自己执行时它只是仪式）。范围严格限定为 `issues_v2.md` 问题 1，未做任何范围外改动。

## 做完哪些

- 新增模块级标志 `writeVerificationUnresolved`，在 `persistExecution()` 的
  "PATCH 成功但写后校验失败"分支置位。
- 锁下在两处：
  1. **按钮状态**：`setOperationDialogPending()` / `updateOperationDialogConfirmState()` /
     `setOperationDialogLoading()` / `setBuyDrawerPending()` / `setBuyDrawerLoading()`
     在标志置位时保持确认按钮 disabled，文案改为「请刷新页面」。取消按钮**不锁**，用户随时可退出。
  2. **`persistExecution()` 入口**：标志置位时直接拒绝并提示，不发任何请求。
     这一层覆盖"取消后重开抽屉"以及 `saveCash()` / `saveCard()` / `reverseExecution()`
     这些没有 pending 按钮的写入入口。
- `docs/03-实现约束.md` 补写这条约束及其原因（为什么只弹提示不够）。
- `index.html` 的 `?v=` 递增到 `20260806c`。

## 做了哪些判断和取舍

- **锁到刷新为止，而不是锁一次。** 这条路径下本地与远端是否一致无法确证，
  唯一能重建事实的动作是刷新页面。没有做"自动重试"或"自动重新拉取后静默恢复"——
  那正是会写出第二条事件的动作，`handoff_v2` 块2 也明令禁止。
- **取消按钮保持可用。** 锁的目的是防重复写入，不是把用户困在弹窗里。
- **没有新增 DOM 元素或横幅。** 按钮文案「请刷新页面」＋两条提示已足够解释，
  加横幅属于范围外补功能（红线 10）。
- **操作弹窗那侧也一并锁上。** `issues_v2` 认定它被 `validateOperationInput()`
  的份额校验"碰巧挡住"；碰巧不是保护，两个入口用同一把锁。
- 标志命名为"unresolved"而非"failed"：语义是"结果未知"，不是"失败"，
  与批3 确立的"不归入成功或失败任一边"一致。

## 确定性检查

- `npm run test:frontend`：通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache PYTHONPATH=automation python3 -m unittest discover -s automation -p 'test_*.py'`：
  `Ran 127 tests` / `OK`。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache python3 -m compileall -q automation`：通过。
  （裸跑会被 macOS 缓存目录权限拦截，沿用 v1/v2 的 `PYTHONPYCACHEPREFIX` 办法。）
- `git diff --check`：通过。

### 变异测试（确认新测试不是摆设）

把 `writeVerificationUnresolved = true;` 注释掉后重跑前端测试：
`ERR_ASSERTION actual: false, expected: true` —— 测试确实会红。随后已还原并复跑全绿。

新增断言覆盖：标志置位、两个入口的按钮禁用与文案、取消按钮仍可用、
`persistExecution()` 在锁生效期间拒绝且**未调用 `saveData()`**。

## 哪里偏了 / 哪里停了

- 中途一次前端测试因我把 `document.getElementById` 桩收窄，导致早前抽屉用例遗留的
  300ms `focus()` 定时器取到 null 而崩溃。已改回让桩继续覆盖 `buyNodes`/`operationNodes`。
  这是测试脚手架问题，与被测逻辑无关。
- 无停手条件。未提交、未推送。

## 改了哪些文件

- `js/app.js`
- `js/test_app.js`
- `index.html`
- `docs/03-实现约束.md`
