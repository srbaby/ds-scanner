# receipt_v2_b1 ｜ handoff_v2 ｜ 批1回执

## 做完哪些

- 买入抽屉 `openDrawer()` 先打开抽屉，再异步刷新当日扫描器清单；刷新期间确认按钮禁用，`#new-reason-status` 显示明确的加载中文案。
- 扫描器刷新成功或失败后都会恢复确认按钮可点；刷新失败记录为网络失败状态，不会把买入入口永久锁死。
- `addHolding()` 通过现有逐项校验后立即进入 pending：确认按钮显示“正在登记…”，确认与取消同时禁用；写入成功或失败后恢复。
- 保留原有代码、数量、100 份整数倍、成本、资金、日期、依据校验，以及成功后的自动关闭行为。
- 为买入抽屉按钮增加稳定 DOM id，并在 `js/test_app.js` 覆盖抽屉开启顺序、刷新在途/失败恢复、提交 pending/成功失败恢复。

## 做了哪些判断和取舍

- 禁用状态只用于扫描器刷新和写入在途，不把依据有效性变成常驻禁用，避免用户输入代码后得到无法解释的死按钮。
- 取消按钮在扫描器刷新期间保持可用，允许用户在网络请求未完成时退出；只有写入 pending 时才与确认按钮一起禁用。
- 使用前端 `node:vm` 测试替身验证异步时序，没有进行真实 Gist 写入实验。

## 确定性检查

- `npm run test:frontend`：通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache PYTHONPATH=automation python3 -m unittest discover -s automation -p 'test_*.py'`：127 项通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache python3 -m compileall -q automation`：通过。
- `git diff --check`：通过。

## 哪里偏了 / 哪里停了

- 无完成条件偏差；没有真实 Gist 写入、提交或推送。

## 改了哪些文件

- `js/app.js`
- `js/test_app.js`
- `index.html`
