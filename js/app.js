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

const OBSERVE_REPO = 'srbaby/ds-scanner';
const OBSERVE_WORKFLOW = 'observe.yml';
const OBSERVE_REF = 'main';
const DEFAULT_VERSIONS = {
  methodology_version: 'v3.1',
  prompt_contract_version: 'v3.1',
  data_schema_version: 'v3.0',
};

// ============================================================
// 状态
// ============================================================
let TOKEN = '', GIST_ID = '', holdingsData = {}, dashboardData = null, statsData = null, observerRequestData = null, gistETag = null;
let versionData = { ...DEFAULT_VERSIONS };
let executionEvents = [];
let dataManifest = {};
let gistRevision = '';
let currentAiActions = [];
let operationSaveInFlight = false;
const editOpenState = new Set();

// ============================================================
// 初始化
// ============================================================
window.onload = async () => {
  TOKEN   = localStorage.getItem('ds_token') || '';
  GIST_ID = localStorage.getItem('ds_gist')  || '';
  document.getElementById('new-date').value = today();
  await loadVersionManifest();
  document.getElementById('app-version').textContent = versionData.methodology_version;
  const brandRefresh = document.getElementById('brand-refresh');
  if (brandRefresh) {
    const trigger = () => location.reload();
    brandRefresh.addEventListener('click', trigger);
    brandRefresh.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        trigger();
      }
    });
  }

  if (TOKEN && GIST_ID) {
    document.getElementById('input-token').value = TOKEN;
    document.getElementById('input-gist').value  = GIST_ID;
    document.getElementById('auth-screen').style.display = 'none';
    document.getElementById('main-screen').style.display = 'block';
    loadData().then(() => {
      renderAll();
      renderDashboard(dashboardData);
      renderObserver(statsData);
      renderExecutionHistory();
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

function currentYear() {
  return today().slice(0, 4);
}

function executionFileName(year = currentYear()) {
  return `execution_events_${year}.jsonl`;
}

async function loadVersionManifest() {
  try {
    const r = await fetch('VERSION.json', { cache: 'no-store' });
    if (r.ok) versionData = { ...DEFAULT_VERSIONS, ...(await r.json()) };
  } catch (e) {
    versionData = { ...DEFAULT_VERSIONS };
  }
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
    renderObserver(statsData);
    renderExecutionHistory();
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
  gistETag = r.headers.get('ETag');
  gistRevision = gist.history?.[0]?.version || '';

  const raw = gist.files?.['holdings.json']?.content;
  if (!raw) throw new Error('Gist 中没有 holdings.json');
  holdingsData = JSON.parse(raw);
  editOpenState.clear();
  if (!holdingsData.holdings) holdingsData.holdings = [];
  if (!holdingsData.cash_available) holdingsData.cash_available = 0;

  const rawDashboard = gist.files?.['dashboard.json']?.content;
  dashboardData = rawDashboard ? JSON.parse(rawDashboard) : null;

  const rawStats = gist.files?.['stats.json']?.content;
  statsData = rawStats ? JSON.parse(rawStats) : null;

  const rawObserverRequest = gist.files?.['observer_request.json']?.content;
  observerRequestData = rawObserverRequest ? JSON.parse(rawObserverRequest) : null;

  const rawEvents = gist.files?.[executionFileName()]?.content || '';
  executionEvents = parseJsonl(rawEvents);
  const rawManifest = gist.files?.['data_manifest.json']?.content;
  dataManifest = rawManifest ? JSON.parse(rawManifest) : {};
}

// ============================================================
// 写回 Gist
// ============================================================
async function saveData(extraFiles = {}, successMessage = '✅ 已保存') {
  setStatus('同步中…', '');
  try {
    const content = JSON.stringify(holdingsData, null, 2);
    // 注意：GitHub Gist PATCH 接口不支持 If-Match 条件请求头，带上就会被直接拒绝
    // （400 "Conditional request headers are not allowed in unsafe requests unless
    // supported by the endpoint"）。之前加 If-Match 是想做乐观并发校验，但这个接口不支持，
    // 会导致所有写入（买入/加仓/减仓/清仓/改资金）100%保存失败，因此不发送该头。
    const r = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
      method: 'PATCH',
      headers: {
        Authorization: `token ${TOKEN}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ files: {
        'holdings.json': { content },
        ...Object.fromEntries(Object.entries(extraFiles).map(([name, value]) => [
          name, { content: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
        ])),
      } })
    });
    if (!r.ok) {
      const detail = await r.text().catch(() => '');
      throw new Error(`HTTP ${r.status}${detail ? ' ' + detail.slice(0, 200) : ''}`);
    }
    gistETag = r.headers.get('ETag');
    const updated = await r.json().catch(() => ({}));
    gistRevision = updated.history?.[0]?.version || gistRevision;
    setStatus('已同步', 'ok');
    document.getElementById('display-sync').textContent =
      new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'});
    flashRefresh();
    toast(successMessage, 'success');
    return true;
  } catch(e) {
    setStatus('同步失败', 'err');
    toast('❌ 未写入: ' + e.message, 'error');
    return false;
  }
}

function parseJsonl(raw) {
  return String(raw || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    .map(line => {
      try { return JSON.parse(line); } catch (e) { return null; }
    }).filter(Boolean);
}

function dumpJsonl(rows) {
  return rows.map(row => JSON.stringify(row)).join('\n') + (rows.length ? '\n' : '');
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function makeEventId(prefix = 'evt') {
  const uuid = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${uuid}`;
}

function holdingSnapshot(data, symbol) {
  if (!symbol) return null;
  const row = (data.holdings || []).find(h => normalizeFullSymbol(h.symbol) === normalizeFullSymbol(symbol) && Number(h.qty) > 0);
  return row ? deepClone(row) : null;
}

function portfolioMetrics(data) {
  const positions = (data.holdings || []).filter(h => Number(h.qty) > 0)
    .reduce((sum, h) => sum + Number(h.qty || 0) * Number(h.cost || 0), 0);
  const cash = Number(data.cash_available || 0);
  const total = positions + cash;
  return {
    account_total_value: Number(total.toFixed(2)),
    total_position_pct: total > 0 ? Number((positions / total * 100).toFixed(4)) : 0,
    valuation_basis: 'holding_cost',
  };
}

function selectedReason(selectId) {
  const select = document.getElementById(selectId);
  const option = select?.selectedOptions?.[0];
  if (!option) {
    return {
      ai_action_id: '',
      rule_code: 'MANUAL_BACKFILL',
      signal_grade: 'UNKNOWN',
      reason_zh: '人工补录',
      target_position_before_pct: null,
      target_position_after_pct: null,
      position_delta_pct: null,
      data_confidence: 'manual',
    };
  }
  try {
    return JSON.parse(option.dataset.reason || '{}');
  } catch (e) {
    return {};
  }
}

function buildExecutionEvent(eventType, symbol, beforeData, afterData, reason, extra = {}) {
  const beforeHolding = holdingSnapshot(beforeData, symbol);
  const afterHolding = holdingSnapshot(afterData, symbol);
  const beforeMetrics = portfolioMetrics(beforeData);
  const afterMetrics = portfolioMetrics(afterData);
  const qtyBefore = Number(beforeHolding?.qty || 0);
  const qtyAfter = Number(afterHolding?.qty || 0);
  const cashBefore = Number(beforeData.cash_available || 0);
  const cashAfter = Number(afterData.cash_available || 0);
  const cashDelta = Number((cashAfter - cashBefore).toFixed(2));
  const qtyDelta = qtyAfter - qtyBefore;
  const inferredPrice = qtyDelta && cashDelta
    ? Number((Math.abs(cashDelta) / Math.abs(qtyDelta)).toFixed(6))
    : null;
  return {
    event_id: makeEventId(),
    schema_version: versionData.data_schema_version,
    methodology_version: versionData.methodology_version,
    occurred_at: new Date().toLocaleString('sv-SE'),
    recorded_at: new Date().toISOString(),
    trade_date: today(),
    event_type: eventType,
    action: eventType,
    status: 'effective',
    symbol: symbol ? normalizeFullSymbol(symbol) : '',
    qty_before: qtyBefore,
    qty_after: qtyAfter,
    qty_delta: qtyDelta,
    cost_before: beforeHolding?.cost ?? null,
    cost_after: afterHolding?.cost ?? null,
    cash_before: cashBefore,
    cash_after: cashAfter,
    cash_delta: cashDelta,
    holding_before: beforeHolding,
    holding_after: afterHolding,
    account_total_value_before: beforeMetrics.account_total_value,
    account_total_value_after: afterMetrics.account_total_value,
    total_position_before_pct: beforeMetrics.total_position_pct,
    total_position_after_pct: afterMetrics.total_position_pct,
    valuation_basis: afterMetrics.valuation_basis,
    execution_price: inferredPrice,
    price_source: inferredPrice ? 'cash_delta_inferred' : (eventType === 'BUY' || eventType === 'ADD' ? 'holding_cost' : 'not_provided'),
    ai_action_id: reason.ai_action_id || '',
    rule_code: reason.rule_code || 'MANUAL_BACKFILL',
    signal_grade: reason.signal_grade || 'UNKNOWN',
    reason_zh: reason.reason_zh || '人工补录',
    target_position_before_pct: reason.target_position_before_pct ?? null,
    target_position_after_pct: reason.target_position_after_pct ?? null,
    position_delta_pct: reason.position_delta_pct ?? null,
    data_confidence: reason.data_confidence || (reason.ai_action_id ? 'ai_matched' : 'manual'),
    ...extra,
  };
}

function updateDataManifest(events) {
  const year = currentYear();
  const file = executionFileName(year);
  const last = events[events.length - 1];
  const files = { ...(dataManifest.files || {}) };
  files[file] = {
    kind: 'execution_events',
    year: Number(year),
    schema_version: versionData.data_schema_version,
    status: 'active',
    row_count: events.length,
    last_event_id: last?.event_id || '',
    updated_at: new Date().toISOString(),
  };
  dataManifest = {
    schema_version: versionData.data_schema_version,
    methodology_version: versionData.methodology_version,
    updated_at: new Date().toISOString(),
    files,
    legacy_files: {
      ...(dataManifest.legacy_files || {}),
      'trades.jsonl': { status: 'read_only_archive', migrated_to: `trades_${year}.jsonl` },
      'portfolio_snapshots.jsonl': { status: 'read_only_archive', migrated_to: `portfolio_snapshots_${year}.jsonl` },
    },
    migration_policy: {
      gist_file_warning_bytes: 500000,
      database_migration_bytes: 800000,
      database_target: 'Cloudflare D1',
    },
  };
}

async function assertNoRemoteChange() {
  const r = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
    headers: { Authorization: `token ${TOKEN}` },
    cache: 'no-store',
  });
  if (!r.ok) throw new Error(`并发检查失败 HTTP ${r.status}`);
  const gist = await r.json();
  const remoteRevision = gist.history?.[0]?.version || '';
  if (gistRevision && remoteRevision && gistRevision !== remoteRevision) {
    throw new Error('Gist 已被其他任务更新，请刷新页面后重试');
  }
}

async function verifyEventWritten(eventId) {
  const r = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
    headers: { Authorization: `token ${TOKEN}` },
    cache: 'no-store',
  });
  if (!r.ok) throw new Error(`写后校验失败 HTTP ${r.status}`);
  const gist = await r.json();
  gistRevision = gist.history?.[0]?.version || gistRevision;
  const raw = gist.files?.[executionFileName()]?.content || '';
  if (!parseJsonl(raw).some(row => row.event_id === eventId)) {
    throw new Error('写后校验未找到事件ID，请刷新确认');
  }
}

async function persistExecution(event, beforeData, afterData) {
  if (operationSaveInFlight) {
    toast('正在写入，请勿重复提交', 'error');
    return false;
  }
  operationSaveInFlight = true;
  const previousEvents = deepClone(executionEvents);
  const previousManifest = deepClone(dataManifest);
  try {
    await assertNoRemoteChange();
    executionEvents = [...executionEvents, event];
    holdingsData = afterData;
    updateDataManifest(executionEvents);
    const eventContent = dumpJsonl(executionEvents);
    const eventBytes = new TextEncoder().encode(eventContent).length;
    if (eventBytes >= 800000) {
      throw new Error('年度事件文件已达到800KB，请先迁移至Cloudflare D1');
    }
    dataManifest.files[executionFileName()].content_bytes = eventBytes;
    dataManifest.files[executionFileName()].content_sha256 = await sha256Hex(eventContent);
    const ok = await saveData({
      [executionFileName()]: eventContent,
      'data_manifest.json': dataManifest,
    }, '✅ 操作已登记');
    if (!ok) throw new Error('Gist 保存失败');
    await verifyEventWritten(event.event_id);
    if (eventBytes >= 500000) {
      toast('⚠️ 事件文件已超过500KB，请安排数据库迁移', 'error');
    }
    renderAll();
    renderExecutionHistory();
    return true;
  } catch (e) {
    holdingsData = beforeData;
    executionEvents = previousEvents;
    dataManifest = previousManifest;
    renderAll();
    renderExecutionHistory();
    setStatus('未写入', 'err');
    toast('❌ 未写入: ' + e.message, 'error');
    return false;
  } finally {
    operationSaveInFlight = false;
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
    const digits = h.symbol.replace(/\D/g, '');
    const poolName = CODE_MAP[digits]?.name;
    const name = poolName || h.name || h.symbol;
    const displayCode = h.symbol.replace(/^(sh|sz)/, '');
    const prefix = h.symbol.startsWith('sh') ? 'SH' : 'SZ';
    const reduced = h.is_reduced ? '<span class="holding-flag holding-flag-reduced">减仓</span>' : '';
    const isOpen = editOpenState.has(fullIdx);
    const openClass = isOpen ? ' is-open' : '';

    return `
    <div class="holding-card${openClass}" id="card-${fullIdx}">
      <div class="card-main" onclick="toggleEdit(${fullIdx})">
        <div class="card-code-cell">
          <div class="card-code">${displayCode}</div>
          <div class="card-exch">${prefix}</div>
        </div>
        <div class="card-info">
          <div class="card-title-row">
            <div class="card-name" id="name-${fullIdx}">${name}</div>
            ${reduced}
          </div>
          <div class="card-meta">${h.qty.toLocaleString()} 份 · 成本 ${h.cost} · ${h.buy_date}</div>
        </div>
        <div class="card-col card-col-qty">${h.qty.toLocaleString()}</div>
        <div class="card-col card-col-cost">${h.cost}</div>
        <div class="card-col card-col-date">${h.buy_date}</div>
        <div class="card-expand-indicator" aria-hidden="true">▾</div>
      </div>
      <div class="card-edit${isOpen ? ' open' : ''}" id="edit-${fullIdx}">
        <div class="edit-correction-note">更正持仓（仅纠错，不代表买卖交易）</div>
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
          <button class="btn btn-primary edit-save-btn" onclick="saveCard(${fullIdx})">确认更正</button>
          <button class="btn btn-ghost edit-cancel-btn" onclick="toggleEdit(${fullIdx})">取消</button>
        </div>
        <div class="edit-action-row">
          <button class="card-btn card-btn-add" onclick="openAdd(${fullIdx})">加仓</button>
          <button class="card-btn card-btn-reduce" onclick="openReduce(${fullIdx})">减仓</button>
          <button class="card-btn card-btn-close" onclick="closePosition(${fullIdx})">清仓</button>
        </div>
      </div>
    </div>`;
  }).join('');

  // ─── 异步补全池外名称（仅对无名称的标的触发 JSONP） ───
  active.forEach(h => {
    if (CODE_MAP[h.symbol.replace(/\D/g, '')]?.name || h.name) return;
    const fullIdx = holdingsData.holdings.indexOf(h);
    fetchOnlineName(h.symbol, (onlineName) => {
      const nameEl = document.getElementById(`name-${fullIdx}`);
      if (nameEl && onlineName) {
        nameEl.textContent = onlineName;
        h.name = onlineName;
      }
    });
  });
} // <─── 注意！这个大括号必须在最后面，用来闭合 renderAll 函数

