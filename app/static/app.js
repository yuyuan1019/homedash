// HomeDash 前端：vanilla JS，单页家庭管理 Tab

const API = {
  bootstrapStatus: '/api/auth/bootstrap-status',
  bootstrapAdmin: '/api/auth/bootstrap-admin',
  login: '/api/auth/login',
  logout: '/api/auth/logout',
  me: '/api/auth/me',
  users: '/api/admin/users',
  user: (id) => `/api/admin/users/${id}`,
  userPassword: (id) => `/api/admin/users/${id}/password`,
  items: '/api/items',
  item: (id) => `/api/items/${id}`,
  itemUsage: (id) => `/api/items/${id}/usage`,
  itemPurchase: (id) => `/api/items/${id}/purchase`,
  itemHistory: (id) => `/api/items/${id}/history`,
  predictions: '/api/items/predictions',
  itemFacets: '/api/items/facets',
  itemImages: (id) => `/api/items/${id}/images`,
  itemImage: (id, imgId) => `/api/items/${id}/images/${encodeURIComponent(imgId)}`,
  placements: '/api/placements',
  placement: (id) => `/api/placements/${id}`,
  placementSuggest: (id) => `/api/placements/${id}/suggest`,
  placementConfirm: (id) => `/api/placements/${id}/confirm`,
  placementImages: (id) => `/api/placements/${id}/images`,
  placementImage: (id, imgId) => `/api/placements/${id}/images/${encodeURIComponent(imgId)}`,
  todos: (status = 'open') => `/api/todos?status=${status}`,
  todo: (id) => `/api/todos/${id}`,
  todoDone: (id) => `/api/todos/${id}/done`,
  todoReopen: (id) => `/api/todos/${id}/reopen`,
  aiAudit: '/api/ai/audit',
  aiRevert: '/api/ai/revert',
  aiSuggestedChips: '/api/ai/suggested-chips',
  aiChat: '/api/ai/chat',
  aiItemCategory: '/api/ai/item-category',
  setupStatus: '/api/setup/status',
  setupLlmConfig: '/api/setup/llm/config',
  setupLlmSave: '/api/setup/llm/save',
  setupLlmTest: '/api/setup/llm/test',
  setupLlmModels: '/api/setup/llm/models',
  setupBraveConfig: '/api/setup/brave/config',
  setupBraveSave: '/api/setup/brave/save',
  setupBraveTest: '/api/setup/brave/test',
  setupAmapConfig: '/api/setup/amap/config',
  setupAmapSave: '/api/setup/amap/save',
  setupAmapTest: '/api/setup/amap/test',
  setupAgentConfig: '/api/setup/agent/config',
  setupAgentSave: '/api/setup/agent/save',
  setupNotifyConfig: '/api/setup/notify/config',
  setupNotifySave: '/api/setup/notify/save',
  setupNotifyTest: '/api/setup/notify/test',
  notifyTest: '/api/notify/test',
  travelPlans: '/api/travel/plans',
  travelPlan: (id) => `/api/travel/plans/${id}`,
  travelRecommend: (id) => `/api/travel/plans/${id}/recommend`,
  travelPacking: (id) => `/api/travel/plans/${id}/packing`,
  travelSuggest: '/api/travel/suggest',
  travelSpots: (id) => `/api/travel/plans/${id}/spots`,
};

let currentTab = 'ai';
let todoStatus = 'open';
let todoQuery = '';      // 待办即时搜索：按标题或内容过滤
let todosCache = [];     // 当前已加载的待办，供搜索框重渲染时复用，避免重复请求
let chatMessages = [];
let setupStatusData = null;
let itemCategoryTimer = null;
let itemFacetsCache = null;
let currentUser = null;

// ============ 工具函数 ============

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
  }
  if (res.status === 401 && !url.startsWith('/api/auth/')) renderAuthForm(false);
  return { ok: res.ok, status: res.status, data };
}

function toast(msg, type = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = type;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3000);
}

function showModal(html) {
  const el = document.getElementById('modal');
  el.innerHTML = html;
  el.classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal').classList.add('hidden');
}

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));
}

// 从后端错误响应里提取可读提示：FastAPI 422 的 detail 是数组，直接 toast 会显示成 [object Object]
function detailMsg(data, fallback = '操作失败') {
  const d = data?.detail;
  if (typeof d === 'string' && d) return d;
  if (Array.isArray(d) && d.length) {
    const first = d[0];
    if (typeof first === 'string') return first;
    const loc = Array.isArray(first?.loc) ? first.loc.filter((x) => x !== 'body').join('.') : '';
    return first?.msg ? (loc ? `${loc}: ${first.msg}` : first.msg) : fallback;
  }
  return fallback;
}

