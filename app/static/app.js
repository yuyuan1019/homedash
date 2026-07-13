// HomeDash 前端：vanilla JS，单页家庭管理 Tab

const API = {
  devices: '/api/devices',
  deviceStatus: '/api/devices/status',
  deviceOn: (name) => `/api/devices/${encodeURIComponent(name)}/on`,
  deviceOff: (name) => `/api/devices/${encodeURIComponent(name)}/off`,
  deviceVisibility: (name) => `/api/devices/${encodeURIComponent(name)}/visibility`,
  uptime: '/api/uptime/status',
  items: '/api/items',
  item: (id) => `/api/items/${id}`,
  itemUsage: (id) => `/api/items/${id}/usage`,
  itemPurchase: (id) => `/api/items/${id}/purchase`,
  itemHistory: (id) => `/api/items/${id}/history`,
  predictions: '/api/items/predictions',
  todos: (status = 'open') => `/api/todos?status=${status}`,
  todo: (id) => `/api/todos/${id}`,
  todoDone: (id) => `/api/todos/${id}/done`,
  todoReopen: (id) => `/api/todos/${id}/reopen`,
  aiParse: '/api/ai/parse',
  aiApply: '/api/ai/apply',
};

const TYPE_GROUPS = [
  { key: 'light', label: '灯光', icon: '💡' },
  { key: 'airconditioner', label: '空调', icon: '❄️' },
  { key: 'airpurifier', label: '空气净化器', icon: '🌬️' },
  { key: 'plug', label: '插座', icon: '🔌' },
  { key: 'camera', label: '摄像头', icon: '📷' },
  { key: 'cooker', label: '厨电', icon: '🍳' },
  { key: 'kettle', label: '厨电', icon: '🍳' },
  { key: 'waterpuri', label: '厨电', icon: '🍳' },
  { key: 'feeder', label: '宠物', icon: '🐱' },
  { key: 'petwaterer', label: '宠物', icon: '🐱' },
  { key: 'speaker', label: '音箱', icon: '🔊' },
];

const TYPE_FALLBACK = { key: 'other', label: '其他', icon: '📦' };

let currentTab = 'devices';
let devicesData = [];
let deviceStatusMap = {}; // name -> status
let autoRefreshTimer = null;
let todoStatus = 'open';
let aiActions = [];
let aiConfidence = 'low';

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
  return new Date().toISOString().split('T')[0];
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
  if (tab === 'devices') loadDevices();
  if (tab === 'uptime') loadUptime();
  if (tab === 'items') loadItems();
  if (tab === 'todos') loadTodos();
  if (tab === 'ai') renderAiWorkbench();
}

function initTabs() {
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
}

// ============ 设备 Tab ============

function getGroupInfo(type) {
  const t = String(type).toLowerCase();
  const found = TYPE_GROUPS.find((g) => g.key === t);
  if (found) return found;
  if (['cooker', 'kettle', 'waterpuri'].includes(t)) return TYPE_GROUPS.find((g) => g.key === 'cooker');
  if (['feeder', 'petwaterer'].includes(t)) return TYPE_GROUPS.find((g) => g.key === 'feeder');
  return TYPE_FALLBACK;
}

function getDeviceEmoji(type) {
  return getGroupInfo(type).icon;
}

async function toggleDevice(name, turnOn, inputEl) {
  if (inputEl) inputEl.disabled = true;
  const url = turnOn ? API.deviceOn(name) : API.deviceOff(name);
  const { ok, data } = await fetchJSON(url, { method: 'POST' });
  if (ok) {
    toast(`${name} 已${turnOn ? '开启' : '关闭'}`, 'success');
    if (!deviceStatusMap[name]) deviceStatusMap[name] = { name };
    deviceStatusMap[name].online = true;
    deviceStatusMap[name].power = turnOn ? 'on' : 'off';
    renderDevices();
  } else {
    if (inputEl) {
      inputEl.checked = !turnOn; // 回滚开关
      inputEl.disabled = false;
    }
    toast(data?.detail || `${name} 操作失败`, 'error');
  }
}