function toggleEdit(idx) {
  if (editOpenState.has(idx)) {
    editOpenState.delete(idx);
  } else {
    editOpenState.add(idx);
  }
  renderAll();
}

// ============================================================
// 快速操作指引（仅提取标准回复末尾的执行窗口/操作清单）
// ============================================================
function getAiSection(text, heading) {
  const lines = String(text || '').split('\n');
  const start = lines.findIndex(line => line.trim().startsWith(`【${heading}】`));
  if (start < 0) return [];
  const out = [];
  for (let i = start + 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (/^【[^】]+】/.test(line)) break;
    if (line) out.push(line);
  }
  return out;
}

function normalizeActionType(raw) {
  const t = String(raw || '').trim().toUpperCase();
  if (['SELL', 'BUY', 'HOLD', 'SKIP', 'ADD', 'REDUCE', 'WATCH'].includes(t)) return t;
  if (/卖出|清仓|止损/.test(raw)) return 'SELL';
  if (/减仓/.test(raw)) return 'REDUCE';
  if (/买入/.test(raw)) return 'BUY';
  if (/加仓/.test(raw)) return 'ADD';
  if (/持有|持\b/.test(raw)) return 'HOLD';
  if (/观察|待确认/.test(raw)) return 'WATCH';
  if (/不开新仓|不操作|观望/.test(raw)) return 'SKIP';
  return 'INFO';
}

function actionLabel(type) {
  return {
    SELL: '卖出', BUY: '买入', HOLD: '持有', SKIP: '不开', ADD: '加仓',
    REDUCE: '减仓', WATCH: '观察', CASH_UPDATE: '改资金',
    CORRECT_POSITION: '更正持仓', CORRECT_REASON: '更正原因',
    REVERSE_EVENT: '撤销', INFO: '提示'
  }[type] || '提示';
}

function normalizeActionField(value) {
  const text = String(value || '').trim();
  return text === '—' ? '' : text;
}