// 简单的 Markdown 渲染函数
function renderMarkdown(text) {
  if (!text) return '';

  // 转义 HTML 特殊字符
  let html = esc(text);

  // 代码块 ```language\ncode\n```
  html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
    return `<pre><code class="language-${lang || 'text'}">${code.trim()}</code></pre>`;
  });

  // 行内代码 `code`
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // 粗体 **text** 或 __text__
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');

  // 斜体 *text* 或 _text_
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/_([^_]+)_/g, '<em>$1</em>');

  // 标题 ## Heading
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // 无序列表 - item 或 * item
  html = html.replace(/^[*-] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

  // 有序列表 1. item
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  // 链接 [text](url)
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  // 换行
  html = html.replace(/\n/g, '<br>');

  return html;
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function fmtNumber(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return parseFloat(Number(n).toFixed(2));
}

function todayInput() {
  // 用本地日期，避免 UTC 折算导致默认值差一天
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// 拦截 modal 关闭按钮
function bindModalClose() {
  document.querySelectorAll('.close-btn, .modal-cancel').forEach((btn) => {
    btn.addEventListener('click', closeModal);
  });
}

// ============ Tab 切换 ============

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${tab}`));
  if (tab === 'items') loadItems();
  if (tab === 'todos') loadTodos();
  if (tab === 'ai') renderAiWorkbench();
  if (tab === 'setup') loadSetup();
  if (tab === 'travel') loadTravelPlans();
}

function initTabs() {
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // 滑动切换 tab
  let touchStartX = 0;
  let touchStartY = 0;
  const tabOrder = ['ai', 'items', 'todos', 'travel'];
  
  document.addEventListener('touchstart', (e) => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
  }, { passive: true });
  
  document.addEventListener('touchend', (e) => {
    if (!document.getElementById('modal').classList.contains('hidden')) return;  // 弹窗打开时不拦截滑动切 Tab
    const touchEndX = e.changedTouches[0].clientX;
    const touchEndY = e.changedTouches[0].clientY;
    const diffX = touchStartX - touchEndX;
    const diffY = touchStartY - touchEndY;
    
    // 水平滑动距离大于垂直滑动，且超过阈值
    if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 50) {
      const currentIndex = tabOrder.indexOf(currentTab);
      if (currentIndex === -1) return;
      
      if (diffX > 0 && currentIndex < tabOrder.length - 1) {
        // 向左滑，下一个 tab
        switchTab(tabOrder[currentIndex + 1]);
      } else if (diffX < 0 && currentIndex > 0) {
        // 向右滑，上一个 tab
        switchTab(tabOrder[currentIndex - 1]);
      }
    }
  }, { passive: true });
}

// ============ 旅游计划 Tab ============

let travelPlans = [];
let discoverCache = null;  // { request:{...}, response:{strategy_note, source, candidates} } 缓存最近一次目的地推荐，跨列表刷新保留

const TRANSPORT_OPTIONS = ['不限', '高铁', '自驾', '飞机'];
const STRATEGY_OPTIONS = ['综合', '度假优先', '性价比优先', '不网红优先'];
const BUDGET_OPTIONS = ['不限', '经济', '舒适'];
const TRAVEL_TAG_OPTIONS = ['温泉', '海岛', '自然山水', '古镇', 'City Walk', '亲子', '美食', '徒步', '露营', '人文'];

async function loadTravelPlans() {
  const container = document.getElementById('tab-travel');
  container.innerHTML = '<div class="loading">加载旅游计划...</div>';
  const { ok, data } = await fetchJSON(API.travelPlans);
  if (!ok) {
    // 加载失败也保留「新建行程」入口，避免空白页无从恢复
    container.innerHTML = `<div class="section-header"><div><h2>🧳 旅游计划</h2></div><button class="btn btn-primary" id="travel-add">＋ 新建行程</button></div><div class="empty">${esc(detailMsg(data, '加载失败'))}</div>`;
    document.getElementById('travel-add').addEventListener('click', () => showTravelForm());
    return;
  }
  travelPlans = data || [];
  container.innerHTML = `
    <div class="section-header"><div><h2>🧳 旅游计划</h2><p class="section-subtitle">发现小众目的地 · 规划行程 · 打包行李</p></div><div class="travel-header-actions"><button class="btn" id="travel-discover-btn">✨ 发现目的地</button><button class="btn btn-primary" id="travel-add">＋ 新建行程</button></div></div>
    ${renderDiscoverPanel()}
    <div class="section-mini-title">我的行程</div>
    <div class="travel-list">${travelPlans.length ? travelPlans.map(renderTravelCard).join('') : '<div class="empty">还没有行程。点上方「✨ 发现目的地」让 AI 按交通方式推荐小众去处，或「＋ 新建行程」手动添加。</div>'}</div>`;
  document.getElementById('travel-add').addEventListener('click', () => showTravelForm());
  document.getElementById('travel-discover-btn').addEventListener('click', () => {
    const panel = document.getElementById('discover-panel');
    if (panel) { panel.open = true; document.getElementById('dc-origin')?.focus(); }
  });
  bindDiscoverEvents();
  container.querySelectorAll('[data-travel-action]').forEach((btn) => btn.addEventListener('click', () => handleTravelAction(btn.dataset.travelAction, Number(btn.dataset.id))));
  container.querySelectorAll('.packing-check').forEach((box) => box.addEventListener('change', () => togglePacked(Number(box.dataset.id), Number(box.dataset.index), box.checked)));
  container.querySelectorAll('.spot-check').forEach((box) => box.addEventListener('change', () => toggleSpotBooked(Number(box.dataset.id), Number(box.dataset.index), box.checked)));
}

function renderTravelCard(plan) {
  const items = plan.packing_items || [];
  const packed = items.filter((item) => item.packed).length;
  const spots = plan.spots || [];
  const spotBooked = spots.filter((s) => s.booked).length;
  const prefs = [];
  if (plan.origin_city) prefs.push(`从 ${plan.origin_city} 出发`);
  if (plan.transport_mode) prefs.push(plan.transport_mode);
  if (plan.strategy) prefs.push(plan.strategy);
  const prefBadges = prefs.map((x) => `<span class="badge badge-outline">${esc(x)}</span>`).join('');
  const tagBadges = (plan.tags || []).map((t) => `<span class="badge badge-outline">${esc(t)}</span>`).join('');
  return `<article class="travel-card">
    <div class="travel-card-head"><div><h3>${esc(plan.destination)}</h3><div class="item-meta">${esc(plan.start_date)} 至 ${esc(plan.end_date)} · ${plan.travelers} 人${plan.activities ? ` · ${esc(plan.activities)}` : ''}</div>${(prefBadges || tagBadges) ? `<div class="travel-prefs">${prefBadges}${tagBadges}</div>` : ''}</div>
      <div class="travel-actions"><button class="btn btn-small" data-travel-action="edit" data-id="${plan.id}">编辑</button><button class="btn btn-small btn-danger" data-travel-action="delete" data-id="${plan.id}">删除</button></div></div>
    ${plan.notes ? `<div class="travel-notes muted">📝 ${esc(plan.notes)}</div>` : ''}
    ${plan.weather_summary ? `<div class="weather-summary"><b>天气参考：</b>${esc(plan.weather_summary)}<span class="badge badge-outline">${esc(plan.weather_source || '')}</span></div>` : ''}
    <div class="packing-head"><b>🧳 行李清单 ${items.length ? `${packed}/${items.length}` : ''}</b><div><button class="btn btn-small" data-travel-action="packing" data-id="${plan.id}">${items.length ? '编辑清单' : '手动添加'}</button> <button class="btn btn-primary btn-small" data-travel-action="recommend" data-id="${plan.id}">${items.length ? '重新生成' : 'AI 生成建议'}</button></div></div>
    <div class="packing-list">${items.length ? items.map((item, index) => `<label class="packing-row ${item.packed ? 'packed' : ''}"><input class="packing-check" data-id="${plan.id}" data-index="${index}" type="checkbox" ${item.packed ? 'checked' : ''}><span><b>${esc(item.name)}</b> · ${esc(item.quantity)} <small>${esc(item.category)}${item.note ? ` · ${esc(item.note)}` : ''}</small></span></label>`).join('') : ''}</div>
    <div class="packing-head"><b>🎯 推荐玩法 ${spots.length ? `${spotBooked}/${spots.length}` : ''}</b><div><button class="btn btn-small" data-travel-action="spots" data-id="${plan.id}">${spots.length ? '重新生成' : 'AI 生成玩法'}</button></div></div>
    <div class="spots-list">${spots.length ? spots.map((s, i) => `<label class="spot-row ${s.booked ? 'booked' : ''}"><input class="spot-check" data-id="${plan.id}" data-index="${i}" type="checkbox" ${s.booked ? 'checked' : ''}><span><b>${esc(s.name)}</b> · ${esc(s.type || '景点')}${s.duration_hours != null ? ` · ${s.duration_hours}h` : ''}${s.cost ? ` · ${esc(s.cost)}` : ''}<small>${esc(s.why || '')}</small></span></label>`).join('') : ''}</div>
  </article>`;
}

function showTravelForm(plan = null, prefill = null) {
  const p = plan || prefill || {};
  const tagsStr = (plan?.tags || prefill?.tags || []).join(', ');
  showModal(`<div class="modal-content"><button class="close-btn">×</button><h2>${plan ? '编辑' : '新建'}旅游计划</h2><form id="travel-form">
    <div class="form-row"><div class="form-group"><label>目的地</label><input id="travel-destination" required maxlength="100" value="${esc(p.destination || '')}" placeholder="例如：成都"></div><div class="form-group"><label>出发城市</label><input id="travel-origin" maxlength="60" value="${esc(p.origin_city || '')}" placeholder="例如：成都"></div></div>
    <div class="form-row"><div class="form-group"><label>开始日期</label><input id="travel-start" type="date" required value="${esc(p.start_date || todayInput())}"></div><div class="form-group"><label>结束日期</label><input id="travel-end" type="date" required value="${esc(p.end_date || todayInput())}"></div></div>
    <div class="form-row"><div class="form-group"><label>出行人数</label><input id="travel-people" type="number" min="1" max="30" required value="${p.travelers || 1}"></div><div class="form-group"><label>交通方式</label><select id="travel-transport">${TRANSPORT_OPTIONS.map((o) => `<option ${o === (p.transport_mode || '') ? 'selected' : ''}>${o}</option>`).join('')}</select></div></div>
    <div class="form-row"><div class="form-group"><label>主策略</label><select id="travel-strategy">${STRATEGY_OPTIONS.map((o) => `<option ${o === (p.strategy || '') ? 'selected' : ''}>${o}</option>`).join('')}</select></div><div class="form-group"><label>预算档</label><select id="travel-budget">${BUDGET_OPTIONS.map((o) => `<option ${o === (p.budget_tier || '') ? 'selected' : ''}>${o}</option>`).join('')}</select></div></div>
    <div class="form-group"><label>偏好标签（逗号分隔）</label><input id="travel-tags" maxlength="120" value="${esc(tagsStr)}" placeholder="例如：温泉, 自然"></div>
    <div class="form-group"><label>活动偏好</label><input id="travel-activities" maxlength="500" value="${esc(p.activities || '')}" placeholder="例如：徒步、美食、亲子"></div>
    <div class="form-group"><label>补充备注</label><textarea id="travel-notes" maxlength="1000" placeholder="例如：带儿童、容易晕车">${esc(p.notes || '')}</textarea></div>
    <div class="modal-actions"><button type="button" class="btn modal-cancel">取消</button><button class="btn btn-primary" type="submit">保存</button></div></form></div>`);
  bindModalClose();
  document.getElementById('travel-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const tags = document.getElementById('travel-tags').value.split(',').map((s) => s.trim()).filter(Boolean);
    const payload = {
      destination: document.getElementById('travel-destination').value.trim(),
      origin_city: document.getElementById('travel-origin').value.trim(),
      start_date: document.getElementById('travel-start').value,
      end_date: document.getElementById('travel-end').value,
      travelers: Number(document.getElementById('travel-people').value),
      transport_mode: document.getElementById('travel-transport').value,
      strategy: document.getElementById('travel-strategy').value,
      budget_tier: document.getElementById('travel-budget').value,
      tags,
      activities: document.getElementById('travel-activities').value.trim(),
      notes: document.getElementById('travel-notes').value.trim(),
    };
    const { ok, data } = await fetchJSON(plan ? API.travelPlan(plan.id) : API.travelPlans, { method: plan ? 'PUT' : 'POST', body: JSON.stringify(payload) });
    if (!ok) { toast(detailMsg(data, '保存失败'), 'error'); return; }
    closeModal(); toast('旅游计划已保存', 'success'); loadTravelPlans();
  });
}

async function handleTravelAction(action, id) {
  const plan = travelPlans.find((item) => item.id === id);
  if (!plan) return;
  if (action === 'edit') return showTravelForm(plan);
  if (action === 'packing') return showPackingEditor(plan);
  if (action === 'spots') return generateSpots(plan);
  if (action === 'delete') {
    if (!confirm(`确定删除“${plan.destination}”旅游计划吗？`)) return;
    const { ok, data } = await fetchJSON(API.travelPlan(id), { method: 'DELETE' });
    if (!ok) return toast(detailMsg(data, '删除失败'), 'error');
    toast('旅游计划已删除', 'success'); return loadTravelPlans();
  }
  if (action === 'recommend') {
    if ((plan.packing_items || []).length && !confirm('重新生成会替换当前清单，已勾选的物品将按名称保留勾选状态。确定继续吗？')) return;
    // 推理模型生成约需 1 分钟：按钮显示已用秒数，避免干等无感
    const btn = document.querySelector(`[data-travel-action="recommend"][data-id="${id}"]`);
    const originalText = btn?.textContent;
    const startedAt = Date.now();
    let ticker = null;
    if (btn) {
      btn.disabled = true;
      const tick = () => { btn.textContent = `⏳ 生成中… ${Math.floor((Date.now() - startedAt) / 1000)}s（约 1 分钟）`; };
      tick();
      ticker = setInterval(tick, 1000);
    }
    toast('正在查询天气并生成行李建议，约需 1 分钟…');
    try {
      const { ok, data } = await fetchJSON(API.travelRecommend(id), { method: 'POST' });
      if (!ok) return toast(detailMsg(data, '生成失败'), 'error');
      toast('行李建议已生成，可继续修改', 'success');
      return loadTravelPlans();
    } catch {
      toast('生成失败，请检查网络后重试', 'error');
    } finally {
      if (ticker) clearInterval(ticker);
      if (btn) { btn.disabled = false; btn.textContent = originalText; }
    }
  }
}

// 行李常用物品快捷添加（按分类分组），点击即加入清单
const PACKING_QUICK_ADD = [
  { category: '证件', items: ['身份证', '护照', '银行卡', '医保卡'] },
  { category: '衣物', items: ['内衣', '内裤', '袜子', '睡衣', 'T恤', '外套', '裤子'] },
  { category: '洗护', items: ['牙刷', '牙膏', '毛巾', '洗发水', '沐浴露', '防晒霜'] },
  { category: '电子', items: ['充电宝', '充电器', '数据线', '耳机'] },
  { category: '药品', items: ['常备药', '创可贴', '晕车药'] },
  { category: '其他', items: ['耳塞', '眼罩', '雨伞', '纸巾', '水杯'] },
];

function showPackingEditor(plan) {
  const items = (plan.packing_items || []).map((item) => ({ ...item }));
  const hasName = (name) => items.some((it) => it.name.trim() === name);
  const quickAddHtml = `<div class="packing-quick">${PACKING_QUICK_ADD.map((group) =>
    `<div class="packing-quick-group"><span class="packing-quick-label">${esc(group.category)}</span>${group.items.map((name) =>
      `<button type="button" class="packing-chip" data-name="${esc(name)}" data-category="${esc(group.category)}">${esc(name)}</button>`).join('')}</div>`).join('')}</div>`;
  const renderRows = () => {
    document.getElementById('packing-edit-list').innerHTML = items.length ? items.map((item, index) => `<div class="packing-edit-row">
        <input class="pe-name" data-field="name" data-index="${index}" value="${esc(item.name)}" placeholder="物品名称">
        <input class="pe-qty" data-field="quantity" data-index="${index}" value="${esc(item.quantity)}" placeholder="数量">
        <input class="pe-cat" data-field="category" data-index="${index}" value="${esc(item.category)}" placeholder="分类">
        <input class="pe-note" data-field="note" data-index="${index}" value="${esc(item.note || '')}" placeholder="备注">
        <button type="button" class="btn btn-small btn-danger packing-remove" data-index="${index}">删除</button>
      </div>`).join('') : '<div class="empty" style="padding:.6rem 0;">还没有物品，点上方常用物品或「＋ 手动添加一项」</div>';
    // 已加入清单的快捷项置灰，防重复
    document.querySelectorAll('.packing-chip').forEach((chip) => chip.classList.toggle('added', hasName(chip.dataset.name)));
    document.querySelectorAll('#packing-edit-list input').forEach((input) => input.addEventListener('input', () => { items[Number(input.dataset.index)][input.dataset.field] = input.value; }));
    document.querySelectorAll('.packing-remove').forEach((btn) => btn.addEventListener('click', () => { items.splice(Number(btn.dataset.index), 1); renderRows(); }));
  };
  showModal(`<div class="modal-content modal-wide"><button class="close-btn">×</button><h2>编辑 ${esc(plan.destination)} 行李清单</h2>
    <div class="packing-quick-title">常用物品（点一下加入清单）</div>
    ${quickAddHtml}
    <div id="packing-edit-list"></div>
    <button type="button" class="btn" id="packing-add">＋ 手动添加一项</button>
    <div class="modal-actions"><button type="button" class="btn modal-cancel">取消</button><button class="btn btn-primary" id="packing-save">保存清单</button></div>
  </div>`);
  bindModalClose(); renderRows();
  document.querySelectorAll('.packing-chip').forEach((chip) => chip.addEventListener('click', () => {
    const name = chip.dataset.name;
    if (hasName(name)) { toast(`「${name}」已在清单中`, 'info'); return; }
    items.push({ name, quantity: '1', category: chip.dataset.category, note: '', packed: false });
    renderRows();
  }));
  document.getElementById('packing-add').addEventListener('click', () => { items.push({ name: '', quantity: '1', category: '其他', note: '', packed: false }); renderRows(); });
  document.getElementById('packing-save').addEventListener('click', async () => {
    const clean = items.filter((item) => item.name.trim()).map((item) => ({ ...item, name: item.name.trim(), quantity: item.quantity || '1', category: item.category || '其他' }));
    const { ok, data } = await fetchJSON(API.travelPacking(plan.id), { method: 'PUT', body: JSON.stringify({ items: clean }) });
    if (!ok) return toast(detailMsg(data, '保存失败'), 'error');
    closeModal(); toast('行李清单已保存', 'success'); loadTravelPlans();
  });
}

async function togglePacked(id, index, checked) {
  const plan = travelPlans.find((item) => item.id === id);
  if (!plan?.packing_items[index]) return;
  plan.packing_items[index].packed = checked;
  const { ok, data } = await fetchJSON(API.travelPacking(id), { method: 'PUT', body: JSON.stringify({ items: plan.packing_items }) });
  if (!ok) {
    plan.packing_items[index].packed = !checked;  // 回滚乐观更新
    toast(detailMsg(data, '更新失败'), 'error');
  }
  loadTravelPlans();  // 成功/失败都重新拉取，以服务端为准，避免缓存与库长期不一致
}

async function toggleSpotBooked(id, index, checked) {
  const plan = travelPlans.find((item) => item.id === id);
  if (!plan?.spots[index]) return;
  plan.spots[index].booked = checked;
  const { ok, data } = await fetchJSON(API.travelSpots(id), { method: 'PUT', body: JSON.stringify({ items: plan.spots }) });
  if (!ok) {
    plan.spots[index].booked = !checked;  // 回滚乐观更新
    toast(detailMsg(data, '更新失败'), 'error');
  }
  loadTravelPlans();
}

async function generateSpots(plan) {
  if ((plan.spots || []).length && !confirm('重新生成会替换当前玩法清单，已勾选的将按名称保留。确定继续吗？')) return;
  // 推理模型生成约需 1 分钟：按钮显示已用秒数
  const btn = document.querySelector(`[data-travel-action="spots"][data-id="${plan.id}"]`);
  const originalText = btn?.textContent;
  const startedAt = Date.now();
  let ticker = null;
  if (btn) {
    btn.disabled = true;
    const tick = () => { btn.textContent = `⏳ 生成中… ${Math.floor((Date.now() - startedAt) / 1000)}s`; };
    tick();
    ticker = setInterval(tick, 1000);
  }
  toast('正在生成非网红玩法清单，约需 1 分钟…');
  try {
    const { ok, data } = await fetchJSON(API.travelSpots(plan.id), { method: 'POST' });
    if (!ok) return toast(detailMsg(data, '生成失败'), 'error');
    toast('玩法清单已生成，可勾选已安排的项目', 'success');
    return loadTravelPlans();
  } catch {
    toast('生成失败，请检查网络后重试', 'error');
  } finally {
    if (ticker) clearInterval(ticker);
    if (btn) { btn.disabled = false; btn.textContent = originalText; }
  }
}

// ============ 目的地推荐（发现目的地）============

function renderDiscoverPanel() {
  const req = discoverCache?.request || {};
  const origin = req.origin_city || '';
  const transport = req.transport_mode || '不限';
  const strategy = req.strategy || '综合';
  const budget = req.budget_tier || '不限';
  const selTags = req.tags || [];
  const resultsHtml = discoverCache?.response
    ? renderDiscoverResults(discoverCache.response)
    : '<div class="muted discover-hint">填好条件后点「AI 推荐目的地」。系统会按你的策略推荐小众、有度假感的目的地，并标注出发地到各候选的交通时长。</div>';
  const opt = (arr, cur) => arr.map((o) => `<option ${o === cur ? 'selected' : ''}>${o}</option>`).join('');
  return `<details class="card discover-card" id="discover-panel" ${discoverCache ? 'open' : ''}>
    <summary class="section-title">✨ 发现目的地（按交通方式推荐 · 避开网红）</summary>
    <div class="discover-form">
      <div class="form-group"><label>出发城市</label><input id="dc-origin" value="${esc(origin)}" placeholder="例如：成都" maxlength="60"></div>
      <div class="form-group"><label>交通方式</label><select id="dc-transport">${opt(TRANSPORT_OPTIONS, transport)}</select></div>
      <div class="form-group"><label>天数</label><input id="dc-days" type="number" min="1" max="90" value="${req.days || 3}"></div>
      <div class="form-group"><label>人数</label><input id="dc-people" type="number" min="1" max="30" value="${req.travelers || 2}"></div>
      <div class="form-group"><label>主策略</label><select id="dc-strategy">${opt(STRATEGY_OPTIONS, strategy)}</select></div>
      <div class="form-group"><label>预算档</label><select id="dc-budget">${opt(BUDGET_OPTIONS, budget)}</select></div>
      <div class="form-group"><label>出行月份（可选）</label><input id="dc-month" type="number" min="1" max="12" value="${req.month || ''}"></div>
    </div>
    <div class="form-group"><label>偏好标签（可多选）</label><div class="tag-chips">${TRAVEL_TAG_OPTIONS.map((t) => `<button type="button" class="tag-chip ${selTags.includes(t) ? 'selected' : ''}" data-tag="${esc(t)}">${esc(t)}</button>`).join('')}</div></div>
    <div class="form-actions"><button type="button" class="btn btn-primary" id="dc-submit">AI 推荐目的地</button></div>
    <div id="discover-results">${resultsHtml}</div>
  </details>`;
}

function bindDiscoverEvents() {
  document.getElementById('dc-submit')?.addEventListener('click', discoverDestinations);
  document.querySelectorAll('.tag-chip').forEach((chip) => chip.addEventListener('click', () => chip.classList.toggle('selected')));
  bindDiscoverResultEvents();
}

function bindDiscoverResultEvents() {
  const cands = discoverCache?.response?.candidates || [];
  document.querySelectorAll('[data-candidate-index]').forEach((btn) => {
    const idx = Number(btn.dataset.candidateIndex);
    if (cands[idx]) btn.addEventListener('click', () => addCandidateToPlan(cands[idx]));
  });
}

function readDiscoverRequest() {
  const tags = [...document.querySelectorAll('.tag-chip.selected')].map((b) => b.dataset.tag);
  const monthVal = document.getElementById('dc-month').value.trim();
  return {
    origin_city: document.getElementById('dc-origin').value.trim(),
    transport_mode: document.getElementById('dc-transport').value,
    days: Number(document.getElementById('dc-days').value) || 3,
    travelers: Number(document.getElementById('dc-people').value) || 2,
    strategy: document.getElementById('dc-strategy').value,
    budget_tier: document.getElementById('dc-budget').value,
    month: monthVal ? Number(monthVal) : null,
    tags,
  };
}

function renderDiscoverResults(data) {
  const cands = data.candidates || [];
  if (!cands.length) return '<div class="empty">未生成候选，换个条件重试</div>';
  const note = data.strategy_note ? `<div class="discover-note muted">🎯 ${esc(data.strategy_note)} <span class="badge badge-outline">${esc(data.source || '')}</span></div>` : '';
  return `${note}<div class="discover-candidates">${cands.map(renderDiscoverCandidate).join('')}</div>`;
}

function renderDiscoverCandidate(c, index) {
  const t = c.transport || {};
  const accBadge = t.accuracy === '高德精确'
    ? '<span class="badge badge-ok">高德精确</span>'
    : (t.accuracy ? `<span class="badge badge-outline">${esc(t.accuracy)}</span>` : '');
  const dur = t.duration_hours != null ? `${t.duration_hours}h` : '时长未知';
  const dist = t.distance_km != null ? ` · ${t.distance_km}km` : '';
  const transportLine = t.mode ? `<div class="candidate-transport">🚗 ${esc(t.mode)} · ${dur}${dist} ${accBadge}${t.note ? ` <small class="muted">${esc(t.note)}</small>` : ''}</div>` : '';
  const highlights = (c.highlights || []).length ? `<div class="candidate-highlights"><b>亮点：</b>${c.highlights.map((h) => `<span class="chip-mini">${esc(h)}</span>`).join('')}</div>` : '';
  const tags = (c.tags || []).length ? `<div class="candidate-tags">${c.tags.map((tg) => `<span class="badge badge-outline">${esc(tg)}</span>`).join('')}</div>` : '';
  const metaBits = [c.est_budget_per_person, c.best_days, c.season].filter(Boolean).map((x) => esc(x));
  const meta = metaBits.length ? `<div class="candidate-meta muted">${metaBits.join(' · ')}</div>` : '';
  return `<div class="discover-candidate">
    <div class="candidate-head"><div><h4>${esc(c.name)}</h4>${c.region ? `<div class="muted">${esc(c.region)}</div>` : ''}</div>
      <button class="btn btn-small btn-primary" data-candidate-index="${index}">加入行程</button></div>
    ${transportLine}
    ${c.vibe ? `<div class="candidate-vibe">${esc(c.vibe)}</div>` : ''}
    ${c.why_not_viral ? `<div class="candidate-why">🤫 ${esc(c.why_not_viral)}</div>` : ''}
    ${highlights}
    ${meta}
    ${tags}
    ${c.caveats ? `<div class="candidate-caveats muted">⚠ ${esc(c.caveats)}</div>` : ''}
  </div>`;
}

function addCandidateToPlan(candidate) {
  const req = discoverCache?.request || {};
  showTravelForm(null, {
    destination: candidate.name,
    origin_city: req.origin_city || '',
    transport_mode: req.transport_mode || '不限',
    strategy: req.strategy || '综合',
    budget_tier: req.budget_tier || '不限',
    tags: candidate.tags || [],
  });
}

async function discoverDestinations() {
  const req = readDiscoverRequest();
  if (!req.origin_city) { toast('请填写出发城市', 'error'); return; }
  const btn = document.getElementById('dc-submit');
  const originalText = btn?.textContent;
  const startedAt = Date.now();
  let ticker = null;
  if (btn) {
    btn.disabled = true;
    const tick = () => { btn.textContent = `⏳ 推荐中… ${Math.floor((Date.now() - startedAt) / 1000)}s`; };
    tick();
    ticker = setInterval(tick, 1000);
  }
  document.getElementById('discover-results').innerHTML = '<div class="muted">正在结合 LLM 与高德交通时长生成候选，约需 1 分钟…</div>';
  toast('正在推荐目的地，约需 1 分钟…');
  try {
    const { ok, data } = await fetchJSON(API.travelSuggest, { method: 'POST', body: JSON.stringify(req) });
    if (!ok) {
      document.getElementById('discover-results').innerHTML = `<div class="empty">${esc(detailMsg(data, '推荐失败'))}</div>`;
      return toast(detailMsg(data, '推荐失败'), 'error');
    }
    discoverCache = { request: req, response: data };
    document.getElementById('discover-results').innerHTML = renderDiscoverResults(data);
    bindDiscoverResultEvents();
    toast(`已推荐 ${(data.candidates || []).length} 个目的地`, 'success');
  } catch {
    toast('推荐失败，请检查网络后重试', 'error');
  } finally {
    if (ticker) clearInterval(ticker);
    if (btn) { btn.disabled = false; btn.textContent = originalText; }
  }
}

// ============ 日用品 Tab ============

function getBadge(item) {
  const pred = item.prediction || {};
  // 「紧急」只在库存到/低于用户设的最低库存时出现；库存高于最低值时不再标红，
  // 即便按消耗速率预测短期内会用完，也只显示「偏低」而非「紧急」。
  if (Number(item.current_stock) <= Number(item.min_stock || 0)) {
    return '<span class="badge badge-danger">紧急</span>';
  }
  if (pred.need_buy) return '<span class="badge badge-warn">偏低</span>';
  const days = pred.days_until_empty;
  if (days !== null && days < 14) return '<span class="badge badge-warn">偏低</span>';
  return '<span class="badge badge-ok">充足</span>';
}

function renderItemCard(item) {
  const p = item.prediction || {};
  const days = p.days_until_empty;
  const daysText = days === null || days === undefined ? '—' : `${Math.floor(days)} 天`;
  const suggest = p.need_buy ? `建议 ${p.suggested_qty} ${item.unit || '个'}` : '';
  const place = item.location ? ` · ${esc(item.location)}` : '';
  const expiry = item.expires_at ? ` · 到期 ${esc(item.expires_at)}` : '';
  return `
    <div class="item-card" data-id="${item.id}">
      <div class="item-info">
        <div class="item-name">${esc(item.name)} ${item.has_images ? '<span class="item-photo-marker" title="有照片">📷</span>' : ''} ${getBadge(item)}</div>
        <div class="item-meta">${esc(item.category || '未分类')} · 剩余 ${fmtNumber(item.current_stock)} ${esc(item.unit || '个')}${place}${expiry}</div>
      </div>
      <div class="item-tags">
        <span class="badge badge-outline">预计 ${daysText}</span>
        ${suggest ? `<span class="badge badge-warn">${esc(suggest)}</span>` : ''}
      </div>
    </div>`;
}

function renderItems(items) {
  const container = document.getElementById('tab-items');
  const needBuy = items.filter((i) => i.prediction?.need_buy).sort((a, b) => (a.prediction?.days_until_empty || 0) - (b.prediction?.days_until_empty || 0));
  const sufficient = items.filter((i) => !i.prediction?.need_buy);

  let html = `
    <div class="toolbar">
      <button class="btn btn-primary" id="add-item-btn">+ 添加物品</button>
      <button class="btn" id="shopping-list-btn">📋 购物清单</button>
      <button class="btn" id="log-placement-btn">📍 记录收纳</button>
    </div>`;

  if (!items.length) {
    html += '<div class="empty-state">暂无物品，点击「添加物品」开始</div>';
    container.innerHTML = html;
    bindItemToolbar();
    return;
  }

  if (needBuy.length) {
    html += `
      <div class="section-title">⚠ 需要购买 (${needBuy.length})</div>
      <div class="group need-buy-group">
        ${needBuy.map(renderItemCard).join('')}
      </div>`;
  }

  if (sufficient.length) {
    html += `
      <div class="section-title">✓ 库存充足 (${sufficient.length})</div>
      <div class="group sufficient-group">
        ${sufficient.map(renderItemCard).join('')}
      </div>`;
  }

  container.innerHTML = html;
  bindItemToolbar();
  document.querySelectorAll('#tab-items .item-card').forEach((card) => {
    card.addEventListener('click', () => showItemDetail(Number(card.dataset.id)));
  });
}

function bindItemToolbar() {
  document.getElementById('add-item-btn')?.addEventListener('click', () => showItemForm());
  document.getElementById('shopping-list-btn')?.addEventListener('click', showShoppingList);
  document.getElementById('log-placement-btn')?.addEventListener('click', () => showPlacementForm());
}

async function loadItems() {
  const container = document.getElementById('tab-items');
  container.innerHTML = '<div class="loading">加载日用品中...</div>';
  const { ok, data } = await fetchJSON(API.items);
  if (!ok) {
    container.innerHTML = `<div class="empty-state">日用品加载失败：${data?.detail || '未知错误'}</div>`;
    return;
  }
  renderItems(data || []);
}

// ============ 日用品 Modal ============

async function loadItemFacets() {
  if (itemFacetsCache) return itemFacetsCache;
  const { ok, data } = await fetchJSON(API.itemFacets);
  if (!ok || !data) return { categories: [], units: [], locations: [], defaults: { categories: [], units: [] } };
  itemFacetsCache = data;
  return data;
}

// 服务端频次降序值在前、默认值补后，去重合并成 datalist 候选
function mergeFacetOptions(serverValues, defaults) {
  const seen = new Set();
  const out = [];
  for (const v of [...(serverValues || []), ...(defaults || [])]) {
    const name = String(v || '').trim();
    if (name && !seen.has(name)) { seen.add(name); out.push(name); }
  }
  return out;
}

// ============ 物品图片（与待办图片同构，复用 showImagePreview 放大浏览器与 pendingImageUrls） ============

function itemImageUrl(itemId, imageId) { return API.itemImage(itemId, imageId); }

function renderItemImages(item) {
  if (!item?.images?.length) return '';
  return `<div class="todo-image-grid">${item.images.map((image) => `
    <div class="todo-image-thumb">
      <img src="${itemImageUrl(item.id, image.id)}" alt="物品图片">
      <button class="todo-image-remove" type="button" data-image-id="${image.id}" title="移除图片">&times;</button>
    </div>`).join('')}</div>`;
}

function currentExistingItemImageCount() {
  return document.querySelectorAll('#item-existing-images .todo-image-thumb').length;
}

function renderPendingItemImages() {
  const input = document.getElementById('item-images');
  const container = document.getElementById('item-pending-images');
  if (!input || !container) return;
  for (const url of pendingImageUrls) URL.revokeObjectURL(url);
  pendingImageUrls.clear();
  container.innerHTML = [...input.files].map((file) => {
    const url = URL.createObjectURL(file);
    pendingImageUrls.add(url);
    return `    <div class="todo-image-thumb"><img src="${url}" alt="待上传图片" title="${esc(file.name)}"></div>`;
  }).join('');
}

function setItemImageFiles(files) {
  const input = document.getElementById('item-images');
  const valid = files.filter(isSupportedTodoImage);
  if (!input || !valid.length) return 0;
  const capacity = 5 - currentExistingItemImageCount();
  if (capacity <= 0) { toast('每个物品最多 5 张图片', 'error'); return 0; }
  const added = valid.slice(0, capacity);
  const transfer = new DataTransfer();
  added.forEach((file) => transfer.items.add(file));
  input.files = transfer.files;
  renderPendingItemImages();
  if (valid.length > added.length) toast('图片数量已达到 5 张上限', 'error');
  return added.length;
}

function addItemImageFiles(files) {
  const input = document.getElementById('item-images');
  const before = input?.files.length || 0;
  setItemImageFiles([...(input?.files || []), ...files]);
  return Math.max(0, (input?.files.length || 0) - before);
}

function bindItemImageRemoveButtons(itemId) {
  document.querySelectorAll('#item-existing-images .todo-image-remove').forEach((button) => {
    button.addEventListener('click', () => deleteItemImage(itemId, button.dataset.imageId));
  });
}

async function uploadOneItemImage(itemId, file, signal) {
  if (file.size > 10 * 1024 * 1024) return `${file.name} 超过 10MB`;
  const form = new FormData();
  form.append('image', file);
  let response;
  try {
    response = await fetch(API.itemImages(itemId), { method: 'POST', body: form, signal });
  } catch (error) {
    if (error?.name === 'AbortError') return `${file.name} 已取消`;
    return `${file.name} 网络错误`;
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) return data?.detail || `${file.name} 上传失败`;
  return null;
}

async function uploadItemImages(formState) {
  const input = document.getElementById('item-images');
  if (!input || !input.files.length) return;
  const failed = [];
  for (const file of [...input.files]) {
    const reason = await uploadOneItemImage(formState.id, file, formState.abort?.signal);
    if (reason) failed.push({ file, reason });
  }
  if (formState.abort?.signal?.aborted) return;
  const transfer = new DataTransfer();
  failed.forEach((it) => transfer.items.add(it.file));
  input.files = transfer.files;
  renderPendingItemImages();
  if (failed.length) {
    const first = failed[0].reason;
    throw new Error(failed.length === 1 ? first : `${failed.length} 张图片上传失败（${first}）`);
  }
}

async function refreshExistingItemImages(itemId) {
  const { ok, data } = await fetchJSON(API.item(itemId));
  if (!ok) return;
  const container = document.getElementById('item-existing-images');
  if (container) { container.innerHTML = renderItemImages(data); bindItemImageRemoveButtons(itemId); }
}

async function deleteItemImage(itemId, imageId) {
  const { ok, data } = await fetchJSON(itemImageUrl(itemId, imageId), { method: 'DELETE' });
  if (!ok) { toast(data?.detail || '删除失败', 'error'); return; }
  toast('图片已删除', 'success');
  const container = document.getElementById('item-existing-images');
  if (container) { container.innerHTML = renderItemImages(data); bindItemImageRemoveButtons(itemId); }
}

async function showItemForm(item = null) {
  const isEdit = !!item;
  const formState = { id: item?.id, abort: new AbortController() };
  pendingImageUrls.forEach((url) => URL.revokeObjectURL(url)); pendingImageUrls.clear();
  const facets = await loadItemFacets();
  const categoryOpts = mergeFacetOptions(facets.categories, facets.defaults.categories);
  const unitOpts = mergeFacetOptions(facets.units, facets.defaults.units);
  const locationOpts = facets.locations || [];  // 存放地点为用户私有，无冷启动默认
  const datalist = (id, opts) => `<datalist id="${id}">${opts.map((o) => `<option value="${esc(o)}">`).join('')}</datalist>`;
  showModal(`
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title">${isEdit ? '编辑物品' : '添加物品'}</div>
        <button class="close-btn">&times;</button>
      </div>
      <div class="form-group">
        <label>名称 *</label>
        <input id="item-name" value="${item?.name || ''}">
      </div>
      <div class="form-group">
        <label>分类</label>
        <input id="item-category" list="item-category-list" value="${item?.category || ''}">
        ${datalist('item-category-list', categoryOpts)}
      </div>
      <div class="form-group">
        <label>单位</label>
        <input id="item-unit" list="item-unit-list" value="${item?.unit || '个'}">
        ${datalist('item-unit-list', unitOpts)}
      </div>
      <div class="form-group">
        <label>当前库存</label>
        <input type="number" step="any" id="item-stock" value="${item?.current_stock ?? 0}">
      </div>
      <div class="form-group">
        <label>最低库存</label>
        <input type="number" step="any" id="item-min" value="${item?.min_stock ?? 1}">
      </div>
      <div class="form-group">
        <label>存放地点</label>
        <input id="item-location" list="item-location-list" placeholder="如：卫生间 / 厨房柜 / 储物间" value="${item?.location || ''}">
        ${datalist('item-location-list', locationOpts)}
      </div>
      <div class="form-group">
        <label>到期年月</label>
        <input type="month" id="item-expires" value="${item?.expires_at || ''}">
      </div>
      <div class="form-group">
        <label>图片（最多 5 张，每张不超过 10MB，可直接粘贴）</label>
        <div id="item-existing-images">${renderItemImages(item)}</div>
        <div id="item-pending-images" class="todo-image-grid"></div>
        <input type="file" id="item-images" accept="image/jpeg,image/png,image/gif,image/webp" multiple>
      </div>
      <div class="form-actions">
        <button class="btn modal-cancel">取消</button>
        <button class="btn btn-primary" id="save-item">${isEdit ? '保存' : '添加'}</button>
      </div>
    </div>`);
  bindModalClose();
  // 关闭/取消时中止进行中的图片上传；保存成功后由 saveItem 上传所选图片
  document.querySelectorAll('.close-btn, .modal-cancel').forEach((btn) => btn.addEventListener('click', () => formState.abort.abort()));
  document.getElementById('save-item').addEventListener('click', () => saveItem(formState));
  if (!isEdit) document.getElementById('item-name').addEventListener('blur', suggestItemCategory);
  bindItemImageRemoveButtons(formState.id);
  const itemImageInput = document.getElementById('item-images');
  itemImageInput.addEventListener('change', () => setItemImageFiles([...itemImageInput.files]));
  itemImageInput.closest('.modal-content').addEventListener('paste', (event) => {
    const added = addItemImageFiles([...(event.clipboardData?.files || [])]);
    if (added) { event.preventDefault(); toast(`已粘贴 ${added} 张图片，保存后上传`, 'success'); }
  });
}

async function suggestItemCategory() {
  const name = document.getElementById('item-name').value.trim();
  const categoryInput = document.getElementById('item-category');
  if (!name || categoryInput.value.trim()) return;
  clearTimeout(itemCategoryTimer);
  itemCategoryTimer = setTimeout(async () => {
    const { ok, data } = await fetchJSON(API.aiItemCategory, { method: 'POST', body: JSON.stringify({ name }) });
    if (ok && data?.category && !categoryInput.value.trim()) categoryInput.value = data.category;
  }, 200);
}

async function saveItem(formState) {
  const payload = {
    name: document.getElementById('item-name').value.trim(),
    category: document.getElementById('item-category').value.trim() || null,
    unit: document.getElementById('item-unit').value.trim() || '个',
    current_stock: parseFloat(document.getElementById('item-stock').value) || 0,
    min_stock: parseFloat(document.getElementById('item-min').value) || 0,
    location: document.getElementById('item-location').value.trim() || null,
    expires_at: document.getElementById('item-expires').value || null,
  };
  if (!payload.name) { toast('名称必填', 'error'); return; }
  const wasNew = !formState.id;
  if (wasNew) {
    const { ok, data } = await fetchJSON(API.items, { method: 'POST', body: JSON.stringify(payload) });
    if (!ok) { toast(data?.detail || '保存失败', 'error'); return; }
    formState.id = data.id;
    const saveBtn = document.getElementById('save-item'); if (saveBtn) saveBtn.textContent = '保存';
  } else {
    const { ok } = await fetchJSON(API.item(formState.id), { method: 'PUT', body: JSON.stringify(payload) });
    if (!ok) { toast('保存失败', 'error'); return; }
  }
  let uploadError = null;
  try { await uploadItemImages(formState); } catch (error) { uploadError = error.message; }
  if (uploadError) {
    // 物品已落库：刷新已存在图片区，提示仅图片失败可重试，避免误判整体失败重填导致重复
    await refreshExistingItemImages(formState.id);
    toast(`${wasNew ? '物品已创建' : '物品已保存'}，但 ${uploadError}（可再次点保存重试）`, 'error');
    itemFacetsCache = null;
    loadItems();
    return;
  }
  toast(wasNew ? '添加成功' : '保存成功', 'success');
  itemFacetsCache = null;
  closeModal();
  loadItems();
}

async function showItemDetail(id) {
  const [itemRes, historyRes] = await Promise.all([
    fetchJSON(API.item(id)),
    fetchJSON(API.itemHistory(id)),
  ]);
  if (!itemRes.ok) { toast(itemRes.data?.detail || '物品不存在', 'error'); return; }
  const item = itemRes.data;
  const history = historyRes.ok ? historyRes.data : [];
  const p = item.prediction || {};
  const daysText = Number.isFinite(p.days_until_empty) ? `${Math.floor(p.days_until_empty)} 天` : '—';
  const place = item.location ? ` · ${esc(item.location)}` : '';
  const expiry = item.expires_at ? ` · 到期 ${esc(item.expires_at)}` : '';
  const historyHtml = (history || []).slice().reverse().map((h) => {
    const isUsage = h.type === 'usage';
    return `
      <div class="history-item">
        <span>${isUsage ? '🔴 消耗' : '🟢 购买'} ${fmtNumber(h.amount)} ${esc(item.unit || '个')}</span>
        <span style="color:var(--muted);font-size:0.8rem;">${fmtDate(h.at)} ${esc(h.note || '')}</span>
      </div>`;
  }).join('') || '<div class="empty-state" style="padding:1rem;">暂无记录</div>';

  showModal(`
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title">${esc(item.name)}</div>
        <button class="close-btn">&times;</button>
      </div>
      <div style="margin-bottom:1rem;color:var(--muted);font-size:0.9rem;">
        ${esc(item.category || '未分类')} · 剩余 ${fmtNumber(item.current_stock)} ${esc(item.unit || '个')} · 预计 ${daysText}${place}${expiry}
      </div>
      ${item.images?.length ? `<div class="todo-image-strip" style="margin-bottom:0.8rem;">${item.images.map((image, index) => `<img src="${itemImageUrl(item.id, image.id)}" alt="物品图片" class="todo-image-preview" data-src="${itemImageUrl(item.id, image.id)}" data-index="${index}">`).join('')}</div>` : ''}
      <div class="toolbar" style="margin-bottom:0.8rem;">
        <button class="btn" id="log-usage-btn">记录消耗</button>
        <button class="btn" id="log-purchase-btn">记录购买</button>
        <button class="btn" id="edit-item-btn">编辑</button>
        <button class="btn" style="color:var(--down);" id="delete-item-btn">删除</button>
      </div>
      <div class="section-title">历史记录</div>
      <div class="history-list">${historyHtml}</div>
    </div>`);
  bindModalClose();
  document.getElementById('log-usage-btn').addEventListener('click', () => showLogForm(id, 'usage'));
  document.getElementById('log-purchase-btn').addEventListener('click', () => showLogForm(id, 'purchase'));
  document.getElementById('edit-item-btn').addEventListener('click', () => showItemForm(item));
  document.getElementById('delete-item-btn').addEventListener('click', () => deleteItem(id));
  // 物品图片点击放大，支持左右切换（复用 showImagePreview）
  document.querySelectorAll('#modal .todo-image-preview').forEach((img) => {
    img.addEventListener('click', () => {
      const urls = (item.images || []).map((image) => itemImageUrl(item.id, image.id));
      const idx = Number(img.dataset.index);
      showImagePreview(urls[idx], urls, idx);
    });
  });
}

function showLogForm(id, type) {
  const isUsage = type === 'usage';
  showModal(`
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title">${isUsage ? '记录消耗' : '记录购买'}</div>
        <button class="close-btn">&times;</button>
      </div>
      <div class="form-group">
        <label>数量 *</label>
        <input type="number" step="any" id="log-amount" value="1">
      </div>
      ${isUsage ? '' : '<div class="form-group"><label>价格（可选）</label><input type="number" step="0.01" id="log-price"></div>'}
      <div class="form-group">
        <label>备注（可选）</label>
        <input id="log-note">
      </div>
      <div class="form-group">
        <label>日期（可选，默认今天）</label>
        <input type="date" id="log-date" value="${todayInput()}">
      </div>
      <div class="form-actions">
        <button class="btn modal-cancel">取消</button>
        <button class="btn btn-primary" id="save-log">保存</button>
      </div>
    </div>`);
  bindModalClose();
  document.getElementById('save-log').addEventListener('click', () => saveLog(id, type));
}

async function saveLog(id, type) {
  const amount = parseFloat(document.getElementById('log-amount').value);
  if (!amount || amount <= 0) { toast('数量必须大于 0', 'error'); return; }
  const payload = { amount };
  const dateVal = document.getElementById('log-date').value;
  const note = document.getElementById('log-note').value.trim();
  if (dateVal) payload[type === 'usage' ? 'logged_at' : 'purchased_at'] = dateVal;
  if (note) payload.note = note;
  if (type === 'purchase') {
    const price = parseFloat(document.getElementById('log-price').value);
    if (!Number.isNaN(price)) payload.price = price;
  }
  const url = type === 'usage' ? API.itemUsage(id) : API.itemPurchase(id);
  const { ok, data } = await fetchJSON(url, { method: 'POST', body: JSON.stringify(payload) });
  if (ok) {
    toast(type === 'usage' ? '消耗记录已保存' : '购买记录已保存', 'success');
    closeModal();
    loadItems();
  } else {
    toast(data?.detail || '保存失败', 'error');
  }
}

async function deleteItem(id) {
  if (!confirm('确定删除该物品？相关记录也会被删除。')) return;
  const { ok, data } = await fetchJSON(API.item(id), { method: 'DELETE' });
  if (ok) {
    toast('删除成功', 'success');
    itemFacetsCache = null;
    closeModal();
    loadItems();
  } else {
    toast(data?.detail || '删除失败', 'error');
  }
}

async function showShoppingList() {
  const { ok, data } = await fetchJSON(API.predictions);
  if (!ok) { toast(data?.detail || '获取购物清单失败', 'error'); return; }
  const items = (data?.need_buy || []);
  const listText = items.length
    ? items.map((i) => `- ${i.name}：${i.prediction?.suggested_qty || 0} ${i.unit || '个'}（预计 ${i.prediction?.days_until_empty === null ? '—' : Math.floor(i.prediction.days_until_empty) + ' 天'}）`).join('\n')
    : '当前无需购买任何物品';
  showModal(`
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title">📋 购物清单</div>
        <button class="close-btn">&times;</button>
      </div>
      <pre style="white-space:pre-wrap;background:var(--bg);padding:0.8rem;border-radius:8px;font-size:0.9rem;">${listText}</pre>
      <div class="form-actions">
        <button class="btn modal-cancel">关闭</button>
        <button class="btn btn-primary" id="copy-list">复制</button>
      </div>
    </div>`);
  bindModalClose();
  document.getElementById('copy-list').addEventListener('click', () => {
    navigator.clipboard.writeText(listText).then(() => toast('已复制到剪贴板', 'success'));
  });
}

// ============ 收纳知识库（placements） ============

function placementImageUrl(pid, imageId) { return API.placementImage(pid, imageId); }

function showPlacementForm(placement = null) {
  pendingImageUrls.forEach((url) => URL.revokeObjectURL(url)); pendingImageUrls.clear();
  showModal(`
    <div class="modal-content">
      <div class="modal-header"><div class="modal-title">${placement ? '编辑收纳记录' : '📍 记录收纳'}</div><button class="close-btn">&times;</button></div>
      <div class="form-group"><label>放了什么 / 描述 *</label><textarea id="placement-desc" placeholder="例如：把猫粮备用装塞到了阳台储物柜上层">${esc(placement?.description || '')}</textarea></div>
      <div class="form-group"><label>位置（可选）</label><input id="placement-location" value="${esc(placement?.location || '')}" placeholder="例如：阳台储物柜上层"></div>
      <div class="form-group"><label>备注（可选）</label><input id="placement-note" value="${esc(placement?.note || '')}"></div>
      <div class="form-group"><label>照片（可选，最多 5 张，每张不超过 10MB）</label><input type="file" id="placement-images" accept="image/jpeg,image/png,image/gif,image/webp" multiple></div>
      <div class="form-actions"><button class="btn modal-cancel">取消</button><button class="btn btn-primary" id="placement-save">保存并关联物品</button></div>
    </div>`);
  bindModalClose();
  document.getElementById('placement-save').addEventListener('click', () => savePlacement());
}

async function savePlacement() {
  const description = document.getElementById('placement-desc').value.trim();
  if (!description) { toast('描述必填', 'error'); return; }
  const payload = {
    description,
    location: document.getElementById('placement-location').value.trim() || null,
    note: document.getElementById('placement-note').value.trim() || null,
  };
  const btn = document.getElementById('placement-save');
  if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
  const { ok, data } = await fetchJSON(API.placements, { method: 'POST', body: JSON.stringify(payload) });
  if (!ok) { if (btn) { btn.disabled = false; btn.textContent = '保存并关联物品'; } toast(detailMsg(data, '保存失败'), 'error'); return; }
  const pid = data.id;
  // 上传所选图片：单张失败不阻断（收纳记录已建）
  const files = [...(document.getElementById('placement-images')?.files || [])].filter(isSupportedTodoImage).slice(0, 5);
  for (const file of files) {
    if (file.size > 10 * 1024 * 1024) { toast(`${file.name} 超过 10MB，已跳过`, 'error'); continue; }
    const form = new FormData(); form.append('image', file);
    try { await fetch(API.placementImages(pid), { method: 'POST', body: form }); } catch { /* 单张失败继续 */ }
  }
  // 调 LLM 给候选；推理模型较慢，按钮显示已用秒数；未配置/失败则降级为空候选，用户手动勾选
  let placement = data;
  const suggestStartedAt = Date.now();
  let ticker = null;
  if (btn) {
    const tick = () => { btn.textContent = `AI 关联中… ${Math.floor((Date.now() - suggestStartedAt) / 1000)}s（约 1 分钟）`; };
    tick();
    ticker = setInterval(tick, 1000);
  }
  const sg = await fetchJSON(API.placementSuggest(pid), { method: 'POST' });
  if (ticker) clearInterval(ticker);
  if (sg.ok) placement = sg.data;
  else if (sg.status === 503) toast('AI 未配置，可手动选择关联物品', 'info');
  else toast(detailMsg(sg.data, '候选生成失败，可手动选择'), 'error');
  closeModal();
  showPlacementCandidates(placement);
}

async function showPlacementCandidates(placement) {
  // 全部物品与 LLM 候选合并成一个勾选列表：候选靠前、高置信度预勾选；其余物品可手动加选
  const itemsRes = await fetchJSON(API.items);
  const allItems = itemsRes.ok ? itemsRes.data : [];
  const candMap = new Map();
  for (const c of (placement.candidate_items || [])) { if (c.item_id != null) candMap.set(c.item_id, c); }
  const ordered = [
    ...allItems.filter((it) => candMap.has(it.id)),
    ...allItems.filter((it) => !candMap.has(it.id)),
  ];
  const checked = new Set([...candMap.keys()].filter((id) => (candMap.get(id)?.confidence ?? 0) >= 0.5));
  const renderList = () => {
    const filter = (document.getElementById('placement-filter')?.value || '').trim().toLowerCase();
    document.getElementById('placement-candidate-list').innerHTML = (ordered
      .filter((it) => !filter || (it.name || '').toLowerCase().includes(filter) || (it.category || '').toLowerCase().includes(filter))
      .map((it) => {
        const c = candMap.get(it.id);
        const conf = c ? Math.round((c.confidence || 0) * 100) : null;
        const confBadge = c ? `<span class="badge ${conf >= 66 ? 'badge-ok' : conf >= 40 ? 'badge-warn' : 'badge-outline'}">${conf}%</span>` : '';
        const reason = c?.reason ? `<span class="muted" style="font-size:.78rem;">${esc(c.reason)}</span>` : '';
        return `<label class="placement-candidate"><input type="checkbox" value="${it.id}" ${checked.has(it.id) ? 'checked' : ''}><span class="placement-candidate-main"><b>${esc(it.name)}</b> <span class="muted">${esc(it.category || '未分类')}</span> ${confBadge}</span>${reason}</label>`;
      }).join('')) || '<div class="empty" style="padding:.6rem 0;">没有匹配的物品</div>';
    document.querySelectorAll('#placement-candidate-list input[type=checkbox]').forEach((box) => {
      box.addEventListener('change', () => { if (box.checked) checked.add(Number(box.value)); else checked.delete(Number(box.value)); });
    });
  };
  const imageStrip = placement.images?.length
    ? `<div class="todo-image-strip" style="margin-bottom:.6rem;">${placement.images.map((img) => `<img src="${placementImageUrl(placement.id, img.id)}" alt="收纳照片" class="todo-image-preview">`).join('')}</div>`
    : '';
  showModal(`
    <div class="modal-content modal-wide">
      <div class="modal-header"><div class="modal-title">确认收纳关联</div><button class="close-btn">&times;</button></div>
      <div style="margin-bottom:.6rem;"><b>${esc(placement.description)}</b>${placement.location ? ` · <span class="muted">${esc(placement.location)}</span>` : ''}</div>
      ${imageStrip}
      <div class="form-group"><label>关联到哪些库存物品（勾选）</label><input id="placement-filter" placeholder="搜索物品名/分类筛选…"></div>
      <div id="placement-candidate-list" class="placement-candidate-list"></div>
      <div class="form-group" style="margin-top:.6rem;"><label>位置（可修改）</label><input id="placement-confirm-location" value="${esc(placement.location || '')}"></div>
      <div class="modal-actions"><button class="btn modal-cancel">跳过</button><button class="btn btn-primary" id="placement-confirm">确认</button></div>
    </div>`);
  bindModalClose();
  renderList();
  document.getElementById('placement-filter').addEventListener('input', renderList);
  document.getElementById('placement-confirm').addEventListener('click', async () => {
    const itemIds = [...checked];
    const location = document.getElementById('placement-confirm-location').value.trim() || null;
    const { ok, data } = await fetchJSON(API.placementConfirm(placement.id), { method: 'PUT', body: JSON.stringify({ item_ids: itemIds, location }) });
    if (!ok) return toast(detailMsg(data, '确认失败'), 'error');
    toast('收纳记录已确认，AI 可检索', 'success');
    closeModal();
  });
}

// ============ 重点待办 Tab ============

function todoPriorityLabel(priority) {
  return { high: '高', medium: '中', low: '低' }[priority] || '中';
}

function todoPriorityBadge(priority) {
  const cls = { high: 'badge-danger', medium: 'badge-warn', low: 'badge-ok' }[priority] || 'badge-warn';
  return `<span class="badge ${cls}">${esc(todoPriorityLabel(priority))}</span>`;
}

function renderTodoCard(todo) {
  const due = todo.due_date ? `截止 ${todo.due_date}` : '未设截止日';
  const meta = due;
  const action = todo.status === 'done'
    ? `<button class="btn btn-small todo-reopen" data-id="${todo.id}">重新打开</button>`
    : `<button class="btn btn-small todo-done" data-id="${todo.id}">完成</button>`;

  // 根据优先级添加颜色class
  let priorityClass = '';
  if (todo.priority === 'low') priorityClass = 'priority-low';
  else if (todo.priority === 'medium') priorityClass = 'priority-medium';
  else if (todo.priority === 'high') priorityClass = 'priority-high';

  return `
    <div class="todo-card ${todo.status === 'done' ? 'done' : ''} ${todo.overdue ? 'overdue' : ''} ${priorityClass}" data-id="${todo.id}">
      <div class="todo-main">
        <div class="todo-title">${esc(todo.title)} ${todoPriorityBadge(todo.priority)} ${todo.overdue ? '<span class="badge badge-danger">已过期</span>' : ''}</div>
        <div class="todo-meta">${esc(meta)}</div>
        ${todo.note ? `<div class="todo-note">${esc(todo.note)}</div>` : ''}
        ${todo.images?.length ? `<div class="todo-image-strip">${todo.images.map((image, index) => `<img src="${todoImageUrl(todo.id, image.id)}" alt="待办图片" class="todo-image-preview" data-src="${todoImageUrl(todo.id, image.id)}" data-todo-id="${todo.id}" data-index="${index}">`).join('')}</div>` : ''}
      </div>
      <div class="todo-actions">
        ${action}
        <button class="btn btn-small todo-edit" data-id="${todo.id}">编辑</button>
      </div>
    </div>`;
}

function renderTodos(todos) {
  const container = document.getElementById('tab-todos');
  // 客户端即时搜索：按标题或内容（note）子串过滤，不区分大小写（照抄 placement-filter 模式）
  const q = todoQuery.trim().toLowerCase();
  const shown = q ? todos.filter((t) => (t.title || '').toLowerCase().includes(q) || (t.note || '').toLowerCase().includes(q)) : todos;
  const emptyTitle = todoStatus === 'open' ? '暂无未完成重点待办' : '暂无已完成重点待办';
  const emptyMsg = !todos.length ? emptyTitle : '没有匹配的待办';
  container.innerHTML = `
    <div class="toolbar">
      <button class="btn btn-primary" id="add-todo-btn">+ 添加待办</button>
      <button class="btn ${todoStatus === 'open' ? 'btn-primary' : ''}" id="show-open-todos">未完成</button>
      <button class="btn ${todoStatus === 'done' ? 'btn-primary' : ''}" id="show-done-todos">已完成</button>
      <input id="todo-search" class="todo-search" type="search" placeholder="搜索标题或内容…" value="${esc(todoQuery)}">
    </div>
    ${shown.length ? `<div class="todo-list">${shown.map(renderTodoCard).join('')}</div>` : `<div class="empty-state">${emptyMsg}</div>`}`;
  document.getElementById('add-todo-btn').addEventListener('click', () => showTodoForm());
  document.getElementById('show-open-todos').addEventListener('click', () => {
    todoStatus = 'open';
    todoQuery = '';  // 切换未完成/已完成时清空搜索，避免跨状态残留无效关键词
    loadTodos();
  });
  document.getElementById('show-done-todos').addEventListener('click', () => {
    todoStatus = 'done';
    todoQuery = '';
    loadTodos();
  });
  document.getElementById('todo-search').addEventListener('input', (e) => {
    todoQuery = e.target.value;
    renderTodos(todosCache);  // 复用已加载数据即时重渲染，不重复请求后端
  });
  document.querySelectorAll('.todo-done').forEach((button) => {
    button.addEventListener('click', () => setTodoStatus(Number(button.dataset.id), true));
  });
  document.querySelectorAll('.todo-reopen').forEach((button) => {
    button.addEventListener('click', () => setTodoStatus(Number(button.dataset.id), false));
  });
  document.querySelectorAll('.todo-edit').forEach((button) => {
    button.addEventListener('click', () => showTodoDetail(Number(button.dataset.id)));
  });
  // 添加图片点击放大功能，支持左右切换
  document.querySelectorAll('.todo-image-preview').forEach((img) => {
    img.addEventListener('click', () => {
      const todoId = img.dataset.todoId;
      const imageIndex = Number(img.dataset.index);
      const todo = todos.find(t => t.id === Number(todoId));
      if (todo && todo.images && todo.images.length > 0) {
        const allImageUrls = todo.images.map(image => todoImageUrl(todo.id, image.id));
        showImagePreview(allImageUrls[imageIndex], allImageUrls, imageIndex);
      } else {
        showImagePreview(img.dataset.src);
      }
    });
  });
}

async function loadTodos() {
  const container = document.getElementById('tab-todos');
  container.innerHTML = '<div class="loading">加载重点待办中...</div>';
  const { ok, data } = await fetchJSON(API.todos(todoStatus));
  if (!ok) {
    container.innerHTML = `<div class="empty-state">待办加载失败：${data?.detail || '未知错误'}</div>`;
    return;
  }
  todosCache = data || [];  // 缓存当前列表，供搜索框 input 事件即时过滤重渲染
  renderTodos(todosCache);
}

function todoImageUrl(todoId, imageId) { return `/api/todos/${todoId}/images/${encodeURIComponent(imageId)}`; }

function renderTodoImages(todo) {
  if (!todo?.images?.length) return '';
  return `<div class="todo-image-grid">${todo.images.map((image) => `
    <div class="todo-image-thumb">
      <img src="${todoImageUrl(todo.id, image.id)}" alt="待办图片">
      <button class="todo-image-remove" type="button" data-image-id="${image.id}" title="移除图片">&times;</button>
    </div>`).join('')}</div>`;
}

const pendingImageUrls = new Set();

function isSupportedTodoImage(file) {
  return ['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type);
}

function revokePendingTodoImageUrls() {
  for (const url of pendingImageUrls) URL.revokeObjectURL(url);
  pendingImageUrls.clear();
}

function currentExistingImageCount() {
  return document.querySelectorAll('#todo-existing-images .todo-image-thumb').length;
}

function renderPendingTodoImages() {
  const input = document.getElementById('todo-images');
  const container = document.getElementById('todo-pending-images');
  if (!input || !container) return;
  revokePendingTodoImageUrls();
  container.innerHTML = [...input.files].map((file) => {
    const url = URL.createObjectURL(file);
    pendingImageUrls.add(url);
    return `    <div class="todo-image-thumb"><img src="${url}" alt="待上传图片" title="${esc(file.name)}"></div>`;
  }).join('');
}

function setTodoImageFiles(files) {
  const input = document.getElementById('todo-images');
  const valid = files.filter(isSupportedTodoImage);
  if (!input || !valid.length) return 0;
  const capacity = 5 - currentExistingImageCount();
  if (capacity <= 0) {
    toast('每个待办最多 5 张图片', 'error');
    return 0;
  }
  const added = valid.slice(0, capacity);
  const transfer = new DataTransfer();
  added.forEach((file) => transfer.items.add(file));
  input.files = transfer.files;
  renderPendingTodoImages();
  if (valid.length > added.length) toast('图片数量已达到 5 张上限', 'error');
  return added.length;
}

function addTodoImageFiles(files) {
  const input = document.getElementById('todo-images');
  const before = input?.files.length || 0;
  setTodoImageFiles([...(input?.files || []), ...files]);
  return Math.max(0, (input?.files.length || 0) - before);
}

function bindTodoImageRemoveButtons(todoId) {
  document.querySelectorAll('#todo-existing-images .todo-image-remove').forEach((button) => {
    button.addEventListener('click', () => deleteTodoImage(todoId, button.dataset.imageId));
  });
}

function showTodoForm(todo = null) {
  const isEdit = !!todo;
  const formState = { id: todo?.id, abort: new AbortController() };
  revokePendingTodoImageUrls();
  showModal(`
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title">${isEdit ? '编辑重点待办' : '添加重点待办'}</div>
        <button class="close-btn">&times;</button>
      </div>
      <div class="form-group"><label>标题 *</label><input id="todo-title" value="${todo?.title || ''}"></div>
      <div class="form-group"><label>备注</label><textarea id="todo-note">${todo?.note || ''}</textarea></div>
      <div class="form-group"><label>优先级</label>
        <select id="todo-priority">
          ${['high', 'medium', 'low'].map((value) => `<option value="${value}" ${(todo?.priority || 'medium') === value ? 'selected' : ''}>${todoPriorityLabel(value)}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label>截止日期</label><input type="date" id="todo-due-date" value="${todo?.due_date || ''}"></div>
      <div class="form-group"><label>图片（最多 5 张，每张不超过 10MB，可直接粘贴）</label><div id="todo-existing-images">${renderTodoImages(todo)}</div><div id="todo-pending-images" class="todo-image-grid"></div><input type="file" id="todo-images" accept="image/jpeg,image/png,image/gif,image/webp" multiple></div>
      <div class="form-actions">
        ${isEdit ? '<button class="btn" id="delete-todo-btn" style="color:var(--down);">删除</button>' : ''}
        <button class="btn modal-cancel">取消</button>
        <button class="btn btn-primary" id="save-todo">${isEdit ? '保存' : '添加'}</button>
      </div>
    </div>`);
  bindModalClose();
  // 关闭/取消弹窗时中止进行中的图片上传，避免已取消的文件继续落库。
  document.querySelectorAll('.close-btn, .modal-cancel').forEach((btn) => btn.addEventListener('click', () => formState.abort.abort()));
  document.getElementById('save-todo').addEventListener('click', () => saveTodo(formState));
  document.getElementById('delete-todo-btn')?.addEventListener('click', () => deleteTodo(todo.id));
  bindTodoImageRemoveButtons(formState.id);
  const imageInput = document.getElementById('todo-images');
  imageInput.addEventListener('change', () => setTodoImageFiles([...imageInput.files]));
  imageInput.closest('.modal-content').addEventListener('paste', (event) => {
    const files = [...(event.clipboardData?.files || [])];
    const added = addTodoImageFiles(files);
    if (added) {
      event.preventDefault();
      toast(`已粘贴 ${added} 张图片，保存后上传`, 'success');
    }
  });
}

function todoPayload() {
  return {
    title: document.getElementById('todo-title').value.trim(),
    note: document.getElementById('todo-note').value.trim() || null,
    priority: document.getElementById('todo-priority').value,
    due_date: document.getElementById('todo-due-date').value || null,
  };
}

async function uploadOneTodoImage(todoId, file, signal) {
  if (file.size > 10 * 1024 * 1024) return `${file.name} 超过 10MB`;
  const form = new FormData();
  form.append('image', file);
  let response;
  try {
    response = await fetch(`/api/todos/${todoId}/images`, { method: 'POST', body: form, signal });
  } catch (error) {
    if (error?.name === 'AbortError') return `${file.name} 已取消`;
    return `${file.name} 网络错误`;
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) return data?.detail || `${file.name} 上传失败`;
  return null;
}

async function uploadTodoImages(formState) {
  const input = document.getElementById('todo-images');
  if (!input || !input.files.length) return;
  const failed = [];
  for (const file of [...input.files]) {
    // 单张失败（含网络异常/取消）只记录原因并继续，保证下面的重置逻辑一定执行，
    // 避免中途抛出跳过重置、导致重试时重复上传已成功的图片。
    const reason = await uploadOneTodoImage(formState.id, file, formState.abort?.signal);
    if (reason) failed.push({ file, reason });
  }
  if (formState.abort?.signal?.aborted) {
    // 用户已取消（关闭/取消弹窗）：不再重置输入框、不再渲染预览、不抛错，
    // 让 saveTodo 走正常清理路径（revoke blob、loadTodos），避免在已关弹窗上做无意义
    // DOM 操作、跨待办污染的刷新 GET，以及「已取消」这类自相矛盾的提示。
    return;
  }
  // 成功的移出输入框，失败的保留供重试，避免重试时重复上传已成功的图片。
  const transfer = new DataTransfer();
  failed.forEach((item) => transfer.items.add(item.file));
  input.files = transfer.files;
  renderPendingTodoImages();
  if (failed.length) {
    const first = failed[0].reason;
    throw new Error(failed.length === 1 ? first : `${failed.length} 张图片上传失败（${first}）`);
  }
}

async function refreshExistingTodoImages(todoId) {
  // 从服务端重拉并刷新已存在图片区，使缩略图与容量计数与 DB 一致。
  const { ok, data } = await fetchJSON(API.todo(todoId));
  if (!ok) return;
  const container = document.getElementById('todo-existing-images');
  if (container) {
    container.innerHTML = renderTodoImages(data);
    bindTodoImageRemoveButtons(todoId);
  }
}

async function saveTodo(formState) {
  const payload = todoPayload();
  if (!payload.title) { toast('标题必填', 'error'); return; }
  // formState.id 可变：新建成功后写回，使上传失败后的重试走 PUT，避免重复建待办。
  const wasNew = !formState.id;
  if (wasNew) {
    const { ok, data } = await fetchJSON(API.todos(), { method: 'POST', body: JSON.stringify(payload) });
    if (!ok) { toast(data?.detail || '保存失败', 'error'); return; }
    formState.id = data.id;
    // 新建已落库：把按钮切到「保存」态，提示用户待办已存在、可重试上传。
    const saveBtn = document.getElementById('save-todo');
    if (saveBtn) saveBtn.textContent = '保存';
  } else {
    const { ok } = await fetchJSON(API.todo(formState.id), { method: 'PUT', body: JSON.stringify(payload) });
    if (!ok) { toast('保存失败', 'error'); return; }
  }
  let uploadError = null;
  try {
    await uploadTodoImages(formState);
  } catch (error) {
    uploadError = error.message;
  }
  if (uploadError) {
    // 待办已落库：明确告知「已创建/已保存」，仅图片失败可重试，
    // 避免用户误以为整体失败而重填导致重复待办。
    // 已上传成功的图已落库——从服务端刷新已存在图片区，使容量计数与缩略图准确，
    // 否则 currentExistingImageCount 仍为 0，用户继续选图会误判容量、最终被后端拒。
    await refreshExistingTodoImages(formState.id);
    toast(`${wasNew ? '待办已创建' : '待办已保存'}，但 ${uploadError}（可再次点保存重试）`, 'error');
    loadTodos();
    return;
  }
  toast(wasNew ? '待办已添加' : '待办已保存', 'success');
  revokePendingTodoImageUrls();
  closeModal();
  loadTodos();
}

async function deleteTodoImage(todoId, imageId) {
  const { ok, data } = await fetchJSON(`/api/todos/${todoId}/images/${encodeURIComponent(imageId)}`, { method: 'DELETE' });
  if (!ok) { toast(data?.detail || '移除图片失败', 'error'); return; }
  // 只局部刷新已存在图片区，保留用户正在编辑的标题/备注和已选的待传文件。
  const container = document.getElementById('todo-existing-images');
  if (container) {
    container.innerHTML = renderTodoImages(data);
    bindTodoImageRemoveButtons(todoId);
  }
}

async function showTodoDetail(id) {
  const { ok, data } = await fetchJSON(API.todo(id));
  if (!ok) { toast(data?.detail || '待办不存在', 'error'); return; }
  showTodoForm(data);
}

async function setTodoStatus(id, done) {
  const { ok, data } = await fetchJSON(done ? API.todoDone(id) : API.todoReopen(id), { method: 'POST' });
  if (!ok) { toast(data?.detail || '操作失败', 'error'); return; }
  toast(done ? '待办已完成' : '待办已重新打开', 'success');
  loadTodos();
}

async function deleteTodo(id) {
  if (!confirm('确定删除该待办？')) return;
  const { ok, data } = await fetchJSON(API.todo(id), { method: 'DELETE' });
  if (!ok) { toast(data?.detail || '删除失败', 'error'); return; }
  toast('待办已删除', 'success');
  closeModal();
  loadTodos();
}

let currentImageIndex = 0;
let currentImages = [];

function showImagePreview(imageSrc, allImages = [], startIndex = 0) {
  currentImages = allImages.length > 0 ? allImages : [imageSrc];
  currentImageIndex = startIndex;

  const hasPrev = currentImageIndex > 0;
  const hasNext = currentImageIndex < currentImages.length - 1;
  const counter = currentImages.length > 1 ? `<div class="image-counter">${currentImageIndex + 1} / ${currentImages.length}</div>` : '';

  showModal(`
    <div class="modal-content image-preview-modal">
      <div class="image-preview-container" id="image-preview-container">
        <button class="image-nav-btn image-nav-prev ${!hasPrev ? 'hidden' : ''}" id="image-prev-btn">‹</button>
        <img src="${currentImages[currentImageIndex]}" alt="图片预览" class="image-preview-full" id="preview-image">
        <button class="image-nav-btn image-nav-next ${!hasNext ? 'hidden' : ''}" id="image-next-btn">›</button>
        ${counter}
        <button class="image-close-btn" id="image-close-btn">×</button>
      </div>
    </div>`);

  // 点击空白区域关闭
  const container = document.getElementById('image-preview-container');
  container.addEventListener('click', (e) => {
    if (e.target === container || e.target.id === 'preview-image') {
      closeModal();
    }
  });

  // 关闭按钮
  document.getElementById('image-close-btn')?.addEventListener('click', (e) => {
    e.stopPropagation();
    closeModal();
  });

  // 左右切换按钮
  document.getElementById('image-prev-btn')?.addEventListener('click', (e) => {
    e.stopPropagation();
    navigateImage(-1);
  });

  document.getElementById('image-next-btn')?.addEventListener('click', (e) => {
    e.stopPropagation();
    navigateImage(1);
  });

  // 键盘导航
  document.addEventListener('keydown', handleImageKeydown);

  // 触摸滑动支持
  let touchStartX = 0;
  let touchEndX = 0;

  container.addEventListener('touchstart', (e) => {
    touchStartX = e.changedTouches[0].screenX;
  }, { passive: true });

  container.addEventListener('touchend', (e) => {
    touchEndX = e.changedTouches[0].screenX;
    handleSwipe();
  }, { passive: true });

  function handleSwipe() {
    const diff = touchStartX - touchEndX;
    if (Math.abs(diff) > 50) { // 最小滑动距离
      if (diff > 0 && hasNext) {
        navigateImage(1); // 向左滑，下一张
      } else if (diff < 0 && hasPrev) {
        navigateImage(-1); // 向右滑，上一张
      }
    }
  }
}

function navigateImage(direction) {
  const newIndex = currentImageIndex + direction;
  if (newIndex >= 0 && newIndex < currentImages.length) {
    currentImageIndex = newIndex;
    updateImagePreview();
  }
}

function updateImagePreview() {
  const img = document.getElementById('preview-image');
  const prevBtn = document.getElementById('image-prev-btn');
  const nextBtn = document.getElementById('image-next-btn');
  const counter = document.querySelector('.image-counter');

  if (img) {
    img.src = currentImages[currentImageIndex];
  }

  if (prevBtn) {
    prevBtn.classList.toggle('hidden', currentImageIndex === 0);
  }

  if (nextBtn) {
    nextBtn.classList.toggle('hidden', currentImageIndex === currentImages.length - 1);
  }

  if (counter) {
    counter.textContent = `${currentImageIndex + 1} / ${currentImages.length}`;
  }
}

function handleImageKeydown(e) {
  if (e.key === 'ArrowLeft') {
    navigateImage(-1);
  } else if (e.key === 'ArrowRight') {
    navigateImage(1);
  } else if (e.key === 'Escape') {
    closeModal();
  }
}

// 清理键盘事件监听
const originalCloseModal = closeModal;
closeModal = function() {
  document.removeEventListener('keydown', handleImageKeydown);
  currentImages = [];
  currentImageIndex = 0;
  originalCloseModal();
};

// ============ AI 工作台 Tab ============

function actionLabel(action) {
  const name = action.name || action.item_name || '';
  const labels = {
    'item.purchase': `购买 ${action.amount} ${action.unit || ''} ${name}`,
    'item.usage': `消耗 ${action.amount} ${action.unit || ''} ${name}`,
    'item.set_stock': `盘点 ${name} 库存为 ${action.current_stock}`,
    'item.create': `新建物品 ${name}`,
    'todo.create': `新建待办 ${action.title || ''}`,
    'todo.complete': `完成待办 #${action.todo_id || ''}`,
    'todo.reopen': `重开待办 #${action.todo_id || ''}`,
    'todo.update': `更新待办 #${action.todo_id || ''}`,
    'todo.delete': `删除待办 #${action.todo_id || ''}`,
    'query.need_buy': '查询需要购买的日用品',
    'query.items': `查询库存 ${name}`,
    'query.open_todos': '查询未完成待办',
    'query.overdue_todos': '查询过期待办',
  };
  return esc(labels[action.op] || action.op);
}

function renderAiWorkbench() {
  const container = document.getElementById('tab-ai');

  let messagesHtml = '';
  if (chatMessages.length === 0) {
    messagesHtml = '<div class="chat-welcome">👋 你好！我是 HomeDash 家庭助手<br><br>我可以帮你管理库存、记录待办<br>也可以聊天和查资料</div>';
  } else {
    messagesHtml = chatMessages.map((msg) => {
      const label = msg.role === 'user' ? '你' : '助手';
      const bubbleClass = msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant';
      // 用户消息使用 esc 转义，助手消息使用 Markdown 渲染
      const content = msg.role === 'user' ? esc(msg.content) : renderMarkdown(msg.content);
      return `<div class="chat-message ${msg.role}"><div class="chat-label">${label}</div><div class="chat-bubble ${bubbleClass}">${content}</div></div>`;
    }).join('');
  }

  container.innerHTML = `
    <div class="card ai-workbench">
      <div class="ai-chips"></div>
      <div class="chat-messages" id="ai-messages">${messagesHtml}</div>
      <div id="ai-loading" class="ai-loading" style="display:none;">
        <div class="ai-loading-spinner"></div>
        <div class="ai-loading-text">思考中...</div>
      </div>
      <div class="chat-input-row">
        <textarea id="ai-text" class="chat-textarea" placeholder="输入指令或问题..." rows="1"></textarea>
        <button class="chat-send-btn" id="ai-send-btn" title="发送">▶</button>
      </div>
      <button class="ai-audit-toggle" id="ai-audit-toggle">📋 查看操作溯源 ▸</button>
      <div id="ai-audit-panel" class="ai-audit-panel">
        <div id="ai-audit-list" class="audit-list"></div>
        <div id="audit-footer"></div>
      </div>
    </div>`;

  loadSuggestedChips();

  const textarea = document.getElementById('ai-text');
  const sendBtn = document.getElementById('ai-send-btn');
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAiMessage(); }
  });
  textarea.addEventListener('input', () => {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 100) + 'px';
  });
  sendBtn.addEventListener('click', sendAiMessage);

  document.getElementById('ai-audit-toggle').addEventListener('click', toggleAudit);

  const messagesEl = document.getElementById('ai-messages');
  if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderAuditRow(r) {
  // 根据阶段和是否有操作判断标签
  let stageLabel = '';
  if (r.stage === 'parse') {
    stageLabel = '解析';
  } else if (r.stage === 'apply') {
    stageLabel = '执行';
  } else if (r.stage === 'chat') {
    // chat阶段如果有actions，显示为"执行"，否则显示为"对话"
    const hasActions = r.actions_json && r.actions_json !== '[]';
    stageLabel = hasActions ? '执行' : '对话';
  } else {
    stageLabel = '其他';
  }

  const okBadge = r.ok
    ? '<span class="badge badge-ok">成功</span>'
    : '<span class="badge badge-danger">失败</span>';
  const revertedTag = r.reverted ? '<span class="badge badge-outline">已撤回</span>' : '';
  const time = r.created_at ? r.created_at.slice(5, 16).replace('T', ' ') : '';

  // 用户问题（始终显示）
  const question = r.raw_text || '无内容';

  // 详情内容（点击展开）
  let detailsHtml = '';

  // AI回复（使用Markdown渲染）
  if (r.llm_reply) {
    const renderedReply = renderMarkdown(r.llm_reply);
    detailsHtml += `<div class="audit-detail-reply">${renderedReply}</div>`;
  }

  // 错误信息
  if (r.error) {
    detailsHtml += `<div class="audit-detail-error">错误：${esc(r.error)}</div>`;
  }

  // 操作列表
  try {
    const acts = JSON.parse(r.actions_json || '[]');
    if (acts.length > 0) {
      const actionsHtml = acts.map((a) => `<div class="audit-action-item">${actionLabel(a)}</div>`).join('');
      detailsHtml += `<div class="audit-detail-actions"><div class="audit-detail-label">执行操作：</div>${actionsHtml}</div>`;
    }
  } catch { /* ignore */ }

  // 前后对比
  try {
    const before = JSON.parse(r.before_json || '[]');
    const after = JSON.parse(r.after_json || '[]');
    if (before.length > 0) {
      const parts = before.map((b, i) => {
        const a = after[i] || {};
        const bRow = b.row ? `前: ${esc(b.row.name || '')} = ${fmtNumber(b.row.current_stock)}` : '前: 无';
        const aRow = a.row ? `后: ${esc(a.row.name || '')} = ${fmtNumber(a.row.current_stock)}` : '后: 已删';
        return `<div class="audit-compare-item">${bRow} → ${aRow}</div>`;
      });
      detailsHtml += `<div class="audit-detail-compare"><div class="audit-detail-label">数据变化：</div>${parts.join('')}</div>`;
    }
  } catch { /* ignore */ }

  // 元数据
  const model = r.llm_model ? esc(r.llm_model) : '';
  const dur = r.duration_ms != null ? `${r.duration_ms}ms` : '';
  if (model || dur) {
    detailsHtml += `<div class="audit-detail-meta">模型: ${model || '—'} · 耗时: ${dur || '—'}</div>`;
  }

  const revertBtn = ((r.stage === 'apply' || r.stage === 'chat') && r.ok && !r.reverted && r.actions_json && r.actions_json !== '[]')
    ? `<button class="btn btn-small audit-revert-btn" data-revert="${r.id}">撤回</button>` : '';

  return `
    <div class="audit-row" data-audit-id="${r.id}">
      <div class="audit-row-header" onclick="toggleAuditDetail(${r.id})">
        <div class="audit-row-main">
          <div class="audit-row-badges">
            ${okBadge}
            <span class="badge badge-outline">${stageLabel}</span>
            ${revertedTag}
          </div>
          <div class="audit-row-question">${esc(question)}</div>
        </div>
        <div class="audit-row-meta">
          <span class="audit-row-time">${time}</span>
          <span class="audit-row-expand">▸</span>
        </div>
      </div>
      <div class="audit-row-details" id="audit-detail-${r.id}" style="display:none;">
        ${detailsHtml}
        ${revertBtn ? `<div class="audit-detail-actions-bar">${revertBtn}</div>` : ''}
      </div>
    </div>`;
}

