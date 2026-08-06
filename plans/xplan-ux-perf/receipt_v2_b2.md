# receipt_v2_b2 ｜ handoff_v2 ｜ 批2回执

## 做完哪些

- 新增 `requirements-observe.txt`，仅声明 `requests>=2.31`；`automation/observe.py` 的观察工作流改为安装该清单。
- `observe.yml` 的 pip 缓存键改为依赖清单，不再依赖 `automation/*.py` 或 `VERSION.json`。
- `scan.yml` 保持 v1 的 `requirements.txt`、缓存键、步骤顺序和门禁不动。
- `loadInsightData()` 恢复每次调用都读取 `gistClient.index()`，不复用旧 `gistIndex`；`loadData()` 与 `refreshScannerActions()` 未随之改动。
- 在 `docs/03-实现约束.md` 记录了洞察页刻意不复用索引及其新鲜度理由；前端测试覆盖连续两次调用均重新索引。

## 做了哪些判断和取舍

- 观察任务采用独立依赖清单，避免安装扫描链路的 pandas、akshare 等重依赖；缓存仍只由该清单驱动。
- 洞察页保留一次页面加载守卫，但不为节省一次会话请求而复用可能过期的初始索引快照。

## 确定性检查

- `npm run test:frontend`：通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache PYTHONPATH=automation python3 -m unittest discover -s automation -p 'test_*.py'`：127 项通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache python3 -m compileall -q automation`：通过。
- `git diff --check`：通过。

## 哪里偏了 / 哪里停了

- 无完成条件偏差；没有真实 Gist 写入、提交或推送。

## 改了哪些文件

- `.github/workflows/observe.yml`
- `requirements-observe.txt`
- `js/app.js`
- `js/test_app.js`
- `docs/03-实现约束.md`