function parsePipeAction(line) {
  if (!line.includes('|')) return null;
  const cols = line.trim().replace(/^\||\|$/g, '').split('|').map(s => s.trim());
  if (cols.length < 5) return null;
  if (/操作编号|类型/.test(cols[0]) || /^[-:]+$/.test(cols[0])) return null;
  const isV3 = /^OP[-_ ]?\d+/i.test(cols[0]) && cols.length >= 11;
  const offset = isV3 ? 1 : 0;
  const type = normalizeActionType(cols[offset]);
  if (type === 'INFO') return null;
  if (isV3) {
    return {
      actionId: cols[0],
      type,
      code: normalizeActionField(cols[2]),
      name: normalizeActionField(cols[3]),
      currentTarget: normalizeActionField(cols[4]),
      target: normalizeActionField(cols[5]),
      delta: normalizeActionField(cols[6]),
      ruleCode: normalizeActionField(cols[7]),
      signalGrade: normalizeActionField(cols[8]),
      reasonZh: normalizeActionField(cols[9]),
      metrics: normalizeActionField(cols.slice(10).join(' / ')),
      qty: normalizeActionField(cols[6]),
      note: normalizeActionField(cols[9]),
    };
  }
  return {
    type,
    code: normalizeActionField(cols[1]),
    name: normalizeActionField(cols[2]),
    qty: normalizeActionField(cols[3]),
    note: normalizeActionField(cols.slice(4).join(' | ')),
    actionId: '',
    ruleCode: '',
    signalGrade: '',
    reasonZh: normalizeActionField(cols.slice(4).join(' | ')),
    currentTarget: '',
    target: '',
    delta: normalizeActionField(cols[3]),
    metrics: '',
  };
}

function splitActionLines(lines) {
  return lines
    .join('\n')
    .split('\n')
    .map(line => line.trim())
    .filter(line => line && !line.startsWith('注：'));
}

function parseBulletAction(line) {
  let text = String(line || '').replace(/^[\s>*\-•·]+/, '').trim();
  if (!text) return null;
  const type = normalizeActionType(text);
  if (type === 'INFO') return null;
  const codeMatch = text.match(/(?:sh|sz)?\d{6}/i);
  const code = codeMatch ? codeMatch[0] : '';
  let rest = text
    .replace(/^(卖出|买入|持有|加仓|减仓|观察|清仓|止损|不开新仓|不操作|观望)\s*/i, '')
    .replace(code, '')
    .trim();
  const qtyMatch = rest.match(/(全部|一半|\d+(?:\.\d+)?%仓位|\d+(?:\.\d+)?%|\d+份)/);
  const qty = qtyMatch ? qtyMatch[1] : '';
  if (qty) rest = rest.replace(qty, '').trim();
  return { type, code, name: '', qty, note: rest.replace(/[（）()]/g, '').trim() };
}

function extractQuickGuide(aiText) {
  const windowLines = getAiSection(aiText, '执行窗口');
  const actionLines = getAiSection(aiText, '操作清单');
  const windowText = windowLines.find(line => !line.includes('|') && !line.startsWith('类型')) || '';

  let actions = splitActionLines(actionLines)
    .map(parsePipeAction)
    .filter(Boolean);

  if (actions.length === 0) {
    actions = windowLines
      .map(parseBulletAction)
      .filter(Boolean);
  }

  if (!windowText && actions.length === 0) return null;
  return { windowText, actions };
}

function actionToReason(action) {
  return {
    ai_action_id: action.actionId || '',
    rule_code: action.ruleCode || 'MANUAL_BACKFILL',
    signal_grade: action.signalGrade || 'UNKNOWN',
    reason_zh: action.reasonZh || action.note || '人工补录',
    target_position_before_pct: parseFloat(action.currentTarget) || 0,
    target_position_after_pct: parseFloat(action.target) || 0,
    position_delta_pct: parseFloat(action.delta) || 0,
    data_confidence: action.authority === 'scanner' ? 'scanner_authoritative' : action.actionId ? 'ai_matched' : 'manual',
  };
}

function reasonOptionsFor(symbol, types = []) {
  const normalized = symbol ? normalizeFullSymbol(symbol) : '';
  const allowed = Array.isArray(types) ? types : [types];
  const rows = currentAiActions.filter(action => {
    const sameSymbol = normalized && normalizeFullSymbol(action.code) === normalized;
    return sameSymbol && (!allowed.length || allowed.includes(action.type));
  });
  return rows.map(action => ({
    label: `${action.actionId} · ${action.reasonZh || action.note}（${action.ruleCode}）`,
    reason: actionToReason(action),
  }));
}

function manualReasonOption() {
  return {
    label: '人工补录（不计入方法论统计）',
    reason: {
      ai_action_id: '',
      rule_code: 'MANUAL_BACKFILL',
      signal_grade: 'UNKNOWN',
      reason_zh: '人工补录',
      target_position_before_pct: null,
      target_position_after_pct: null,
      position_delta_pct: null,
      data_confidence: 'manual',
    },
  };
}

function fillReasonSelect(selectId, symbol, types, preferredRule = '') {
  const select = document.getElementById(selectId);
  if (!select) return;
  const normalizedTypes = Array.isArray(types) ? types : [types];
  const options = reasonOptionsFor(symbol, types);
  const status = document.getElementById(`${selectId}-status`);
  const manualButton = document.getElementById(`${selectId}-manual`);
  select.dataset.reasonSymbol = symbol || '';
  select.dataset.reasonTypes = JSON.stringify(normalizedTypes);
  select.dataset.preferredRule = preferredRule || '';
  select.dataset.manualOverride = 'false';

  if (options.length) {
    select.disabled = false;
    select.innerHTML = options.map((item, idx) => {
      const selected = preferredRule && item.reason.rule_code === preferredRule ? ' selected' : (!preferredRule && idx === 0 ? ' selected' : '');
      return `<option value="${idx}" data-reason="${escapeHtml(JSON.stringify(item.reason))}"${selected}>${escapeHtml(item.label)}</option>`;
    }).join('');
    if (status) {
      status.className = 'reason-status reason-status-ok';
      status.textContent = `已匹配当日扫描器清单（${options.length} 条）`;
    }
  } else {
    select.disabled = true;
    select.innerHTML = '<option value="">今日扫描器清单无此代码与动作</option>';
    if (status) {
      status.className = 'reason-status reason-status-error';
      status.textContent = symbol
        ? '未匹配到当日扫描器操作，不能按方法论登记。'
        : '请先输入证券代码，以匹配当日扫描器操作。';
    }
  }
  if (manualButton) {
    manualButton.textContent = '转人工补录';
    manualButton.hidden = !symbol;
  }
  if (selectId === 'new-reason') renderBuyGuidance();
}

function toggleManualReason(selectId) {
  const select = document.getElementById(selectId);
  if (!select) return;
  if (select.dataset.manualOverride === 'true') {
    fillReasonSelect(
      selectId,
      select.dataset.reasonSymbol || '',
      JSON.parse(select.dataset.reasonTypes || '[]'),
      select.dataset.preferredRule || '',
    );
    return;
  }
  if (!confirm('人工补录不计入方法论有效性统计。仅用于纠错或补历史，确认继续？')) return;
  const item = manualReasonOption();
  select.disabled = false;
  select.dataset.manualOverride = 'true';
  select.innerHTML = `<option value="manual" data-reason="${escapeHtml(JSON.stringify(item.reason))}" selected>${escapeHtml(item.label)}</option>`;
  const status = document.getElementById(`${selectId}-status`);
  const manualButton = document.getElementById(`${selectId}-manual`);
  if (status) {
    status.className = 'reason-status reason-status-manual';
    status.textContent = '人工补录已启用，本次记录不会进入方法论统计。';
  }
  if (manualButton) manualButton.textContent = '恢复扫描器匹配';
}

function hasValidReason(selectId) {
  const select = document.getElementById(selectId);
  return !!select && !select.disabled && !!select.selectedOptions?.[0]?.dataset.reason;
}

function decisionOperationsToActions(operations) {
  return (operations || []).map(op => ({
    actionId: op.id || '',
    type: normalizeActionType(op.action),
    code: op.symbol || '',
    name: op.name || '',
    currentTarget: String(op.current_target_position_pct ?? 0),
    target: String(op.target_position_pct ?? 0),
    delta: String(op.adjustment_pct ?? 0),
    ruleCode: op.rule_code || '',
    signalGrade: op.signal_grade || '',
    reasonZh: op.reason || '',
    metrics: JSON.stringify(op.metrics || {}),
    qty: `${op.adjustment_pct > 0 ? '+' : ''}${op.adjustment_pct || 0}%`,
    note: op.reason || '',
    authority: 'scanner',
    guidance: op.execution_guidance || null,
  }));
}

