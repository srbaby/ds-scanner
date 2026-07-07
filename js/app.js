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

// ============================================================
// 状态
// ============================================================
let TOKEN = '', GIST_ID = '', holdingsData = {}, dashboardData = null, statsData = null, observerRequestData = null, gistETag = null;
const editOpenState = new Set();

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
      renderObserver(statsData);
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
    renderObserver(statsData);
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
}

// ============================================================
// 写回 Gist
// ============================================================
async function saveData() {
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
      body: JSON.stringify({ files: { 'holdings.json': { content } } })
    });
    if (!r.ok) {
      const detail = await r.text().catch(() => '');
      throw new Error(`HTTP ${r.status}${detail ? ' ' + detail.slice(0, 200) : ''}`);
    }
    gistETag = r.headers.get('ETag');
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
          <button class="btn btn-primary edit-save-btn" onclick="saveCard(${fullIdx})">保存</button>
          <button class="btn btn-ghost edit-cancel-btn" onclick="toggleEdit(${fullIdx})">取消</button>
        </div>
        <div class="edit-action-row">
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
  if (['SELL', 'BUY', 'HOLD', 'SKIP', 'ADD'].includes(t)) return t;
  if (/卖出|清仓|止损/.test(raw)) return 'SELL';
  if (/买入/.test(raw)) return 'BUY';
  if (/加仓/.test(raw)) return 'ADD';
  if (/持有|持\b/.test(raw)) return 'HOLD';
  if (/不开新仓|不操作|观望/.test(raw)) return 'SKIP';
  return 'INFO';
}

function actionLabel(type) {
  return { SELL: '卖出', BUY: '买入', HOLD: '持有', SKIP: '不开', ADD: '加仓', INFO: '提示' }[type] || '提示';
}

function normalizeActionField(value) {
  const text = String(value || '').trim();
  return text === '—' ? '' : text;
}

function parsePipeAction(line) {
  if (!line.includes('|')) return null;
  const cols = line.split('|').map(s => s.trim());
  if (cols.length < 5) return null;
  if (/^类型$/i.test(cols[0]) || /^[-:]+$/.test(cols[0])) return null;
  const type = normalizeActionType(cols[0]);
  if (type === 'INFO') return null;
  return {
    type,
    code: normalizeActionField(cols[1]),
    name: normalizeActionField(cols[2]),
    qty: normalizeActionField(cols[3]),
    note: normalizeActionField(cols.slice(4).join(' | ')),
  };
}

function splitActionLines(lines) {
  return lines
    .join('\n')
    .replace(/\s+(SELL|BUY|HOLD|SKIP|ADD)\s*\|/g, '\n$1 |')
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
    .replace(/^(卖出|买入|持有|加仓|清仓|止损|不开新仓|不操作|观望)\s*/i, '')
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

function renderQuickGuide(data, aiText) {
  const guide = document.getElementById('quick-guide');
  const body = document.getElementById('quick-guide-body');
  const meta = document.getElementById('quick-guide-meta');
  if (!guide || !body || !meta) return false;

  const parsed = extractQuickGuide(aiText);

  if (!parsed) {
    guide.hidden = true;
    body.innerHTML = '';
    meta.textContent = '—';
    return false;
  }

  meta.textContent = [data.generated_at, data.methodology_version].filter(Boolean).join(' · ') || '—';
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
      parts.push('</div>');
    });
    parts.push('</div>');
  }
  body.innerHTML = parts.join('');
  guide.hidden = false;
  return true;
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
  const quickGuide = document.getElementById('quick-guide');
  if (!aiSection || !aiMeta || !aiBody || !reportSection || !reportBody) return;

  if (!data) {
    if (quickGuide) quickGuide.hidden = true;
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

  const ai = data.ai || {};
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

  if (ai.ok && ai.text) {
    const hasQuickGuide = renderQuickGuide(data, ai.text);
    aiSection.classList.remove('ai-err');
    aiBody.innerHTML = renderMarkdown(ai.text);
    aiSection.open = !hasQuickGuide;
    reportSection.open = false; // 干货已展示，原始数据默认折叠
  } else {
    if (quickGuide) quickGuide.hidden = true;
    aiSection.classList.add('ai-err');
    aiSection.open = true;
    aiBody.innerHTML = `<div class="error-box">⚠️ AI分析失败：${escapeHtml(ai.error || '未知错误')}\n\n请展开下方「原始扫描数据」，手动复制给Gemini/DeepSeek网页版分析。</div>`;
    reportSection.open = true; // AI失败兜底：自动展开原始数据
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
  if (!window.crypto?.subtle) return '';
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
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
  delete document.getElementById('new-symbol').dataset.fullCode;
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
  // 用户手动改动了代码输入框，之前通过 selectSuggest 记下的完整代码作废，
  // 否则 addHolding() 会优先用旧的 fullCode 而非当前实际输入的代码（买入代码不匹配的bug）
  delete document.getElementById('new-symbol').dataset.fullCode;
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
    wave_type: '', is_reduced: false,
    _lot_id: makeClientLotId(symbol, date)
  };
  if (comment) entry._comment = comment;

  holdingsData.holdings.push(entry);
  editOpenState.clear();
  closeDrawer();
  renderAll();
  await saveData();
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
  editOpenState.clear();
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
  editOpenState.clear();
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
  editOpenState.delete(idx);
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
