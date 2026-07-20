import assert from 'node:assert/strict';
// vm context 是独立 realm，里面造出来的对象/数组原型和宿主的不是同一个，
// deepStrictEqual 的原型检查会误报。结构比较统一用宽松版。
import { deepEqual as deepEqualLoose } from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

// api.js/decision.js 是普通 <script>（无 export），不能用 import 加载。
// 丢进同一个 vm context，和浏览器共享全局作用域的方式一致。
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const context = { console };
vm.createContext(context);
for (const file of ['api.js', 'decision.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context, { filename: file });
}
// class/function 声明落在 context 的全局词法作用域里，不是 sandbox 自身属性，
// 所以要在 context 内求值取出来。
const [GistClient, parseJsonl, dashboardIsFresh, sortHoldingsForExecution] = vm.runInContext(
  '[GistClient, parseJsonl, dashboardIsFresh, sortHoldingsForExecution]',
  context,
);

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
deepEqualLoose(parseJsonl('{"id":1}\ninvalid\n{"id":2}\n'), [{ id: 1 }, { id: 2 }]);
assert.equal(dashboardIsFresh({ generated_at: '2026-07-15 12:00:00' }, '2026-07-15'), true);
deepEqualLoose(
  sortHoldingsForExecution([{ symbol: 'sh2' }, { symbol: 'sh1' }, { symbol: 'sh3' }], holding => ({
    sh1: { action: 'SELL' }, sh2: { action: 'HOLD' }, sh3: { action: 'REDUCE' },
  }[holding.symbol])),
  [{ symbol: 'sh1' }, { symbol: 'sh3' }, { symbol: 'sh2' }],
);
console.log('api.js tests: OK');