function renderQuickGuide(data, aiText) {
  const guide = document.getElementById('quick-guide');
  const body = document.getElementById('quick-guide-body');
  const meta = document.getElementById('quick-guide-meta');
  if (!guide || !body || !meta) return false;

  const scannerOps = data?.decision?.operations || [];
  const parsed = scannerOps.length ? {
    windowText: '',
    actions: decisionOperationsToActions(scannerOps),
  } : extractQuickGuide(aiText);

  if (!parsed) {
    guide.hidden = true;
    body.innerHTML = '';
    meta.textContent = '—';
    return false;
  }

  meta.textContent = [data.generated_at, data.methodology_version].filter(Boolean).join(' · ') || '—';
  currentAiActions = parsed.actions || [];
  const parts = [];
  if (parsed.windowText) {
    parts.push(`<div class="quick-window">${escapeHtml(parsed.windowText)}</div>`);
  }
  if (parsed.actions.length) {
    parts.push('<div class="quick-actions">');
    parsed.actions.forEach(action => {
      const type = action.type.toLowerCase();
      const main = [action.code, action.name].filter(Boolean).join(' ');
      const title = main || action.note || actionLabel(action.type);
      parts.push(`<div class="quick-action quick-action-${type}">`);
      parts.push(`<div class="quick-type">${actionLabel(action.type)}</div>`);
      parts.push(`<div class="quick-main">${escapeHtml(title)}</div>`);
      parts.push(`<div class="quick-qty">${escapeHtml(action.qty || '')}</div>`);
      if (action.note && action.note !== title) {
        parts.push(`<div class="quick-note">${escapeHtml(action.note)}</div>`);
      }
      if (action.ruleCode) {
        parts.push(`<div class="quick-note">${escapeHtml(action.ruleCode)} · ${escapeHtml(action.reasonZh || '')}</div>`);
      }
      parts.push('</div>');
    });
    parts.push('</div>');
  }
  body.innerHTML = parts.join('');
  guide.hidden = false;
  return true;
}

function renderPolicyWatch(data) {
  const panel = document.getElementById('policy-watch');
  const meta = document.getElementById('policy-watch-meta');
  const badge = document.getElementById('policy-watch-badge');
  const body = document.getElementById('policy-watch-body');
  if (!panel || !meta || !badge || !body) return;

  if (!data || data.enabled === false) {
    panel.hidden = true;
    body.innerHTML = '';
    meta.textContent = '等待政策旁路数据';
    badge.textContent = '—';
    return;
  }

  panel.hidden = false;
  if (data.ok === false) {
    meta.textContent = data.error || '政策旁路观察暂不可用';
    badge.textContent = '未生成';
    body.innerHTML = '<div class="policy-watch-empty">等待下一次扫描生成政策旁路观察。</div>';
    return;
  }

  const summary = data.summary || {};
  const risk = data.holdings_risk || [];
  const triggers = data.near_triggers || [];
  const downgrades = data.near_downgrades || [];
  const deltas = data.active_policy_deltas || [];
  const totalWatch = risk.length + triggers.length + downgrades.length;
  meta.textContent = data.generated_at || '随每日扫描更新';
  meta.title = data.updated_frequency || '';
  badge.textContent = totalWatch ? `${totalWatch}项关注` : '无触发';

  const sections = [];
  sections.push(`<div class="policy-watch-summary">激进度 ${signedNumber(summary.aggression_index || 0)} · ${escapeHtml(summary.verdict || '可接受')} · 活跃偏移 ${summary.active_delta_count || deltas.length}</div>`);
  sections.push(policyWatchRows('持仓风险', risk, 'risk'));
  sections.push(policyWatchRows('可能触发操作', triggers, 'trigger'));
  sections.push(policyWatchRows('持仓降级观察', downgrades, 'risk'));
  if (deltas.length) {
    sections.push('<div class="policy-delta-list">' + deltas.map(row => {
      const cls = row.delta > 0 ? 'is-pos' : 'is-neg';
      return `<span class="policy-delta ${cls}">${escapeHtml(row.theme)} ${signedNumber(row.delta)}</span>`;
    }).join('') + '</div>');
  }
  body.innerHTML = sections.join('');
}

function policyWatchRows(title, rows, tone) {
  if (!rows || !rows.length) return '';
  const items = rows.map(row => {
    const blockers = row.gap?.blockers?.length ? row.gap.blockers.join(' / ') : '已满足主要条件';
    const eventTitle = row.events?.[0]?.title || '';
    const action = row.shadow_action ? `${row.shadow_action} ${row.target_position_pct || 0}%` : `差B级 ${row.gap?.score_to_b ?? '—'}分`;
    return `<div class="policy-watch-row policy-watch-${tone}">
      <div class="policy-watch-row-main">
        <span class="policy-watch-symbol">${escapeHtml(row.symbol || '')}</span>
        <span class="policy-watch-name">${escapeHtml(row.name || '')}</span>
        <span class="policy-watch-action">${escapeHtml(action)}</span>
      </div>
      <div class="policy-watch-row-sub">${escapeHtml(row.theme || '')} ${signedNumber(row.policy_delta || 0)} · 评分 ${row.base_score || 0}→${row.shadow_score || 0} · ${escapeHtml(blockers)}</div>
      ${eventTitle ? `<div class="policy-watch-event">${escapeHtml(eventTitle)}</div>` : ''}
    </div>`;
  }).join('');
  return `<div class="policy-watch-group"><div class="policy-watch-group-title">${escapeHtml(title)}</div>${items}</div>`;
}