function toggleAuditDetail(auditId) {
  const detail = document.getElementById(`audit-detail-${auditId}`);
  const row = document.querySelector(`[data-audit-id="${auditId}"]`);
  const expandIcon = row?.querySelector('.audit-row-expand');

  if (detail && row && expandIcon) {
    const isExpanded = detail.style.display !== 'none';
    detail.style.display = isExpanded ? 'none' : 'block';
    expandIcon.textContent = isExpanded ? '▸' : '▾';
    row.classList.toggle('expanded', !isExpanded);
  }
}

let auditOffset = 0;
let auditHasMore = true;

async function loadAuditList(append = false) {
  const el = document.getElementById('ai-audit-list');
  if (!el) return;
  if (!append) { auditOffset = 0; auditHasMore = true; }

  const pageSize = 20;
  const { ok, data } = await fetchJSON(`${API.aiAudit}?limit=${pageSize}&offset=${auditOffset}`);
  if (!ok || !data?.rows) {
    if (!append) el.innerHTML = '<div class="empty-state">暂无溯源记录</div>';
    return;
  }

  auditOffset += data.rows.length;
  auditHasMore = data.has_more;

  const html = data.rows.map(renderAuditRow).join('');
  if (append) {
    el.insertAdjacentHTML('beforeend', html);
  } else {
    el.innerHTML = html;
  }

  const footer = document.getElementById('audit-footer');
  if (footer) {
    footer.innerHTML = auditHasMore
      ? '<button class="btn btn-small" id="audit-load-more">加载更多...</button>'
      : (data.total > 0 ? '<div class="empty-state">已加载全部 ' + data.total + ' 条记录</div>' : '');
    const btn = document.getElementById('audit-load-more');
    if (btn) btn.addEventListener('click', () => loadAuditList(true));
  }

  el.querySelectorAll('button[data-revert]').forEach((btn) => {
    btn.addEventListener('click', () => revertAi(Number(btn.dataset.revert)));
  });
}

