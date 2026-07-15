const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = {
  console,
  window: { crypto: { randomUUID: () => 'test-uuid' } },
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
vm.runInContext(
  fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8'),
  context,
  { filename: 'app.js' },
);

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

console.log('app.js parser tests: OK');
