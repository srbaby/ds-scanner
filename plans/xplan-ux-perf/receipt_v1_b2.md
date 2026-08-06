# receipt_v1_b2 ｜ handoff_v1 ｜ 批2回执

## 做完哪些

- `build_policy_watchlist()` 新增 `holdings_boost` 与 `pool_weakening`，分别接收持仓 `delta>0`、非持仓 `delta<0`，两组均复用既有 `sort_key` 并限制 5 条。
- `summary` 只新增 `holdings_boost_count`、`pool_weakening_count`；既有分组和字段保持不变。
- 前端新增“持仓政策转强”“池内政策转弱”两组；主题 chip 显示“正向/负向/方向未标注”文字；事件依据显示“正向/负向/混合/方向未标注”。五组均为空但存在活跃主题偏移时显式说明未落到池内标的。
- 补充 6+6 夹具验证新分组进桶与 5 条上限，并补充方向域测试；前端覆盖两个新分组的实际渲染、五组为空时的解释，以及三种方向和缺失/非法值。

## 做了哪些判断和取舍

- 保留既有 `near_downgrades` 分支在前：持仓正向偏移但等级降级时仍归入原有“持仓信号降级”，避免改变既有分组含义；其余持仓正向行才进入 `holdings_boost`。
- 新组样式复用现有 `trigger` / `risk` tone，不新增 CSS 口径。
- `policy_research/test_policy_research.py` 没有直接导入 compare 模块，因为 `docs/03-实现约束.md` 明确禁止该文件采用会触发顶层相对导入错误的方式；新分组的直接夹具测试放在已有的 `automation/test_compare_policy_decision.py`，该测试覆盖完整 compare 包路径；同名 policy 测试补充了 positive/negative/mixed/unknown 域行为。

## 确定性检查

- `npm run test:frontend`：通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache PYTHONPATH=automation python3 -m unittest discover -s automation -p 'test_*.py'`：127 项通过。
- `PYTHONPYCACHEPREFIX=/tmp/xplan-pycache python3 -m compileall -q automation`：通过。
- `git diff --check`：通过。
- 未修改 `ds_scanner.py`、`score_policy_delta.py` 聚合逻辑、`data/etf_base_config.json`、`X-Plan.md`、`VERSION.json`、`Prompt.md`。

## 哪里偏了 / 哪里停了

- 本地没有依赖真实政策运行产物，测试使用夹具，符合冻结包使用限制。
- 无需停手条件。

## 改了哪些文件

- `automation/policy_research/compare_policy_decision.py`
- `automation/test_compare_policy_decision.py`
- `automation/policy_research/test_policy_research.py`
- `js/app.js`
- `js/test_app.js`