async function loadSuggestedChips() {
  // 固定显示7个日常消耗快捷词条
  const chips = [
    '吃一个鸡蛋',
    '吃一包方便面',
    '喝了一罐啤酒',
    '吃了一个面包',
    '用一包抽纸',
    '用一包湿巾',
    '最近有什么需要购买的'
  ];
  const container = document.querySelector('.ai-chips');
  if (!container) return;
  container.innerHTML = chips.map((text) =>
    `<button class="btn btn-small ai-chip">${esc(text)}</button>`
  ).join('');
  container.querySelectorAll('.ai-chip').forEach((button) => button.addEventListener('click', () => {
    document.getElementById('ai-text').value = button.textContent;
  }));
}

async function revertAi(actionId) {
  if (!actionId) { toast('没有可撤回的操作', 'error'); return; }

  const { ok, data } = await fetchJSON(`${API.aiRevert}/${actionId}`, { method: 'POST' });
  if (!ok) {
    toast(data?.detail || '撤回失败', 'error');
    return;
  }

  toast('已撤回操作', 'success');
  renderAiWorkbench();
}


function toggleAudit() {
  const panel = document.getElementById('ai-audit-panel');
  const btn = document.getElementById('ai-audit-toggle');
  const expanded = panel.classList.toggle('expanded');
  if (expanded) {
    loadAuditList();
    btn.textContent = '📋 收起操作溯源 ▾';
  } else {
    btn.textContent = '📋 查看操作溯源 ▸';
  }
}


