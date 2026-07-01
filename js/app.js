// 新增：利用腾讯接口跨境网络获取股票/ETF真实名称
function fetchOnlineName(symbol, callback) {
  const script = document.createElement('script');
  script.src = `https://qt.gtimg.cn/q=${symbol.toLowerCase()}`;
  script.onload = () => {
    try {
      const varName = `v_${symbol.toLowerCase()}`;
      if (window[varName]) {
        const parts = window[varName].split('~');
        if (parts && parts[1]) callback(parts[1]); // parts[1] 就是中文名称
      }
    } catch (e) { console.error(e); }
    script.remove();
  };
  document.body.appendChild(script);
}

// ============================================================
// ETF 池（与 ds_scanner.py 保持一致）
// ============================================================
const ETF_POOL = {
  'sh588000': '科创50ETF',
  'sh512480': '半导体ETF',
  'sh515880': '通信ETF',
  'sz159766': '旅游ETF',
  'sh515120': '创新药ETF',
  'sz159851': '金融科技',
  'sh512880': '证券ETF',
  'sz159915': '创业板ETF',
  'sh515030': '新能车ETF',
  'sz159755': '电池ETF',
  'sh515220': '煤炭ETF',
  'sh516150': '稀土ETF',
  'sh512400': '有色ETF',
  'sh516020': '化工ETF',
  'sh512690': '酒ETF',
  'sh513180': '恒生科技',
  'sh515790': '光伏ETF',
  'sh512660': '军工ETF',
};

// 纯数字代码 → 完整代码映射
const CODE_MAP = {};
for (const [full, name] of Object.entries(ETF_POOL)) {
  CODE_MAP[full.slice(2)] = { full, name };
}

// ============================================================
// 状态
// ============================================================
let TOKEN = '', GIST_ID = '', holdingsData = {}, dashboardData = null;

// ============================================================
// 初始化
// ============================================================
window.onload = () => {
  TOKEN   = localStorage.getItem('ds_token') || '';
  GIST_ID = localStorage.getItem('ds_gist')  || '';
  document.getElementById('new-date').value = today();

  if (TOKEN && GIST_ID) {
    document.getElementById('input-token').value = TOKEN;
    document.getElementById('input-gist').value  = GIST_ID;
    document.getElementById('auth-screen').style.display = 'none';
    document.getElementById('main-screen').style.display = 'block';
    loadData().then(() => {
      renderAll();
      renderDashboard(dashboardData);
      setStatus('已同步', 'ok');
      document.getElementById('display-sync').textContent = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'});
    }).catch(e => {
      document.getElementById('main-screen').style.display = 'none';
      document.getElementById('auth-screen').style.display = 'flex';
      setStatus('连接失败', 'err');
      const err = document.getElementById('auth-err');
      err.textContent = e.message;
      err.style.display = 'block';
    });
  }
};

function today() {
  return new Date().toLocaleDateString('sv-SE'); // YYYY-MM-DD
}

// ============================================================
// 认证
// ============================================================
async function doAuth() {
  TOKEN   = document.getElementById('input-token').value.trim();
  GIST_ID = document.getElementById('input-gist').value.trim();
  const err = document.getElementById('auth-err');
  err.style.display = 'none';

  if (!TOKEN || !GIST_ID) {
    err.textContent = '请填写 Token 和 Gist ID';
    err.style.display = 'block';
    return;
  }
  localStorage.setItem('ds_token', TOKEN);
  localStorage.setItem('ds_gist',  GIST_ID);
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('main-screen').style.display = 'block';
  try {
    await loadData();
    renderAll();
    renderDashboard(dashboardData);
    setStatus('已同步', 'ok');
    document.getElementById('display-sync').textContent = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'});
  } catch(e) {
    document.getElementById('main-screen').style.display = 'none';
    document.getElementById('auth-screen').style.display = 'flex';
    setStatus('连接失败', 'err');
    err.textContent = e.message;
    err.style.display = 'block';
  }
}

