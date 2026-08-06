# receipt_v2_b3 ｜ handoff_v2 ｜ 批3回执

## 做完哪些

- `persistExecution()` 区分 PATCH 本身失败与 PATCH 成功但 `verifyEventWritten()` 失败。
- PATCH 本身失败继续回滚 `holdingsData`、`executionEvents`、`dataManifest`，状态和提示为“未写入”。
- PATCH 已成功但写后校验失败时保留本地台账状态，不显示成功提示，不关闭入口；状态显示“已提交，校验未完成”，并提示“已提交、校验未完成，请刷新确认且不要重复提交”。
- 为 warn 状态和 warn toast 补充视觉样式；前端测试覆盖两条失败路径，并断言校验失败路径的本地状态未回滚。
- 未放宽 `verifyEventWritten()` 的判定、未删除 `assertNoRemoteChange()`，也未自动重试写入。

## 做了哪些判断和取舍

- PATCH 返回成功只说明远端接受了写入；校验结果不确定时如实保留“不确定”语义，避免用户因“未写入”提示再次提交造成 append-only 台账重复事件。
- 校验失败路径复用当前本地渲染以展示已提交状态，但不把它转换成成功态，也不自动刷新或静默修复。

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
- `css/style.css`
- `docs/03-实现约束.md`
