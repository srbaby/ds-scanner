# CLAUDE.md — X_Python(DS波段扫描系统)操作引导

> 本文件是 AI 操作层引导,不定义任何交易规则。规则真理源是本目录 `SPEC.md`。

## 🚦 启动规则

1. **先读 `SPEC.md`** —— 架构、评分体系、三道防线、熔断条件的唯一来源。
2. base分评分规则与更新方法见 `etf_base_config/GEMINI_UPDATE_GUIDE.md`(供 Gemini 使用,Claude 不主动改分)。
3. 不凭记忆假设池内分数/持仓;实时状态在 Gist(`etf_pool.json` / `holdings.json`),本地副本可能滞后。

## ⚠️ 系统边界(重要)

- **这是与主体系完全隔离的影子交易实验系统。** 不与 0号/1号 的 PE 体系、铁律、持仓混同;
  本系统的持仓/信号不写入主体系文档,主体系状态也不影响本系统规则。
- **方法论版本以 SPEC.md 版本记录为准**(当前 v2.6 / ds_scanner v3.0),修订规则先改 SPEC 再改代码。

## ⚠️ Cowork 运行环境护栏

- **系统已全部线上运行**(GitHub Actions + Gist),本地不再跑扫描。
  本目录是落后的镜像副本,`etf_pool.json` / `holdings.json` / `report` 均为历史快照,
  **不可据此判断当前持仓或分数**;实时状态只在 Gist。
- 唯一仍需本地手动维护的是 `etf_base_config.json`(改分后 push 到仓库生效),
  评分方法见 `etf_base_config/GEMINI_UPDATE_GUIDE.md`。
- `ds_scanner.py` 依赖新浪行情 + AKShare,Cowork 沙箱不要尝试抓行情,
  只能对导出的 report/json 副本做离线分析。
- Cowork memory 不复制持仓/分数/现金等状态(避免双真理源)。
