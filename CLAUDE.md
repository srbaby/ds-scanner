# CLAUDE.md — DS波段扫描系统（规格 + AI操作引导）

X-DeepSeek 波段验证系统，基于"价值波段 Value-Swing"方法论，每日尾盘扫描ETF池，生成四维评分报告并通过 Bark 推送（全文塞body），由 Cloudflare Worker 定时触发（交易日北京 14:49）。

> **方法论版本：** 见 `X-Plan.md` 文档头（版本号不再在文件名/本文件维护，避免每次升级改多处）
> **系统版本：** ds_scanner v3.0
> **性质：** 与主体系完全隔离的影子交易实验系统
> 本文件 = 本系统唯一说明文档（原 SPEC.md 已并入，2026-06-11）。

---

## 🤖 AI操作引导（新会话先读这段）

- **影子系统边界**：不与主体系 0号/1号 的 PE 体系、铁律、持仓混同；本系统持仓/信号不写入主体系文档。
- **方法论 canonical = 本目录 `X-Plan.md`**（完整版，含附录A扫描器policy分实现）。开仓/止损止盈/仓位/熔断等一切交易规则只看该文件，
  本文件不保留任何规则摘要（2026-06-12已剥离，见下"交易规则速查索引"）；`automation/ai_review.py` 运行时直接读取该文件全文作为system prompt，不在代码里重复抄写规则。
- **系统已全部线上运行**（GitHub Actions + Gist + Cloudflare Worker），本地不再跑扫描。
  本目录是落后的镜像副本，`data/etf_pool.json` / `data/holdings.json` / `dashboard.json` 均为历史快照，
  **不可据此判断当前持仓或分数**；实时状态只在 Gist。
- 唯一仍需本地手动维护的是 `data/etf_base_config.json`（改分后 push 生效），评分方法见 `data/etf_base_config/GEMINI_UPDATE_GUIDE.md`（供 Gemini 使用，Claude 不主动改分）。
- `automation/ds_scanner.py` 依赖新浪行情 + AKShare，Cowork 沙箱不要尝试抓行情，只能对导出副本做离线分析。
- Cowork memory 不复制持仓/分数/现金/AI分析等状态（避免双真理源）。
- 修订规则先改本文件再改代码。

---

## 架构

```
Cloudflare Worker（cron: 周一至五 北京14:49）
    │ workflow_dispatch 触发
    │ 备用：浏览器访问 Worker URL 带 ?key= 手动触发
    ▼
GitHub Actions（.github/workflows/scan.yml）
    │ 运行 automation/ds_scanner.py
    ├─ 读 GitHub Gist → etf_pool.json（上次policy分）
    ├─ 读 GitHub Gist → holdings.json（当前持仓）
    ├─ 拉取新浪实时行情 + AKShare历史K线
    ├─ 重算policy分 → 写回 Gist etf_pool.json
    └─ 生成 report.txt
    ▼
automation/generate_dashboard.py
    ├─ 调用 ai_review.py → Gemini API（system prompt=X-Plan.md全文，user输入=report.txt）
    └─ 写回 Gist dashboard.json（report原文 + Gemini分析 + 模型/时间/方法论版本；失败不阻塞后续步骤）
    ▼
automation/send_report.py
    └─ Bark推送 report.txt 全文（body，POST JSON，badge红点+icon，不变）
    ▼
index.html（GH Pages，stock.bailuzun.com，持仓管理+AI看板合一）
    └─ 读 Gist holdings.json + dashboard.json：持仓管理置顶，
       AI分析（干货：标准回复格式全文）默认展开，report原文默认折叠
       （AI分析失败时自动展开作兜底）
    ▼
人工决策（必要时辅以DeepSeek/Gemini手动二次分析）
    └─ 14:55-15:00 执行
```

> 阶段1（2026-06-12）只接入Gemini免费API；DeepSeek免费模型接入、多模型分析区对比、二次提醒等见 `automation/优化备忘.md`。

---

## 文件说明