function isPowerOn(power) {
  return power === true || power === 'on' || power === 1 || power === '1' || power === 'true';
}

function renderDeviceCard(dev) {
  const status = deviceStatusMap[dev.name];
  const online = status?.online;
  const powerOn = isPowerOn(status?.power);
  const noHost = !dev.host;
  const isCloud = dev.did && noHost;  // BLE Mesh 设备走云端
  const statusText = online === true ? '在线' : (online === false ? '离线' : '状态未知');
  const badge = isCloud ? '<span class="badge badge-cloud">云端</span>' :
    (noHost ? '<span class="badge badge-warn">无 IP</span>' : '');
  const disabled = noHost && !isCloud;
  const tileClass = [
    'device-tile',
    powerOn ? 'on' : 'off',
    online === false ? 'offline' : '',
  ].filter(Boolean).join(' ');

  const updated = status?.updated_at ? ` · 更新 ${status.updated_at.slice(11, 16)}` : '';
  const error = status?.error ? `<div class="device-error">${status.error}</div>` : '';

  return `
    <div class="${tileClass}" data-name="${dev.name}">
      <div class="device-tile-top">
        <div class="device-icon ${powerOn ? 'on' : ''}">${getDeviceEmoji(dev.type)}</div>
        <label class="switch" title="${disabled ? '不可控' : (powerOn ? '关闭' : '开启')}">
          <input type="checkbox" class="power-switch" data-name="${dev.name}"
            ${powerOn ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
          <span class="slider"></span>
        </label>
      </div>
      <div>
        <div class="device-name">${dev.name}</div>
        <div class="device-meta">
          <span class="status-dot ${online === true ? 'up' : (online === false ? 'down' : 'unknown')}"></span>
          ${statusText}${updated}
          ${badge}
        </div>
        ${error}
      </div>
    </div>`;
}

function renderDevices() {
  const container = document.getElementById('tab-devices');
  if (!devicesData.length) {
    container.innerHTML = `
      <div class="toolbar">
        <button class="btn" id="manage-devices-btn">管理设备</button>
      </div>
      <div class="empty-state">
        暂无可见设备，请在「管理设备」中恢复，或编辑 config/devices.yaml
      </div>`;
    bindDeviceManager();
    return;
  }

  // 按组分类
  const groups = {};
  devicesData.forEach((dev) => {
    const info = getGroupInfo(dev.type);
    if (!groups[info.key]) groups[info.key] = { info, items: [] };
    groups[info.key].items.push(dev);
  });

  // 保持分组顺序
  const orderedKeys = ['light', 'airconditioner', 'airpurifier', 'plug', 'camera', 'cooker', 'feeder', 'speaker', 'other'];
  const sortedKeys = orderedKeys.filter((k) => groups[k]).concat(Object.keys(groups).filter((k) => !orderedKeys.includes(k)));

  let html = `
    <div class="toolbar">
      <button class="btn" id="manage-devices-btn">管理设备</button>
      <button class="btn" id="refresh-status-btn">刷新状态</button>
    </div>`;

  sortedKeys.forEach((key) => {
    const g = groups[key];
    html += `
      <div class="group">
        <div class="group-title">${g.info.icon} ${g.info.label} · ${g.items.length}</div>
        <div class="device-grid">
          ${g.items.map(renderDeviceCard).join('')}
        </div>
      </div>`;
  });

  container.innerHTML = html;
  bindDeviceEvents();
  bindDeviceManager();
  document.getElementById('refresh-status-btn')?.addEventListener('click', refreshDeviceStatus);
}

function bindDeviceEvents() {
  document.querySelectorAll('#tab-devices .power-switch').forEach((input) => {
    input.addEventListener('change', (e) => {
      const name = e.target.dataset.name;
      toggleDevice(name, e.target.checked, e.target);
    });
  });

}

function bindDeviceManager() {
  document.getElementById('manage-devices-btn')?.addEventListener('click', showDeviceManager);
}

