# 死代码候选清单（2026-07-10）

> **性质：事实性扫描结果，不含处理建议。** 只列"扫了什么、用了什么方法、发现了什么"，不删任何代码，给 Opus 审计当现成素材。是否删、怎么删由 Opus 出规格 + 大亨拍板。
>
> 触发背景：用户提到"整个代码有大量 Codex 编写，且很多也没用"，决定等 Opus 最终审计定处理方案，但先做一份纯事实性候选清单。

---

## 方法

对每一类目标做"真实调用点"搜索，而不是简单的文本出现次数（后者会被同名巧合污染，比如所有脚本都有 `def main()`）。每条候选在写进这份清单前都手动复核过上下文，排除了动态拼接类名（如 `` `observer-line-${key}` ``）造成的假阳性。

- **Python**：对 `automation/**/*.py`（不含 test_*）里每个顶层 `def`，在全仓库（.py/.js/.html/.yml/.md）里搜真实调用点 `name(`，排除定义行本身。另外对每个 .py 文件做"文件级可达性"检查：是否被某个 workflow 直接 `python xxx.py` 调用，或被别的 .py `import`。
- **JS**：对 `js/app.js` 里的函数声明（`function foo()` / `const foo = () =>` / `const foo = function` 等形式），在 `js/app.js` + `js/test_app.js` + `index.html` 里搜任意形式的名字出现。
- **CSS**：提取 `css/style.css` 里所有 `.class-name` 选择器，在 `js/app.js` + `index.html` + `js/test_app.js` 里搜字符串是否出现过；对命中"零出现"的，额外人工检查是否是模板字符串动态拼接（`` `prefix-${var}` ``）导致的假阳性。

---

## 确认死代码（真实候选）

### 1. 整个文件：`automation/gemini_reliability_check.py`
- **检查结果**：不被任何 `.github/workflows/*.yml` 直接调用，也不被任何其他 `.py` `import`。
- **已知背景**：这不是新发现——2026-07-10 之前就已经确认 Gemini 自动转正评估放弃推进，`scan.yml` 早就不再调这个脚本了（详见 [`plans/gemini-api-shadow-archive.md`](gemini-api-shadow-archive.md)）。这次只是用机械扫描重新验证了一遍，结果一致。
- **代码本身**：未删除，仍在仓库里。

### 2. JS 函数：`removeCardWithAnimation()` — [js/app.js:1712](../js/app.js#L1712)
- **检查结果**：在 `js/app.js`、`js/test_app.js`、`index.html` 三个文件里都搜不到任何调用点。
- **上下文**：注释写"卡片退出动画：先加 exit 类，动画结束后再执行回调"，函数体给 `card-${idx}` 元素加 `.exit` class 再延时 200ms 执行回调——看起来是一个"删除前先播放退出动画"的功能，但从未被实际的删除/清仓流程调用。
- **关联的死 CSS**（见下）：`.holding-card.exit`，两者是一对，功能大概率是半成品或被放弃的方案。

### 3. CSS 规则：`.holding-card.exit` — [css/style.css:677](../css/style.css#L677)
- **检查结果**：`.exit` 这个 class 在 `js/app.js` / `index.html` 里唯一的来源就是上面第2条的 `removeCardWithAnimation()`，而那个函数本身没有调用点。两者互为因果地成为死代码。

