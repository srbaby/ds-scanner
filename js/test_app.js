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
].join('\n');
const parsed = context.extractQuickGuide(aiText);
assert.equal(parsed.actions.length, 1);
assert.equal(parsed.actions[0].actionId, 'OP-01');
assert.equal(parsed.actions[0].ruleCode, 'B_INITIAL_BUY');
assert.equal(parsed.actions[0].reasonZh, '普通信号首次建仓至10%');
assert.equal(parsed.actions[0].code, 'sh588800');

console.log('app.js parser tests: OK');