async function refreshDeviceStatus() {
  const container = document.getElementById('tab-devices');
  const btn = document.getElementById('refresh-status-btn');
  if (btn) btn.disabled = true;
  const { ok, status, data } = await fetchJSON(API.deviceStatus);
  if (btn) btn.disabled = false;
  if (status === 404) {
    toast('设备状态查询功能开发中', 'info');
    return;
  }
  if (!ok) {
    toast(data?.detail || '刷新状态失败', 'error');
    return;
  }
  deviceStatusMap = {};
  (data || []).forEach((s) => { deviceStatusMap[s.name] = s; });
  renderDevices();
}

async function loadDevices() {
  const container = document.getElementById('tab-devices');
  container.innerHTML = '<div class="loading">加载设备中...</div>';
  const [listRes, statusRes] = await Promise.all([
    fetchJSON(API.devices),
    fetchJSON(API.deviceStatus).catch(() => ({ ok: false, status: 404 })),
  ]);

  if (!listRes.ok) {
    container.innerHTML = `<div class="empty-state">设备列表加载失败：${listRes.data?.detail || '未知错误'}</div>`;
    return;
  }

  devicesData = listRes.data || [];
  if (statusRes.status === 404) {
    toast('设备状态查询功能开发中', 'info');
  } else if (statusRes.ok) {
    deviceStatusMap = {};
    (statusRes.data || []).forEach((s) => { deviceStatusMap[s.name] = s; });
  }
  renderDevices();
}

async function showDeviceManager() {
  const { ok, data } = await fetchJSON(`${API.devices}?include_hidden=true`);
  if (!ok) { toast(data?.detail || '设备列表加载失败', 'error'); return; }
  showModal(`
    <div class="modal-content">
      <div class="modal-header"><div class="modal-title">管理设备展示</div><button class="close-btn">&times;</button></div>
      <p class="device-manager-help">隐藏只影响 HomeDash 页面，不会删除设备或修改配置。</p>
      <div class="device-manager-list">${(data || []).map((device) => `
        <div class="device-manager-row"><span>${device.name}</span><button class="btn btn-small device-visibility" data-name="${device.name}" data-hidden="${device.hidden}">${device.hidden ? '恢复显示' : '隐藏'}</button></div>
      `).join('') || '<div class="empty-state">未配置设备</div>'}</div>
    </div>`);
  bindModalClose();
  document.querySelectorAll('.device-visibility').forEach((button) => button.addEventListener('click', () => setDeviceVisibility(button.dataset.name, button.dataset.hidden !== 'true')));
}

async function setDeviceVisibility(name, hidden) {
  const { ok, data } = await fetchJSON(API.deviceVisibility(name), { method: 'PUT', body: JSON.stringify({ hidden }) });
  if (!ok) { toast(data?.detail || '更新设备展示失败', 'error'); return; }
  toast(hidden ? `${name} 已隐藏` : `${name} 已恢复显示`, 'success');
  closeModal();
  loadDevices();
}

// ============ 监控 Tab ============

function renderUptime(res) {
  const container = document.getElementById('tab-uptime');
  if (!res.available || res.source === 'unavailable') {
    container.innerHTML = '<div class="empty-state">Uptime Kuma 数据库未连接，请检查 KUMA_DB_PATH 配置</div>';
    return;
  }
  const monitors = res.monitors || [];
  if (!monitors.length) {
    container.innerHTML = '<div class="empty-state">暂无监控数据</div>';
    return;
  }
  container.innerHTML = `
    <div class="card">
      ${monitors.map((m) => {
        const up = m.status === 1;
        return `
          <div class="monitor-row" title="${m.msg || ''}">
            <span class="status-dot ${up ? 'up' : 'down'}"></span>
            <span style="flex:1;">${m.name}</span>
            <span class="badge ${up ? 'badge-ok' : 'badge-danger'} badge-outline">${up ? 'UP' : 'DOWN'}</span>
            <span style="width:70px;text-align:right;color:var(--muted);font-size:0.85rem;">${up && m.ping ? m.ping + 'ms' : '—'}</span>
          </div>`;
      }).join('')}
    </div>`;
}