async function sendAiMessage() {
  const input = document.getElementById('ai-text');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.style.height = 'auto';
  chatMessages.push({ role: 'user', content: text });
  renderAiWorkbench();

  const loading = document.getElementById('ai-loading');
  const sendBtn = document.getElementById('ai-send-btn');
  if (loading) loading.style.display = 'flex';
  if (sendBtn) sendBtn.disabled = true;

  try {
    const history = chatMessages.slice(-21, -1).map((msg) => ({ role: msg.role, content: msg.content }));
    const { ok, data } = await fetchJSON(API.aiChat, {
      method: 'POST',
      body: JSON.stringify({ text, session_id: null, history }),
    });
    if (ok && data?.reply) {
      chatMessages.push({ role: 'assistant', content: data.reply });
    } else {
      chatMessages.push({ role: 'assistant', content: data?.detail || '抱歉，请求失败，请稍后重试。' });
    }
  } catch (e) {
    chatMessages.push({ role: 'assistant', content: '网络请求失败，请检查连接后重试。' });
  }

  if (loading) loading.style.display = 'none';
  if (sendBtn) sendBtn.disabled = false;
  renderAiWorkbench();
}

// ============ 全局刷新 ============

function initRefresh() {
  const btn = document.getElementById('refresh-btn');
  btn.addEventListener('click', () => {
    btn.disabled = true;
    setTimeout(() => (btn.disabled = false), 2000);
    if (currentTab === 'items') loadItems();
    if (currentTab === 'todos') loadTodos();
    if (currentTab === 'ai') renderAiWorkbench();
    if (currentTab === 'setup') loadSetup();
  });
}

