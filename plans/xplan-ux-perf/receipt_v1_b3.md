# receipt_v1_b3 ｜ handoff_v1 ｜ 批3回执

## 做完哪些

- 新增 `requirements.txt`，列出 scan 链路依赖 `requests>=2.31`、`pandas>=2.0`、`akshare>=1.12`、`lxml>=4.9`、`beautifulsoup4>=4.12`。
- `scan.yml` 与 `observe.yml` 的 `cache-dependency-path` 均改为 `requirements.txt`，安装均改为 `pip install -r requirements.txt`；扫描工作流仍保留 compileall 在单测之前，政策步骤仍在 `ds_scanner.py` 之前，步骤顺序和 `continue-on-error` 未改。
- `loadInsightData()` 复用非空 `gistIndex`；`gistIndex={}` 时重新调用 `index()`，前端测试覆盖两条路径。

## 做了哪些判断和取舍

- 依赖使用下限约束而非精确版本，减少在 Python 3.11 Actions 环境中因过旧精确版本失效的风险；缓存仍由单一清单内容决定。扫描器业务源文件变化不会再改变缓存依赖文件哈希。
- 没有拆 job、调整步骤顺序、删除测试门禁，也没有改 Cloudflare Worker 或触发方式。

## Actions 耗时对照

- 改动前最近一次实际运行：`scan.yml` run `31078594915`，head SHA `83c679ab69545ead1016ea7b4e5bcab7584f023b`；job 从 `06:49:20Z` 到 `06:51:22Z`，约 122 秒。安装依赖约 12 秒，回归测试约 5 秒，政策研判约 88 秒，扫描约 6 秒。
- 改动后一次 Actions 运行：拿不到。当前改动按冻结要求未提交/未推送，不能触发新 SHA 的 Actions；不估算。
- 缓存失效判据已由工作流静态核对确认：`cache-dependency-path` 不再列扫描器脚本，只指向 `requirements.txt`。

## 确定性检查

- `npm run test:frontend`：通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache PYTHONPATH=automation python3 -m unittest discover -s automation -p 'test_*.py'`：127 项通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache python3 -m compileall -q automation`：通过。
- `git diff --check`：通过。

## 哪里偏了 / 哪里停了

- “改动后 Actions 耗时”因未推送而拿不到，已照实记录，未编造数字。
- 无需停手条件；未提交、未推送、未建分支或 PR。

## 改了哪些文件

- `requirements.txt`
- `.github/workflows/scan.yml`
- `.github/workflows/observe.yml`
- `js/app.js`
- `js/test_app.js`
- `index.html`