async function loadUptime() {
  const container = document.getElementById('tab-uptime');
  container.innerHTML = '<div class="loading">加载监控中...</div>';
  const { ok, data } = await fetchJSON(API.uptime);
  if (!ok) {
    container.innerHTML = `<div class="empty-state">监控加载失败：${data?.detail || '未知错误'}</div>`;
    return;
  }
  renderUptime(data);
}

// ============ 日用品 Tab ============

function getBadge(item) {
  const pred = item.prediction || {};
  if (pred.need_buy) return '<span class="badge badge-danger">紧急</span>';
  const days = pred.days_until_empty;
  if (days !== null && days < 14) return '<span class="badge badge-warn">偏低</span>';
  return '<span class="badge badge-ok">充足</span>';
}

function renderItemCard(item) {
  const p = item.prediction || {};
  const days = p.days_until_empty;
  const daysText = days === null || days === undefined ? '—' : `${Math.floor(days)} 天`;
  const suggest = p.need_buy ? `建议 ${p.suggested_qty} ${item.unit || '个'}` : '';
  return `
    <div class="item-card" data-id="${item.id}">
      <div class="item-info">
        <div class="item-name">${item.name} ${getBadge(item)}</div>
        <div class="item-meta">${item.category || '未分类'} · 剩余 ${fmtNumber(item.current_stock)} ${item.unit || '个'}</div>
      </div>
      <div class="item-tags">
        <span class="badge badge-outline">预计 ${daysText}</span>
        ${suggest ? `<span class="badge badge-warn">${suggest}</span>` : ''}
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

function showItemForm(item = null) {
  const isEdit = !!item;
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
        <input id="item-category" value="${item?.category || ''}">
      </div>
      <div class="form-group">
        <label>单位</label>
        <input id="item-unit" value="${item?.unit || '个'}">
      </div>
      <div class="form-group">
        <label>当前库存</label>
        <input type="number" step="any" id="item-stock" value="${item?.current_stock ?? 0}">
      </div>
      <div class="form-group">
        <label>最低库存</label>
        <input type="number" step="any" id="item-min" value="${item?.min_stock ?? 1}">
      </div>
      <div class="form-actions">
        <button class="btn modal-cancel">取消</button>
        <button class="btn btn-primary" id="save-item">${isEdit ? '保存' : '添加'}</button>
      </div>
    </div>`);
  bindModalClose();
  document.getElementById('save-item').addEventListener('click', () => saveItem(item?.id));
}

async function saveItem(id) {
  const payload = {
    name: document.getElementById('item-name').value.trim(),
    category: document.getElementById('item-category').value.trim() || null,
    unit: document.getElementById('item-unit').value.trim() || '个',
    current_stock: parseFloat(document.getElementById('item-stock').value) || 0,
    min_stock: parseFloat(document.getElementById('item-min').value) || 0,
  };
  if (!payload.name) { toast('名称必填', 'error'); return; }
  const { ok, data } = await fetchJSON(id ? API.item(id) : API.items, {
    method: id ? 'PUT' : 'POST',
    body: JSON.stringify(payload),
  });
  if (ok) {
    toast(id ? '保存成功' : '添加成功', 'success');
    closeModal();
    loadItems();
  } else {
    toast(data?.detail || '操作失败', 'error');
  }
}