function initAccountMenu() {
  const button = document.getElementById('settings-btn');
  const menu = document.getElementById('account-menu');
  const closeMenu = () => {
    menu.classList.add('hidden');
    button.setAttribute('aria-expanded', 'false');
  };
  menu.innerHTML = `
    <div class="account-menu-user">${esc(currentUser.username)}<small>${currentUser.role === 'admin' ? '管理员' : '普通用户'}</small></div>
    ${currentUser.role === 'admin' ? '<button type="button" data-action="setup">系统设置</button>' : ''}
    <button type="button" data-action="logout">退出登录</button>`;
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    menu.classList.toggle('hidden');
    button.setAttribute('aria-expanded', String(!menu.classList.contains('hidden')));
  });
  menu.addEventListener('click', async (event) => {
    const action = event.target.closest('button')?.dataset.action;
    if (action === 'setup') {
      closeMenu();
      switchTab('setup');
    }
    if (action === 'logout') {
      await fetchJSON(API.logout, { method: 'POST' });
      window.location.reload();
    }
  });
  document.addEventListener('click', closeMenu);
}

// ============ 启动 ============

function initApp() {
  document.getElementById('auth-view').classList.add('hidden');
  document.getElementById('app-shell').classList.remove('hidden');
  initTabs();
  initRefresh();
  initAccountMenu();
  if (currentUser.role === 'admin') loadSetupBanner();
  switchTab('ai');
}

