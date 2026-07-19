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
  devices: '/api/devices',
  deviceStatus: '/api/devices/status',
  deviceOn: (name) => `/api/devices/${encodeURIComponent(name)}/on`,
  deviceOff: (name) => `/api/devices/${encodeURIComponent(name)}/off`,
  deviceVisibility: (name) => `/api/devices/${encodeURIComponent(name)}/visibility`,
  deviceOrder: '/api/devices/order',
  deviceTemperature: (name) => `/api/devices/${encodeURIComponent(name)}/temperature`,
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
  aiAudit: '/api/ai/audit',
  aiRevert: '/api/ai/revert',
  aiSuggestedChips: '/api/ai/suggested-chips',
  aiChat: '/api/ai/chat',
  aiItemCategory: '/api/ai/item-category',
  setupStatus: '/api/setup/status',
  setupDevices: '/api/setup/devices',
  setupDevice: (name) => `/api/setup/devices/${encodeURIComponent(name)}`,
  setupXiaomiStep1: '/api/setup/xiaomi-cloud/login-step1',
  setupXiaomiStep2: '/api/setup/xiaomi-cloud/login-step2',
  setupXiaomiTest: '/api/setup/xiaomi-cloud/test',
  setupBleDevices: '/api/setup/ble-devices',
  setupAppConfig: '/api/setup/app/config',
  setupAppSave: '/api/setup/app/save',
  setupLlmConfig: '/api/setup/llm/config',
  setupLlmSave: '/api/setup/llm/save',
  setupLlmTest: '/api/setup/llm/test',
  setupLlmModels: '/api/setup/llm/models',
  setupBraveConfig: '/api/setup/brave/config',
  setupBraveSave: '/api/setup/brave/save',
  setupBraveTest: '/api/setup/brave/test',
  setupNotifyConfig: '/api/setup/notify/config',
  setupNotifySave: '/api/setup/notify/save',
  setupNotifyTest: '/api/setup/notify/test',
  notifyTest: '/api/notify/test',
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

let currentTab = 'ai';
let devicesData = [];
let deviceStatusMap = {}; // name -> status
let autoRefreshTimer = null;
let todoStatus = 'open';
let chatMessages = [];
let setupStatusData = null;
let xiaomiLoginStateId = null;
let itemCategoryTimer = null;
let currentUser = null;
let deviceManageMode = false;
let draggedDeviceName = null;
let draggedDeviceElement = null;
let deviceOrderSaving = false;

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
  if (tab === 'setup') loadSetup();
}