| 文件                                        | 说明                                                         | 维护方式                 |
| ------------------------------------------- | ------------------------------------------------------------ | ------------------------ |
| `X-Plan.md`                                 | **方法论正文（canonical）**，`ai_review.py`运行时读取全文作为system prompt | 演化走流程               |
| `automation/ds_scanner.py`                  | 主扫描脚本 v3.0                                              | 手动迭代                 |
| `automation/ai_review.py`                   | Gemini API调用模块：读`X-Plan.md`+report.txt，输出四维评分分析文本 | 手动迭代                 |
| `automation/generate_dashboard.py`          | 调用ai_review，把report+Gemini分析+元信息写入Gist `dashboard.json` | 手动迭代                 |
| `automation/send_report.py`                 | Bark推送脚本（非交易日自动跳过，report.txt全文塞body，POST避免URL长度限制；APNs单条payload约4KB上限，超长可能截断——已知风险，按选择全文优先） | 手动迭代                 |
| `automation/cf_worker_trigger.js`           | Cloudflare Worker 定时触发器（部署在 CF，本文件为源码存档）  | 手动迭代                 |
| `data/etf_pool.json` / `data/holdings.json` | Gist 镜像的本地历史快照（不可据此判断当前状态）              | 脚本自动写回（线上跑）   |
| `data/etf_base_config.json`                 | 板块政策基础分（0-15分），低频手动维护                       | 手动，重大政策事件后更新 |
| `data/etf_base_config/`                     | base分评分指南与提示词（GEMINI_UPDATE_GUIDE / PROMPT_FOR_GEMINI） | 低频手动                 |
| `index.html`                                | 持仓管理 + AI分析看板（合一），访问 stock.bailuzun.com       | 手动迭代                 |
| `.github/workflows/scan.yml`                | Actions 工作流，仓库内位置同此                               | 手动迭代                 |
| `run_report.bat`                            | 本地手动跑扫描的批处理                                       | 手动迭代                 |
| `CLAUDE.md`                                 | 本文件：系统规格 + AI操作引导                                | 随系统演进               |
| `automation/优化备忘.md`                    | 待办：DeepSeek接入/三栏看板/通知冗余等阶段2-3规划            | 随进展更新               |
| `CNAME`                                     | 自定义域名 stock.bailuzun.com（仅仓库，本地镜像无）          | 固定不动                 |

---

## Gist 数据源

单个私有 Gist，Description: `ds_scanner`，包含两个文件：

| 文件             | 说明                                                         | 维护方式                    |
| ---------------- | ------------------------------------------------------------ | --------------------------- |
| `etf_pool.json`  | ETF池policy总分（base+tech+strength），每日跑完自动写回      | 脚本全自动                  |
| `holdings.json`  | 持仓数据（现金、代码、数量、成本、买入日期）                 | 网页手动维护                |
| `dashboard.json` | AI看板数据：report原文 + Gemini分析 + 生成时间/模型/方法论版本 | generate_dashboard.py全自动 |

脚本读取优先级：**Gist > 本地文件 > 硬编码兜底**。本地跑时不设环境变量自动降级本地文件，行为不变。

---

## 定时触发（Cloudflare Worker）

| 项       | 值                                                           |
| -------- | ------------------------------------------------------------ |
| Worker   | `ds-scan-trigger`（Cloudflare，源码存档 `automation/cf_worker_trigger.js`） |
| Cron     | `49 6 * * MON-FRI`（UTC）= 北京 14:49 周一至五。⚠️ CF cron 星期字段 1=周日，必须用英文缩写 |
| 变量     | `GH_REPO`=srbaby/ds-scanner（文本）、`GH_TOKEN`=fine-grained PAT（机密，仅 Actions 读写） |
| 手动备用 | 浏览器访问 Worker URL `?key=`（PAT 第12-19位）               |
| 准时性   | 实测分钟级（GitHub 自带 cron 延时数小时，已弃用）；iOS 快捷指令已退役（2026-06-11） |

---

## 环境变量（GitHub Actions Secrets）

| 变量名                 | 说明                                                         |
| ---------------------- | ------------------------------------------------------------ |
| `DS_SCANNER_GIST_ID`   | Gist ID（32位）                                              |
| `GITHUB_TOKEN`         | 有 gist scope 的 PAT，Secret名为 `GH_PAT`                    |
| `BARK_KEY`             | Bark App 推送key（不带 `https://api.day.app/` 前缀，与fund-monitor同一套） |
| `GEMINI_API_KEY`       | Google AI Studio 免费API Key，`generate_dashboard.py`用      |
| `GEMINI_MODEL`（可选） | 默认`gemini-2.5-flash`；不配置则用默认值，用于后续切换模型对比质量 |

---

## ETF 观察池（18只）

| 级别 | 代码     | 名称      | 板块     |
| ---- | -------- | --------- | -------- |
| S    | sh588000 | 科创50ETF | 科技成长 |
| S    | sh512480 | 半导体ETF | 半导体   |
| S    | sh515880 | 通信ETF   | 通信     |
| S    | sz159766 | 旅游ETF   | 旅游     |
| S    | sh515120 | 创新药ETF | 创新药   |
| A    | sz159851 | 金融科技  | 金融科技 |
| A    | sh512880 | 证券ETF   | 证券     |
| A    | sz159915 | 创业板ETF | 科技成长 |
| A    | sh515030 | 新能车ETF | 新能车   |
| A    | sz159755 | 电池ETF   | 电池     |
| B    | sh515220 | 煤炭ETF   | 煤炭     |
| B    | sh516150 | 稀土ETF   | 稀土     |
| B    | sh512400 | 有色ETF   | 有色     |
| B    | sh516020 | 化工ETF   | 化工     |
| -    | sh512690 | 酒ETF     | 酒       |
| -    | sh513180 | 恒生科技  | 港股科技 |
| 观   | sh515790 | 光伏ETF   | 光伏     |
| 观   | sh512660 | 军工ETF   | 国防安全 |