function renderAuthForm(bootstrap, message = '') {
  currentUser = null;
  document.getElementById('app-shell').classList.add('hidden');
  const view = document.getElementById('auth-view');
  view.classList.remove('hidden');
  view.innerHTML = `
    <div class="auth-card">
      <div class="auth-logo">🏠</div>
      <h1>HomeDash</h1>
      <p>${bootstrap ? '首次使用，请创建管理员账户' : '登录家庭管理面板'}</p>
      <form id="auth-form">
        <div class="form-group"><label for="auth-username">用户名</label><input id="auth-username" autocomplete="username" required minlength="2" maxlength="32"></div>
        <div class="form-group"><label for="auth-password">密码</label><input id="auth-password" type="password" autocomplete="${bootstrap ? 'new-password' : 'current-password'}" required minlength="8" maxlength="128"></div>
        ${bootstrap ? '<div class="form-group"><label for="auth-password-confirm">确认密码</label><input id="auth-password-confirm" type="password" autocomplete="new-password" required minlength="8" maxlength="128"></div>' : ''}
        <button class="btn btn-primary auth-submit" type="submit">${bootstrap ? '创建管理员并进入' : '登录'}</button>
        <div id="auth-result" class="setup-result ${message ? 'error' : ''}">${esc(message)}</div>
      </form>
    </div>`;
  document.getElementById('auth-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value;
    const result = document.getElementById('auth-result');
    if (bootstrap && password !== document.getElementById('auth-password-confirm').value) {
      result.textContent = '两次输入的密码不一致';
      result.className = 'setup-result error';
      return;
    }
    const button = event.submitter;
    button.disabled = true;
    const response = await fetchJSON(bootstrap ? API.bootstrapAdmin : API.login, {
      method: 'POST', body: JSON.stringify({ username, password }),
    });
    button.disabled = false;
    if (!response.ok) {
      result.textContent = response.data?.detail || (bootstrap ? '创建管理员失败' : '登录失败');
      result.className = 'setup-result error';
      return;
    }
    window.location.reload();
  });
}

async function init() {
  const bootstrap = await fetchJSON(API.bootstrapStatus);
  if (!bootstrap.ok) {
    renderAuthForm(false, bootstrap.data?.detail || '无法读取初始化状态');
    return;
  }
  if (bootstrap.data.required) {
    renderAuthForm(true);
    return;
  }
  const me = await fetchJSON(API.me);
  if (!me.ok) {
    renderAuthForm(false);
    return;
  }
  currentUser = me.data;
  initApp();
}

document.addEventListener('DOMContentLoaded', init);

// ============ 设置 Tab ============

async function loadSetup() {
  await loadSetupStatus();
  renderSetup();
}

async function loadSetupStatus() {
  const { ok, data } = await fetchJSON(API.setupStatus);
  if (ok) setupStatusData = data;
  return setupStatusData;
}

async function loadSetupBanner() {
  const status = await loadSetupStatus();
  const existing = document.getElementById('setup-banner');
  if (!status || !status.missing || !status.missing.length) {
    if (existing) existing.remove();
    return;
  }
  const header = document.querySelector('header');
  const html = `<span>⚠️ 配置不完整：${esc(status.missing.join('、'))}</span><button class="btn btn-small btn-primary" id="setup-banner-btn">前往设置</button>`;
  if (existing) {
    existing.innerHTML = html;
  } else {
    const banner = document.createElement('div');
    banner.id = 'setup-banner';
    banner.className = 'setup-banner';
    banner.innerHTML = html;
    header.insertAdjacentElement('afterend', banner);
  }
  document.getElementById('setup-banner-btn').addEventListener('click', () => switchTab('setup'));
}

function renderSetup() {
  const container = document.getElementById('tab-setup');
  if (!setupStatusData) {
    container.innerHTML = '<div class="loading">加载配置状态中...</div>';
    return;
  }
  const s = setupStatusData;
  const statusClass = (ok) => (ok ? 'status-ok' : 'status-missing');
  const statusText = (ok, label) => `<span class="${statusClass(ok)}">${ok ? '✅' : '❌'} ${label}</span>`;
  const statusOptional = (ok, label) => ok ? statusText(true, label) : `<span class="status-optional">○ ${label} 未配置</span>`;

  container.innerHTML = `
    <div class="card">
      <div class="section-title">配置总览</div>
      <div class="setup-status-grid">
        <div class="setup-status-item">${statusText(s.llm_configured, 'AI 工作台 LLM')}</div>
        <div class="setup-status-item">${statusOptional(s.smtp_configured, 'SMTP 周报（可选）')}</div>
        <div class="setup-status-item">${statusOptional(s.brave_configured, 'Brave 网络搜索（可选）')}</div>
        <div class="setup-status-item">${statusOptional(s.amap_configured, '高德地图交通时长（可选）')}</div>
        <div class="setup-status-item">${statusOptional(s.agent_token_configured, 'Agent Token（可选）')}</div>
      </div>
      ${s.missing && s.missing.length ? `<div class="setup-missing">待处理：${esc(s.missing.join('、'))}</div>` : '<div class="setup-ok">全部配置就绪 🎉</div>'}
    </div>

    <div class="card">
      <div class="section-title">用户管理</div>
      <div class="setup-help">管理员可以新增普通用户或其他管理员。禁用、删除或重置密码会立即使该用户的登录会话失效。</div>
      <form id="user-create-form" class="setup-form">
        <div class="form-row">
          <div class="form-group"><label for="new-username">用户名</label><input id="new-username" placeholder="例如：家人" required minlength="2" maxlength="32" autocomplete="off"></div>
          <div class="form-group"><label for="new-user-password">初始密码</label><input id="new-user-password" type="password" placeholder="至少 8 个字符" required minlength="8" maxlength="128" autocomplete="new-password"></div>
        </div>
        <div class="form-row user-create-actions">
          <div class="form-group"><label for="new-user-role">角色</label><select id="new-user-role"><option value="user">普通用户</option><option value="admin">管理员</option></select></div>
          <div class="form-actions"><button type="submit" class="btn btn-primary">新增用户</button></div>
        </div>
        <div id="user-create-result" class="setup-result"></div>
      </form>
      <div id="user-list" class="setup-subsection"><div class="loading">加载用户中...</div></div>
    </div>

    <details class="card">
      <summary class="section-title">AI 工作台配置</summary>
      <form id="setup-llm-form" class="setup-form">
        <div class="form-group"><label>Base URL</label><input type="text" id="llm-base-url" placeholder="https://your-openai-compatible/v1"></div>
        <div class="form-group"><label>API Key</label><input type="password" id="llm-api-key" placeholder="sk-..."></div>
        <div class="form-row">
          <div class="form-group"><label>模型</label><input type="text" id="llm-model" placeholder="gpt-4o-mini"></div>
          <div class="form-group"><label>超时（秒）</label><input type="number" id="llm-timeout" value="30" min="5" max="120"></div>
        </div>
        <div id="llm-model-list" class="setup-subsection"></div>
        <div class="form-row">
          <div class="form-group"><label><input type="checkbox" id="llm-enabled" checked> 启用 AI 工作台</label></div>
          <div class="form-group"><label><input type="checkbox" id="llm-confirm" checked> 写入前需确认</label></div>
          <div class="form-group"><label>最大 actions</label><input type="number" id="llm-max-actions" value="8" min="1" max="20"></div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">保存并测试</button>
          <button type="button" class="btn" id="llm-test-only-btn">仅测试</button>
          <button type="button" class="btn" id="llm-models-btn">获取模型列表</button>
        </div>
        <div id="llm-result" class="setup-result"></div>
      </form>
    </details>

    <details class="card">
      <summary class="section-title">Brave Search 网络搜索（可选）</summary>
      <div class="setup-help">配置后，家庭顾问可以搜索互联网获取实时信息（天气、新闻等）。<b>API Key 申请：</b><code>https://brave.com/search/api/</code>（免费额度 2,000 次/月）。不配置不影响聊天功能。</div>
      <form id="setup-brave-form" class="setup-form">
        <div class="form-group"><label>API Key</label><input type="password" id="brave-api-key" placeholder="BSA..."></div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">保存并测试</button>
          <button type="button" class="btn" id="brave-test-only-btn">仅测试</button>
        </div>
        <div id="brave-result" class="setup-result"></div>
      </form>
    </details>

    <details class="card">
      <summary class="section-title">高德地图交通时长（可选）</summary>
      <div class="setup-help">配置后，「旅游计划」目的地推荐会显示精确交通时长：自驾用高德驾车路径规划，高铁/飞机按直线距离估算。不配置则降级为 LLM 估算，旅游功能仍可用。<b>Key 申请：</b><code>https://lbs.amap.com/</code>（选「Web 服务」类型）。</div>
      <form id="setup-amap-form" class="setup-form">
        <div class="form-group"><label>高德 Web 服务 Key</label><input type="password" id="amap-api-key" placeholder="高德 Web 服务 Key"></div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">保存并测试</button>
          <button type="button" class="btn" id="amap-test-only-btn">仅测试</button>
        </div>
        <div id="amap-result" class="setup-result"></div>
      </form>
    </details>

    <details class="card">
      <summary class="section-title">Agent Token（可选）</summary>
      <div class="setup-help">配置后，外部 AI agent（如 Hermes）可通过 <code>X-HomeDash-Token</code> 请求头调用 <code>/api/agent/todos/*</code> 接口。不配置时接口无需鉴权，仅限内网使用。</div>
      <form id="setup-agent-form" class="setup-form">
        <div class="form-group"><label>Agent Token</label><input type="password" id="agent-token" placeholder="自定义随机字符串"></div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">保存</button>
        </div>
        <div id="agent-result" class="setup-result"></div>
      </form>
    </details>

    <details class="card">
      <summary class="section-title">SMTP 周报配置</summary>
      <div class="setup-help">保存后写入 <code>data/notify_config.json</code> 并立即生效。QQ 邮箱需使用 SMTP 授权码，不是网页登录密码。</div>
      <form id="setup-notify-form" class="setup-form">
        <div class="form-row">
          <div class="form-group"><label>SMTP Host</label><input type="text" id="smtp-host" placeholder="smtp.qq.com"></div>
          <div class="form-group"><label>SMTP Port</label><input type="number" id="smtp-port" value="465" min="1" max="65535"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>SMTP 用户</label><input type="text" id="smtp-user" placeholder="your@qq.com"></div>
          <div class="form-group"><label>SMTP 授权码</label><input type="password" id="smtp-password" placeholder="授权码"></div>
        </div>
        <div class="form-group"><label>发件人显示</label><input type="text" id="smtp-from" placeholder="HomeDash <your@qq.com>"></div>
        <div class="form-group"><label>收件人（英文逗号分隔）</label><input type="text" id="notify-to" placeholder="person-a@example.com,person-b@example.com"></div>
        <div class="form-row">
          <div class="form-group"><label><input type="checkbox" id="notify-enabled"> 启用周报接口</label></div>
          <div class="form-group"><label><input type="checkbox" id="notify-only-need"> 没有待办和需买时跳过</label></div>
          <div class="form-group"><label>待办最多列出</label><input type="number" id="notify-limit" value="20" min="1" max="100"></div>
        </div>
        <div class="form-group"><label>面板公开链接</label><input type="text" id="homedash-public-url" placeholder="http://127.0.0.1:8088"></div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">保存并测试登录</button>
          <button type="button" class="btn" id="notify-test-only-btn">仅测试 SMTP</button>
          <button type="button" class="btn" id="notify-send-test-btn">立即发送测试周报</button>
        </div>
        <div id="notify-result" class="setup-result"></div>
      </form>
    </details>

  `;

  bindSetupEvents();
  loadLlmConfig();
  loadBraveConfig();
  loadAmapConfig();
  loadAgentConfig();
  loadNotifyConfig();
  loadUsers();
}

function bindSetupEvents() {
  document.getElementById('setup-llm-form').addEventListener('submit', saveLlmConfig);
  document.getElementById('llm-test-only-btn').addEventListener('click', testLlmConfig);
  document.getElementById('llm-models-btn').addEventListener('click', loadLlmModels);
  document.getElementById('setup-brave-form').addEventListener('submit', saveBraveConfig);
  document.getElementById('brave-test-only-btn').addEventListener('click', testBraveConfig);
  document.getElementById('setup-amap-form').addEventListener('submit', saveAmapConfig);
  document.getElementById('amap-test-only-btn').addEventListener('click', testAmapConfig);
  document.getElementById('setup-agent-form').addEventListener('submit', saveAgentConfig);
  document.getElementById('setup-notify-form').addEventListener('submit', saveNotifyConfig);
  document.getElementById('notify-test-only-btn').addEventListener('click', testNotifyConfig);
  document.getElementById('notify-send-test-btn').addEventListener('click', sendTestNotify);
  document.getElementById('user-create-form').addEventListener('submit', createManagedUser);
}

