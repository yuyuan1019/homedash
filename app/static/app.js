// HomeDash 前端：vanilla JS，单页三 Tab

const API = {
  devices: '/api/devices',
  deviceStatus: '/api/devices/status',
  deviceOn: (name) => `/api/devices/${encodeURIComponent(name)}/on`,
  deviceOff: (name) => `/api/devices/${encodeURIComponent(name)}/off`,
  deviceProps: (name) => `/api/devices/${encodeURIComponent(name)}/props`,
  deviceImport: '/api/devices/import',
  uptime: '/api/uptime/status',
  items: '/api/items',
  item: (id) => `/api/items/${id}`,
  itemUsage: (id) => `/api/items/${id}/usage`,
  itemPurchase: (id) => `/api/items/${id}/purchase`,
  itemHistory: (id) => `/api/items/${id}/history`,
  predictions: '/api/items/predictions',
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

const AC_MODES = {
  auto: '自动',
  cool: '制冷',
  heat: '加热',
  fan: '送风',
  dehumidify: '除湿',
};

const PURIFIER_MODES = {
  auto: '自动',
  silent: '静音',
  favorite: '最爱',
  idle: '待机',
};

let currentTab = 'devices';
let devicesData = [];
let deviceStatusMap = {}; // name -> status
let autoRefreshTimer = null;

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

async function toggleDevice(name, turnOn, btn) {
  btn.disabled = true;
  const url = turnOn ? API.deviceOn(name) : API.deviceOff(name);
  const { ok, data } = await fetchJSON(url, { method: 'POST' });
  btn.disabled = false;
  if (ok) {
    toast(`${name} 已${turnOn ? '开启' : '关闭'}`, 'success');
    refreshDeviceStatus();
  } else {
    toast(data?.detail || `${name} 操作失败`, 'error');
  }
}

async function setDeviceProp(name, prop, value) {
  const { ok, data } = await fetchJSON(API.deviceProps(name), {
    method: 'PUT',
    body: JSON.stringify({ [prop]: value }),
  });
  if (ok) {
    toast(`${name} ${prop} 已设为 ${value}`, 'success');
  } else if (data?.detail === 'Not Found' || data?.detail?.includes('不支持')) {
    toast('属性控制功能开发中', 'info');
  } else {
    toast(data?.detail || '设置失败', 'error');
  }
}

function renderDeviceProps(name, type, props) {
  const t = String(type).toLowerCase();
  if (t === 'light') {
    const b = props?.brightness ?? 50;
    const c = props?.color_temp ?? 4000;
    return `
      <div class="props-row">
        <label class="prop">亮度 <input type="range" min="1" max="100" value="${b}" data-prop="brightness" data-name="${name}"> <span>${b}%</span></label>
        <label class="prop">色温 <input type="range" min="2700" max="6500" step="100" value="${c}" data-prop="color_temp" data-name="${name}"> <span>${c}K</span></label>
      </div>`;
  }
  if (t === 'airconditioner') {
    const temp = props?.temperature ?? 26;
    const mode = props?.mode ?? 'auto';
    return `
      <div class="props-row">
        <label class="prop">温度 <input type="range" min="16" max="30" value="${temp}" data-prop="temperature" data-name="${name}"> <span>${temp}°C</span></label>
        <label class="prop">模式
          <select data-prop="mode" data-name="${name}">
            ${Object.entries(AC_MODES).map(([k, v]) => `<option value="${k}" ${mode === k ? 'selected' : ''}>${v}</option>`).join('')}
          </select>
        </label>
      </div>`;
  }
  if (t === 'airpurifier') {
    const level = props?.level ?? 1;
    const mode = props?.mode ?? 'auto';
    return `
      <div class="props-row">
        <label class="prop">档位 <input type="range" min="1" max="3" value="${level}" data-prop="level" data-name="${name}"> <span>${level}</span></label>
        <label class="prop">模式
          <select data-prop="mode" data-name="${name}">
            ${Object.entries(PURIFIER_MODES).map(([k, v]) => `<option value="${k}" ${mode === k ? 'selected' : ''}>${v}</option>`).join('')}
          </select>
        </label>
      </div>`;
  }
  return '';
}

function renderDeviceCard(dev) {
  const status = deviceStatusMap[dev.name];
  const online = status?.online;
  const power = status?.power;
  const noHost = !dev.host;
  const isCloud = dev.did && noHost;  // BLE Mesh 设备走云端
  const dotClass = online === true ? 'up' : (online === false ? 'down' : 'unknown');
  const statusText = online === true ? '在线' : (online === false ? '离线' : '未查询');
  const badge = isCloud ? '<span class="badge badge-ok">☁ 云端控制</span>' :
    (noHost ? '<span class="badge badge-warn">⚠ 未配置 IP</span>' : '');
  const disabled = noHost && !isCloud;

  return `
    <div class="device-card" data-name="${dev.name}">
      <div class="device-info">
        <div class="device-name">${getDeviceEmoji(dev.type)} ${dev.name}</div>
        <div class="device-meta">
          <span class="status-dot ${dotClass}"></span>${statusText}
          ${badge}
        </div>
      </div>
      <div class="device-controls">
        <button class="btn btn-small toggle-btn ${power === 'on' ? 'active' : ''}" ${disabled ? 'disabled' : ''} data-action="on" data-name="${dev.name}">开</button>
        <button class="btn btn-small toggle-btn ${power === 'off' ? 'active' : ''}" ${disabled ? 'disabled' : ''} data-action="off" data-name="${dev.name}">关</button>
      </div>
      ${!isCloud && online ? renderDeviceProps(dev.name, dev.type, status?.props || {}) : ''}
    </div>`;
}

function renderDevices() {
  const container = document.getElementById('tab-devices');
  if (!devicesData.length) {
    container.innerHTML = `
      <div class="toolbar">
        <button class="btn" id="import-btn">📥 粘贴导入</button>
      </div>
      <div class="empty-state">
        未配置设备，请点击「粘贴导入」或编辑 config/devices.yaml
      </div>`;
    bindImportBtn();
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
      <button class="btn" id="import-btn">📥 粘贴导入</button>
      <button class="btn" id="refresh-status-btn">🔄 刷新状态</button>
    </div>`;

  sortedKeys.forEach((key) => {
    const g = groups[key];
    html += `
      <div class="group">
        <div class="group-title">${g.info.icon} ${g.info.label} (${g.items.length})</div>
        ${g.items.map(renderDeviceCard).join('')}
      </div>`;
  });

  container.innerHTML = html;
  bindDeviceEvents();
  bindImportBtn();
  document.getElementById('refresh-status-btn')?.addEventListener('click', refreshDeviceStatus);
}

function bindDeviceEvents() {
  document.querySelectorAll('#tab-devices .toggle-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const name = e.target.dataset.name;
      const action = e.target.dataset.action;
      toggleDevice(name, action === 'on', e.target);
    });
  });

  document.querySelectorAll('#tab-devices input[type="range"]').forEach((input) => {
    input.addEventListener('input', (e) => {
      const label = e.target.parentElement.querySelector('span');
      let suffix = '%';
      if (e.target.dataset.prop === 'color_temp') suffix = 'K';
      if (e.target.dataset.prop === 'temperature') suffix = '°C';
      label.textContent = e.target.value + suffix;
    });
    input.addEventListener('change', (e) => {
      setDeviceProp(e.target.dataset.name, e.target.dataset.prop, parseInt(e.target.value, 10));
    });
  });

  document.querySelectorAll('#tab-devices select[data-prop]').forEach((sel) => {
    sel.addEventListener('change', (e) => {
      setDeviceProp(e.target.dataset.name, e.target.dataset.prop, e.target.value);
    });
  });
}

function bindImportBtn() {
  document.getElementById('import-btn')?.addEventListener('click', showImportModal);
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

// ============ 设备导入 Modal ============

function showImportModal() {
  showModal(`
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title">📥 粘贴导入米家设备</div>
        <button class="close-btn">&times;</button>
      </div>
      <p style="font-size:0.85rem;color:var(--muted);margin-bottom:0.8rem;">
        粘贴 Xiaomi Cloud Tokens Extractor 的输出。自动过滤 BLE 设备和子设备，只导入有 IP 的 WiFi 设备。
      </p>
      <div class="form-group">
        <textarea id="import-raw" placeholder="将 token_extractor 的输出粘贴到此处..."></textarea>
      </div>
      <div class="form-actions">
        <button class="btn modal-cancel">取消</button>
        <button class="btn btn-primary" id="confirm-import">导入</button>
      </div>
    </div>`);
  bindModalClose();
  document.getElementById('confirm-import').addEventListener('click', doImport);
}

async function doImport() {
  const raw = document.getElementById('import-raw').value.trim();
  if (!raw) { toast('请先粘贴内容', 'error'); return; }
  const btn = document.getElementById('confirm-import');
  btn.disabled = true;
  const { ok, status, data } = await fetchJSON(API.deviceImport, {
    method: 'POST',
    body: JSON.stringify({ raw }),
  });
  btn.disabled = false;
  if (status === 404) {
    toast('粘贴导入功能开发中', 'info');
    return;
  }
  if (!ok) {
    toast(data?.detail || '导入失败', 'error');
    return;
  }
  const skipped = (data.skipped_list || []).map((s) => `<li>${s.name || '未知设备'}：${s.reason || '未知原因'}</li>`).join('');
  closeModal();
  showModal(`
    <div class="modal-content">
      <div class="modal-header">
        <div class="modal-title">导入结果</div>
        <button class="close-btn">&times;</button>
      </div>
      <p>导入 ${data.imported || 0} 台，跳过 ${data.skipped || 0} 台</p>
      ${skipped ? `<details style="margin-top:0.8rem;"><summary>查看跳过列表</summary><ul style="font-size:0.85rem;color:var(--muted);">${skipped}</ul></details>` : ''}
      <div class="form-actions"><button class="btn modal-cancel">关闭</button></div>
    </div>`);
  bindModalClose();
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

// ============ 全局刷新 ============

function initRefresh() {
  const btn = document.getElementById('refresh-btn');
  btn.addEventListener('click', () => {
    btn.disabled = true;
    setTimeout(() => (btn.disabled = false), 2000);
    if (currentTab === 'devices') loadDevices();
    if (currentTab === 'uptime') loadUptime();
    if (currentTab === 'items') loadItems();
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