// ============================================================
// 读取 Gist
// ============================================================
async function loadData() {
  setStatus('加载中…', '');
  const r = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
    headers: { Authorization: `token ${TOKEN}` }
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const gist = await r.json();

  const raw = gist.files?.['holdings.json']?.content;
  if (!raw) throw new Error('Gist 中没有 holdings.json');
  holdingsData = JSON.parse(raw);
  if (!holdingsData.holdings) holdingsData.holdings = [];
  if (!holdingsData.cash_available) holdingsData.cash_available = 0;

  const rawDashboard = gist.files?.['dashboard.json']?.content;
  dashboardData = rawDashboard ? JSON.parse(rawDashboard) : null;
}

// ============================================================
// 写回 Gist
// ============================================================
async function saveData() {
  setStatus('同步中…', '');
  try {
    const content = JSON.stringify(holdingsData, null, 2);
    const r = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
      method: 'PATCH',
      headers: {
        Authorization: `token ${TOKEN}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ files: { 'holdings.json': { content } } })
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    setStatus('已同步', 'ok');
    document.getElementById('display-sync').textContent =
      new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'});
    flashRefresh();
    toast('✅ 已保存', 'success');
  } catch(e) {
    setStatus('同步失败', 'err');
    toast('❌ 保存失败: ' + e.message, 'error');
  }
}

// ============================================================
// 渲染
// ============================================================
function renderAll() {
  const active = holdingsData.holdings.filter(h => h.qty > 0);
  document.getElementById('display-cash').textContent =
    '¥ ' + Number(holdingsData.cash_available).toLocaleString('zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2});
  document.getElementById('display-count').textContent = active.length;
  document.getElementById('holdings-badge').textContent = active.length;

  const list = document.getElementById('holdings-list');
  if (active.length === 0) {
    list.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><div>空仓中</div><div class="empty-hint">点击下方按钮买入建仓</div></div>';
    return;
  }

  list.innerHTML = active.map((h, idx) => {
    const fullIdx = holdingsData.holdings.indexOf(h);
    const info = CODE_MAP[h.symbol.slice(2)] || CODE_MAP[h.symbol];
    const name = info ? info.name : h.symbol;
    const displayCode = h.symbol.replace(/^(sh|sz)/, '');
    const prefix = h.symbol.startsWith('sh') ? 'SH' : 'SZ';
    const reduced = h.is_reduced ? ' <span style="color:var(--warn);font-size:10px">减仓</span>' : '';

    return `
    <div class="holding-card" id="card-${fullIdx}" style="animation-delay:${Math.min(idx * 0.04, 0.4)}s">
      <div class="card-main" onclick="toggleEdit(${fullIdx})">
        <div class="card-code-cell">
          <div class="card-code">${displayCode}</div>
          <div class="card-exch">${prefix}</div>
        </div>
        <div class="card-info">
          <div class="card-name" id="name-${fullIdx}">${name}${reduced}</div>
          <div class="card-meta">${h.qty.toLocaleString()} 份 · 成本 ${h.cost} · ${h.buy_date}</div>
        </div>
        <div class="card-col card-col-qty">${h.qty.toLocaleString()}</div>
        <div class="card-col card-col-cost">${h.cost}</div>
        <div class="card-col card-col-date">${h.buy_date}</div>
        <div class="card-actions">
          <button class="card-btn card-btn-reduce" onclick="event.stopPropagation();openReduce(${fullIdx})">减仓</button>
          <button class="card-btn card-btn-close" onclick="event.stopPropagation();closePosition(${fullIdx})">清仓</button>
        </div>
      </div>
      <div class="card-edit" id="edit-${fullIdx}">
        <div class="edit-row">
          <div class="edit-field">
            <div class="field-label">数量</div>
            <input type="number" id="eq-${fullIdx}" value="${h.qty}" inputmode="numeric" step="100">
          </div>
          <div class="edit-field">
            <div class="field-label">成本价</div>
            <input type="number" id="ec-${fullIdx}" value="${h.cost}" inputmode="decimal" step="0.001">
          </div>
        </div>
        <div class="edit-field">
          <div class="field-label">买入日期</div>
          <input type="date" id="ed-${fullIdx}" value="${h.buy_date}">
        </div>
        <div class="edit-save-row">
          <button class="btn btn-primary" onclick="saveCard(${fullIdx})" style="flex:1">保存</button>
          <button class="btn btn-ghost" onclick="toggleEdit(${fullIdx})" style="width:auto;padding:10px 14px">取消</button>
        </div>
      </div>
    </div>`;
  }).join('');

  // ─── ✅ 移动到这里：必须在 renderAll 函数内部执行 ───
  active.forEach(h => {
    const fullIdx = holdingsData.holdings.indexOf(h);
    const digits = h.symbol.replace(/\D/g, '');
    if (!CODE_MAP[digits]) {
      fetchOnlineName(h.symbol, (onlineName) => {
        const nameEl = document.getElementById(`name-${fullIdx}`);
        if (nameEl) {
          const reduced = h.is_reduced ? ' <span style="color:var(--warn);font-size:10px">减仓</span>' : '';
          nameEl.innerHTML = onlineName + reduced;
        }
      });
    }
  });
} // <─── 注意！这个大括号必须在最后面，用来闭合 renderAll 函数

function toggleEdit(idx) {
  const el = document.getElementById(`edit-${idx}`);
  el.classList.toggle('open');
}

// ============================================================
// AI分析看板（dashboard.json：干货=AI回复全文，原始数据折叠）
// ============================================================
function renderDashboard(data) {
  const aiSection = document.getElementById('ai-section');
  const aiMeta    = document.getElementById('ai-meta');
  const aiBody    = document.getElementById('ai-body');
  const reportSection = document.getElementById('report-section');
  const reportBody    = document.getElementById('report-body');
  if (!data) {
    aiSection.classList.remove('ai-err');
    aiSection.classList.remove('is-stale');
    reportSection.classList.remove('is-stale');
    aiMeta.textContent = '—';
    aiBody.innerHTML = '<div class="empty-state"><div class="empty-icon">🤖</div><div>暂无今日 AI 分析</div><div class="empty-hint">等待 dashboard.json 推送</div></div>';
    reportBody.innerHTML = '<div class="empty-state"><div class="empty-icon">📡</div><div>暂无扫描数据</div><div class="empty-hint">等待 report.txt 推送</div></div>';
    return;
  }

  const ai = data.ai || {};
  aiMeta.textContent = [data.generated_at, data.methodology_version, ai.model]
    .filter(Boolean).join(' · ') || '—';

  // 数据过期判断：generated_at 距今超过 24 小时视为过时
  const isStale = (() => {
    if (!data.generated_at) return false;
    const t = new Date(data.generated_at.replace(' ', 'T'));
    if (isNaN(t)) return false;
    return (Date.now() - t.getTime()) > 24 * 3600 * 1000;
  })();
  aiSection.classList.toggle('is-stale', isStale);
  reportSection.classList.toggle('is-stale', isStale);

  if (ai.ok && ai.text) {
    aiSection.classList.remove('ai-err');
    aiBody.innerHTML = marked.parse(ai.text);
    reportSection.open = false; // 干货已展示，原始数据默认折叠
  } else {
    aiSection.classList.add('ai-err');
    aiBody.innerHTML = `<div class="error-box">⚠️ AI分析失败：${escapeHtml(ai.error || '未知错误')}\n\n请展开下方「原始扫描数据」，手动复制给Gemini/DeepSeek网页版分析。</div>`;
    reportSection.open = true; // AI失败兜底：自动展开原始数据
  }

  reportBody.innerHTML = marked.parse(data.report || '(无数据)');
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ============================================================
// 资金编辑
// ============================================================
function toggleCashEdit() {
  const row = document.getElementById('cash-input-row');
  const showing = row.style.display === 'flex';
  row.style.display = showing ? 'none' : 'flex';
  if (!showing) {
    document.getElementById('input-cash').value = holdingsData.cash_available || '';
    document.getElementById('input-cash').focus();
  }
}
async function saveCash() {
  const val = parseFloat(document.getElementById('input-cash').value);
  if (isNaN(val) || val < 0) { toast('金额无效', 'error'); return; }
  holdingsData.cash_available = val;
  document.getElementById('cash-input-row').style.display = 'none';
  renderAll();
  await saveData();
}

// ============================================================
// 买入建仓
// ============================================================
function openDrawer() {
  document.getElementById('new-symbol').value = '';
  document.getElementById('new-qty').value = '';
  document.getElementById('new-cost').value = '';
  document.getElementById('new-date').value = today();
  document.getElementById('new-comment').value = '';
  document.getElementById('suggest-list').classList.remove('open');
  document.getElementById('drawer-overlay').classList.add('open');
  document.getElementById('drawer').classList.add('open');
  setTimeout(() => document.getElementById('new-symbol').focus(), 300);
}
function closeDrawer() {
  document.getElementById('drawer-overlay').classList.remove('open');
  document.getElementById('drawer').classList.remove('open');
}

function onSymbolInput(val) {
  const digits = val.replace(/\D/g, '');
  const list = document.getElementById('suggest-list');
  if (digits.length < 3) { list.classList.remove('open'); return; }

  const matches = Object.entries(ETF_POOL).filter(([code]) =>
    code.slice(2).startsWith(digits)
  );
  if (matches.length === 0) { list.classList.remove('open'); return; }

  list.innerHTML = matches.map(([code, name]) =>
    `<div class="suggest-item" onclick="selectSuggest('${code}','${name}')">
      <span class="suggest-code">${code}</span>
      <span class="suggest-name">${name}</span>
    </div>`
  ).join('');
  list.classList.add('open');
}

function selectSuggest(code, name) {
  document.getElementById('new-symbol').value = code.slice(2);
  document.getElementById('new-symbol').dataset.fullCode = code;
  document.getElementById('suggest-list').classList.remove('open');
  document.getElementById('new-qty').focus();
}

async function addHolding() {
  const rawSym  = document.getElementById('new-symbol').value.trim();
  const qty     = parseInt(document.getElementById('new-qty').value);
  const cost    = parseFloat(document.getElementById('new-cost').value);
  const date    = document.getElementById('new-date').value;
  const comment = document.getElementById('new-comment').value.trim();

  if (!rawSym) { toast('请输入代码', 'error'); return; }
  if (isNaN(qty) || qty <= 0) { toast('数量无效', 'error'); return; }
  if (isNaN(cost) || cost <= 0) { toast('成本价无效', 'error'); return; }
  if (!date) { toast('请选择日期', 'error'); return; }

// 解析完整代码（支持智能判别沪深前缀与自动纠错）
  let symbol = document.getElementById('new-symbol').dataset.fullCode || '';
  if (!symbol) {
    const digits = rawSym.replace(/\D/g, ''); // 提取纯6位数字
    if (digits.length === 6) {
      if (CODE_MAP[digits]) {
        symbol = CODE_MAP[digits].full; // 优先匹配已有可转债/ETF池
      } else if (/^(60|65|68|50|51|52|56|58)/.test(digits)) {
        symbol = 'sh' + digits;        // 上海主板、科创板、上海基金ETF（自动纠正类似 sz588800 的错误）
      } else if (/^(00|30|15|16|18)/.test(digits)) {
        symbol = 'sz' + digits;        // 深圳主板、创业板、深圳基金ETF
      } else if (/^(43|83|87|88)/.test(digits)) {
        symbol = 'bj' + digits;        // 北交所
      } else {
        // 兜底：如果无法识别，看用户有没有手动输入前缀
        symbol = (/^(sh|sz)/i.test(rawSym) ? rawSym.toLowerCase() : 'sh' + digits);
      }
    } else {
      toast('请输入正确的6位证券代码', 'error');
      return;
    }
  }

  // 检查是否已有该持仓（加仓）
  const existing = holdingsData.holdings.find(h => h.symbol === symbol && h.qty > 0);
  if (existing) {
    if (!confirm(`已有 ${symbol} 持仓，确认加仓？`)) return;
  }

  const entry = {
    symbol, qty, cost, buy_date: date,
    wave_type: '', is_reduced: false
  };
  if (comment) entry._comment = comment;

  holdingsData.holdings.push(entry);
  closeDrawer();
  renderAll();
  await saveData();
}

// ============================================================
// 减仓
// ============================================================
function openReduce(idx) {
  const h = holdingsData.holdings[idx];
  const newQty = prompt(`减仓 ${h.symbol}，当前 ${h.qty} 份\n请输入剩余份额：`);
  if (newQty === null) return;
  const qty = parseInt(newQty);
  if (isNaN(qty) || qty < 0 || qty >= h.qty) {
    toast('份额无效（须小于当前持仓且≥0）', 'error');
    return;
  }
  h.qty = qty;
  h.is_reduced = true;
  if (qty === 0) {
    removeCardWithAnimation(idx, () => {
      holdingsData.holdings.splice(idx, 1);
      renderAll();
      saveData();
    });
  } else {
    renderAll();
    saveData();
  }
}

// ============================================================
// 清仓
// ============================================================
function closePosition(idx) {
  const h = holdingsData.holdings[idx];
  if (!confirm(`确认清仓 ${h.symbol}？此操作将删除该记录。`)) return;
  removeCardWithAnimation(idx, () => {
    holdingsData.holdings.splice(idx, 1);
    renderAll();
    saveData();
  });
}

// 卡片退出动画：先加 exit 类，动画结束后再执行回调
function removeCardWithAnimation(idx, callback) {
  const card = document.getElementById(`card-${idx}`);
  if (!card) { callback(); return; }
  card.classList.add('exit');
  // 阻止点击穿透
  card.style.pointerEvents = 'none';
  setTimeout(callback, 200);
}

// ============================================================
// 保存卡片编辑
// ============================================================
async function saveCard(idx) {
  const qty  = parseInt(document.getElementById(`eq-${idx}`).value);
  const cost = parseFloat(document.getElementById(`ec-${idx}`).value);
  const date = document.getElementById(`ed-${idx}`).value;
  if (isNaN(qty) || isNaN(cost) || !date) { toast('数据无效', 'error'); return; }
  holdingsData.holdings[idx].qty = qty;
  holdingsData.holdings[idx].cost = cost;
  holdingsData.holdings[idx].buy_date = date;
  renderAll();
  await saveData();
}

// ============================================================
// 下载 holdings.json
// ============================================================
function downloadHoldings() {
  const ordered = { cash_available: holdingsData.cash_available, holdings: holdingsData.holdings };
  const content = JSON.stringify(ordered, null, 2);
  const blob = new Blob([content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'holdings.json';
  a.click();
  URL.revokeObjectURL(url);
}

// ============================================================
// 工具函数
// ============================================================
function setStatus(text, cls) {
  const el = document.getElementById('sync-status');
  el.textContent = text;
  el.className = 'topbar-status ' + cls;
}

let toastTimer;
function toast(msg, type='') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, 2500);
}

// 数据刷新闪烁：给持仓列表容器加一次短暂高亮
let flashTimer;
function flashRefresh() {
  const list = document.getElementById('holdings-list');
  if (!list) return;
  list.classList.remove('flash-refresh');
  // 强制重排以重启动画
  void list.offsetWidth;
  list.classList.add('flash-refresh');
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => list.classList.remove('flash-refresh'), 900);
}
