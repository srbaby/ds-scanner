import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const indexHtml = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
assert.doesNotMatch(indexHtml, /\son(?:click|input|change|submit)=/);
// 三个前端脚本必须是普通 <script>，不能是 type="module"：它们按顺序共享同一全局
// 作用域，且 file:// 双击打开就能测。改成 module 会静默弄坏 file:// 登录（CORS）。
// 详见 CLAUDE.md「已知坑」第1条。
// 注意：只查 <script> 标签本身，不能全文搜 type="module"——下面那段解释
// 为什么不用 module 的 HTML 注释里就有这个字面量。
assert.doesNotMatch(indexHtml, /<script[^>]*type="module"/);
assert.match(indexHtml, /<script src="js\/api\.js/);
assert.match(indexHtml, /<script src="js\/decision\.js/);
assert.match(indexHtml, /<script src="js\/app\.js/);

const context = {
  console,
  window: { crypto: { randomUUID: () => 'test-uuid' }, addEventListener() {} },
  document: {
    createElement: () => ({ remove() {} }),
    body: { appendChild() {} },
    getElementById: () => null,
  },
  localStorage: { getItem: () => '', setItem() {} },
  fetch: async () => ({ ok: false }),
  setTimeout,
  clearTimeout,
  confirm: () => true,
  Blob,
  URL,
  TextEncoder,
  crypto: globalThis.crypto,
};
vm.createContext(context);
// 按 index.html 里的顺序加载，共享同一全局作用域——和浏览器行为一致，
// app.js 直接引用 api.js/decision.js 的顶层名字，不走 import。
for (const file of ['api.js', 'decision.js', 'app.js']) {
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, file), 'utf8'),
    context,
    { filename: file },
  );
}
const originalPersistExecution = context.persistExecution;

const aiText = [
  '【操作清单】',
  '| 操作编号 | 类型 | 代码 | 名称 | 当前目标仓位% | 今日目标仓位% | 调整仓位 | 规则代码 | 信号等级 | 中文操作依据 | 关键指标 |',
  '|---|---|---|---|---:|---:|---:|---|---|---|---|',
  '| OP-01 | BUY | sh588800 | 科创100ETF | 0% | 10% | +10% | B_INITIAL_BUY | B | 普通信号首次建仓至10% | 评分76/量比1.30 |',
  '| OP-02 | ADD | sh512480 | 半导体ETF | 10% | 15% | +5% | A_CONFIRM_ADD | A | 强势确认加仓至15% | 评分82/量比1.35 |',
  '| OP-03 | REDUCE | sz159915 | 创业板ETF | 20% | 15% | -5% | SIGNAL_DOWNGRADE | A | 信号降级减仓至15% | 评分81/量比1.10 |',
].join('\n');
const parsed = context.extractQuickGuide(aiText);
assert.equal(parsed.actions.length, 3);
assert.equal(parsed.actions[0].actionId, 'OP-01');
assert.equal(parsed.actions[0].ruleCode, 'B_INITIAL_BUY');
assert.equal(parsed.actions[0].reasonZh, '普通信号首次建仓至10%');
assert.equal(parsed.actions[0].code, 'sh588800');
assert.equal(parsed.actions[1].type, 'ADD');
assert.equal(parsed.actions[2].type, 'REDUCE');

const scannerActions = context.decisionOperationsToActions([{
  id: 'OP-09', action: 'BUY', symbol: 'sh588000', name: '科创50ETF',
  current_target_position_pct: 0, target_position_pct: 10, adjustment_pct: 10,
  rule_code: 'B_INITIAL_BUY', signal_grade: 'B', reason: '扫描器权威决策',
  metrics: { score: 78 },
  execution_guidance: {
    reference_price: 2.328, target_amount: 19315.56,
    recommended_shares: 8200, recommended_lots: 82, estimated_amount: 19089.6,
  },
}]);
assert.equal(scannerActions[0].authority, 'scanner');
assert.equal(scannerActions[0].ruleCode, 'B_INITIAL_BUY');
assert.equal(context.actionToReason(scannerActions[0]).data_confidence, 'scanner_authoritative');
assert.equal(scannerActions[0].guidance.recommended_shares, 8200);
const qtyGuidance = context.calculateBuyGuidance(193155.64, 10, 2.328);
assert.equal(qtyGuidance.recommended_shares, 8200);
assert.equal(qtyGuidance.recommended_lots, 82);