### 4. CSS 规则：`.btn-danger` + `.btn-danger:active` — [css/style.css:330-335](../css/style.css#L330)
- **检查结果**：`js/app.js` 和 `index.html` 里搜不到 `btn-danger` 这个字符串（静态或拼接都没有）。
- **对照**：实际"危险操作"按钮（撤销登记）用的是裸 `class="danger"`（[js/app.js:1894](../js/app.js#L1894)），由另一条规则 `.execution-buttons button.danger`（[css/style.css:528](../css/style.css#L528)）负责样式。`.btn-danger` 看起来是命名规范变更后遗留的旧版本，从未清理。

### 5. CSS 规则：`.card-actions` — [css/style.css:1877](../css/style.css#L1877)
- **检查结果**：`js/app.js` / `index.html` 里没有任何元素带这个 class（静态字符串、模板拼接、`classList.add` 都搜过，没有命中）。

### 6. CSS 规则：`.card-secondary-actions` — [css/style.css:821](../css/style.css#L821)（另有响应式媒体查询覆盖在 1724-1729 行）
- **检查结果**：同上，没有任何调用点。

---

## 排查过但确认不是死代码的（假阳性，记录下来避免以后重复排查或误删）

CSS 静态扫描第一轮命中 23 个"零出现"候选，人工复核后排除了 20 个——它们都是通过 JS 模板字符串动态拼接类名，肉眼/纯文本搜索看不出来：

| Class 前缀 | 拼接方式 | 位置 |
|---|---|---|
| `.observer-line-{csi500,hs300,xplan,enhanced_ref}` | `` `observer-line-${line.key}` `` | [js/app.js:1178](../js/app.js#L1178) |
| `.observer-legend-{csi500,hs300,xplan,enhanced_ref}` | `` `observer-legend-${line.key}` `` | [js/app.js:1198](../js/app.js#L1198) |
| `.observer-tooltip-{csi500,hs300,xplan,enhanced_ref}` | `` `observer-tooltip-${line.key}` `` | [js/app.js:1241](../js/app.js#L1241) |
| `.quick-action-{buy,add,hold,sell,skip}` | `` `quick-action-${type}` `` | [js/app.js:858](../js/app.js#L858) |
| `.policy-watch-{risk,trigger}` | `` `policy-watch-${tone}` ``，`tone` 由调用方传入 `'risk'` / `'trigger'` | [js/app.js:911-913](../js/app.js#L911), [js/app.js:929](../js/app.js#L929) |
| `.execution-{corrected,reversed}` | `` `execution-${display.cls}` ``，`cls` 来自 `eventDisplayState()` 的 `'corrected'`/`'reversed'`/`'effective'` | [js/app.js:1845-1857](../js/app.js#L1845), [js/app.js:1897](../js/app.js#L1897) |

Python 侧一个静态扫描误报：`sort_key`（[automation/policy_research/compare_policy_decision.py:238](../automation/policy_research/compare_policy_decision.py#L238)）——它作为 `key=sort_key` 传给 `sorted()`，不带括号调用，纯文本搜 `sort_key(` 搜不到，但确实在用。

---

## 判断力之外的观察（不算"死代码"，但顺手记一下）

- `data/etf_base_config/PROMPT_FOR_GEMINI.md`：仓库里没有任何地方（代码、CLAUDE.md 文件表、其他文档）引用它，只有旁边的 `GEMINI_UPDATE_GUIDE.md` 被正式引用。可能是配套的"直接复制粘贴用提示词"故意不需要被引用，也可能是被 `GEMINI_UPDATE_GUIDE.md` 取代后忘记删。这是文档，不是代码，判断不了是否该删，列出来给 Opus/大亨一并看。

---

## 范围说明（诚实披露，别当成"全仓库审计完成"）

这次只扫了：
- `automation/**/*.py`（不含 `data/` 下的 JSON/MD）的顶层函数 + 文件级可达性
- `js/app.js` 的函数声明
- `css/style.css` 的 class 选择器

**没扫**：Python 类方法、嵌套/闭包函数（除了误报的 `sort_key` 顺手验证了一个）、`index.html` 里的内联脚本、`css/style.css` 的 ID 选择器和标签选择器、`data/` 目录下 JSON 配置里可能存在的废弃字段、`.github/workflows/*.yml` 里的死步骤或死 secret 引用。如果 Opus 审计需要更完整的覆盖，这些是明确的盲区，需要另外补扫。