async function showItemDetail(id) {
  const [{ data: item }, { data: history }] = await Promise.all([
    fetchJSON(API.item(id)),
    fetchJSON(API.itemHistory(id)),
  ]);
  if (!item) { toast('物品不存在', 'error'); return; }
  const p = item.prediction || {};
  const daysText = p.days_until_empty === null ? '—' : `${Math.floor(p.days_until_empty)} 天`;
  const historyHtml = (history || []).slice().reverse().map((h) => {
    const isUsage = h.type === 'usage';
    return `
      <div class="history-item">
        <span>${isUsage ? '🔴 消耗' : '🟢 购买'} ${fmtNumber(h.amount)} ${item.unit || '个'}</span>
        <span style="color:var(--muted);font-size:0.8rem;">${fmtDate(h.at)} ${h.note || ''}</span>
      </div>`;
  }).join('') || '<div class="empty-state" style="padding:1rem;">暂无记录</div>';

  showModal(`
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title">${item.name}</div>
        <button class="close-btn">&times;</button>
      </div>
      <div style="margin-bottom:1rem;color:var(--muted);font-size:0.9rem;">
        ${item.category || '未分类'} · 剩余 ${fmtNumber(item.current_stock)} ${item.unit || '个'} · 预计 ${daysText}
      </div>
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

// ============ 重点待办 Tab ============

function todoPriorityLabel(priority) {
  return { high: '高', medium: '中', low: '低' }[priority] || '中';
}

function todoPriorityBadge(priority) {
  const cls = { high: 'badge-danger', medium: 'badge-warn', low: 'badge-ok' }[priority] || 'badge-warn';
  return `<span class="badge ${cls}">${todoPriorityLabel(priority)}</span>`;
}

function renderTodoCard(todo) {
  const reminder = todo.remind_at ? `提醒 ${fmtDate(todo.remind_at)} ${todo.remind_at.slice(11, 16)}` : '';
  const due = todo.due_date ? `截止 ${todo.due_date}` : '未设截止日';
  const meta = [due, todo.assignee, reminder].filter(Boolean).join(' · ');
  const action = todo.status === 'done'
    ? `<button class="btn btn-small todo-reopen" data-id="${todo.id}">重新打开</button>`
    : `<button class="btn btn-small todo-done" data-id="${todo.id}">完成</button>`;
  return `
    <div class="todo-card ${todo.status === 'done' ? 'done' : ''} ${todo.overdue ? 'overdue' : ''}" data-id="${todo.id}">
      <div class="todo-main">
        <div class="todo-title">${todo.title} ${todoPriorityBadge(todo.priority)} ${todo.overdue ? '<span class="badge badge-danger">已过期</span>' : ''}</div>
        <div class="todo-meta">${meta}</div>
        ${todo.note ? `<div class="todo-note">${todo.note}</div>` : ''}
      </div>
      <div class="todo-actions">
        ${action}
        <button class="btn btn-small todo-edit" data-id="${todo.id}">编辑</button>
      </div>
    </div>`;
}

function renderTodos(todos) {
  const container = document.getElementById('tab-todos');
  const title = todoStatus === 'open' ? '暂无未完成重点待办' : '暂无已完成重点待办';
  container.innerHTML = `
    <div class="toolbar">
      <button class="btn btn-primary" id="add-todo-btn">+ 添加待办</button>
      <button class="btn ${todoStatus === 'open' ? 'btn-primary' : ''}" id="show-open-todos">未完成</button>
      <button class="btn ${todoStatus === 'done' ? 'btn-primary' : ''}" id="show-done-todos">已完成</button>
    </div>
    ${todos.length ? `<div class="todo-list">${todos.map(renderTodoCard).join('')}</div>` : `<div class="empty-state">${title}</div>`}`;
  document.getElementById('add-todo-btn').addEventListener('click', () => showTodoForm());
  document.getElementById('show-open-todos').addEventListener('click', () => {
    todoStatus = 'open';
    loadTodos();
  });
  document.getElementById('show-done-todos').addEventListener('click', () => {
    todoStatus = 'done';
    loadTodos();
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
}

async function loadTodos() {
  const container = document.getElementById('tab-todos');
  container.innerHTML = '<div class="loading">加载重点待办中...</div>';
  const { ok, data } = await fetchJSON(API.todos(todoStatus));
  if (!ok) {
    container.innerHTML = `<div class="empty-state">待办加载失败：${data?.detail || '未知错误'}</div>`;
    return;
  }
  renderTodos(data || []);
}

function datetimeLocalValue(value) {
  return value ? value.slice(0, 16) : '';
}

function showTodoForm(todo = null) {
  const isEdit = !!todo;
  const channels = todo?.remind_channels || [];
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
      <div class="form-group"><label>负责人</label><input id="todo-assignee" value="${todo?.assignee || ''}" placeholder="例如：我、配偶、双方"></div>
      <div class="form-group"><label>提醒时间</label><input type="datetime-local" id="todo-remind-at" value="${datetimeLocalValue(todo?.remind_at)}"></div>
      <div class="form-group"><label>提醒频道</label>
        <div class="todo-channel-options">
          <label><input type="checkbox" name="todo-channel" value="qq" ${channels.includes('qq') ? 'checked' : ''}> QQ</label>
          <label><input type="checkbox" name="todo-channel" value="wechat" ${channels.includes('wechat') ? 'checked' : ''}> 微信</label>
          <label><input type="checkbox" name="todo-channel" value="email" ${channels.includes('email') ? 'checked' : ''}> 仅邮件周报</label>
        </div>
      </div>
      <div class="form-group"><label>重复提醒</label>
        <select id="todo-remind-repeat">
          ${[['none', '不重复'], ['once', '一次'], ['daily', '每天'], ['weekly', '每周']].map(([value, label]) => `<option value="${value}" ${(todo?.remind_repeat || 'none') === value ? 'selected' : ''}>${label}</option>`).join('')}
        </select>
      </div>
      <div class="form-actions">
        ${isEdit ? '<button class="btn" id="delete-todo-btn" style="color:var(--down);">删除</button>' : ''}
        <button class="btn modal-cancel">取消</button>
        <button class="btn btn-primary" id="save-todo">${isEdit ? '保存' : '添加'}</button>
      </div>
    </div>`);
  bindModalClose();
  document.getElementById('save-todo').addEventListener('click', () => saveTodo(todo?.id));
  document.getElementById('delete-todo-btn')?.addEventListener('click', () => deleteTodo(todo.id));
}

