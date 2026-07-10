# 行动1 · 让系统"会喊疼"(Fail-Loud)执行指导书

> 执行模型建议:**Sonnet**(本任务机械、规格清晰、有测试兜底)。
> 本文件自包含:执行者**无需重新审计整个代码库**,按此文件 + 指定函数即可完成。
> 面向的方法论目标:X-Plan 终将接真钱账户,"沉默失败"(崩了还全绿、止损没评估却报无操作)比"少赚"严重得多。本任务把三条静默失败链改成会报警。

---

## 0. 范围与纪律

- **只改**:`automation/ds_scanner.py`、`automation/send_report.py`、`.github/workflows/scan.yml`、`automation/test_ds_scanner.py`。
- **一个 PR 交付**,标题 `fix: fail-loud on data outage / scan crash (行动1)`。
- **禁改**:四维评分公式、B/A/S 门槛、目标仓位档、`build_authoritative_decision` 的决策 elif 链逻辑、任何方法论阈值。本任务是**可观测性**,不是方法论。
- 不新增 `requirements.txt`(项目坚持去依赖清单化,见 CLAUDE.md)。

---

## 1. 改动 A:多源行情兜底(新浪 → 腾讯)

**现状**:`fetch_sina_realtime(codes)`([ds_scanner.py:363](../automation/ds_scanner.py))是唯一行情源。新浪限流/返回空时,整条链拿不到价。

**要求**:
1. 新增 `fetch_tencent_realtime(codes)`,请求 `http://qt.gtimg.cn/q=<逗号分隔codes>`,响应 `encoding="gbk"`,按 `var v_<code>="..."` 逐行解析,字段以 `~` 分割:`parts[1]=name`、`parts[3]=price`、`parts[4]=last_close`。返回结构与 `fetch_sina_realtime` **同键**(name/price/last_close/change_pct),但:
   - **`volume` 一律置 0**,并加 `"partial": True`。**理由(已替你拍死):腾讯 gtimg 的成交量单位与新浪不一致,若拿去算量比会引入隐性单位 bug,可能驱动错误 BUY。腾讯兜底只用于"拿到价、评估止损/趋势",不参与量比升档。**
   - `change_pct` 用 `(price/last_close-1)*100`,`last_close<=0` 时置 0。
2. 新增包装函数 `fetch_realtime(codes)`:先 `fetch_sina_realtime`;对**缺失或 price<=0** 的 code,用 `fetch_tencent_realtime` 补齐并合并(腾讯条目带 `partial=True`)。
3. `scan_market`([ds_scanner.py:988](../automation/ds_scanner.py))和 `scan_holdings_with_wave_management` 里对持仓的补票([ds_scanner.py:1040-1043](../automation/ds_scanner.py))改调 `fetch_realtime`。`refresh_etf_pool` 可保持原样(池刷新非关键路径)。
4. `scan_etf_pool`([ds_scanner.py:1172](../automation/ds_scanner.py)):当某标的 `realtime[code].get("partial")` 为真时,向 `quality_issues` 追加 `"PARTIAL_QUOTE_NO_VOLUME"`。这样 `data_quality.valid=False` → `determine_signal_grade` 返回"无效" → **它不会产生 BUY/ADD,但持仓的 -8%/逻辑止损仍照常评估**。这正是我们要的安全语义。

---

## 2. 改动 B:无报价持仓**绝不静默丢弃**

**现状**:[ds_scanner.py:1045-1047](../automation/ds_scanner.py) `price = realtime.get(code, {}).get("price", 0); if price == 0: continue`。持仓一旦拿不到价就从 `holdings_data` 消失,当天 -8% 和逻辑止损**完全不评估**,清单却显示"无操作"。这是全系统最危险的一条链。

**要求**:
1. `scan_holdings_with_wave_management` 里维护一个 `unpriced_holdings = []`。当 `fetch_realtime` 双源后 `price` 仍为 0 时:**不要 continue**,改为 `unpriced_holdings.append(code.replace("sh","").replace("sz",""))` 后 continue(该持仓确实无法算风控,但要被记录上报,而不是消失)。
2. 函数返回值增加 `unpriced_holdings`(改成返回 4 元组;更新 `main` 里的解包 [ds_scanner.py:1765](../automation/ds_scanner.py))。
3. 把 `unpriced_holdings` 传给 `build_authoritative_decision`(新增参数,默认 `None`),写进 `decision["portfolio"]`:
   - `"health"`: `"degraded"` 若 `unpriced_holdings` 非空,否则 `"ok"`;
   - `"data_gap_holdings"`: `unpriced_holdings or []`。

---

## 3. 改动 C:崩溃时也要产出可上报的 decision,而不是 exit 0 假装成功