---

## 交易规则速查索引（规则一律读 X-Plan.md，本文件不展开）

| 规则                                                 | 位置（X-Plan.md） |
| ---------------------------------------------------- | ----------------- |
| 开仓：三道金牌 + 四维评分 + 仓位对应                 | 模块2 / 模块7     |
| 止损止盈：三道防线 + 梯度/动态止盈                   | 模块3             |
| 持仓-新信号冲突矩阵                                  | 模块4             |
| 异常情况SOP                                          | 模块5             |
| 资金/仓位硬约束、加仓管理                            | 模块6             |
| 选品白/黑名单、爆发力评级                            | 模块8             |
| 熔断与转实盘（毕业）条件                             | 模块9             |
| 扫描器policy分实现（base/tech/strength、软止损阈值） | 附录A             |

---

## 每日流程

```
14:49  Cloudflare Worker 自动触发 Actions（cron: 49 6 * * MON-FRI，UTC）
~14:51 Gemini自动分析完成，写入Gist dashboard.json
~14:53 收到Bark推送（带badge红点），打开 index.html 查看AI分析（干货，默认展开）
~14:55 人工决策确认（Gemini分析失败时，仍可长按Bark通知复制report全文发给DeepSeek/Gemini手动分析）
14:55-15:00  尾盘执行
收盘后  更新 holdings.json（stock.bailuzun.com）
```

---

## 前端页面（GH Pages，stock.bailuzun.com）

单页 `index.html`（持仓管理 + AI看板合一），自上而下：

| 区块                       | 功能                                                         |
| -------------------------- | ------------------------------------------------------------ |
| 持仓管理（置顶）           | 可用资金/持仓列表，买入建仓（代码自动联想补全池内ETF）/ 减仓（自动标记`is_reduced: true`）/ 清仓（删除记录）/ 修改数量、成本、买入日期，所有操作实时写回Gist `holdings.json` |
| 🤖 今日AI分析（默认展开）   | Gemini回复全文（标准回复格式=持仓指令/新机会/执行窗口，即"干货"），含止损/开仓信号高亮徽章 |
| 📡 原始扫描数据（默认折叠） | report.txt原文；AI分析失败时自动展开作人工兜底               |

AI分析与原始数据来自Gist `dashboard.json`（只读）。GitHub Token + Gist ID 存浏览器localStorage，登录一次后自动读取。

---

## 本地运行

```bash
# 以下命令均在 X-Plan/ 根目录下执行

# 设置环境变量（可选，不设则降级本地文件）
export DS_SCANNER_GIST_ID=你的GistID
export GITHUB_TOKEN=你的PAT

# 运行
python3 automation/ds_scanner.py

# 强制刷新policy分
python3 automation/ds_scanner.py --refresh-policy
```

依赖：`pip install requests pandas akshare lxml beautifulsoup4`

---

## 版本记录

| 版本                    | 日期       | 核心变更                                                     |
| ----------------------- | ---------- | ------------------------------------------------------------ |
| 前端合一                | 2026-06-12 | `index.html`与`dashboard.html`合并为单页：持仓管理置顶，🤖今日AI分析（干货=Gemini标准回复格式全文，含止损/开仓信号徽章）默认展开于持仓下方，📡report原文默认折叠（AI分析失败时自动展开兜底）；删除`dashboard.html`，同步更新`X-Plan.md`模块1执行流程描述、`generate_dashboard.py`文档字符串及本文件架构图/文件说明/前端页面/每日流程 |
| 文档去重+方法论文档修订 | 2026-06-12 | ① CLAUDE.md剥离全部规则摘要（Policy评分/开仓/止损止盈/仓位/熔断/转实盘六节），替换为速查索引，消除双真理源；② `X-Plan.md`自动化适配修订（规则无变更）：扫描器policy分实现迁入附录A、澄清"逻辑止损触发器=policy总分<15"与四维评分"政策催化30分"双口径、模块1/5/10改写为自动化架构、价格止损执行口径统一（盘中跌破立即清仓）、版本历史精简至2条；③canonical文件`X-Plan_v2.6.md`重命名为`X-Plan.md`（版本号移入文件内部头部，避免后续方法论升级需改文件名+全项目引用） |
