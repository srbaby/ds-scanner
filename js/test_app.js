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