function todoPayload() {
  const channels = [...document.querySelectorAll('input[name="todo-channel"]:checked')].map((input) => input.value);
  return {
    title: document.getElementById('todo-title').value.trim(),
    note: document.getElementById('todo-note').value.trim() || null,
    priority: document.getElementById('todo-priority').value,
    due_date: document.getElementById('todo-due-date').value || null,
    assignee: document.getElementById('todo-assignee').value.trim() || null,
    remind_at: document.getElementById('todo-remind-at').value || null,
    remind_channels: channels,
    remind_repeat: document.getElementById('todo-remind-repeat').value,
  };
}

async function saveTodo(id) {
  const payload = todoPayload();
  if (!payload.title) { toast('标题必填', 'error'); return; }
  const { ok, data } = await fetchJSON(id ? API.todo(id) : API.todos(), {
    method: id ? 'PUT' : 'POST',
    body: JSON.stringify(payload),
  });
  if (!ok) { toast(data?.detail || '保存失败', 'error'); return; }
  toast(id ? '待办已保存' : '待办已添加', 'success');
  closeModal();
  loadTodos();
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

// ============ AI 工作台 Tab ============

function actionLabel(action) {
  const labels = {
    'item.purchase': `购买 ${action.amount} ${action.unit || ''} ${action.name || ''}`,
    'item.usage': `消耗 ${action.amount} ${action.unit || ''} ${action.name || ''}`,
    'item.set_stock': `盘点 ${action.name || ''} 库存为 ${action.current_stock}`,
    'item.create': `新建物品 ${action.name || ''}`,
    'todo.create': `新建待办 ${action.title || ''}`,
    'todo.complete': `完成待办 #${action.todo_id || ''}`,
    'todo.reopen': `重开待办 #${action.todo_id || ''}`,
    'todo.update': `更新待办 #${action.todo_id || ''}`,
    'todo.delete': `删除待办 #${action.todo_id || ''}`,
    'query.need_buy': '查询需要购买的日用品',
    'query.items': `查询库存 ${action.name || ''}`,
    'query.open_todos': '查询未完成待办',
    'query.overdue_todos': '查询过期待办',
  };
  return labels[action.op] || action.op;
}

function renderAiWorkbench(message = '', results = null) {
  const container = document.getElementById('tab-ai');
  const preview = aiActions.length ? `
    <div class="ai-preview">
      <div class="section-title">操作预览</div>
      ${aiActions.map((action, index) => `<label class="ai-action"><input type="checkbox" data-index="${index}" checked> ${actionLabel(action)}</label>`).join('')}
      <div class="form-actions"><button class="btn" id="ai-clear">取消</button><button class="btn btn-primary" id="ai-apply">确认写入数据库</button></div>
    </div>` : '';
  const resultText = results ? `<pre class="ai-results">${JSON.stringify(results, null, 2)}</pre>` : '';
  container.innerHTML = `
    <div class="card ai-workbench">
      <div class="ai-chips"><button class="btn btn-small ai-chip">加 10 包方便面</button><button class="btn btn-small ai-chip">用掉 2 卷卫生纸</button><button class="btn btn-small ai-chip">新建待办换滤芯</button><button class="btn btn-small ai-chip">现在有什么要买的</button></div>
      <div class="form-group"><label>用中文描述你想做什么</label><textarea id="ai-text" placeholder="例如：加 10 包方便面，并添加高优先级待办换滤芯">${message}</textarea></div>
      <div class="form-actions"><button class="btn btn-primary" id="ai-parse">生成操作预览</button></div>
      <div id="ai-response"></div>${preview}${resultText}
    </div>`;
  document.querySelectorAll('.ai-chip').forEach((button) => button.addEventListener('click', () => {
    document.getElementById('ai-text').value = button.textContent;
  }));
  document.getElementById('ai-parse').addEventListener('click', parseAi);
  document.getElementById('ai-clear')?.addEventListener('click', () => { aiActions = []; renderAiWorkbench(); });
  document.getElementById('ai-apply')?.addEventListener('click', applyAi);
}

async function parseAi() {
  const text = document.getElementById('ai-text').value.trim();
  if (!text) { toast('请输入指令', 'error'); return; }
  const { ok, data } = await fetchJSON(API.aiParse, { method: 'POST', body: JSON.stringify({ text }) });
  if (!ok) { toast(data?.detail || 'AI 解析失败', 'error'); return; }
  aiActions = data.actions || [];
  aiConfidence = data.confidence || 'low';
  renderAiWorkbench(text, data.read_results);
  const response = document.getElementById('ai-response');
  response.textContent = data.reply || '已生成操作预览。';
  response.className = 'ai-reply';
}

async function applyAi() {
  const selected = [...document.querySelectorAll('.ai-action input:checked')].map((input) => aiActions[Number(input.dataset.index)]);
  const writes = selected.filter((action) => !action.op.startsWith('query.'));
  if (!writes.length) { toast('当前只有查询操作，无需写入', 'info'); return; }
  const { ok, data } = await fetchJSON(API.aiApply, { method: 'POST', body: JSON.stringify({ actions: writes, raw_text: document.getElementById('ai-text').value.trim(), confidence: aiConfidence }) });
  if (!ok) { toast(data?.detail || '写入失败', 'error'); return; }
  aiActions = [];
  toast('AI 操作已写入', 'success');
  renderAiWorkbench('', data.results);
}

// ============ 全局刷新 ============

function initRefresh() {
  const btn = document.getElementById('refresh-btn');
  btn.addEventListener('click', () => {
    btn.disabled = true;
    setTimeout(() => (btn.disabled = false), 2000);
    if (currentTab === 'devices') loadDevices();
    if (currentTab === 'uptime') loadUptime();
    if (currentTab === 'items') loadItems();
    if (currentTab === 'todos') loadTodos();
    if (currentTab === 'ai') renderAiWorkbench();
  });
}

function initAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  autoRefreshTimer = setInterval(() => {
    if (currentTab === 'uptime') loadUptime();
  }, 60000);
}

// ============ 启动 ============

function init() {
  initTabs();
  initRefresh();
  initAutoRefresh();
  switchTab('devices');
}

document.addEventListener('DOMContentLoaded', init);