function initTabs() {
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
  
  // 滑动切换 tab
  let touchStartX = 0;
  let touchStartY = 0;
  const tabOrder = ['ai', 'items', 'todos', 'uptime', 'devices'];
  
  document.addEventListener('touchstart', (e) => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
  }, { passive: true });
  
  document.addEventListener('touchend', (e) => {
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

function temperatureOptions(capability, current) {
  const options = ['<option value="">选择温度</option>'];
  for (let value = capability.min; value <= capability.max + 1e-7; value += capability.step) {
    const clean = parseFloat(value.toFixed(6));
    options.push(`<option value="${clean}" ${Number(current) === clean ? 'selected' : ''}>${clean}℃</option>`);
  }
  return options.join('');
}

function renderTemperatureControl(dev, status) {
  const capability = dev.capabilities?.temperature;
  if (!capability) return '';
  const target = Number.isFinite(Number(status?.target_temperature)) && status?.target_temperature !== null
    ? Number(status.target_temperature) : null;
  const lower = target === null ? null : parseFloat((target - capability.step).toFixed(6));
  const upper = target === null ? null : parseFloat((target + capability.step).toFixed(6));
  return `<div class="temperature-control">
    <div class="temperature-label">目标温度 <b>${target === null ? '未知' : `${target}℃`}</b></div>
    <div class="temperature-actions">
      <button class="temperature-step" data-name="${esc(dev.name)}" data-temperature="${lower ?? ''}" ${lower === null || lower < capability.min ? 'disabled' : ''}>−</button>
      <select class="temperature-select" data-name="${esc(dev.name)}" aria-label="${esc(dev.name)}目标温度">${temperatureOptions(capability, target)}</select>
      <button class="temperature-step" data-name="${esc(dev.name)}" data-temperature="${upper ?? ''}" ${upper === null || upper > capability.max ? 'disabled' : ''}>＋</button>
    </div>
  </div>`;
}

function renderDeviceCard(dev) {
  const status = deviceStatusMap[dev.name];
  const online = status?.online;
  const powerOn = isPowerOn(status?.power);
  const isCloud = dev.connection === 'cloud';
  const statusText = online === true ? '在线' : (online === false ? '离线' : '状态未知');
  const badge = isCloud ? '<span class="badge badge-cloud">云端</span>' :
    (dev.connection === 'unknown' ? '<span class="badge badge-warn">未配置连接</span>' : '');
  const disabled = dev.connection === 'unknown';
  const tileClass = [
    'device-tile',
    powerOn ? 'on' : 'off',
    online === false ? 'offline' : '',
    deviceManageMode ? 'editing' : '',
  ].filter(Boolean).join(' ');

  const updated = status?.updated_at ? ` · 更新 ${status.updated_at.slice(11, 16)}` : '';
  const error = status?.error ? `<div class="device-error">${esc(status.error)}</div>` : '';

  return `
    <div class="${tileClass}" data-name="${esc(dev.name)}" draggable="${deviceManageMode}">
      <div class="device-tile-top">
        <div class="device-icon ${powerOn ? 'on' : ''}">${getDeviceEmoji(dev.type)}</div>
        ${deviceManageMode ? `<div class="device-edit-actions">
          <button class="drag-handle" type="button" title="拖动排序" aria-label="拖动 ${esc(dev.name)}">☰</button>
          <button class="btn btn-small device-visibility" type="button" data-name="${esc(dev.name)}" data-hidden="true">隐藏</button>
        </div>` : `<label class="switch" title="${disabled ? '不可控' : (powerOn ? '关闭' : '开启')}">
          <input type="checkbox" class="power-switch" data-name="${esc(dev.name)}"
            ${powerOn ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
          <span class="slider"></span>
        </label>`}
      </div>
      <div>
        <div class="device-name">${esc(dev.name)}</div>
        <div class="device-meta">
          <span class="status-dot ${online === true ? 'up' : (online === false ? 'down' : 'unknown')}"></span>
          ${statusText}${updated}
          ${badge}
        </div>
        ${error}
        ${deviceManageMode ? '' : renderTemperatureControl(dev, status)}
      </div>
    </div>`;
}

function renderDevices() {
  const container = document.getElementById('tab-devices');
  const visible = devicesData.filter((device) => !device.hidden);
  const hidden = devicesData.filter((device) => device.hidden);
  let html = `
    <div class="toolbar">
      <button class="btn ${deviceManageMode ? 'btn-primary' : ''}" id="manage-devices-btn">${deviceManageMode ? '完成管理' : '管理设备'}</button>
      ${deviceManageMode ? '' : '<button class="btn" id="refresh-status-btn">刷新状态</button>'}
    </div>`;
  if (deviceManageMode) html += '<div class="device-manager-help">拖动任意设备调整全局顺序；隐藏不会删除设备或修改配置。</div>';
  html += visible.length
    ? `<div class="device-grid ${deviceManageMode ? 'device-sort-grid' : ''}">${visible.map(renderDeviceCard).join('')}</div>`
    : '<div class="empty-state">暂无可见设备</div>';
  if (deviceManageMode) {
    html += `<div class="hidden-devices-section">
      <div class="group-title">已隐藏设备 · ${hidden.length}</div>
      <div class="hidden-device-list">${hidden.map((device) => `<div class="hidden-device-row"><span>${getDeviceEmoji(device.type)} ${esc(device.name)}</span><button class="btn btn-small device-visibility" data-name="${esc(device.name)}" data-hidden="false">恢复显示</button></div>`).join('') || '<div class="empty-state">没有隐藏设备</div>'}</div>
    </div>`;
  }

  container.innerHTML = html;
  bindDeviceEvents();
  document.getElementById('manage-devices-btn')?.addEventListener('click', toggleDeviceManagement);
  document.getElementById('refresh-status-btn')?.addEventListener('click', refreshDeviceStatus);
}

function bindDeviceEvents() {
  document.querySelectorAll('#tab-devices .power-switch').forEach((input) => {
    input.addEventListener('change', (e) => {
      const name = e.target.dataset.name;
      toggleDevice(name, e.target.checked, e.target);
    });
  });
  document.querySelectorAll('#tab-devices .device-visibility').forEach((button) => button.addEventListener('click', () => setDeviceVisibility(button.dataset.name, button.dataset.hidden === 'true')));
  document.querySelectorAll('#tab-devices .temperature-step').forEach((button) => button.addEventListener('click', () => setDeviceTemperature(button.dataset.name, Number(button.dataset.temperature), button)));
  document.querySelectorAll('#tab-devices .temperature-select').forEach((select) => select.addEventListener('change', () => {
    if (select.value !== '') setDeviceTemperature(select.dataset.name, Number(select.value), select);
  }));
  if (deviceManageMode) bindDeviceSorting();
}

async function setDeviceTemperature(name, temperature, control) {
  if (!Number.isFinite(temperature)) return;
  control.disabled = true;
  const { ok, data } = await fetchJSON(API.deviceTemperature(name), { method: 'PUT', body: JSON.stringify({ temperature }) });
  control.disabled = false;
  if (!ok) { toast(data?.detail || `${name} 温度设置失败`, 'error'); return; }
  if (!deviceStatusMap[name]) deviceStatusMap[name] = { name };
  deviceStatusMap[name].target_temperature = data.target_temperature;
  toast(`${name} 已设为 ${data.target_temperature}℃`, 'success');
  renderDevices();
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
    fetchJSON(`${API.devices}?include_hidden=true`),
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

async function preloadDeviceStatus() {
  // 预加载设备状态，进入设备页时可立即显示
  try {
    const [listRes, statusRes] = await Promise.all([
      fetchJSON(`${API.devices}?include_hidden=true`),
      fetchJSON(API.deviceStatus).catch(() => ({ ok: false })),
    ]);
    if (listRes.ok) devicesData = listRes.data || [];
    if (statusRes.ok) {
      deviceStatusMap = {};
      (statusRes.data || []).forEach((s) => { deviceStatusMap[s.name] = s; });
    }
  } catch (e) {
    // 预加载失败不影响后续操作
  }
}

async function toggleDeviceManagement() {
  deviceManageMode = !deviceManageMode;
  if (!devicesData.length) await loadDevices();
  else renderDevices();
}

async function setDeviceVisibility(name, hidden) {
  const { ok, data } = await fetchJSON(API.deviceVisibility(name), { method: 'PUT', body: JSON.stringify({ hidden }) });
  if (!ok) { toast(data?.detail || '更新设备展示失败', 'error'); return; }
  toast(hidden ? `${name} 已隐藏` : `${name} 已恢复显示`, 'success');
  loadDevices();
}

function mergedDeviceOrder() {
  const visibleNames = [...document.querySelectorAll('#tab-devices .device-sort-grid .device-tile')].map((tile) => tile.dataset.name);
  let visibleIndex = 0;
  return devicesData.map((device) => device.hidden ? device.name : visibleNames[visibleIndex++]);
}

async function saveDeviceOrderFromDom() {
  if (deviceOrderSaving) return;
  const deviceNames = mergedDeviceOrder();
  if (deviceNames.some((name) => !name)) return;
  deviceOrderSaving = true;
  const { ok, data } = await fetchJSON(API.deviceOrder, { method: 'PUT', body: JSON.stringify({ device_names: deviceNames }) });
  deviceOrderSaving = false;
  if (!ok) {
    toast(data?.detail || '设备顺序保存失败', 'error');
    loadDevices();
    return;
  }
  const byName = Object.fromEntries(devicesData.map((device) => [device.name, device]));
  devicesData = data.device_names.map((name) => byName[name]);
  toast('设备顺序已保存', 'success');
  renderDevices();
}

function moveDraggedBefore(target, clientX, clientY) {
  const dragged = draggedDeviceElement;
  if (!dragged || !target || dragged === target) return;
  const rect = target.getBoundingClientRect();
  const after = clientY > rect.top + rect.height / 2 || (Math.abs(clientY - (rect.top + rect.height / 2)) < rect.height / 3 && clientX > rect.left + rect.width / 2);
  target.parentElement.insertBefore(dragged, after ? target.nextSibling : target);
}

function bindDeviceSorting() {
  const grid = document.querySelector('#tab-devices .device-sort-grid');
  if (!grid) return;
  grid.addEventListener('dragover', (event) => {
    event.preventDefault();
    const target = event.target.closest('.device-tile');
    if (target?.parentElement === grid) moveDraggedBefore(target, event.clientX, event.clientY);
  });
  grid.addEventListener('dragenter', (event) => {
    event.preventDefault();
    const target = event.target.closest('.device-tile');
    if (target?.parentElement === grid) moveDraggedBefore(target, event.clientX, event.clientY);
  });
  grid.addEventListener('drop', (event) => {
    event.preventDefault();
    const target = event.target.closest('.device-tile');
    if (target?.parentElement === grid) moveDraggedBefore(target, event.clientX, event.clientY);
  });
  grid.querySelectorAll('.device-tile').forEach((tile) => {
    tile.addEventListener('dragstart', (event) => {
      draggedDeviceName = tile.dataset.name;
      draggedDeviceElement = tile;
      tile.classList.add('dragging');
      event.dataTransfer.effectAllowed = 'move';
    });
    tile.addEventListener('dragend', () => {
      tile.classList.remove('dragging');
      draggedDeviceName = null;
      draggedDeviceElement = null;
      saveDeviceOrderFromDom();
    });
  });
  grid.querySelectorAll('.drag-handle').forEach((handle) => {
    let active = false;
    let timer = null;
    const finish = () => {
      clearTimeout(timer);
      if (!active) return;
      active = false;
      handle.closest('.device-tile').classList.remove('dragging');
      draggedDeviceName = null;
      draggedDeviceElement = null;
      saveDeviceOrderFromDom();
    };
    handle.addEventListener('pointerdown', (event) => {
      timer = setTimeout(() => {
        active = true;
        draggedDeviceName = handle.closest('.device-tile').dataset.name;
        draggedDeviceElement = handle.closest('.device-tile');
        draggedDeviceElement.classList.add('dragging');
        handle.setPointerCapture?.(event.pointerId);
      }, 250);
    });
    handle.addEventListener('pointermove', (event) => {
      if (!active) return;
      event.preventDefault();
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('.device-tile');
      if (target?.parentElement === grid) moveDraggedBefore(target, event.clientX, event.clientY);
    });
    handle.addEventListener('pointerup', finish);
    handle.addEventListener('pointercancel', finish);
  });
}

// ============ 监控 Tab ============

function fmtUptimeUrl(url) {
  if (!url) return '';
  return String(url).replace(/^https?:\/\//, '').replace(/\/$/, '');
}

function fmtAgo(ts) {
  if (!ts) return '—';
  const sec = Math.floor(Date.now() / 1000 - Number(ts));
  if (sec < 0 || Number.isNaN(sec)) return '—';
  if (sec < 60) return `${sec} 秒前`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

function renderUptime(res) {
  const container = document.getElementById('tab-uptime');
  const link = res.public_url ? `<a class="btn btn-primary" href="${esc(res.public_url)}" target="_blank" rel="noopener">打开 Uptime 配置</a>` : '<span class="setup-help">设置 <code>KUMA_PUBLIC_URL</code> 后可从这里跳转到 Uptime Kuma 配置页。</span>';
  const toolbar = `<div class="toolbar">${link}<button class="btn" id="refresh-uptime-btn">刷新监控</button></div>`;
  if (!res.available || res.source === 'unavailable') {
    container.innerHTML = `${toolbar}<div class="empty-state">Uptime Kuma 数据库未连接，请检查 KUMA_DB_PATH 配置</div>`;
    document.getElementById('refresh-uptime-btn')?.addEventListener('click', loadUptime);
    return;
  }
  const monitors = res.monitors || [];
  if (!monitors.length) {
    container.innerHTML = `${toolbar}<div class="empty-state">暂无监控数据</div>`;
    document.getElementById('refresh-uptime-btn')?.addEventListener('click', loadUptime);
    return;
  }

  const sorted = monitors.slice().sort((a, b) => (a.status === 1 ? 1 : -1) - (b.status === 1 ? 1 : -1));
  const total = monitors.length;
  const upCount = monitors.filter((m) => m.status === 1).length;
  const downCount = total - upCount;
  const rate = total ? Math.round((upCount / total) * 100) : 0;

  container.innerHTML = `
    ${toolbar}
    <div class="uptime-summary">
      <div class="uptime-summary-item"><div class="uptime-summary-value">${total}</div><div class="uptime-summary-label">监控总数</div></div>
      <div class="uptime-summary-item up"><div class="uptime-summary-value">${upCount}</div><div class="uptime-summary-label">在线</div></div>
      <div class="uptime-summary-item down"><div class="uptime-summary-value">${downCount}</div><div class="uptime-summary-label">离线</div></div>
      <div class="uptime-summary-item rate"><div class="uptime-summary-value">${rate}%</div><div class="uptime-summary-label">可用率</div></div>
    </div>
    <div class="uptime-grid">
      ${sorted.map((m) => {
        const up = m.status === 1;
        const url = fmtUptimeUrl(m.url);
        return `
          <div class="uptime-card ${up ? 'up' : 'down'}" title="${esc(m.msg || '')}">
            <div class="uptime-card-header">
              <div class="uptime-card-name">${esc(m.name)}</div>
              <span class="uptime-status-badge ${up ? 'up' : 'down'}">
                <span class="status-dot ${up ? 'up' : 'down'}"></span>${up ? 'UP' : 'DOWN'}
              </span>
            </div>
            ${url ? `<div class="uptime-card-url">${esc(url)}</div>` : ''}
            <div class="uptime-card-footer">
              <span class="uptime-card-ping">${up && m.ping ? `⏱ ${m.ping} ms` : '—'}</span>
              <span>${fmtAgo(m.time)}</span>
            </div>
          </div>`;
      }).join('')}
    </div>`;
  document.getElementById('refresh-uptime-btn')?.addEventListener('click', loadUptime);
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
  const place = item.location ? ` · ${esc(item.location)}` : '';
  const expiry = item.expires_at ? ` · 到期 ${esc(item.expires_at)}` : '';
  return `
    <div class="item-card" data-id="${item.id}">
      <div class="item-info">
        <div class="item-name">${esc(item.name)} ${getBadge(item)}</div>
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
        <input id="item-category" list="item-category-list" value="${item?.category || ''}">
        <datalist id="item-category-list"><option value="纸品"><option value="洗护"><option value="清洁"><option value="厨房"><option value="宠物"><option value="冷冻"><option value="药品"><option value="其他"></datalist>
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
      <div class="form-group">
        <label>存放地点</label>
        <input id="item-location" placeholder="如：卫生间 / 厨房柜 / 储物间" value="${item?.location || ''}">
      </div>
      <div class="form-group">
        <label>到期年月</label>
        <input type="month" id="item-expires" value="${item?.expires_at || ''}">
      </div>
      <div class="form-actions">
        <button class="btn modal-cancel">取消</button>
        <button class="btn btn-primary" id="save-item">${isEdit ? '保存' : '添加'}</button>
      </div>
    </div>`);
  bindModalClose();
  document.getElementById('save-item').addEventListener('click', () => saveItem(item?.id));
  if (!isEdit) document.getElementById('item-name').addEventListener('blur', suggestItemCategory);
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

async function saveItem(id) {
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
  renderTodos(data || []);
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
    if (currentTab === 'devices') loadDevices();
    if (currentTab === 'uptime') loadUptime();
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

function initAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  autoRefreshTimer = setInterval(() => {
    if (currentTab === 'uptime') loadUptime();
  }, 60000);
}

// ============ 启动 ============

function initApp() {
  document.getElementById('auth-view').classList.add('hidden');
  document.getElementById('app-shell').classList.remove('hidden');
  initTabs();
  initRefresh();
  initAccountMenu();
  initAutoRefresh();
  if (currentUser.role === 'admin') loadSetupBanner();
  preloadDeviceStatus();  // 预加载设备状态
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
  const showDeviceSetup = !(s.devices_yaml_exists && s.devices_count > 0 && s.xiaomi_cloud_status);

  container.innerHTML = `
    <div class="card">
      <div class="section-title">配置总览</div>
      <div class="setup-status-grid">
        <div class="setup-status-item">${statusText(s.devices_yaml_exists && s.devices_count > 0, `米家设备 (${s.devices_count})`)}</div>
        <div class="setup-status-item">${statusText(s.xiaomi_cloud_status, '小米云端凭据')}</div>
        <div class="setup-status-item">${statusText(s.llm_configured, 'AI 工作台 LLM')}</div>
        <div class="setup-status-item">${statusOptional(s.smtp_configured, 'SMTP 周报（可选）')}</div>
        <div class="setup-status-item">${statusOptional(s.brave_configured, 'Brave 网络搜索（可选）')}</div>
        <div class="setup-status-item">${statusOptional(s.kuma_public_url_configured, 'Uptime 跳转（可选）')}</div>
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

    <div class="card ${showDeviceSetup ? '' : 'hidden'}">
      <div class="section-title">米家设备</div>
      <div class="setup-help">
        <b>说明：</b>WiFi 设备需要 host + 32 位 token；BLE Mesh 设备需要 did（可从小米云端登录后获取）。
        <br>token 获取方式：使用 <code>miiocli discover</code> 或从米家备份中提取。
      </div>
      <details class="setup-subsection">
        <summary>查看已配置设备</summary>
        <div id="setup-device-list" class="setup-subsection"><div class="loading">加载中...</div></div>
      </details>
      <form id="setup-device-form" class="setup-form">
        <input type="hidden" id="device-edit-name">
        <div class="form-row">
          <div class="form-group"><label>名称</label><input type="text" id="device-name" placeholder="客厅灯" required></div>
          <div class="form-group"><label>类型</label><select id="device-type"><option value="light">灯</option><option value="plug">插座</option><option value="outlet"> outlet</option><option value="airconditioner">空调</option><option value="switch">开关</option><option value="airpurifier">空气净化器</option><option value="other">其他</option></select></div>
        </div>
        <div class="form-group"><label>模型 model</label><input type="text" id="device-model" placeholder="yeelink.light.lamp1"></div>
        <div class="form-row">
          <div class="form-group"><label>局域网 host（WiFi 设备）</label><input type="text" id="device-host" placeholder="192.168.1.100"></div>
          <div class="form-group"><label>token（WiFi 设备）</label><input type="text" id="device-token" placeholder="32 位十六进制" maxlength="32"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>云端 did（BLE Mesh 设备）</label><input type="text" id="device-did" placeholder="123456789"></div>
          <div class="form-group"><label>siid（可选，默认 2）</label><input type="number" id="device-siid" placeholder="2"></div>
        </div>
        <div class="form-actions"><button type="submit" class="btn btn-primary">保存设备</button><button type="button" class="btn" id="device-form-reset">重置</button></div>
      </form>
    </div>

    <div class="card ${showDeviceSetup ? '' : 'hidden'}">
      <div class="section-title">小米云端登录</div>
      <div class="setup-help">用于 BLE Mesh 设备控制。登录成功后凭据保存在 <code>data/xiaomi_cloud.json</code>，不保存密码。</div>
      <form id="setup-xiaomi-form" class="setup-form">
        <div class="form-row">
          <div class="form-group"><label>小米账号</label><input type="text" id="xiaomi-username" placeholder="手机号/邮箱"></div>
          <div class="form-group"><label>密码</label><input type="password" id="xiaomi-password" placeholder="小米密码"></div>
        </div>
        <div id="xiaomi-captcha-box" class="hidden">
          <div class="form-group"><label>验证码</label><img id="xiaomi-captcha-img" alt="验证码"><input type="text" id="xiaomi-captcha-code" placeholder="输入验证码"></div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary" id="xiaomi-login-btn">${xiaomiLoginStateId ? '提交验证码' : '登录'}</button>
          <button type="button" class="btn" id="xiaomi-test-btn">测试连接</button>
          <button type="button" class="btn" id="xiaomi-ble-btn">查看 BLE 设备</button>
        </div>
        <div id="xiaomi-login-result" class="setup-result"></div>
      </form>
      <div id="setup-ble-list" class="setup-subsection"></div>
    </div>

    <div class="card">
      <div class="section-title">监控跳转</div>
      <form id="setup-app-form" class="setup-form">
        <div class="form-group"><label>Uptime Kuma 页面地址</label><input type="text" id="kuma-public-url" placeholder="http://127.0.0.1:3001"></div>
        <div class="form-actions"><button type="submit" class="btn btn-primary">保存</button></div>
        <div id="app-config-result" class="setup-result"></div>
      </form>
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
  if (showDeviceSetup) loadDeviceList();
  loadAppConfig();
  loadLlmConfig();
  loadBraveConfig();
  loadNotifyConfig();
  loadUsers();
}

function bindSetupEvents() {
  document.getElementById('setup-device-form').addEventListener('submit', saveSetupDevice);
  document.getElementById('device-form-reset').addEventListener('click', resetDeviceForm);
  document.getElementById('setup-xiaomi-form').addEventListener('submit', submitXiaomiLogin);
  document.getElementById('xiaomi-test-btn').addEventListener('click', testXiaomiCloud);
  document.getElementById('xiaomi-ble-btn').addEventListener('click', loadBleDevices);
  document.getElementById('setup-app-form').addEventListener('submit', saveAppConfig);
  document.getElementById('setup-llm-form').addEventListener('submit', saveLlmConfig);
  document.getElementById('llm-test-only-btn').addEventListener('click', testLlmConfig);
  document.getElementById('llm-models-btn').addEventListener('click', loadLlmModels);
  document.getElementById('setup-brave-form').addEventListener('submit', saveBraveConfig);
  document.getElementById('brave-test-only-btn').addEventListener('click', testBraveConfig);
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

async function loadDeviceList() {
  const container = document.getElementById('setup-device-list');
  const { ok, data } = await fetchJSON(API.setupDevices);
  if (!ok || !data || !data.length) {
    container.innerHTML = '<div class="empty-state">暂无设备配置</div>';
    return;
  }
  container.innerHTML = `<div class="setup-list">${data.map((d) => `
    <div class="setup-list-item">
      <details class="device-config-detail">
        <summary><b>${esc(d.name)}</b> <span class="tag">${esc(d.type)}</span></summary>
        <small>model: ${esc(d.model || '—')}</small><br>
        <small>${d.host ? `host: ${esc(d.host)}` : `did: ${esc(d.did || '—')}`}</small>
        ${d.siid ? `<br><small>siid: ${esc(d.siid)}</small>` : ''}
      </details>
      <div class="setup-list-actions">
        <button class="btn btn-small" data-action="edit" data-name="${esc(d.name)}">编辑</button>
        <button class="btn btn-small btn-danger" data-action="delete" data-name="${esc(d.name)}">删除</button>
      </div>
    </div>`).join('')}</div>`;
  container.querySelectorAll('[data-action="edit"]').forEach((btn) => btn.addEventListener('click', () => editDevice(btn.dataset.name)));
  container.querySelectorAll('[data-action="delete"]').forEach((btn) => btn.addEventListener('click', () => deleteSetupDevice(btn.dataset.name)));
}

async function saveSetupDevice(e) {
  e.preventDefault();
  const payload = {
    name: document.getElementById('device-name').value.trim(),
    original_name: document.getElementById('device-edit-name').value.trim(),
    type: document.getElementById('device-type').value,
    model: document.getElementById('device-model').value.trim(),
    host: document.getElementById('device-host').value.trim(),
    token: document.getElementById('device-token').value.trim(),
    did: document.getElementById('device-did').value.trim(),
    siid: document.getElementById('device-siid').value ? parseInt(document.getElementById('device-siid').value, 10) : null,
  };
  const { ok, data } = await fetchJSON(API.setupDevices, { method: 'POST', body: JSON.stringify(payload) });
  if (!ok) { toast(data?.detail || '保存失败', 'error'); return; }
  toast('设备已保存', 'success');
  resetDeviceForm();
  await loadDeviceList();
  await refreshSetupOverview();
}

async function deleteSetupDevice(name) {
  if (!confirm(`确定删除设备「${name}」？`)) return;
  const { ok, data } = await fetchJSON(API.setupDevice(name), { method: 'DELETE' });
  if (!ok) { toast(data?.detail || '删除失败', 'error'); return; }
  toast('设备已删除', 'success');
  await loadDeviceList();
  await refreshSetupOverview();
}

function editDevice(name) {
  fetchJSON(API.setupDevices).then(({ ok, data }) => {
    if (!ok) return;
    const d = data.find((x) => x.name === name);
    if (!d) return;
    document.getElementById('device-name').value = d.name || '';
    document.getElementById('device-type').value = d.type || 'light';
    document.getElementById('device-model').value = d.model || '';
    document.getElementById('device-host').value = d.host || '';
    document.getElementById('device-token').value = d.token || '';
    document.getElementById('device-did').value = d.did || '';
    document.getElementById('device-siid').value = d.siid || '';
    document.getElementById('device-edit-name').value = d.name || '';
  });
}

function resetDeviceForm() {
  document.getElementById('setup-device-form').reset();
  document.getElementById('device-edit-name').value = '';
}

function updateXiaomiLoginButton() {
  const btn = document.getElementById('xiaomi-login-btn');
  if (btn) btn.textContent = xiaomiLoginStateId ? '提交验证码' : '登录';
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
    <div class="setup-status-item">${statusText(s.devices_yaml_exists && s.devices_count > 0, `米家设备 (${s.devices_count})`)}</div>
    <div class="setup-status-item">${statusText(s.xiaomi_cloud_status, '小米云端凭据')}</div>
    <div class="setup-status-item">${statusText(s.llm_configured, 'AI 工作台 LLM')}</div>
    <div class="setup-status-item">${statusOptional(s.smtp_configured, 'SMTP 周报（可选）')}</div>
    <div class="setup-status-item">${statusOptional(s.brave_configured, 'Brave 网络搜索（可选）')}</div>
    <div class="setup-status-item">${statusOptional(s.kuma_public_url_configured, 'Uptime 跳转（可选）')}</div>`;
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

async function submitXiaomiLogin(e) {
  e.preventDefault();
  const btn = document.getElementById('xiaomi-login-btn');
  const resultBox = document.getElementById('xiaomi-login-result');
  const captchaBox = document.getElementById('xiaomi-captcha-box');
  const captchaImg = document.getElementById('xiaomi-captcha-img');

  btn.disabled = true;
  try {
    if (xiaomiLoginStateId) {
      const { ok, data } = await fetchJSON(API.setupXiaomiStep2, {
        method: 'POST',
        body: JSON.stringify({
          state_id: xiaomiLoginStateId,
          captcha_code: document.getElementById('xiaomi-captcha-code').value.trim(),
          username: document.getElementById('xiaomi-username').value.trim(),
          password: document.getElementById('xiaomi-password').value,
        }),
      });
      if (!ok) { resultBox.textContent = data?.detail || '登录失败'; resultBox.className = 'setup-result error'; return; }
      if (data.status === 'success') {
        xiaomiLoginStateId = null;
        captchaBox.classList.add('hidden');
        resultBox.textContent = `登录成功，userId=${data.user_id}`;
        resultBox.className = 'setup-result success';
        updateXiaomiLoginButton();
        await refreshSetupOverview();
      } else if (data.status === 'captcha_required') {
        xiaomiLoginStateId = data.state_id;
        captchaImg.src = data.captcha_base64;
        captchaBox.classList.remove('hidden');
        resultBox.textContent = data.message || '需要验证码';
        resultBox.className = 'setup-result';
        updateXiaomiLoginButton();
      }
    } else {
      const { ok, data } = await fetchJSON(API.setupXiaomiStep1, {
        method: 'POST',
        body: JSON.stringify({
          username: document.getElementById('xiaomi-username').value.trim(),
          password: document.getElementById('xiaomi-password').value,
        }),
      });
      if (!ok) { resultBox.textContent = data?.detail || '登录失败'; resultBox.className = 'setup-result error'; return; }
      if (data.status === 'success') {
        resultBox.textContent = `登录成功，userId=${data.user_id}`;
        resultBox.className = 'setup-result success';
        await refreshSetupOverview();
      } else if (data.status === 'captcha_required') {
        xiaomiLoginStateId = data.state_id;
        captchaImg.src = data.captcha_base64;
        captchaBox.classList.remove('hidden');
        resultBox.textContent = data.message || '需要验证码';
        resultBox.className = 'setup-result';
        updateXiaomiLoginButton();
      }
    }
  } finally {
    btn.disabled = false;
  }
}

async function testXiaomiCloud() {
  const resultBox = document.getElementById('xiaomi-login-result');
  resultBox.textContent = '测试中...';
  const { ok, data } = await fetchJSON(API.setupXiaomiTest, { method: 'POST' });
  resultBox.textContent = data?.message || (ok ? '连接正常' : '连接失败');
  resultBox.className = `setup-result ${data?.ok ? 'success' : 'error'}`;
}

async function loadBleDevices() {
  const container = document.getElementById('setup-ble-list');
  container.innerHTML = '<div class="loading">加载中...</div>';
  const { ok, data } = await fetchJSON(API.setupBleDevices);
  if (!ok) { container.innerHTML = '<div class="empty-state">加载失败</div>'; return; }
  if (!data || !data.length) { container.innerHTML = '<div class="empty-state">暂无 BLE 设备记录，请先登录小米云端</div>'; return; }
  container.innerHTML = `<div class="setup-list">${data.map((d) => `
    <div class="setup-list-item">
      <div><b>${esc(d.name)}</b> <small>did=${esc(d.did)}</small><br><small>model=${esc(d.model)}</small></div>
      <button class="btn btn-small" data-did="${esc(d.did)}" data-name="${esc(d.name)}" data-model="${esc(d.model)}">填入</button>
    </div>`).join('')}</div>`;
  container.querySelectorAll('button[data-did]').forEach((btn) => btn.addEventListener('click', () => {
    document.getElementById('device-name').value = btn.dataset.name;
    document.getElementById('device-did').value = btn.dataset.did;
    document.getElementById('device-model').value = btn.dataset.model;
    document.getElementById('device-type').value = 'light';
    toast('已填入设备表单', 'info');
  }));
}

async function loadAppConfig() {
  const { ok, data } = await fetchJSON(API.setupAppConfig);
  if (!ok || !data) return;
  document.getElementById('kuma-public-url').value = data.kuma_public_url || '';
}

async function saveAppConfig(e) {
  e.preventDefault();
  const resultBox = document.getElementById('app-config-result');
  const payload = { kuma_public_url: document.getElementById('kuma-public-url').value.trim() };
  const { ok, data } = await fetchJSON(API.setupAppSave, { method: 'POST', body: JSON.stringify(payload) });
  if (!ok) {
    resultBox.textContent = data?.detail || '保存失败';
    resultBox.className = 'setup-result error';
    return;
  }
  resultBox.textContent = '监控跳转地址已保存';
  resultBox.className = 'setup-result success';
  await refreshSetupOverview();
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
