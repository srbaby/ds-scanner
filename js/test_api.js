import assert from 'node:assert/strict';
import { GistClient, parseJsonl } from './api.js';
import { dashboardIsFresh, sortHoldingsForExecution } from './decision.js';

const calls = [];
const fetchImpl = async (url, options = {}) => {
  calls.push({ url, options });
  if (url.includes('/gists/')) return { ok: true, json: async () => ({ files: { 'large.json': { raw_url: 'https://raw.example/large.json', truncated: true } } }) };
  if (url.includes('raw.example')) return { ok: true, text: async () => '{"ok":true}' };
  return { ok: false, status: 500, text: async () => 'failure' };
};
const client = new GistClient({ token: 'test', gistId: 'gist', fetchImpl });
const index = await client.index();
assert.equal(await client.readFile(index, 'large.json'), '{"ok":true}');
assert.equal(calls[1].url, 'https://raw.example/large.json');
assert.deepEqual(parseJsonl('{"id":1}\ninvalid\n{"id":2}\n'), [{ id: 1 }, { id: 2 }]);
assert.equal(dashboardIsFresh({ generated_at: '2026-07-15 12:00:00' }, '2026-07-15'), true);
assert.deepEqual(
  sortHoldingsForExecution([{ symbol: 'sh2' }, { symbol: 'sh1' }, { symbol: 'sh3' }], holding => ({
    sh1: { action: 'SELL' }, sh2: { action: 'HOLD' }, sh3: { action: 'REDUCE' },
  }[holding.symbol])),
  [{ symbol: 'sh1' }, { symbol: 'sh3' }, { symbol: 'sh2' }],
);
console.log('api.js tests: OK');
