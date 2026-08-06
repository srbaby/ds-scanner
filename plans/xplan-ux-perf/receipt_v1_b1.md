# receipt_v1_b1 ｜ handoff_v1 ｜ 批1回执

## 做完哪些

- 操作弹窗先 `showModal()`，再等待 `refreshScannerActions()`；刷新期间确认按钮禁用，依据区域显示“正在刷新今日扫描器清单，请稍候…”。刷新完成后按三态结果恢复或继续禁用确认按钮。
- 确认登记进入 pending：确认按钮变为“正在登记…”，确认与取消同时禁用；写入成功或失败后恢复。`operationSaveInFlight` 仍保留为并发兜底，但不再对重复提交发红色 error toast。
- `saveData()` 不再提前显示成功提示；`persistExecution()` 只有在写后校验找到事件 ID 后显示一次“✅ 操作已登记”。
- 写后校验优先读取 PATCH 响应中的未截断事件文件；文件缺失或 `truncated` 时回退到 `index()` + `readFile()`，拿不到内容不通过。

## 做了哪些判断和取舍

- pending 只作用于操作弹窗，不影响买入抽屉、资金编辑等其他入口；取消在加载扫描器时仍可用，避免网络请求阻塞退出。
- `saveData()` 返回 PATCH 后的 Gist 对象，由唯一调用方 `persistExecution()` 传入校验；没有引入额外请求头，也没有改变事件字段或 append-only 台账。
- 按冻结包的逻辑往返口径，旧路径为 `assertNoRemoteChange` + PATCH + 写后重读校验共 3 次；正常新路径为 2 次；PATCH 响应截断/缺失回退为 3 次。前端替身测试直接观测到内联路径 `index/readFile=0/0`、回退路径 `1/1`。

## 确定性检查

- `npm run test:frontend`：通过；新增覆盖弹窗开启顺序、加载禁用态、提交 pending/恢复、PATCH 内联校验和截断回退。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache PYTHONPATH=automation python3 -m unittest discover -s automation -p 'test_*.py'`：127 项通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache python3 -m compileall -q automation`：通过。
- `git diff --check`：通过。

## 哪里偏了 / 哪里停了

- 没有真实 Gist 写入验证，按冻结包使用前端测试替身。
- 首次执行裸 `python3 -m compileall -q automation` 被本机 macOS Python 试图写入受限的 `~/Library/Caches/com.apple.python` 拦截；使用临时 `PYTHONPYCACHEPREFIX` 重跑同一语法门禁通过。无源码语法错误。
- 无需停手条件。

## 改了哪些文件

- `js/app.js`
- `js/test_app.js`
- `index.html`
- `docs/03-实现约束.md`