**现状**:`main()`([ds_scanner.py:1729](../automation/ds_scanner.py))把一切异常 try 掉、打 traceback、**正常返回**。Actions 步骤永远绿。

**要求(已替你拍死 Actions红 vs Bark红 的先后)**:**Bark 是主报警通道(总能发、降级即红);Actions 状态是次要记录。** 所以:
1. `main()` 的 `except Exception` 分支里:打印 traceback **后**,尽力写一个最小 `decision.json`:`{"schema_version":"v3.0","authority":"scanner","operations":[],"portfolio":{"health":"crashed","data_gap_holdings":[]},"error":str(e)}`。**不要在这里 `sys.exit(1)`**(否则会跳过后续 Bark 步骤,把报警一起吞了)。
2. 正常路径下,`decision["portfolio"]["health"]` 由改动 B 决定。

---

## 4. 改动 D:send_report 把降级变成红色 Bark

**文件**:`automation/send_report.py`(`build_bark_body` [send_report.py:110](../automation/send_report.py))。

**要求**:
1. 从 `dashboard_data["decision"]["portfolio"]` 读 `health` 与 `data_gap_holdings`。
2. 当 `health != "ok"`(含 `degraded`/`crashed`)或 `data_gap_holdings` 非空:在 body **最顶部**插入醒目块,例如:
   ```
   🔴 数据降级 · 止损未评估
   无行情持仓：512690 / 588800（请手动核价，勿依赖本清单判断止损）
   ```
   `health=="crashed"` 时文案为 `🔴 扫描崩溃 · 本次无有效决策,请勿依据执行`。
3. `build_payload` 的 `title` 在降级/崩溃时前缀加 `🔴`。
4. 保留现有 `is_trade_day` 跳过逻辑不变。

---

## 5. 改动 E:workflow 健康门禁(Actions 记录诚实,但排在 Bark 之后)

**文件**:`.github/workflows/scan.yml`。在 **Bark 推送步骤之后**追加一步:

```yaml
      - name: 扫描健康门禁（在Bark之后，仅让Actions历史诚实）
        if: always()
        run: |
          python -c "import json,sys; d=json.load(open('decision.json')); h=(d.get('portfolio') or {}).get('health','ok'); print('health=',h); sys.exit(1 if h!='ok' else 0)"
```

顺序保证:先发红 Bark → 再把 job 标红。两个通道都到位,且报警不会被 exit 1 吞掉。

---

## 6. 验收标准(逐条可测)

- [ ] `fetch_realtime` 在新浪返回空时,能从腾讯拿到 price,且腾讯条目 `partial=True`、`volume=0`。
- [ ] 某 ETF 只有腾讯价(partial)时,其 `signal_grade=="无效"`,不出现在 BUY/ADD 操作里。
- [ ] 持仓双源都无价时:**不消失**,记入 `decision["portfolio"]["data_gap_holdings"]`,`health=="degraded"`。
- [ ] `main` 内部抛异常时:`decision.json` 仍被写出且 `health=="crashed"`,进程**不** exit 非零。
- [ ] `build_bark_body` 在 degraded/crashed 时,body 顶部含 🔴 告警且列出无价标的。
- [ ] 现有全部单测仍通过(`python -m unittest` 那一串)。

---

## 7. 对抗性验证(**必须真跑,把输出贴进 PR 描述**;单测通过≠修好)

在 `automation/test_ds_scanner.py` 新增并运行:
1. `test_unpriced_holding_is_reported_not_dropped`:构造一个持仓,mock `fetch_realtime` 对其返回空 → 断言该 symbol 出现在 `decision["portfolio"]["data_gap_holdings"]` 且 `health=="degraded"`(而不是从操作清单消失)。
2. `test_partial_quote_cannot_produce_buy`:mock 一个 `partial=True` 的池内标的 → 断言 `signal_grade=="无效"` 且不产生 BUY。
3. `test_bark_body_flags_degraded`:给 `build_bark_body` 传 `health=="degraded"` 的 dashboard → 断言返回文本含"止损未评估"。

**并手动模拟断源**:临时让 `fetch_sina_realtime` 返回 `{}`(可用 monkeypatch 或本地跑),确认 `build_bark_body` 输出顶部为红色告警。把这段实际输出贴到 PR。

---

## 8. 交付报告格式(Sonnet 完成后回给用户)

1. 改了哪些文件、每处几行;
2. 第 6 节验收清单逐条 ✅/❌;
3. 第 7 节三个新测试 + 手动断源验证的**真实终端输出**;
4. 任何你拿不准、觉得可能触及方法论的地方 —— **标出来留给 Opus/大亨复核,不要自己拍**。
