# [已归档] X-Plan Gemini API 验证与转正方案

> **归档说明（2026-07-10）**：Gemini 转正评估已放弃，不再推进。当前状态：
> - `automation/gemini_reliability_check.py` 代码保留，但 `.github/workflows/scan.yml` 不再调用它，日常流程没有 Gemini 验证步骤，也不发送 Gemini 相关 Bark 推送。
> - 正式 AI provider 仍然只有 DeepSeek（见 `automation/ai_review.py`）。
> - 本文件原为根目录 `Gemini_API_验证与转正方案.md`，因内容已与实际代码/工作流脱节而移到这里存档；如果未来重启 Gemini 转正评估，可以参考下面的原始方案，但需要先核对代码现状再执行，不要直接照搬。

---

# X-Plan Gemini API 验证与转正方案（原文，已过期）

**创建日期：** 2026-07-02
**状态：** 影子验证阶段（已于 2026-07-10 放弃推进，见上方归档说明）
**目标：** 验证 Gemini API 是否足够稳定，可在未来替代当前正式 AI 分析 provider

---

## 1. 当前结论

X-Plan 当前正式 AI 分析仍使用 DeepSeek，Gemini API 先作为影子验证运行。

影子验证只回答三个问题：

```
1. Gemini API 今天是否可达？
2. Gemini 是否能按 Prompt.md 输出合格的操作清单？
3. Gemini 的耗时是否适合 14:55 尾盘窗口？
```

影子验证不替代正式分析、不写入看板、不改变任何交易建议。

---

## 2. 每日链路

GitHub Actions 顺序：

```
1. ds_scanner.py 生成 report.txt
2. generate_dashboard.py 调用正式 DeepSeek 分析并写入 dashboard.json
3. send_report.py 推送原始扫描报告 Bark
4. gemini_reliability_check.py 调用 Gemini API 并独立推送验证结果 Bark
```

关键原则：

```
原扫描报告优先。
Gemini 验证失败不得阻塞原 Bark 报告。
Gemini 验证失败不得影响 dashboard.json。
```

---

## 3. Gemini 验证范围

验证脚本：`automation/gemini_reliability_check.py`

输入：

```
Prompt.md
report.txt
```

API：

```
POST https://generativelanguage.googleapis.com/v1beta/interactions
Header: x-goog-api-key: $GEMINI_API_KEY
```

默认模型：

```
GEMINI_MODEL=gemini-3.5-flash
```

模型可通过环境变量覆盖，不写死在业务规则里。

---

## 4. 验证指标

每日记录并推送：

| 字段 | 含义 |
|---|---|
| `ok` | API 是否成功返回 |
| `model` | 实际调用模型 |
| `latency_ms` | API 耗时 |
| `text_length` | 回复长度 |
| `format_ok` | 回复格式是否合格 |
| `action_count` | 操作清单动作行数量 |
| `error_snippet` | 失败时的错误摘要 |

格式合格要求：

```
1. 回复非空
2. 包含【操作清单】
3. 包含表头：类型 | 代码 | 名称 | 数量 | 说明
4. 至少一行以 SELL / BUY / HOLD / SKIP / ADD 开头
```

若回复中出现旧系统名，记录为命名警告。

---

## 5. Bark 推送

Gemini 验证使用独立 Bark 推送，不合并进扫描报告。

成功标题：

```
✅ X-Plan Gemini API OK YYYY-MM-DD
```

失败标题：

```
⚠️ X-Plan Gemini API FAIL YYYY-MM-DD
```

成功推送等级：

```
active
```

失败推送等级：

```
timeSensitive
```

正文包含：

```
模型
耗时
格式验证结果
动作行数
回复长度
首条动作预览
错误摘要（失败时）
```

---

## 6. 转正标准

Gemini API 转为正式 provider 前，至少满足：

```
1. 连续 5 个交易日 API 调用成功
2. 连续 5 个交易日 format_ok=true
3. 没有明显漏判持仓止损信号
4. 没有明显漏掉三道金牌已通过且评分 >=75 的候选
5. 常规耗时稳定，不影响 14:55-15:00 决策窗口
```

人工判断口径：

```
只看是否能支持每日一眼决策，不追求文字风格最优。
若 Gemini 输出比 DeepSeek 更简洁、更稳定、更少误判，可考虑转正。
若 Gemini 经常格式漂移，即使内容不错，也不转正。
```

---

## 7. 转正方案

转正时只做 provider 切换，不改变方法论：

```
Prompt.md 仍是唯一每日 AI Core Prompt。
X-Plan.md 仍是方法论正本。
report.txt 输入结构不变。
dashboard.json 输出结构尽量保持兼容。
```

推荐转正方式：

```
1. 在 ai_review.py 中新增 Gemini 正式调用函数
2. 增加 XPLAN_AI_PROVIDER 环境变量
3. 默认 XPLAN_AI_PROVIDER=gemini
4. DeepSeek 调用函数保留为 fallback
5. generate_dashboard.py 读取 provider 结果，不直接关心底层模型
```

转正后的 provider 策略：

```
主 provider：Gemini
备用 provider：DeepSeek
```

失败兜底：

```
Gemini 调用失败 → 自动尝试 DeepSeek
Gemini 格式不合格 → dashboard 标注警告，可人工读原 report 兜底
双 provider 都失败 → report 原文照常 Bark 推送
```

---

## 8. 回滚方案

若 Gemini 转正后出现连续异常：

```
1. 将 XPLAN_AI_PROVIDER 改回 deepseek
2. 保留 Gemini 影子验证 step
3. dashboard 与 Bark 报告不需要结构性回滚
4. 复核异常原因后再决定是否重新转正
```

触发回滚的情况：

```
连续 2 个交易日 API 调用失败
连续 2 个交易日 format_ok=false
出现一次明确漏判价格止损或逻辑止损
尾盘窗口内明显超时，影响人工决策
```

---

## 9. 环境变量

当前影子验证阶段需要：

```
GEMINI_API_KEY      必填，GitHub Actions secret
GEMINI_MODEL        可选，默认 gemini-3.5-flash
BARK_KEY            必填，现有 Bark 推送 key
BARK_KEY_WIFE       可选，第二接收方
```

未来转正阶段新增：

```
XPLAN_AI_PROVIDER   gemini / deepseek
```

---

## 10. 暂不做的事

本阶段不做：

```
1. 不把 Gemini 分析写入 dashboard.json
2. 不改前端看板
3. 不做 Gemini / DeepSeek 双模型并排展示
4. 不让 Gemini 结果参与真实交易建议
5. 不新增人工周末复盘义务
```

---

## 11. 参考

- Gemini API Text generation: https://ai.google.dev/gemini-api/docs/text-generation
- Gemini API Models: https://ai.google.dev/gemini-api/docs/models