function signedNumber(value) {
  const n = Number(value || 0);
  return `${n > 0 ? '+' : ''}${Number.isInteger(n) ? n : n.toFixed(2)}`;
}
// ============================================================
// 扫描器权威决策 + AI非权威审计
// ============================================================
function renderDashboard(data) {
  const aiSection = document.getElementById('ai-section');
  const aiMeta    = document.getElementById('ai-meta');
  const aiBody    = document.getElementById('ai-body');
  const reportSection = document.getElementById('report-section');
  const reportBody    = document.getElementById('report-body');
  const quickGuide = document.getElementById('quick-guide');
  if (!aiSection || !aiMeta || !aiBody || !reportSection || !reportBody) return;

  if (!data) {
    currentAiActions = [];
    if (quickGuide) quickGuide.hidden = true;
    renderPolicyWatch(null);
    aiSection.classList.remove('ai-err');
    aiSection.classList.remove('is-stale');
    aiSection.classList.remove('is-fresh');
    reportSection.classList.remove('is-stale');
    reportSection.classList.remove('is-fresh');
    aiMeta.textContent = '—';
    aiBody.innerHTML = '<div class="empty-state"><div class="empty-icon">🤖</div><div>暂无今日 AI 分析</div><div class="empty-hint">等待 dashboard.json 推送</div></div>';
    reportBody.innerHTML = '<div class="empty-state"><div class="empty-icon">📡</div><div>暂无扫描数据</div><div class="empty-hint">等待 report.txt 推送</div></div>';
    return;
  }

  renderPolicyWatch(data.policy_research);

  const ai = data.audit || data.ai || {};
  aiMeta.textContent = [data.methodology_version, ai.model]
    .filter(Boolean).join(' · ') || '—';

  // 数据过期判断：同日不标过期；周末对周五数据宽松；超过24h标记
  const isStale = (() => {
    if (!data.generated_at) return false;
    const t = new Date(data.generated_at.replace(' ', 'T'));
    if (isNaN(t)) return false;
    const now = new Date();
    // 同一自然日 → 不过期
    if (t.toDateString() === now.toDateString()) return false;
    // 周末宽松：周五/周四数据延长到周一早上
    const hoursSince = (now - t) / (3600 * 1000);
    const day = now.getDay();
    if ((day === 0 || day === 6) && hoursSince < 72) return false;
    if (day === 1 && hoursSince < 84) return false;
    // 超过24h → 过期
    return hoursSince > 24;
  })();
  aiSection.classList.toggle('is-stale', isStale);
  reportSection.classList.toggle('is-stale', isStale);
  aiSection.classList.toggle('is-fresh', !isStale && !!data.generated_at);
  reportSection.classList.toggle('is-fresh', !isStale && !!data.generated_at);

  const hasDecision = !!data?.decision?.operations?.length;
  const hasQuickGuide = renderQuickGuide(data, (data.ai || {}).text || '');
  if (ai.enabled === false) {
    aiSection.classList.remove('ai-err');
    aiBody.innerHTML = '<div class="empty-state"><div class="empty-icon">📡</div><div>每日AI审计已停用</div><div class="empty-hint">操作清单由扫描器确定性生成</div></div>';
    aiSection.open = false;
    reportSection.open = false;
  } else if (ai.ok && ai.text) {
    aiSection.classList.remove('ai-err');
    aiBody.innerHTML = renderMarkdown(ai.text);
    aiSection.open = !hasQuickGuide;
    reportSection.open = false; // 干货已展示，原始数据默认折叠
  } else {
    if (!hasDecision) {
      currentAiActions = [];
      if (quickGuide) quickGuide.hidden = true;
    }
    aiSection.classList.toggle('ai-err', !hasDecision);
    aiSection.open = true;
    aiBody.innerHTML = `<div class="error-box">⚠️ AI审计不可用：${escapeHtml(ai.error || '未知错误')}\n\n扫描器权威操作清单仍然有效。</div>`;
    reportSection.open = !hasDecision;
  }

  reportBody.innerHTML = renderMarkdown(data.report || '(无数据)');
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function renderMarkdown(text) {
  if (window.marked && typeof window.marked.parse === 'function') {
    return window.marked.parse(text);
  }
  return escapeHtml(text).replace(/\n/g, '<br>');
}

// ============================================================
// 量化观察面板（stats.json：只读展示，确认按钮只写一致性信号）
// ============================================================
function renderObserver(data) {
  const panel = document.getElementById('observer-panel');
  const meta = document.getElementById('observer-meta');
  const kpis = document.getElementById('observer-kpis');
  const chart = document.getElementById('observer-chart');
  const legend = document.getElementById('observer-legend');
  const insight = document.getElementById('observer-insight');
  const progress = document.getElementById('observer-progress');
  const quality = document.getElementById('observer-quality');
  if (!panel || !meta || !kpis || !chart || !legend || !progress || !quality) return;

  if (!data) {
    meta.textContent = observerRequestData?.requested_at
      ? `已确认 ${observerRequestData.requested_at}`
      : '等待线上观察任务';
    kpis.innerHTML = observerEmptyKpis();
    chart.innerHTML = '<div class="observer-chart-empty">暂无净值曲线</div>';
    legend.innerHTML = '';
    if (insight) insight.innerHTML = '';
    progress.innerHTML = observerProgressRows();
    quality.textContent = 'stats.json 尚未生成';
    return;
  }

  meta.textContent = data.generated_at ? `更新 ${data.generated_at}` : '已生成';
  const summary = data.summary || {};
  kpis.innerHTML = [
    observerKpi('总收益', pctText(summary.total_return_pct), summary.total_return_pct),
    observerKpi('最大回撤', pctText(summary.max_drawdown_pct), summary.max_drawdown_pct),
    observerKpi('胜率', pctText(summary.win_rate_pct), summary.win_rate_pct),
    observerKpi('盈亏比', numText(summary.profit_loss_ratio), summary.profit_loss_ratio),
    observerKpi('平均持仓', dayText(summary.avg_holding_days), summary.avg_holding_days),
  ].join('');

  renderObserverChartInteractive(chart, legend, data.series || {}, data, insight);

  const graduation = data.graduation || {};
  const breaker = data.circuit_breaker || {};
  progress.innerHTML = observerProgressRows([
    ['毕业A', graduation.condition_a_progress_pct, graduation.message || '观察中'],
    ['毕业B', graduation.condition_b_progress_pct, '绝对收益线'],
    ['熔断', breaker.condition_a_progress_pct, breaker.message || '正常'],
  ]);

  const dq = data.data_quality || {};
  const notes = Array.isArray(dq.notes) && dq.notes.length ? ` · ${dq.notes.slice(0, 2).join(' / ')}` : '';
  quality.textContent = `成交 ${dq.trade_count || 0} · 低置信 ${dq.low_confidence_trade_count || 0} · 快照 ${dq.snapshot_count || 0}${notes}`;
}

function observerEmptyKpis() {
  return ['总收益', '最大回撤', '胜率', '盈亏比', '平均持仓']
    .map(label => observerKpi(label, '—', null))
    .join('');
}

function observerKpi(label, value, raw) {
  const cls = raw < 0 ? ' is-neg' : raw > 0 ? ' is-pos' : '';
  return `<div class="observer-kpi${cls}">
    <div class="observer-kpi-label">${label}</div>
    <div class="observer-kpi-val">${escapeHtml(value)}</div>
  </div>`;
}

function observerProgressRows(rows = []) {
  if (!rows.length) rows = [['毕业A', 0, '等待数据'], ['毕业B', 0, '等待数据'], ['熔断', 0, '正常']];
  return rows.map(([label, value, note]) => {
    const pct = Math.max(0, Math.min(100, Number(value) || 0));
    return `<div class="observer-progress-row">
      <div class="observer-progress-head">
        <span>${escapeHtml(label)}</span>
        <span>${pct.toFixed(0)}%</span>
      </div>
      <div class="observer-bar"><div style="width:${pct}%"></div></div>
      <div class="observer-progress-note">${escapeHtml(note || '')}</div>
    </div>`;
  }).join('');
}

function renderObserverChartInteractive(chartEl, legendEl, series, stats = {}, insightEl = null) {
  const lineDefs = [
    ['xplan', 'X-Plan', 'solid'],
    ['hs300', '沪深300全收益', 'dash'],
    ['csi500', '中证500全收益', 'dot'],
    ['enhanced_ref', '宽基增强参考', 'longdash'],
  ];
  const lines = lineDefs.map(([key, label, style]) => {
    const points = Array.isArray(series[key]) ? series[key] : [];
    const byDate = new Map(points.map(p => [p.date, Number(p.value)]).filter(([, v]) => Number.isFinite(v)));
    return { key, label, style, points, byDate };
  }).filter(line => line.points.length > 0);

  if (!lines.length) {
    chartEl.innerHTML = '<div class="observer-chart-empty">暂无净值曲线</div>';
    legendEl.innerHTML = '';
    if (insightEl) insightEl.innerHTML = '';
    return;
  }

  const dates = Array.from(new Set(lines.flatMap(line => line.points.map(p => p.date).filter(Boolean)))).sort();
  const all = lines.flatMap(line => Array.from(line.byDate.values()));
  const min = Math.min(...all, 95);
  const max = Math.max(...all, 105);
  const pad = Math.max((max - min) * 0.12, 2);
  const lo = min - pad;
  const hi = max + pad;
  const width = 640;
  const height = 220;
  const left = 34;
  const right = 14;
  const top = 16;
  const bottom = 26;
  const plotW = width - left - right;
  const plotH = height - top - bottom;
  const xFor = idx => left + (dates.length <= 1 ? plotW : (idx / (dates.length - 1)) * plotW);
  const yFor = value => top + (1 - (value - lo) / (hi - lo || 1)) * plotH;
  const dashMap = { solid: '', dash: '8 7', dot: '2 7', longdash: '14 6' };

  const grid = [lo, (lo + hi) / 2, hi].map(v => {
    const y = yFor(v);
    return `<line class="observer-grid" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"></line>
      <text class="observer-axis" x="2" y="${y + 4}">${v.toFixed(0)}</text>`;
  }).join('');

  const svgLines = lines.map(line => {
    let started = false;
    const d = dates.map((date, idx) => {
      const value = line.byDate.get(date);
      if (!Number.isFinite(value)) {
        started = false;
        return '';
      }
      const cmd = started ? 'L' : 'M';
      started = true;
      return `${cmd}${xFor(idx).toFixed(1)},${yFor(value).toFixed(1)}`;
    }).filter(Boolean).join(' ');
    return `<path class="observer-line observer-line-${line.key}" d="${d}" stroke-dasharray="${dashMap[line.style]}"></path>`;
  }).join('');

  const hitAreas = dates.map((date, idx) => {
    const prevX = idx === 0 ? left : (xFor(idx - 1) + xFor(idx)) / 2;
    const nextX = idx === dates.length - 1 ? width - right : (xFor(idx) + xFor(idx + 1)) / 2;
    return `<rect class="observer-hit" data-index="${idx}" x="${prevX.toFixed(1)}" y="${top}" width="${(nextX - prevX).toFixed(1)}" height="${plotH}"></rect>`;
  }).join('');

  chartEl.innerHTML = `<div class="observer-tooltip" hidden></div>
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="观察净值曲线">
      ${grid}
      ${svgLines}
      <line class="observer-hover-line" x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}" hidden></line>
      ${hitAreas}
    </svg>`;

  legendEl.innerHTML = lines.map(line => {
    const lastPoint = [...line.points].reverse().find(p => Number.isFinite(Number(p.value)));
    const lastValue = lastPoint ? Number(lastPoint.value).toFixed(1) : '--';
    return `<div class="observer-legend-item observer-legend-${line.key}">
      <span></span>${escapeHtml(line.label)} ${lastValue}
    </div>`;
  }).join('');

  const tooltip = chartEl.querySelector('.observer-tooltip');
  const hoverLine = chartEl.querySelector('.observer-hover-line');
  chartEl.querySelectorAll('.observer-hit').forEach(hit => {
    hit.addEventListener('mousemove', event => {
      const idx = Number(hit.dataset.index);
      const date = dates[idx];
      const x = xFor(idx);
      if (hoverLine) {
        hoverLine.setAttribute('x1', x.toFixed(1));
        hoverLine.setAttribute('x2', x.toFixed(1));
        hoverLine.hidden = false;
      }
      if (tooltip) {
        tooltip.innerHTML = observerTooltipHtml(date, lines);
        tooltip.hidden = false;
        const box = chartEl.getBoundingClientRect();
        const leftPx = Math.min(Math.max(event.clientX - box.left + 12, 8), Math.max(box.width - 240, 8));
        const topPx = Math.max(event.clientY - box.top - 18, 8);
        tooltip.style.left = `${leftPx}px`;
        tooltip.style.top = `${topPx}px`;
      }
    });
    hit.addEventListener('mouseleave', () => {
      if (tooltip) tooltip.hidden = true;
      if (hoverLine) hoverLine.hidden = true;
    });
  });

  if (insightEl) insightEl.innerHTML = observerInsightHtml(lines, stats);
}

function observerTooltipHtml(date, lines) {
  const xplan = observerLineValue(lines, 'xplan', date);
  const hs300 = observerLineValue(lines, 'hs300', date);
  const csi500 = observerLineValue(lines, 'csi500', date);
  const rows = lines.map(line => {
    const value = line.byDate.get(date);
    const text = Number.isFinite(value) ? value.toFixed(2) : '--';
    return `<div class="observer-tooltip-row observer-tooltip-${line.key}">
      <span>${escapeHtml(line.label)}</span><strong>${text}</strong>
    </div>`;
  }).join('');
  const hsExcess = Number.isFinite(xplan) && Number.isFinite(hs300) ? xplan - hs300 : null;
  const csiExcess = Number.isFinite(xplan) && Number.isFinite(csi500) ? xplan - csi500 : null;
  const excessText = [
    Number.isFinite(hsExcess) ? `较沪深300 ${signedNum(hsExcess)}点` : '',
    Number.isFinite(csiExcess) ? `较中证500 ${signedNum(csiExcess)}点` : '',
  ].filter(Boolean).join(' / ');
  return `<div class="observer-tooltip-date">${escapeHtml(date || '')}</div>
    ${rows}
    ${excessText ? `<div class="observer-tooltip-note">${escapeHtml(excessText)}</div>` : ''}`;
}

function observerInsightHtml(lines, stats) {
  const lastDate = Array.from(new Set(lines.flatMap(line => line.points.map(p => p.date).filter(Boolean)))).sort().pop();
  const xplan = observerLineValue(lines, 'xplan', lastDate);
  const hs300 = observerLineValue(lines, 'hs300', lastDate);
  const csi500 = observerLineValue(lines, 'csi500', lastDate);
  const enhanced = observerLineValue(lines, 'enhanced_ref', lastDate);
  const parts = [];
  if (Number.isFinite(xplan) && Number.isFinite(hs300)) parts.push(`较沪深300 ${signedNum(xplan - hs300)}点`);
  if (Number.isFinite(xplan) && Number.isFinite(csi500)) parts.push(`较中证500 ${signedNum(xplan - csi500)}点`);
  if (Number.isFinite(xplan) && Number.isFinite(enhanced)) parts.push(`较增强参考 ${signedNum(xplan - enhanced)}点`);
  const graduation = stats.graduation || {};
  const breaker = stats.circuit_breaker || {};
  const gradB = Number(graduation.condition_b_progress_pct);
  const breakerA = Number(breaker.condition_a_progress_pct);
  const tail = [
    Number.isFinite(gradB) ? `毕业B ${gradB.toFixed(0)}%` : '',
    Number.isFinite(breakerA) ? `熔断压力 ${breakerA.toFixed(0)}%` : '',
  ].filter(Boolean).join('，');
  const summary = parts.length ? `当前 ${Number(xplan).toFixed(1)}，${parts.join('，')}` : '等待更多观察点';
  return `<strong>图表解读</strong>：${escapeHtml(summary)}${tail ? `；${escapeHtml(tail)}` : ''}。`;
}

function observerLineValue(lines, key, date) {
  const line = lines.find(item => item.key === key);
  if (!line || !date) return null;
  const value = line.byDate.get(date);
  return Number.isFinite(value) ? value : null;
}

function signedNum(value) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}`;
}

async function confirmObservation() {
  if (!TOKEN || !GIST_ID) return;
  const btn = document.getElementById('observer-confirm-btn');
  if (btn) btn.disabled = true;
  setStatus('确认观察…', '');
  try {
    const canonical = canonicalHoldingsForObserve();
    const request = {
      requested_at: new Date().toLocaleString('sv-SE'),
      date: today(),
      source: 'frontend_confirm',
      holdings_canonical: canonical,
      holdings_hash: await sha256Short(JSON.stringify(canonical)),
      note: '用户确认当前 holdings.json 已补录完成，可高置信观察',
    };
    const r = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
      method: 'PATCH',
      headers: {
        Authorization: `token ${TOKEN}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ files: { 'observer_request.json': { content: JSON.stringify(request, null, 2) } } })
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    observerRequestData = request;
    renderObserver(statsData);
    const triggered = await triggerObserveWorkflow();
    setStatus(triggered ? '已触发观察' : '已确认', 'ok');
    toast(triggered ? '✅ 已确认并触发观察' : '✅ 已确认观察，晚间兜底会处理', 'success');
  } catch(e) {
    setStatus('确认失败', 'err');
    toast('❌ 确认失败: ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function triggerObserveWorkflow() {
  try {
    const r = await fetch(`https://api.github.com/repos/${OBSERVE_REPO}/actions/workflows/${OBSERVE_WORKFLOW}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify({ ref: OBSERVE_REF, inputs: { observe_date: today() } }),
    });
    return r.status === 204;
  } catch (e) {
    return false;
  }
}

function canonicalHoldingsForObserve() {
  const rows = (holdingsData.holdings || [])
    .filter(h => Number(h.qty) > 0)
    .map(h => {
      const symbol = normalizeFullSymbol(h.symbol);
      return {
        symbol,
        name: h.name || ETF_POOL[symbol] || symbol,
        qty: parseInt(h.qty) || 0,
        cost: Number(Number(h.cost || 0).toFixed(6)),
        buy_date: String(h.buy_date || ''),
        _lot_id: h._lot_id || '',
        is_reduced: !!h.is_reduced,
      };
    })
    .sort((a, b) => [a.symbol, a.buy_date, a.cost, a.qty, a._lot_id].join('|').localeCompare([b.symbol, b.buy_date, b.cost, b.qty, b._lot_id].join('|')));
  return {
    cash_available: Number(Number(holdingsData.cash_available || 0).toFixed(2)),
    holdings: rows,
  };
}

function normalizeFullSymbol(raw) {
  const text = String(raw || '').trim().toLowerCase();
  const digits = text.replace(/\D/g, '');
  if (digits.length !== 6) return text;
  if (/^(sh|sz|bj)/.test(text)) return text.slice(0, 2) + digits;
  if (/^(60|65|68|50|51|52|56|58)/.test(digits)) return 'sh' + digits;
  if (/^(00|30|15|16|18)/.test(digits)) return 'sz' + digits;
  return 'sh' + digits;
}

async function sha256Short(text) {
  return (await sha256Hex(text)).slice(0, 16);
}

async function sha256Hex(text) {
  if (!window.crypto?.subtle) return '';
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function pctText(value) {
  if (value === null || value === undefined || value === '') return '—';
  return `${Number(value).toFixed(2)}%`;
}

function numText(value) {
  if (value === null || value === undefined || value === '') return '—';
  return Number(value).toFixed(2);
}

function dayText(value) {
  if (value === null || value === undefined || value === '') return '—';
  return `${Number(value).toFixed(1)}天`;
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
  const before = deepClone(holdingsData);
  const after = deepClone(holdingsData);
  after.cash_available = val;
  const reason = {
    ai_action_id: '',
    rule_code: 'CASH_UPDATE',
    signal_grade: 'N/A',
    reason_zh: '可用资金调整（非交易）',
    data_confidence: 'manual',
  };
  const event = buildExecutionEvent('CASH_UPDATE', '', before, after, reason);
  document.getElementById('cash-input-row').style.display = 'none';
  await persistExecution(event, before, after);
}

// ============================================================
// 买入建仓
// ============================================================
function calculateBuyGuidance(totalAsset, adjustmentPct, referencePrice, lotSize = 100) {
  const total = Number(totalAsset);
  const delta = Number(adjustmentPct);
  const price = Number(referencePrice);
  if (!(total > 0) || !(delta > 0) || !(price > 0) || !(lotSize > 0)) return null;
  const targetAmount = total * delta / 100;
  const lots = Math.floor(targetAmount / price / lotSize);
  const shares = lots * lotSize;
  if (shares <= 0) return null;
  const estimatedAmount = shares * price;
  return {
    lot_size: lotSize,
    reference_price: Number(price.toFixed(3)),
    target_amount: Number(targetAmount.toFixed(2)),
    recommended_shares: shares,
    recommended_lots: lots,
    estimated_amount: Number(estimatedAmount.toFixed(2)),
    rounding_residual: Number((targetAmount - estimatedAmount).toFixed(2)),
  };
}

function currentBuyGuidance() {
  const raw = document.getElementById('new-symbol')?.value || '';
  const digits = raw.replace(/\D/g, '');
  if (digits.length !== 6) return null;
  const symbol = normalizeFullSymbol(
    document.getElementById('new-symbol')?.dataset.fullCode || raw
  );
  const reason = selectedReason('new-reason');
  const action = currentAiActions.find(item =>
    item.actionId === reason.ai_action_id
    && normalizeFullSymbol(item.code) === symbol
    && ['BUY', 'ADD'].includes(item.type)
  ) || currentAiActions.find(item =>
    normalizeFullSymbol(item.code) === symbol && ['BUY', 'ADD'].includes(item.type)
  );
  if (!action) return null;

  const signal = (dashboardData?.decision?.signals || []).find(item =>
    normalizeFullSymbol(item.full_symbol || item.symbol) === symbol
  );
  const enteredPrice = Number(document.getElementById('new-cost')?.value);
  const calculated = calculateBuyGuidance(
    dashboardData?.decision?.portfolio?.total_asset,
    Number(action.delta),
    enteredPrice > 0 ? enteredPrice : signal?.price,
  );
  return calculated || action.guidance || null;
}

function renderBuyGuidance() {
  const el = document.getElementById('new-guidance');
  if (!el) return;
  const guidance = currentBuyGuidance();
  if (!guidance) {
    el.innerHTML = '输入当日 BUY / ADD 标的后显示建议份额';
    return;
  }
  el.innerHTML = `
    <strong>扫描器执行参考</strong><br>
    目标新增约 ¥${Number(guidance.target_amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}，
    建议 <strong>${Number(guidance.recommended_shares).toLocaleString()} 份
    （${Number(guidance.recommended_lots)} 手）</strong><br>
    扫描参考价 ${Number(guidance.reference_price).toFixed(3)}，
    预计占用 ¥${Number(guidance.estimated_amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
    <div><button type="button" class="reason-manual-btn" onclick="applyBuyGuidance()">填入建议</button></div>
    <small>实际成交价、费用和可用资金以券商为准</small>`;
}

function applyBuyGuidance() {
  const guidance = currentBuyGuidance();
  if (!guidance) {
    toast('当前没有可用的扫描器份额建议', 'error');
    return;
  }
  document.getElementById('new-qty').value = guidance.recommended_shares;
  document.getElementById('new-cost').value = Number(guidance.reference_price).toFixed(3);
  document.getElementById('new-cash').value = Math.max(
    0,
    Number(holdingsData.cash_available || 0) - Number(guidance.estimated_amount || 0)
  ).toFixed(2);
  updateNewPreview();
}

function openDrawer() {
  document.getElementById('new-symbol').value = '';
  delete document.getElementById('new-symbol').dataset.fullCode;
  document.getElementById('new-qty').value = '';
  document.getElementById('new-cost').value = '';
  document.getElementById('new-date').value = today();
  document.getElementById('new-cash').value = holdingsData.cash_available || '';
  fillReasonSelect('new-reason', '', ['BUY', 'ADD']);
  updateNewPreview();
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
  // 用户手动改动了代码输入框，之前通过 selectSuggest 记下的完整代码作废，
  // 否则 addHolding() 会优先用旧的 fullCode 而非当前实际输入的代码（买入代码不匹配的bug）
  delete document.getElementById('new-symbol').dataset.fullCode;
  const digits = val.replace(/\D/g, '');
  if (digits.length === 6) {
    const symbol = normalizeFullSymbol(val);
    const existing = (holdingsData.holdings || []).some(h => normalizeFullSymbol(h.symbol) === symbol && Number(h.qty) > 0);
    fillReasonSelect('new-reason', symbol, existing ? ['ADD'] : ['BUY']);
  } else {
    fillReasonSelect('new-reason', '', ['BUY', 'ADD']);
  }
  updateNewPreview();
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
  const existing = (holdingsData.holdings || []).some(h => normalizeFullSymbol(h.symbol) === code && Number(h.qty) > 0);
  fillReasonSelect('new-reason', code, existing ? ['ADD'] : ['BUY']);
  updateNewPreview();
  document.getElementById('new-qty').focus();
}

async function addHolding() {
  const rawSym  = document.getElementById('new-symbol').value.trim();
  const qty     = parseInt(document.getElementById('new-qty').value);
  const cost    = parseFloat(document.getElementById('new-cost').value);
  const date    = document.getElementById('new-date').value;
  const cashAfter = parseFloat(document.getElementById('new-cash').value);

  if (!rawSym) { toast('请输入代码', 'error'); return; }
  if (isNaN(qty) || qty <= 0) { toast('数量无效', 'error'); return; }
  if (qty % 100 !== 0) { toast('ETF买入数量必须是100份的整数倍', 'error'); return; }
  if (isNaN(cost) || cost <= 0) { toast('成本价无效', 'error'); return; }
  if (isNaN(cashAfter) || cashAfter < 0) { toast('操作后可用资金无效', 'error'); return; }
  if (!date) { toast('请选择日期', 'error'); return; }
  if (!hasValidReason('new-reason')) {
    toast('未匹配到当日扫描器操作；如属纠错或补历史，请先显式启用人工补录', 'error');
    return;
  }

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

  const before = deepClone(holdingsData);
  const after = deepClone(holdingsData);
  const existingAfter = after.holdings.find(h => normalizeFullSymbol(h.symbol) === symbol && Number(h.qty) > 0);
  const entry = {
    symbol, qty, cost, buy_date: date,
    wave_type: '', is_reduced: false,
    _lot_id: makeClientLotId(symbol, date)
  };
  if (existingAfter) {
    existingAfter.qty = Number(existingAfter.qty) + qty;
    existingAfter.cost = cost;
  } else {
    after.holdings.push(entry);
  }
  after.cash_available = cashAfter;
  const eventType = existingAfter ? 'ADD' : 'BUY';
  const reason = selectedReason('new-reason');
  const event = buildExecutionEvent(eventType, symbol, before, after, reason);
  editOpenState.clear();
  if (await persistExecution(event, before, after)) closeDrawer();
}

function updateNewPreview() {
  const qty = parseInt(document.getElementById('new-qty')?.value);
  const cost = parseFloat(document.getElementById('new-cost')?.value);
  const cash = parseFloat(document.getElementById('new-cash')?.value);
  const el = document.getElementById('new-preview');
  if (!el) return;
  if (!Number.isFinite(qty) || !Number.isFinite(cost) || !Number.isFinite(cash)) {
    el.textContent = '填写后显示持仓与资金变化';
    return;
  }
  el.textContent = `本次登记 ${qty.toLocaleString()} 份，成本 ${cost.toFixed(3)}；可用资金 ${Number(holdingsData.cash_available || 0).toFixed(2)} → ${cash.toFixed(2)}`;
}

function makeClientLotId(symbol, buyDate) {
  const day = String(buyDate || today()).replace(/\D/g, '').slice(0, 8);
  const prefix = `${symbol}#${day}#`;
  const used = (holdingsData.holdings || [])
    .map(h => h._lot_id || '')
    .filter(id => id.startsWith(prefix))
    .map(id => parseInt((id.match(/(\d+)$/) || [0, 0])[1], 10))
    .filter(Number.isFinite);
  const next = (used.length ? Math.max(...used) : 0) + 1;
  return `${prefix}${String(next).padStart(2, '0')}`;
}

// ============================================================
// 加仓 / 减仓
// ============================================================
function openAdd(idx) {
  const h = holdingsData.holdings[idx];
  openOperationDialog('ADD', idx, {
    title: `加仓 ${h.symbol}`,
    qty: h.qty,
    cost: h.cost,
    cash: holdingsData.cash_available,
    reasonTypes: ['ADD'],
  });
}

function openReduce(idx) {
  const h = holdingsData.holdings[idx];
  openOperationDialog('REDUCE', idx, {
    title: `减仓 ${h.symbol}`,
    qty: h.qty,
    cost: h.cost,
    cash: holdingsData.cash_available,
    reasonTypes: ['REDUCE'],
  });
}

// ============================================================
// 清仓
// ============================================================
function closePosition(idx) {
  const h = holdingsData.holdings[idx];
  openOperationDialog('SELL', idx, {
    title: `清仓 ${h.symbol}`,
    qty: 0,
    cost: h.cost,
    cash: holdingsData.cash_available,
    reasonTypes: ['SELL'],
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
  const before = deepClone(holdingsData);
  const after = deepClone(holdingsData);
  after.holdings[idx].qty = qty;
  after.holdings[idx].cost = cost;
  after.holdings[idx].buy_date = date;
  const reason = {
    ai_action_id: '',
    rule_code: 'CORRECT_POSITION',
    signal_grade: 'N/A',
    reason_zh: '更正持仓登记（不计入方法论统计）',
    data_confidence: 'correction',
  };
  const event = buildExecutionEvent('CORRECT_POSITION', after.holdings[idx].symbol, before, after, reason);
  editOpenState.delete(idx);
  await persistExecution(event, before, after);
}

function openOperationDialog(mode, idx, options = {}) {
  const dialog = document.getElementById('operation-dialog');
  const h = Number.isInteger(idx) && idx >= 0 ? holdingsData.holdings[idx] : null;
  document.getElementById('operation-mode').value = mode;
  document.getElementById('operation-index').value = Number.isInteger(idx) ? idx : '';
  document.getElementById('operation-event-id').value = options.eventId || '';
  document.getElementById('operation-dialog-title').textContent = options.title || '登记操作';
  document.getElementById('operation-qty').value = options.qty ?? h?.qty ?? '';
  document.getElementById('operation-cost').value = options.cost ?? h?.cost ?? '';
  document.getElementById('operation-cash').value = options.cash ?? holdingsData.cash_available ?? '';
  document.getElementById('operation-qty-label').textContent =
    mode === 'ADD' ? '操作后总份额' : '操作后剩余份额';
  document.getElementById('operation-qty-wrap').style.display = mode === 'CORRECT_REASON' ? 'none' : 'block';
  document.getElementById('operation-cost-wrap').style.display = ['REDUCE', 'SELL', 'CORRECT_REASON'].includes(mode) ? 'none' : 'block';
  document.getElementById('operation-cash-wrap').style.display = mode === 'CORRECT_REASON' ? 'none' : 'block';
  const symbol = h?.symbol || options.symbol || '';
  fillReasonSelect('operation-reason', symbol, options.reasonTypes || [mode], options.preferredRule || '');
  document.getElementById('operation-preview').textContent =
    mode === 'CORRECT_REASON'
      ? '只更正操作依据，不改变持仓和资金。原记录会保留并标记为已更正。'
      : mode === 'ADD'
        ? `当前 ${h?.qty ?? 0} 份；请填写加仓后的总份额、持仓成本和可用资金。`
        : `当前 ${h?.qty ?? 0} 份；请填写操作后的剩余份额和可用资金。`;
  dialog.showModal();
}

function closeOperationDialog() {
  document.getElementById('operation-dialog').close();
}

function validateOperationInput(mode, currentQty, qtyAfter, costAfter) {
  if (mode === 'ADD') {
    if (!Number.isFinite(qtyAfter) || qtyAfter <= Number(currentQty)) {
      return '加仓后的总份额必须大于当前持仓';
    }
    if (!Number.isFinite(costAfter) || costAfter <= 0) {
      return '加仓后的持仓成本无效';
    }
    return '';
  }
  if (!Number.isFinite(qtyAfter) || qtyAfter < 0 || qtyAfter >= Number(currentQty)) {
    return '剩余份额必须小于当前持仓且不小于0';
  }
  if (mode === 'SELL' && qtyAfter !== 0) {
    return '清仓后的剩余份额必须为0';
  }
  return '';
}

async function confirmOperationDialog() {
  const mode = document.getElementById('operation-mode').value;
  const idx = parseInt(document.getElementById('operation-index').value);
  const targetEventId = document.getElementById('operation-event-id').value;
  if (!hasValidReason('operation-reason')) {
    toast('未匹配到当日扫描器操作；如属纠错或补历史，请先显式启用人工补录', 'error');
    return;
  }
  const reason = selectedReason('operation-reason');
  if (mode === 'CORRECT_REASON') {
    const original = executionEvents.find(row => row.event_id === targetEventId);
    if (!original) { toast('找不到原操作记录', 'error'); return; }
    const before = deepClone(holdingsData);
    const event = buildExecutionEvent('CORRECT_REASON', original.symbol, before, before, reason, {
      target_event_id: targetEventId,
      previous_rule_code: original.rule_code,
      previous_reason_zh: original.reason_zh,
    });
    if (await persistExecution(event, before, before)) closeOperationDialog();
    return;
  }

  const h = holdingsData.holdings[idx];
  if (!h) { toast('持仓不存在，请刷新', 'error'); return; }
  const qtyAfter = parseInt(document.getElementById('operation-qty').value);
  const costAfter = parseFloat(document.getElementById('operation-cost').value);
  const cashAfter = parseFloat(document.getElementById('operation-cash').value);
  const operationError = validateOperationInput(mode, h.qty, qtyAfter, costAfter);
  if (operationError) { toast(operationError, 'error'); return; }
  if (!Number.isFinite(cashAfter) || cashAfter < 0) {
    toast('操作后可用资金无效', 'error'); return;
  }
  const before = deepClone(holdingsData);
  const after = deepClone(holdingsData);
  const symbol = h.symbol;
  if (mode === 'ADD') {
    after.holdings[idx].qty = qtyAfter;
    after.holdings[idx].cost = costAfter;
  } else if (qtyAfter === 0) {
    after.holdings.splice(idx, 1);
  } else {
    after.holdings[idx].qty = qtyAfter;
    after.holdings[idx].is_reduced = true;
  }
  after.cash_available = cashAfter;
  const event = buildExecutionEvent(mode, symbol, before, after, reason);
  editOpenState.clear();
  if (await persistExecution(event, before, after)) closeOperationDialog();
}

function eventDisplayState(event) {
  const reversed = executionEvents.some(row => row.event_type === 'REVERSE_EVENT' && row.target_event_id === event.event_id);
  if (reversed) return { status: '已撤销', cls: 'reversed' };
  const correction = [...executionEvents].reverse()
    .find(row => row.event_type === 'CORRECT_REASON' && row.target_event_id === event.event_id);
  if (correction) return {
    status: '已更正',
    cls: 'corrected',
    reason_zh: correction.reason_zh,
    rule_code: correction.rule_code,
  };
  return { status: '有效', cls: 'effective' };
}

function canReverseEvent(event) {
  if (!['BUY', 'ADD', 'REDUCE', 'SELL', 'CASH_UPDATE', 'CORRECT_POSITION'].includes(event.event_type)) return false;
  if (eventDisplayState(event).status === '已撤销') return false;
  const index = executionEvents.findIndex(row => row.event_id === event.event_id);
  const laterEffectiveEvents = executionEvents.slice(index + 1)
    .filter(row => !['CORRECT_REASON', 'REVERSE_EVENT'].includes(row.event_type));
  if (event.event_type === 'CASH_UPDATE') {
    return laterEffectiveEvents.length === 0;
  }
  return !laterEffectiveEvents.some(row =>
    event.symbol && normalizeFullSymbol(row.symbol) === normalizeFullSymbol(event.symbol)
  );
}

function renderExecutionHistory() {
  const list = document.getElementById('execution-list');
  const meta = document.getElementById('execution-meta');
  if (!list || !meta) return;
  const baseEvents = executionEvents.filter(row => !['CORRECT_REASON', 'REVERSE_EVENT'].includes(row.event_type));
  const todayCount = baseEvents.filter(row => String(row.trade_date || row.occurred_at || '').startsWith(today())).length;
  meta.textContent = `今日 ${todayCount} 笔 · 本年 ${baseEvents.length} 笔 · ${executionFileName()}`;
  if (!baseEvents.length) {
    list.innerHTML = '<div class="empty-state"><div>暂无操作记录</div><div class="empty-hint">买卖、资金修改和更正都会显示在这里</div></div>';
    return;
  }
  list.innerHTML = [...baseEvents].reverse().slice(0, 30).map(event => {
    const display = eventDisplayState(event);
    const reason = display.reason_zh || event.reason_zh || '—';
    const rule = display.rule_code || event.rule_code || '—';
    const qtyText = event.symbol
      ? `${Number(event.qty_before || 0).toLocaleString()} → ${Number(event.qty_after || 0).toLocaleString()} 份`
      : `资金 ${Number(event.cash_before || 0).toFixed(2)} → ${Number(event.cash_after || 0).toFixed(2)}`;
    const canCorrectReason = ['BUY', 'ADD', 'REDUCE', 'SELL'].includes(event.event_type);
    const actions = display.status === '已撤销' ? '' : `
      ${canCorrectReason ? `<button onclick="correctEventReason('${event.event_id}')">更正原因</button>` : ''}
      ${canReverseEvent(event) ? `<button class="danger" onclick="reverseExecution('${event.event_id}')">撤销登记</button>` : ''}
    `;
    return `<div class="execution-row execution-${display.cls}">
      <div class="execution-row-main">
        <span class="execution-action">${escapeHtml(actionLabel(event.event_type))}</span>
        <strong>${escapeHtml(event.symbol || '可用资金')}</strong>
        <span>${escapeHtml(qtyText)}</span>
        <span class="execution-status">${display.status}</span>
      </div>
      <div class="execution-reason">${escapeHtml(reason)} · ${escapeHtml(rule)}</div>
      <div class="execution-foot">
        <span>${escapeHtml(event.occurred_at || '')}</span>
        <div class="execution-buttons">${actions}</div>
      </div>
    </div>`;
  }).join('');
}

function correctEventReason(eventId) {
  const event = executionEvents.find(row => row.event_id === eventId);
  if (!event) return;
  openOperationDialog('CORRECT_REASON', -1, {
    title: `更正 ${event.symbol || '资金'} 的操作依据`,
    eventId,
    symbol: event.symbol,
    reasonTypes: [event.action],
    preferredRule: event.rule_code,
  });
}

async function reverseExecution(eventId) {
  const original = executionEvents.find(row => row.event_id === eventId);
  if (!original || !canReverseEvent(original)) {
    toast('该记录已有后续同标的操作，请使用更正登记', 'error');
    return;
  }
  if (!confirm('仅撤销 X-Plan 登记，不会撤销券商真实成交。确认继续？')) return;
  const before = deepClone(holdingsData);
  const after = deepClone(holdingsData);
  if (original.symbol) {
    after.holdings = (after.holdings || []).filter(h => normalizeFullSymbol(h.symbol) !== normalizeFullSymbol(original.symbol));
    if (original.holding_before && Number(original.holding_before.qty) > 0) {
      after.holdings.push(deepClone(original.holding_before));
    }
  }
  after.cash_available = Number((Number(after.cash_available || 0) - Number(original.cash_delta || 0)).toFixed(2));
  const reason = {
    ai_action_id: '',
    rule_code: 'REVERSE_EVENT',
    signal_grade: 'N/A',
    reason_zh: `撤销登记：${original.reason_zh || original.rule_code || original.event_type}`,
    data_confidence: 'correction',
  };
  const event = buildExecutionEvent('REVERSE_EVENT', original.symbol, before, after, reason, {
    target_event_id: original.event_id,
    reversed_event_type: original.event_type,
  });
  await persistExecution(event, before, after);
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