vm.runInContext(`currentAiActions = ${JSON.stringify(parsed.actions)}`, context);
const buyReasons = context.reasonOptionsFor('588800', ['BUY']);
assert.equal(buyReasons.length, 1);
assert.equal(buyReasons[0].reason.rule_code, 'B_INITIAL_BUY');
const addReasons = context.reasonOptionsFor('512480', ['ADD']);
assert.equal(addReasons.length, 1);
assert.equal(addReasons[0].reason.rule_code, 'A_CONFIRM_ADD');
assert.equal(context.reasonOptionsFor('sh588800', ['ADD']).length, 0);
assert.equal(context.reasonOptionsFor('sh000001', ['BUY']).length, 0);
assert.equal(context.manualReasonOption().reason.rule_code, 'MANUAL_BACKFILL');
assert.equal(context.manualReasonOption().reason.data_confidence, 'manual');
assert.equal(context.validateOperationInput('ADD', 1000, 1500, 1.23), '');
assert.match(context.validateOperationInput('ADD', 1000, 1000, 1.23), /大于当前持仓/);
assert.equal(context.validateOperationInput('REDUCE', 1000, 500, NaN), '');
assert.equal(context.validateOperationInput('SELL', 1000, 0, NaN), '');
assert.match(context.validateOperationInput('SELL', 1000, 500, NaN), /必须为0/);

vm.runInContext(`
  holdingsData = {
    cash_available: 143707.1,
    holdings: [{ symbol: 'sh515120', qty: 30800, cost: 0.627, buy_date: '2026-07-02' }]
  };
  dashboardData = {
    generated_at: today() + ' 12:01:48',
    decision: {
      portfolio: { total_asset: 194432.7 },
      signals: [{ symbol: '515120', full_symbol: 'sh515120', price: 1.647 }]
    }
  };
`, context);
const legacySell = {
  id: 'OP-01', action: 'SELL', symbol: 'sh515120', name: '创新药ETF广发',
  current_target_position_pct: 10, target_position_pct: 0, adjustment_pct: -10,
  rule_code: 'PROFIT_WEAKEN', signal_grade: '无效', reason: '已有浮盈但评分或资金转弱',
};
const sellActions = context.decisionOperationsToActions([legacySell]);
assert.equal(sellActions[0].type, 'SELL');
assert.equal(sellActions[0].guidance.side, 'SELL');
assert.equal(sellActions[0].guidance.recommended_shares, 30800);
assert.equal(sellActions[0].guidance.post_trade_shares, 0);
assert.equal(sellActions[0].qty, '清仓 · 卖出 30,800 份');
vm.runInContext(`currentAiActions = ${JSON.stringify(sellActions)}`, context);
assert.equal(context.reasonOptionsFor('sh515120', ['REDUCE', 'SELL']).length, 1);
assert.equal(context.reasonOptionsFor('sh515120', ['REDUCE', 'SELL'])[0].reason.rule_code, 'PROFIT_WEAKEN');
const dialogNodes = {
  'operation-dialog': { dataset: { requestedMode: 'REDUCE' } },
  'operation-mode': { value: 'REDUCE' },
  'operation-index': { value: '0' },
  'operation-reason': { selectedOptions: [{ dataset: { reason: JSON.stringify(context.actionToReason(sellActions[0])) } }] },
  'operation-qty': { value: 30800, readOnly: false },
  'operation-dialog-title': { textContent: '' },
  'operation-qty-label': { textContent: '' },
  'operation-cost-wrap': { style: {} },
  'operation-preview': { textContent: '', innerHTML: '' },
};
context.document.getElementById = id => dialogNodes[id] || null;
context.syncOperationModeFromReason();
assert.equal(dialogNodes['operation-mode'].value, 'SELL');
assert.equal(dialogNodes['operation-qty'].value, 0);
assert.equal(dialogNodes['operation-qty'].readOnly, true);
assert.match(dialogNodes['operation-dialog-title'].textContent, /^清仓/);
dialogNodes['operation-dialog'].dataset.requestedMode = 'CORRECT_REASON';
dialogNodes['operation-mode'].value = 'CORRECT_REASON';
context.syncOperationModeFromReason();
assert.equal(dialogNodes['operation-mode'].value, 'CORRECT_REASON');