async function loadUsers() {
  const container = document.getElementById('user-list');
  if (!container) return;
  const { ok, data } = await fetchJSON(API.users);
  if (!ok) {
    container.innerHTML = `<div class="setup-result error">${esc(data?.detail || '用户列表加载失败')}</div>`;
    return;
  }
  container.innerHTML = `<div class="setup-list">${data.map((user) => {
    const self = user.id === currentUser.id;
    return `<div class="setup-list-item user-list-item" data-user-id="${user.id}">
      <div class="user-summary"><b>${esc(user.username)}</b>${self ? '<span class="tag">当前账户</span>' : ''}<small>最后登录：${esc(user.last_login_at || '尚未登录')}</small></div>
      <div class="user-fields">
        <select class="managed-user-role" ${self ? 'disabled' : ''}><option value="user" ${user.role === 'user' ? 'selected' : ''}>普通用户</option><option value="admin" ${user.role === 'admin' ? 'selected' : ''}>管理员</option></select>
        <label><input class="managed-user-enabled" type="checkbox" ${user.enabled ? 'checked' : ''} ${self ? 'disabled' : ''}> 启用</label>
      </div>
      <div class="setup-list-actions">
        ${self ? '' : '<button class="btn btn-small" data-action="save-user">保存</button>'}
        <button class="btn btn-small" data-action="reset-password">重置密码</button>
        ${self ? '' : '<button class="btn btn-small btn-danger" data-action="delete-user">删除</button>'}
      </div>
    </div>`;
  }).join('')}</div>`;
  container.querySelectorAll('[data-action="save-user"]').forEach((button) => button.addEventListener('click', () => updateManagedUser(button.closest('.user-list-item'))));
  container.querySelectorAll('[data-action="reset-password"]').forEach((button) => button.addEventListener('click', () => showPasswordReset(Number(button.closest('.user-list-item').dataset.userId))));
  container.querySelectorAll('[data-action="delete-user"]').forEach((button) => button.addEventListener('click', () => deleteManagedUser(Number(button.closest('.user-list-item').dataset.userId))));
}

async function createManagedUser(event) {
  event.preventDefault();
  const result = document.getElementById('user-create-result');
  const payload = {
    username: document.getElementById('new-username').value.trim(),
    password: document.getElementById('new-user-password').value,
    role: document.getElementById('new-user-role').value,
  };
  const { ok, data } = await fetchJSON(API.users, { method: 'POST', body: JSON.stringify(payload) });
  result.textContent = ok ? '用户已新增' : (data?.detail || '新增用户失败');
  result.className = `setup-result ${ok ? 'success' : 'error'}`;
  if (ok) {
    event.target.reset();
    loadUsers();
  }
}

async function updateManagedUser(row) {
  const userId = Number(row.dataset.userId);
  const payload = {
    role: row.querySelector('.managed-user-role').value,
    enabled: row.querySelector('.managed-user-enabled').checked,
  };
  const { ok, data } = await fetchJSON(API.user(userId), { method: 'PUT', body: JSON.stringify(payload) });
  toast(ok ? '用户信息已保存' : (data?.detail || '保存失败'), ok ? 'success' : 'error');
  if (ok) loadUsers();
}

function showPasswordReset(userId) {
  showModal(`<div class="modal-content">
    <div class="modal-header"><div class="modal-title">重置用户密码</div><button class="close-btn">&times;</button></div>
    <div class="form-group"><label>新密码（至少 8 个字符）</label><input id="managed-new-password" type="password" minlength="8" maxlength="128" autocomplete="new-password"></div>
    <div class="form-group"><label>确认新密码</label><input id="managed-new-password-confirm" type="password" minlength="8" maxlength="128" autocomplete="new-password"></div>
    <div class="form-actions"><button class="btn modal-cancel">取消</button><button class="btn btn-primary" id="save-managed-password">确认重置</button></div>
  </div>`);
  bindModalClose();
  document.getElementById('save-managed-password').addEventListener('click', async () => {
    const password = document.getElementById('managed-new-password').value;
    if (password !== document.getElementById('managed-new-password-confirm').value) {
      toast('两次输入的密码不一致', 'error');
      return;
    }
    const { ok, data } = await fetchJSON(API.userPassword(userId), { method: 'PUT', body: JSON.stringify({ password }) });
    if (!ok) {
      toast(data?.detail || '密码重置失败', 'error');
      return;
    }
    closeModal();
    toast('密码已重置，该用户需要重新登录', 'success');
    if (userId === currentUser.id) setTimeout(() => window.location.reload(), 800);
  });
}

async function deleteManagedUser(userId) {
  if (!confirm('确定删除该用户吗？删除后无法恢复，该用户会立即退出登录。')) return;
  const { ok, data } = await fetchJSON(API.user(userId), { method: 'DELETE' });
  toast(ok ? '用户已删除' : (data?.detail || '删除失败'), ok ? 'success' : 'error');
  if (ok) loadUsers();
}

async function refreshSetupOverview() {
  await loadSetupStatus();
  await loadSetupBanner();
  const s = setupStatusData;
  if (!s) return;
  const grid = document.querySelector('.setup-status-grid');
  if (!grid) return;
  const statusText = (ok, label) => `<span class="${ok ? 'status-ok' : 'status-missing'}">${ok ? '✅' : '❌'} ${label}</span>`;
  const statusOptional = (ok, label) => ok ? statusText(true, label) : `<span class="status-optional">○ ${label} 未配置</span>`;
  grid.innerHTML = `
    <div class="setup-status-item">${statusText(s.llm_configured, 'AI 工作台 LLM')}</div>
    <div class="setup-status-item">${statusOptional(s.smtp_configured, 'SMTP 周报（可选）')}</div>
    <div class="setup-status-item">${statusOptional(s.brave_configured, 'Brave 网络搜索（可选）')}</div>
    <div class="setup-status-item">${statusOptional(s.agent_token_configured, 'Agent Token（可选）')}</div>`;
  const missing = document.querySelector('.setup-missing, .setup-ok');
  if (missing) {
    if (s.missing && s.missing.length) {
      missing.className = 'setup-missing';
      missing.textContent = `待处理：${s.missing.join('、')}`;
    } else {
      missing.className = 'setup-ok';
      missing.textContent = '全部配置就绪 🎉';
    }
  }
}


async function loadLlmConfig() {
  const { ok, data } = await fetchJSON(API.setupLlmConfig);
  if (!ok || !data) return;
  document.getElementById('llm-base-url').value = data.base_url || '';
  document.getElementById('llm-api-key').value = data.api_key || '';
  document.getElementById('llm-model').value = data.model || '';
  document.getElementById('llm-timeout').value = data.timeout_sec || 30;
  document.getElementById('llm-enabled').checked = data.enabled !== false;
  document.getElementById('llm-confirm').checked = data.confirm_required !== false;
  document.getElementById('llm-max-actions').value = data.max_actions || 8;
}

async function saveLlmConfig(e) {
  e.preventDefault();
  const payload = {
    base_url: document.getElementById('llm-base-url').value.trim(),
    api_key: document.getElementById('llm-api-key').value.trim(),
    model: document.getElementById('llm-model').value.trim(),
    timeout_sec: parseFloat(document.getElementById('llm-timeout').value) || 30,
    enabled: document.getElementById('llm-enabled').checked,
    confirm_required: document.getElementById('llm-confirm').checked,
    max_actions: parseInt(document.getElementById('llm-max-actions').value, 10) || 8,
  };
  const { ok, data } = await fetchJSON(API.setupLlmSave, { method: 'POST', body: JSON.stringify(payload) });
  const resultBox = document.getElementById('llm-result');
  if (!ok) {
    resultBox.textContent = data?.detail || '保存失败';
    resultBox.className = 'setup-result error';
    return;
  }
  resultBox.textContent = data.message || (data.tested ? '保存成功，连接正常' : '保存成功，但连接测试失败');
  resultBox.className = `setup-result ${data.tested ? 'success' : 'warning'}`;
  await refreshSetupOverview();
}

async function testLlmConfig() {
  const payload = {
    base_url: document.getElementById('llm-base-url').value.trim(),
    api_key: document.getElementById('llm-api-key').value.trim(),
    model: document.getElementById('llm-model').value.trim(),
    timeout_sec: parseFloat(document.getElementById('llm-timeout').value) || 30,
  };
  const resultBox = document.getElementById('llm-result');
  resultBox.textContent = '测试中...';
  const { ok, data } = await fetchJSON(API.setupLlmTest, { method: 'POST', body: JSON.stringify(payload) });
  resultBox.textContent = data?.message || (ok ? '连接正常' : '连接失败');
  resultBox.className = `setup-result ${data?.ok ? 'success' : 'error'}`;
}

async function loadLlmModels() {
  const box = document.getElementById('llm-model-list');
  box.innerHTML = '<div class="loading">获取模型列表中...</div>';
  const { ok, data } = await fetchJSON(API.setupLlmModels);
  if (!ok || !data?.ok || !data.models?.length) {
    box.innerHTML = `<div class="setup-result error">${esc(data?.message || data?.detail || '无法获取模型列表')}</div>`;
    return;
  }
  box.innerHTML = `<div class="setup-list">${data.models.map((model) => `
    <button type="button" class="btn btn-small llm-model-choice" data-model="${esc(model)}">${esc(model)}</button>
  `).join('')}</div>`;
  box.querySelectorAll('.llm-model-choice').forEach((btn) => btn.addEventListener('click', () => {
    document.getElementById('llm-model').value = btn.dataset.model;
    toast(`已选择模型 ${btn.dataset.model}`, 'success');
  }));
}

async function loadBraveConfig() {
  const { ok, data } = await fetchJSON(API.setupBraveConfig);
  if (!ok || !data) return;
  document.getElementById('brave-api-key').value = data.api_key || '';
}

async function saveBraveConfig(e) {
  e.preventDefault();
  const payload = { api_key: document.getElementById('brave-api-key').value.trim() };
  const { ok, data } = await fetchJSON(API.setupBraveSave, { method: 'POST', body: JSON.stringify(payload) });
  const resultBox = document.getElementById('brave-result');
  if (!ok) {
    resultBox.textContent = data?.detail || '保存失败';
    resultBox.className = 'setup-result error';
    return;
  }
  resultBox.textContent = data.message || (data.tested ? '保存成功，Brave Search 连接正常' : '保存成功，但连接测试失败');
  resultBox.className = `setup-result ${data.tested ? 'success' : 'warning'}`;
  await refreshSetupOverview();
}

async function testBraveConfig() {
  const payload = { api_key: document.getElementById('brave-api-key').value.trim() };
  const resultBox = document.getElementById('brave-result');
  resultBox.textContent = '测试中...';
  const { ok, data } = await fetchJSON(API.setupBraveTest, { method: 'POST', body: JSON.stringify(payload) });
  resultBox.textContent = data?.message || (ok ? '连接正常' : '连接失败');
  resultBox.className = `setup-result ${data?.ok ? 'success' : 'error'}`;
}

async function loadAmapConfig() {
  const { ok, data } = await fetchJSON(API.setupAmapConfig);
  if (!ok || !data) return;
  document.getElementById('amap-api-key').value = data.api_key || '';
}

async function saveAmapConfig(e) {
  e.preventDefault();
  const payload = { api_key: document.getElementById('amap-api-key').value.trim() };
  const { ok, data } = await fetchJSON(API.setupAmapSave, { method: 'POST', body: JSON.stringify(payload) });
  const resultBox = document.getElementById('amap-result');
  if (!ok) {
    resultBox.textContent = data?.detail || '保存失败';
    resultBox.className = 'setup-result error';
    return;
  }
  resultBox.textContent = data.message || (data.tested ? '保存成功，高德 Key 有效' : '保存成功，但连接测试失败');
  resultBox.className = `setup-result ${data.tested ? 'success' : 'warning'}`;
  await refreshSetupOverview();
}

async function testAmapConfig() {
  const payload = { api_key: document.getElementById('amap-api-key').value.trim() };
  const resultBox = document.getElementById('amap-result');
  resultBox.textContent = '测试中...';
  const { ok, data } = await fetchJSON(API.setupAmapTest, { method: 'POST', body: JSON.stringify(payload) });
  resultBox.textContent = data?.message || (ok ? '连接正常' : '连接失败');
  resultBox.className = `setup-result ${data?.ok ? 'success' : 'error'}`;
}

async function loadAgentConfig() {
  const { ok, data } = await fetchJSON(API.setupAgentConfig);
  if (!ok || !data) return;
  document.getElementById('agent-token').value = data.token || '';
}

async function saveAgentConfig(e) {
  e.preventDefault();
  const payload = { token: document.getElementById('agent-token').value.trim() };
  const { ok, data } = await fetchJSON(API.setupAgentSave, { method: 'POST', body: JSON.stringify(payload) });
  const resultBox = document.getElementById('agent-result');
  if (!ok) {
    resultBox.textContent = data?.detail || '保存失败';
    resultBox.className = 'setup-result error';
    return;
  }
  resultBox.textContent = data.message || '保存成功';
  resultBox.className = 'setup-result success';
  await refreshSetupOverview();
}

async function loadNotifyConfig() {
  const { ok, data } = await fetchJSON(API.setupNotifyConfig);
  if (!ok || !data) return;
  document.getElementById('smtp-host').value = data.smtp_host || '';
  document.getElementById('smtp-port').value = data.smtp_port || 465;
  document.getElementById('smtp-user').value = data.smtp_user || '';
  document.getElementById('smtp-password').value = data.smtp_password || '';
  document.getElementById('smtp-from').value = data.smtp_from || '';
  document.getElementById('notify-to').value = data.notify_to || '';
  document.getElementById('notify-enabled').checked = data.notify_enabled === true;
  document.getElementById('notify-only-need').checked = data.notify_only_when_need_buy === true;
  document.getElementById('notify-limit').value = data.notify_todo_limit || 20;
  document.getElementById('homedash-public-url').value = data.homedash_public_url || '';
}

function notifyPayload() {
  return {
    smtp_host: document.getElementById('smtp-host').value.trim(),
    smtp_port: parseInt(document.getElementById('smtp-port').value, 10) || 465,
    smtp_user: document.getElementById('smtp-user').value.trim(),
    smtp_password: document.getElementById('smtp-password').value.trim(),
    smtp_from: document.getElementById('smtp-from').value.trim(),
    notify_to: document.getElementById('notify-to').value.trim(),
    notify_enabled: document.getElementById('notify-enabled').checked,
    notify_only_when_need_buy: document.getElementById('notify-only-need').checked,
    notify_todo_limit: parseInt(document.getElementById('notify-limit').value, 10) || 20,
    homedash_public_url: document.getElementById('homedash-public-url').value.trim(),
  };
}

async function saveNotifyConfig(e) {
  e.preventDefault();
  const resultBox = document.getElementById('notify-result');
  resultBox.textContent = '保存并测试中...';
  const { ok, data } = await fetchJSON(API.setupNotifySave, { method: 'POST', body: JSON.stringify(notifyPayload()) });
  if (!ok) {
    resultBox.textContent = data?.detail || '保存失败';
    resultBox.className = 'setup-result error';
    return;
  }
  resultBox.textContent = data.message || (data.tested ? '保存成功，SMTP 登录正常' : '保存成功，但 SMTP 登录失败');
  resultBox.className = `setup-result ${data.tested ? 'success' : 'warning'}`;
  await refreshSetupOverview();
}

async function testNotifyConfig() {
  const resultBox = document.getElementById('notify-result');
  resultBox.textContent = '测试中...';
  const { ok, data } = await fetchJSON(API.setupNotifyTest, { method: 'POST', body: JSON.stringify(notifyPayload()) });
  resultBox.textContent = data?.message || (ok ? 'SMTP 正常' : 'SMTP 失败');
  resultBox.className = `setup-result ${data?.ok ? 'success' : 'error'}`;
}

async function sendTestNotify() {
  const resultBox = document.getElementById('notify-result');
  resultBox.textContent = '发送测试周报中...';
  const { ok, data } = await fetchJSON(API.notifyTest, { method: 'POST' });
  if (!ok) {
    resultBox.textContent = data?.detail || '发送失败';
    resultBox.className = 'setup-result error';
    return;
  }
  resultBox.textContent = data.sent ? `已发送：待办 ${data.todo_count} 项，需买 ${data.buy_count} 项` : (data.reason || '未发送');
  resultBox.className = `setup-result ${data.sent ? 'success' : 'warning'}`;
}