const before = {
  cash_available: 10000,
  holdings: [{ symbol: 'sh512480', qty: 1000, cost: 1.1, buy_date: '2026-07-01' }],
};
const after = {
  cash_available: 9000,
  holdings: [{ symbol: 'sh512480', qty: 1500, cost: 1.2, buy_date: '2026-07-01' }],
};
const addEvent = context.buildExecutionEvent(
  'ADD',
  'sh512480',
  before,
  after,
  addReasons[0].reason,
);
assert.equal(addEvent.event_type, 'ADD');
assert.equal(addEvent.qty_delta, 500);

vm.runInContext(`executionEvents = [
  { event_id: 'cash-1', event_type: 'CASH_UPDATE', symbol: '' },
  { event_id: 'buy-1', event_type: 'BUY', symbol: 'sh512480' }
]`, context);
assert.equal(
  context.canReverseEvent({ event_id: 'cash-1', event_type: 'CASH_UPDATE', symbol: '' }),
  false,
);
assert.equal(
  context.canReverseEvent({ event_id: 'buy-1', event_type: 'BUY', symbol: 'sh512480' }),
  true,
);

// --- 政策加减分必须可穿透核对：标题 + 原文链接 + 日期 ---
const evidenceHtml = context.policyDeltaEvidence({
  theme: '证券',
  delta: -1,
  events: [
    {
      title: '中国证券监督管理委员会行政处罚决定书',
      url: 'http://www.csrc.gov.cn/csrc/c101800/c7647255/content.shtml',
      source: '证监会政策法规',
      published_at: '2026-06-30',
      published_at_estimated: false,
      effective_delta: -1,
    },
  ],
});
assert.match(evidenceHtml, /证券 负向 -1/);
assert.match(evidenceHtml, /1条依据/);
assert.match(evidenceHtml, /中国证券监督管理委员会行政处罚决定书/);
assert.match(evidenceHtml, /href="http:\/\/www\.csrc\.gov\.cn/);
assert.match(evidenceHtml, /2026-06-30/);
assert.match(evidenceHtml, /方向未标注/);
assert.match(evidenceHtml, /rel="noopener noreferrer"/);

// 抓取日期要标出来，别让人以为是源站标注的发布日
const estimatedHtml = context.policyDeltaEvidence({
  theme: 'AI算力',
  delta: -2,
  events: [{ title: '答记者问', url: 'https://www.mofcom.gov.cn/a.html', published_at: '2026-07-29', published_at_estimated: true, effective_delta: -1 }],
});
assert.match(estimatedHtml, /抓取日/);

// 政策链接来自抓取的外部页面，非 http(s) 协议不能进 href
assert.equal(context.safeHttpUrl('javascript:alert(1)'), '');
assert.equal(context.safeHttpUrl('data:text/html,<script>'), '');
assert.equal(context.safeHttpUrl('https://www.gov.cn/a.htm'), 'https://www.gov.cn/a.htm');
const hostileHtml = context.policyDeltaEvidence({
  theme: '证券',
  delta: 1,
  events: [{ title: '恶意链接', url: 'javascript:alert(1)', published_at: '2026-07-29', effective_delta: 1 }],
});
assert.doesNotMatch(hostileHtml, /href=/);
assert.match(hostileHtml, /恶意链接/);

// 事件方向必须直出中文；正向、负向、混合都覆盖，缺失/非法值不能猜方向。
const directionHtml = context.policyDeltaEvidence({
  theme: '综合',
  delta: 1,
  events: [
    { title: '正向事件', direction: 'positive', published_at: '2026-07-29' },
    { title: '负向事件', direction: 'negative', published_at: '2026-07-29' },
    { title: '混合事件', direction: 'mixed', published_at: '2026-07-29' },
    { title: '未标注事件', direction: 'unexpected', published_at: '2026-07-29' },
  ],
});
assert.match(directionHtml, /综合 正向 \+1/);
assert.match(directionHtml, /正向事件[\s\S]*正向/);
assert.match(directionHtml, /负向事件[\s\S]*负向/);
assert.match(directionHtml, /混合事件[\s\S]*混合/);
assert.match(directionHtml, /未标注事件[\s\S]*方向未标注/);

// 没有依据时退回成普通徽章，不能渲染出空的展开框
assert.doesNotMatch(context.policyDeltaEvidence({ theme: '银行', delta: 1, events: [] }), /<details/);

// 操作弹窗先打开，再等待扫描器刷新；刷新未完成时确认按钮必须锁住且有中文加载态。
const operationTrace = [];
const operationNodes = {
  'operation-dialog': { dataset: {}, showModal: () => operationTrace.push('showModal'), close() {} },
  'operation-mode': { value: 'REDUCE' },
  'operation-index': { value: '0' },
  'operation-event-id': { value: '' },
  'operation-dialog-title': { textContent: '' },
  'operation-qty': { value: 1000 },
  'operation-cost': { value: 1.1 },
  'operation-cash': { value: 9000 },
  'operation-qty-label': { textContent: '' },
  'operation-qty-wrap': { style: {} },
  'operation-cost-wrap': { style: {} },
  'operation-cash-wrap': { style: {} },
  'operation-reason': {
    disabled: false,
    dataset: {},
    innerHTML: '',
    selectedOptions: [{ dataset: { reason: JSON.stringify({ ai_action_id: 'op-1', rule_code: 'REDUCE' }) } }],
  },
  'operation-reason-status': { className: '', textContent: '' },
  'operation-reason-manual': { hidden: false, textContent: '' },
  'operation-preview': { textContent: '', innerHTML: '' },
  'operation-confirm-btn': { disabled: false, dataset: {}, textContent: '确认登记' },
  'operation-cancel-btn': { disabled: false, dataset: {}, textContent: '取消' },
};
context.document.getElementById = id => operationNodes[id] || null;
context.holdingsData = {
  cash_available: 10000,
  holdings: [{ symbol: 'sh512480', qty: 1000, cost: 1.1, buy_date: '2026-07-01' }],
};
context.window.__releaseRefresh = null;
vm.runInContext(`
  refreshScannerActions = () => {
    window.__operationTrace.push('refresh-start');
    return new Promise(resolve => { window.__releaseRefresh = resolve; });
  };
  fillReasonSelect = () => {
    document.getElementById('operation-reason').disabled = false;
    document.getElementById('operation-reason-status').textContent = '已匹配当日扫描器清单（1 条）';
  };
  syncOperationModeFromReason = () => {};
`, context);
context.window.__operationTrace = operationTrace;
const opening = context.openOperationDialog('REDUCE', 0);
assert.deepEqual(operationTrace, ['showModal', 'refresh-start']);
assert.equal(operationNodes['operation-confirm-btn'].disabled, true);
assert.match(operationNodes['operation-reason-status'].textContent, /正在刷新/);
context.window.__releaseRefresh();
await opening;
assert.equal(operationNodes['operation-confirm-btn'].disabled, false);

// 确认登记进入 pending 后，网络未返回前两个按钮都不可操作；结束后恢复。
operationNodes['operation-mode'].value = 'CORRECT_REASON';
operationNodes['operation-event-id'].value = 'original-1';
operationNodes['operation-confirm-btn'].disabled = false;
operationNodes['operation-confirm-btn'].dataset.pending = 'false';
operationNodes['operation-reason'].disabled = false;
vm.runInContext(`executionEvents = [{ event_id: 'original-1', event_type: 'REDUCE', symbol: 'sh512480', rule_code: 'REDUCE', reason_zh: '测试' }]`, context);
context.window.__releasePersist = null;
vm.runInContext(`
  persistExecution = () => new Promise(resolve => { window.__releasePersist = resolve; });
`, context);
const saving = context.confirmOperationDialog();
assert.equal(operationNodes['operation-confirm-btn'].disabled, true);
assert.equal(operationNodes['operation-confirm-btn'].textContent, '正在登记…');
assert.equal(operationNodes['operation-cancel-btn'].disabled, true);
context.window.__releasePersist(true);
await saving;
assert.equal(operationNodes['operation-confirm-btn'].disabled, false);
assert.equal(operationNodes['operation-confirm-btn'].textContent, '确认登记');
assert.equal(operationNodes['operation-cancel-btn'].disabled, false);

// 买入抽屉也必须先打开再刷新；刷新失败后确认按钮仍恢复可点，依据状态负责说明失败。
const buyTrace = [];
const buyClassList = label => ({
  add: () => buyTrace.push(`${label}-open`),
  remove: () => buyTrace.push(`${label}-close`),
  toggle() {},
  contains: () => false,
});
const buyNodes = {
  'new-symbol': { value: '', dataset: {}, focus() {} },
  'new-qty': { value: '' },
  'new-cost': { value: '' },
  'new-date': { value: '' },
  'new-cash': { value: '' },
  'new-reason': {
    disabled: false,
    dataset: {},
    innerHTML: '',
    selectedOptions: [{ dataset: { reason: JSON.stringify({ rule_code: 'B_INITIAL_BUY' }) } }],
  },
  'new-reason-status': { className: '', textContent: '' },
  'new-reason-manual': { hidden: false, textContent: '' },
  'new-guidance': { innerHTML: '' },
  'new-preview': { textContent: '' },
  'suggest-list': { classList: buyClassList('suggest') },
  'drawer-overlay': { classList: buyClassList('overlay') },
  drawer: { classList: buyClassList('drawer') },
  'new-confirm-btn': { disabled: false, dataset: {}, textContent: '确认买入' },
  'new-cancel-btn': { disabled: false, dataset: {}, textContent: '取消' },
};
context.document.getElementById = id => buyNodes[id] || operationNodes[id] || null;
context.window.__releaseBuyRefresh = null;
vm.runInContext(`
  refreshScannerActions = () => {
    window.__buyTrace.push('refresh-start');
    return new Promise(resolve => { window.__releaseBuyRefresh = resolve; });
  };
  fillReasonSelect = () => {
    const select = document.getElementById('new-reason');
    const status = document.getElementById('new-reason-status');
    select.disabled = !lastScanStatus.ok;
    status.textContent = lastScanStatus.ok ? '已匹配当日扫描器清单（1 条）' : '⚠️ 今日信号未确认（网络请求失败）';
  };
`, context);
context.window.__buyTrace = buyTrace;
const buyOpening = context.openDrawer();
assert.deepEqual(buyTrace, ['suggest-close', 'overlay-open', 'drawer-open', 'refresh-start']);
assert.equal(buyNodes['new-confirm-btn'].disabled, true);
assert.match(buyNodes['new-reason-status'].textContent, /正在刷新/);
vm.runInContext(`lastScanStatus = { ok: true, fresh: true, reason: '', generatedDate: today() }`, context);
context.window.__releaseBuyRefresh();
await buyOpening;
assert.equal(buyNodes['new-confirm-btn'].disabled, false);
assert.equal(buyNodes['new-cancel-btn'].disabled, false);

vm.runInContext(`refreshScannerActions = async () => { throw new Error('offline'); }`, context);
await context.openDrawer();
assert.equal(buyNodes['new-confirm-btn'].disabled, false);
assert.match(buyNodes['new-reason-status'].textContent, /网络请求失败/);

// 买入提交 pending 覆盖成功和失败两条结束路径。
buyNodes['new-symbol'].value = '512480';
buyNodes['new-symbol'].dataset.fullCode = 'sh512480';
buyNodes['new-qty'].value = 1000;
buyNodes['new-cost'].value = 1.2;
buyNodes['new-date'].value = '2026-08-06';
buyNodes['new-cash'].value = 9000;
buyNodes['new-reason'].disabled = false;
buyNodes['new-reason'].selectedOptions = [{ dataset: { reason: JSON.stringify({
  ai_action_id: 'buy-1', rule_code: 'B_INITIAL_BUY', signal_grade: 'B', reason_zh: '测试买入', data_confidence: 'scanner_authoritative',
}) } }];
buyNodes['new-confirm-btn'].disabled = false;
context.window.__releaseBuyPersist = null;
vm.runInContext(`persistExecution = () => new Promise(resolve => { window.__releaseBuyPersist = resolve; });`, context);
const buying = context.addHolding();
assert.equal(buyNodes['new-confirm-btn'].disabled, true);
assert.equal(buyNodes['new-confirm-btn'].textContent, '正在登记…');
assert.equal(buyNodes['new-cancel-btn'].disabled, true);
context.window.__releaseBuyPersist(true);
await buying;
assert.equal(buyNodes['new-confirm-btn'].disabled, false);
assert.equal(buyNodes['new-cancel-btn'].disabled, false);

vm.runInContext(`persistExecution = async () => false`, context);
const failedBuying = context.addHolding();
await failedBuying;
assert.equal(buyNodes['new-confirm-btn'].disabled, false);
assert.equal(buyNodes['new-cancel-btn'].disabled, false);

// 看板实际渲染两个新分组；有主题偏移但没有池内行时不能留白。
const policyNodes = {
  'policy-watch': { hidden: true },
  'policy-watch-meta': { textContent: '', title: '' },
  'policy-watch-badge': { textContent: '' },
  'policy-watch-body': { innerHTML: '' },
};
context.document.getElementById = id => policyNodes[id] || buyNodes[id] || operationNodes[id] || null;
const policyRow = { symbol: 'sh512480', name: '证券ETF', theme: '证券', policy_delta: 1, base_score: 80, shadow_score: 82, gap: { blockers: [] } };
context.renderPolicyWatch({
  enabled: true,
  summary: { aggression_index: 0, verdict: '可接受', active_delta_count: 2 },
  active_policy_deltas: [],
  holdings_boost: [policyRow],
  pool_weakening: [{ ...policyRow, symbol: 'sh512400', name: '有色ETF', policy_delta: -1 }],
});
assert.match(policyNodes['policy-watch-body'].innerHTML, /持仓政策转强/);
assert.match(policyNodes['policy-watch-body'].innerHTML, /池内政策转弱/);
context.renderPolicyWatch({
  enabled: true,
  summary: { aggression_index: 0, verdict: '可接受', active_delta_count: 1 },
  active_policy_deltas: [{ theme: '证券', delta: 1, events: [] }],
});
assert.match(policyNodes['policy-watch-body'].innerHTML, /均未落到池内标的/);

// PATCH 响应带内联文件时不再往返；缺失/截断时必须回退到旧的重新读取校验。
const eventFilename = context.executionFileName();
context.window.__verifyIndexCalls = 0;
context.window.__verifyReadCalls = 0;
vm.runInContext(`gistClient = {
  index: async () => {
    window.__verifyIndexCalls += 1;
    return { history: [{ version: 'fallback-version' }], files: { ${JSON.stringify(eventFilename)}: {} } };
  },
  readFile: async () => {
    window.__verifyReadCalls += 1;
    return JSON.stringify({ event_id: 'event-fallback' });
  },
}`, context);
await context.verifyEventWritten('event-inline', {
  history: [{ version: 'inline-version' }],
  files: { [eventFilename]: { truncated: false, content: JSON.stringify({ event_id: 'event-inline' }) } },
});
assert.equal(context.window.__verifyIndexCalls, 0);
assert.equal(context.window.__verifyReadCalls, 0);
await context.verifyEventWritten('event-fallback', {
  files: { [eventFilename]: { truncated: true } },
});
assert.equal(context.window.__verifyIndexCalls, 1);
assert.equal(context.window.__verifyReadCalls, 1);

// PATCH 成功但校验失败：保留本地已提交状态，提示不要重复提交；PATCH 失败仍回滚。
const syncStatusNode = { textContent: '', className: '' };
const toastNode = { textContent: '', className: '' };
context.document.getElementById = id => ({
  'sync-status': syncStatusNode,
  toast: toastNode,
  policyNodes,
  ...buyNodes,
  ...operationNodes,
}[id] || policyNodes[id] || buyNodes[id] || operationNodes[id] || null);
vm.runInContext(`
  assertNoRemoteChange = async () => {};
  updateDataManifest = () => {};
  sha256Hex = async () => 'test-hash';
  renderAll = () => {};
  renderExecutionHistory = () => {};
  holdingsData = { cash_available: 100, holdings: [] };
  executionEvents = [];
  dataManifest = { files: { ${JSON.stringify(eventFilename)}: {} } };
  operationSaveInFlight = false;
`, context);
context.__originalPersistExecution = originalPersistExecution;
vm.runInContext('persistExecution = __originalPersistExecution', context);
const patchEvent = { event_id: 'patch-ok-but-unverified', event_type: 'BUY', symbol: 'sh512480' };
vm.runInContext(`
  saveData = async () => { window.__patchCalled = true; return { files: {} }; };
  verifyEventWritten = async () => { window.__verifyCalled = true; throw new Error('校验网络抖动'); };
`, context);
context.window.__patchCalled = false;
context.window.__verifyCalled = false;
const verificationFailure = await context.persistExecution(
  patchEvent,
  { cash_available: 100, holdings: [] },
  { cash_available: 90, holdings: [{ symbol: 'sh512480', qty: 100 }] },
);
assert.equal(verificationFailure, false);
assert.match(vm.runInContext('JSON.stringify(holdingsData)', context), /sh512480/);
assert.match(vm.runInContext('JSON.stringify(executionEvents)', context), /patch-ok-but-unverified/);
assert.match(toastNode.textContent, /已提交.*不要重复提交/);
assert.match(toastNode.className, /warn/);
assert.equal(syncStatusNode.textContent, '已提交，校验未完成');
assert.match(syncStatusNode.className, /warn/);

// 校验没跑完 = 台账状态不可确证。写入入口必须锁到用户刷新页面为止：
// 此时 assertNoRemoteChange() 拦不住重复提交（gistFileContents 已同步成写入后的内容），
// 再提交一次就会在 append-only 台账里留下同一笔交易的第二条事件。
assert.equal(vm.runInContext('writeVerificationUnresolved', context), true);

context.document.getElementById = id => ({
  'sync-status': syncStatusNode,
  toast: toastNode,
  ...buyNodes,
  ...operationNodes,
}[id] || null);
context.setBuyDrawerPending(false);
assert.equal(buyNodes['new-confirm-btn'].disabled, true);
assert.equal(buyNodes['new-confirm-btn'].textContent, '请刷新页面');
assert.equal(buyNodes['new-cancel-btn'].disabled, false);
context.setBuyDrawerLoading(false);
assert.equal(buyNodes['new-confirm-btn'].disabled, true);
operationNodes['operation-confirm-btn'].dataset.pending = 'false';
context.setOperationDialogPending(false);
assert.equal(operationNodes['operation-confirm-btn'].disabled, true);
assert.equal(operationNodes['operation-confirm-btn'].textContent, '请刷新页面');
assert.equal(operationNodes['operation-cancel-btn'].disabled, false);

// 锁生效期间连写入函数本身也要拒绝，覆盖"取消后重开抽屉"等绕过按钮的路径。
context.window.__patchCalled = false;
const lockedAttempt = await context.persistExecution(
  { event_id: 'blocked-while-unresolved', event_type: 'BUY', symbol: 'sh512480' },
  { cash_available: 100, holdings: [] },
  { cash_available: 90, holdings: [] },
);
assert.equal(lockedAttempt, false);
assert.equal(context.window.__patchCalled, false);
assert.match(toastNode.textContent, /请先刷新页面确认台账/);

vm.runInContext(`
  saveData = async () => false;
  holdingsData = { cash_available: 100, holdings: [] };
  executionEvents = [];
  operationSaveInFlight = false;
  writeVerificationUnresolved = false;
`, context);
const patchFailure = await context.persistExecution(
  { event_id: 'patch-failed', event_type: 'BUY', symbol: 'sh512480' },
  { cash_available: 100, holdings: [] },
  { cash_available: 90, holdings: [{ symbol: 'sh512480', qty: 100 }] },
);
assert.equal(patchFailure, false);
assert.doesNotMatch(vm.runInContext('JSON.stringify(holdingsData)', context), /sh512480/);
assert.equal(vm.runInContext('executionEvents.length', context), 0);
assert.match(toastNode.textContent, /未写入/);
assert.match(toastNode.className, /error/);
assert.equal(syncStatusNode.textContent, '未写入');
assert.match(syncStatusNode.className, /err/);

// 洞察页每次首次进入都重新读取索引，避免长开标签页拿到旧快照。
context.window.__insightIndexCalls = 0;
vm.runInContext(`
  gistIndex = { files: { 'dashboard.json': {} } };
  dashboardData = { report_file: 'report.txt' };
  gistFileContents = {};
  gistClient = {
    index: async () => { window.__insightIndexCalls += 1; return { files: {} }; },
    readFiles: async () => ({ 'stats.json': '{}', 'observer_request.json': '{}', 'report.txt': '报告' }),
  };
  renderDashboard = () => {};
  renderObserver = () => {};
  renderExecutionHistory = () => {};
`, context);
await context.loadInsightData();
assert.equal(context.window.__insightIndexCalls, 1);
await context.loadInsightData();
assert.equal(context.window.__insightIndexCalls, 2);

console.log('app.js parser tests: OK');
