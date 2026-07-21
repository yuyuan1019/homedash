# 旅游/待办 代码审查修复计划（FIXPLAN）

> ✅ **状态：已完成（存档）。** 下文 11 个修复点全部落地于提交 `b17abc5`，已逐条静态核对确认在代码中。本文件保留作历史记录；权威文档见根目录 `AGENTS.md` / `DEVPLAN.md` / `README.md` / `DESIGN.md`。

> 来源：对提交 `cebfa9b`（待办17）+ `89e460b`（待办16）的多角度代码审查（10 角度 → xhigh 验证 → 补漏），共 14 条 CONFIRMED 发现，合并同根后 **11 个修复点**。每条补丁的 `old_string` 已由 checker 在当前文件中**逐字核对匹配**，`new_string` 已判定正确且完整、无回归——可按顺序直接套用。

## 套用流程
1. 按「优先级顺序」逐条套用下表补丁（每条 old→new 是精确替换，上下文已足够唯一）。
2. 全部套完后跑自检：`python -m app.modules.travel` 与 `python -m app.modules.setup`（应全绿；其中 transport-coerce / clear-amap-key 会改自检用例）。
3. 前端语法：`node --check app/static/app.js`。
4. 手动 UI 验证（见各条「验证」）。
5. 提交：建议一个 fix commit，message 如 `fix: 旅游/待办审查修复 11 项（待办16+17 回归 + 健壮性）`。

## 优先级总览

| # | 优先级 | 修复点 | 发现 | 文件 | 风险 |
|---|--------|--------|------|------|------|
| 1 | 必修 | `update-plan-clear-weather` — update_plan 目的地变化时一并清空 weather_summary/weather_source | R6 | travel.py | low |
| 2 | 必修 | `tags-fullwidth-comma` — 偏好标签支持全角逗号/顿号切分 | R7 app.js | app.js | low |
| 3 | 必修 | `todo-search-focus` — 待办搜索框逐字失焦：拆出 renderTodoList 只刷列表层 | R1 | app.js | low |
| 4 | 必修 | `amap-nondict-defense` — 高德/配置非 dict JSON 防御（R3/R4/R5） | R3 travel.py, R5 travel.py, R4 setup.py | setup.py+travel.py | low |
| 5 | 必修 | `discover-decouple` — loadTravelPlans 列表刷新与发现面板解耦（R2） | R2 | app.js | low |
| 6 | 健壮性 | `typeerror-excepts` — travel.py suggest/recommend_spots 的 except 元组补 TypeError | R9, R10 | travel.py | low |
| 7 | 健壮性 | `hours-not-none` — _compute_transport 非自驾分支 hours=0.0 被当缺失（falsy） | R11 | travel.py | low |
| 8 | 健壮性 | `transport-coerce` — DestinationSuggestion.transport 加 before-coerce：非 dict 不再丢整条候选 | R12 | travel.py | low |
| 9 | 健壮性 | `amap-tag-from-results` — amap_tag 改由实际 enrichment 结果决定，而非仅看 amap_key 是否存在 | R8 | travel.py | low |
| 10 | 打磨 | `number-finite-check` — readDiscoverRequest 用 Number.isFinite + 显式判空替换 || 默认值，避免把 0 静默改写 | R13 | app.js | low |
| 11 | 打磨 | `clear-amap-key` — 高德 Key 清空输入框清不掉已存值（_merge_amap_payload 空串回退 current） | R14 | setup.py | low |

> 必修 5 条直接影响刚上线功能（待办搜索无法连续输入、发现面板输入丢失、高德非 dict 崩溃 500、改目的地不清天气、全角逗号标签）。健壮性 4 条为低概率 500/数据不一致。打磨 2 条为小体验。

---

## 1. [必修] `update-plan-clear-weather` — update_plan 目的地变化时一并清空 weather_summary/weather_source

- R6: travel.py 的 update_plan 在 destination 变化的分支里只清了 spots_json，没清同样依赖目的地的 weather_summary/weather_source（NULL），导致新目的地旁仍显示旧天气

**风险**：low　｜　**发现编号**：R6

**补丁** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
    # 目的地变了，旧的「非网红玩法」清单也作废
    if str(prev["destination"]) != payload.destination:
        await db.execute("UPDATE travel_plans SET spots_json='[]' WHERE id=?", (plan_id,))
```

新：

```python
    # 目的地变了，旧的「非网红玩法」清单与旧天气都作废（weather 同样绑定目的地）
    if str(prev["destination"]) != payload.destination:
        await db.execute(
            "UPDATE travel_plans SET spots_json='[]', weather_summary=NULL, weather_source=NULL WHERE id=?",
            (plan_id,),
        )
```

> _destination 变化时，spots_json 和 weather_summary/weather_source 都依赖旧目的地，必须一起清空，否则新目的地旁会残留旧天气文案（R6）。复用已存在的 NULL 语义，与上方日期变化清天气的写法一致，最小改动。_

**验证**

跑模块自检：`python -m app.modules.travel`（应无报错）。手动验证：① 创建一条 travel plan（目的地 A，写入 weather_summary/weather_source，可用 PUT /travel/plans/{id}/weather 或既有流程触发）；② PUT /api/travel/plans/{id} 把 destination 改成 B；③ GET /api/travel/plans 应看到 destination=B、spots_json='[]'、weather_summary=NULL、weather_source=NULL。日期变化分支（line 334-335）保持不动，仅目的地变化时新增清天气。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

范围仅 destination 变化分支，不动日期变化分支（line 334-335 已清天气，行为正确）。与 R8（amap_tag/source 标记）、R12（DestinationSuggestion.transport 校验）等其它修复点无重叠，独立套用。旧库历史数据若 weather_source 非空且 destination 当时与现在一致，不会被误清——仅在本 PATCH 触发的目的地变化时清。

</details>

---

## 2. [必修] `tags-fullwidth-comma` — 偏好标签支持全角逗号/顿号切分

- R7 app.js:319 showTravelForm 提交时 travel-tags 用 .split(',')，全角逗号「，」(U+FF0C) 和顿号「、」不会切分，导致 "温泉，徒步、美食" 被整串存成单个 tag（数组仅 1 个元素），后续按标签筛选/展示完全失效。

**风险**：low　｜　**发现编号**：R7 app.js

**补丁** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
    const tags = document.getElementById('travel-tags').value.split(',').map((s) => s.trim()).filter(Boolean);
```

新：

```javascript
    const tags = document.getElementById('travel-tags').value.split(/[,，、]/).map((s) => s.trim()).filter(Boolean);
```

> _R7：原 .split(',') 只识别半角逗号，中文输入法默认产出的全角「，」(U+FF0C) 与顿号「、」(U+3001) 不被切分，整串被 trim 后存成单个 tag。换成正则 /[,，、]/ 同时支持半角逗号、全角逗号、顿号（与第 313 行 activities placeholder "徒步、美食、亲子" 的顿号习惯一致），后续 .map(trim).filter(Boolean) 行为不变，空段/首尾空白照旧被丢弃。_

**验证**

前端纯 JS，无对应 python -m app.modules.X 自检。手动验证：
1) uvicorn app.main:app --reload，浏览器打开「旅游」面板。
2) 新建旅游计划，在「偏好标签」输入「温泉, 自然，徒步、美食」（混用半角、全角、顿号），保存。
3) 在 DevTools Network 看该 POST /api/travel/plans 请求体 tags 字段应为 4 元素数组 [\"温泉\",\"自然\",\"徒步\",\"美食\"]；修复前为 [\"温泉, 自然，徒步、美食\"] 单元素。
4) 重新打开编辑框，确认输入框回显为半角逗号分隔（第 306 行 join(', ') 不变），且再次保存仍切分为 4 个 tag。
5) 老数据（仅含半角逗号的 tags）行为不变。"

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

范围：仅 R7。tag 解析后端为 JSON list 透传（travel.py 不再 split），无后端配套改动。
与其它修复点交互：无；本补丁只改 app.js:319 一行，与 R1（todo 搜索框失焦，app.js:1282）/ R2（loadTravelPlans 重建发现面板，app.js:452）/ R13（readDiscoverRequest Number||默认值，app.js:532）均为不同函数、不冲突。
范围外同源旧 bug（不修）：app.js:313 travel-activities 的 placeholder「徒步、美食、亲子」用顿号，但 activities 字段（payload.activities = value.trim()，行 330）整段存为单一字符串、前端从不 split，不存在本 bug；保持现状。
第 306 行 tagsStr join(', ') 是回显用的半角分隔，正好被新 split 正确识别，无需改动。"

</details>

---

## 3. [必修] `todo-search-focus` — 待办搜索框逐字失焦：拆出 renderTodoList 只刷列表层

- R1: renderTodos 在 #todo-search 的 input 事件里被调用（app.js:1282），它把整个 #tab-todos 的 innerHTML 重建一遍——包括搜索框自身（app.js:1261-1268）。每输一个字，#todo-search 被销毁重建，焦点丢失，无法连续输入。修复：拆出 renderTodoList(todos) 只刷新列表/空态子层，搜索框所在的 toolbar 不重建；input 事件改为调 renderTodoList(todosCache)。

**风险**：low　｜　**发现编号**：R1

**补丁** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
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
```

新：

```javascript
function renderTodoList(todos) {
  // 只刷新列表/空态子层，不重建 toolbar（含 #todo-search），
  // 保证搜索框 input 事件重渲染时焦点不丢失。
  const host = document.getElementById('todo-list-host');
  if (!host) return;
  const q = todoQuery.trim().toLowerCase();
  const shown = q ? todos.filter((t) => (t.title || '').toLowerCase().includes(q) || (t.note || '').toLowerCase().includes(q)) : todos;
  const emptyTitle = todoStatus === 'open' ? '暂无未完成重点待办' : '暂无已完成重点待办';
  const emptyMsg = !todos.length ? emptyTitle : '没有匹配的待办';
  host.innerHTML = shown.length ? `<div class="todo-list">${shown.map(renderTodoCard).join('')}</div>` : `<div class="empty-state">${emptyMsg}</div>`;
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

function renderTodos(todos) {
  const container = document.getElementById('tab-todos');
  container.innerHTML = `
    <div class="toolbar">
      <button class="btn btn-primary" id="add-todo-btn">+ 添加待办</button>
      <button class="btn ${todoStatus === 'open' ? 'btn-primary' : ''}" id="show-open-todos">未完成</button>
      <button class="btn ${todoStatus === 'done' ? 'btn-primary' : ''}" id="show-done-todos">已完成</button>
      <input id="todo-search" class="todo-search" type="search" placeholder="搜索标题或内容…" value="${esc(todoQuery)}">
    </div>
    <div id="todo-list-host"></div>`;
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
    renderTodoList(todosCache);  // 仅刷新列表层，不重建搜索框，避免逐字失焦
  });
  renderTodoList(todos);
}
```

> _renderTodos 原本把 #todo-search 也一起重建，input 事件里再调 renderTodos 导致每输一个字焦点即丢。拆出 renderTodoList 只刷 #todo-list-host 子层后，输入框常驻 toolbar 不被销毁；同时把列表内按钮/图片事件绑定移到 renderTodoList 内（列表重建后必须重绑），renderTodos 只在首次/状态切换时建骨架，行为（esc/筛选/空文案/切换清空）全部保留。_

**验证**

前端文件无 python -m 自检，验证以手动为主：1) `uvicorn app.main:app --reload` 启动，浏览器打开重点待办 Tab。2) 在搜索框连续输入 3-5 个字符，焦点应保持在输入框、光标不跳，列表随输入即时过滤。3) 切换「未完成/已完成」按钮：搜索框被清空、列表刷新（todoQuery='' 走 loadTodos→renderTodos 重建骨架，行为不变）。4) 清空搜索框：列表恢复全量。5) 列表项「完成/重新打开/编辑/图片放大」按钮在过滤后仍可用（事件随 renderTodoList 重绑）。6) 无匹配关键词时显示「没有匹配的待办」，列表为空时显示对应空态文案。可选：浏览器控制台无报错。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

仅前端 app/static/app.js 单文件、纯展示层重构，无 API/数据/后端改动。与其他 13 条发现无重叠（R2 travel discover 面板、R3-R14 travel.py/setup.py 后端健壮性，均不影响此处）。同源模式提醒：app.js 里 loadTravelPlans (R2) 存在相同的「重建容器吞掉子面板输入」反模式，但属另一修复点范围，本补丁不触碰。todosCache/todoQuery/todoStatus 三个全局状态变量沿用原声明，无需新增。

</details>

---

## 4. [必修] `amap-nondict-defense` — 高德/配置非 dict JSON 防御（R3/R4/R5）

- R3 travel.py:542 — /travel/suggest 里 origin_coord = await _amap_geocode(...) 的 except 元组 (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) 未含 AttributeError；当高德返回合法但非 dict JSON（限流反爬页 HTML 被 httpx 当 JSON 解析成 str/list、或 status_code<400 但 body 是数组）时，_amap_geocode 里 data.get('status') 抛 AttributeError → 直接 500，破坏「无高德降级 LLM 估算」契约。
- R5 travel.py:66 — _amap_api_key 调 cfg.get('api_key')，而 _amap_config 的 json.load 在文件被手工误改成 [1,2,3] 或 "abc" 时返回非 dict（仅 JSONDecodeError 被捕获，合法非 dict JSON 不报错）；cfg 真值非空时 .get 抛 AttributeError → /travel/suggest 等所有读 amap_key 的路由 500。
- R4 setup.py:322 — _test_amap_connection 里 data = resp.json() 后直接 data.get('status')；except 仅含 (httpx.HTTPError, ValueError)，非 dict JSON 抛 AttributeError → 500。该函数被 save_amap_config 在 _write_json 落盘之后调用，一旦抛异常前端看到 500「保存失败」但 Key 实际已写入 data/amap_config.json，状态不一致；test_amap_config 同样 500。

**风险**：low　｜　**发现编号**：R3 travel.py, R5 travel.py, R4 setup.py

**补丁 1** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
```

新：

```python
    try:
        with open(path) as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):  # 防御误改成列表/字符串等合法但非 dict JSON
            return None
        return cfg
    except (json.JSONDecodeError, OSError):
        return None
```

> _R5 根因：json.load 对合法非 dict JSON（[]、"str"、42）不抛 JSONDecodeError，原代码直接返回该值，下游 _amap_api_key 的 cfg.get(...) 即 AttributeError。在 load 边界加 isinstance 检查，使配置层始终返回 dict | None，与签名一致；env_key 分支与异常分支行为不变。_

**补丁 2** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
    data = resp.json()  # 高德非 JSON（验证码页）时抛 ValueError，由调用方捕获
    if str(data.get("status")) != "1":  # ponytail: 高德 status 是字符串 "1"
```

新：

```python
    data = resp.json()  # 高德非 JSON（验证码页）时抛 ValueError，由调用方捕获
    if not isinstance(data, dict):  # 限流反爬页等可能返回合法但非 dict JSON，按失败降级
        return None
    if str(data.get("status")) != "1":  # ponytail: 高德 status 是字符串 "1"
```

> _R3 根因防御（源头）：status_code<400 但 body 非 dict 时 data.get('status') 抛 AttributeError。在 _amap_geocode 内返回 None 即可让所有调用方（suggest 路由 origin、_compute_transport dest）统一走降级，不必每处都补 except。_

**补丁 3** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
            try:
                origin_coord = await _amap_geocode(geo_client, amap_key, payload.origin_city)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                origin_coord = None
```

新：

```python
            try:
                origin_coord = await _amap_geocode(geo_client, amap_key, payload.origin_city)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
                origin_coord = None
```

> _R3 兜底：spec ④。即使 _amap_geocode 内部未来回归或出现其他 AttributeError，suggest 路由也能把 origin_coord 置 None 后让 _compute_transport 走 LLM 估算 fallback，而非整条推荐 500。属最小增量（仅扩元组）。_

**补丁 4** — `app/modules/setup.py`

旧（当前文件中逐字存在）：

```python
def _amap_file_config() -> dict | None:
    if not os.path.isfile(AMAP_CONFIG_FILE):
        return None
    try:
        with open(AMAP_CONFIG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
```

新：

```python
def _amap_file_config() -> dict | None:
    if not os.path.isfile(AMAP_CONFIG_FILE):
        return None
    try:
        with open(AMAP_CONFIG_FILE) as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):  # 防御误改成列表/字符串等合法但非 dict JSON
            return None
        return cfg
    except (json.JSONDecodeError, OSError):
        return None
```

> _R5 setup 侧同源：_amap_config 调 file_cfg.get('api_key')，_amap_configured 调 .get，若 _amap_file_config 返回非空 list/str 即 AttributeError。在 load 边界拦截，下游三处调用（_amap_config / _amap_configured / get_amap_config 的 _amap_file_config() 真值判断）全部安全。带函数签名以保证在 setup.py 内唯一（该文件还有 4 处相同 try/except）。_

**补丁 5** — `app/modules/setup.py`

旧（当前文件中逐字存在）：

```python
        if resp.status_code != 200:
            return False, f"高德连接失败 (HTTP {resp.status_code})"
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return False, "高德连接失败，请检查网络与 Key"
    if str(data.get("status")) != "1":
```

新：

```python
        if resp.status_code != 200:
            return False, f"高德连接失败 (HTTP {resp.status_code})"
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return False, "高德连接失败，请检查网络与 Key"
    if not isinstance(data, dict):  # 限流反爬页等返回合法但非 dict JSON，避免 .get 抛 AttributeError→500
        return False, "高德返回格式异常，请检查 Key 或稍后重试"
    if str(data.get("status")) != "1":
```

> _R4 根因：_test_amap_connection 在 save_amap_config 落盘后调用，原代码非 dict 时抛 AttributeError→500，前端看到失败但 Key 已写入（状态不一致）。改为返回 (False, 中文提示) 后，save_amap_config 返回 200 + "保存成功，但高德返回格式异常..."，test_amap_config 同理，降级契约恢复。_

**验证**

1) 自检（必跑，两模块都改了）：
   - `python -m app.modules.travel` —— 走 __main__ 块（travel.py:715），覆盖 PlanIn/SuggestIn/DestinationSuggestion/SpotItem/haversine/TransportInfo 容错；本次只加 isinstance 防御，不应有断言变化。
   - `python -m app.modules.setup` —— 走 __main__ 块（setup.py:621）。
2) 手动构造非 dict 配置文件验证 R5：
   - 写 data/amap_config.json 为 `[]` 或 `\"abc\"`，确保无 AMAP_API_KEY 环境变量，调 `python -c "from app.modules.travel import _amap_api_key; print(_amap_api_key())"` 应返回 None（修复前 AttributeError）；同样 `from app.modules.setup import _amap_config, _amap_configured; print(_amap_config(), _amap_configured())` 应分别返回 {'api_key':''} 与 False。
3) 手动 mock 非 dict 响应验证 R3/R4：
   - 对 _amap_geocode：用一个 httpx.AsyncClient 的 mock 让 resp.json() 返回 \"HTML反爬页\"，断言 _amap_geocode(...) is None。
   - 对 _test_amap_connection：mock resp.json() 返回 []，断言返回 (False, '高德返回格式异常...')；调 POST /api/setup/amap/save（已登录 admin）应得 200 + tested=False，且 data/amap_config.json 已正确落盘（验证状态一致）。
4) 端到端：AMAP_API_KEY 配一个失效 Key 启动 uvicorn，POST /api/travel/suggest 带 origin_city，应正常返回 candidates 且 transport.accuracy 落到「LLM 估算/距离估算」，不出现 500。"

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

覆盖范围：5 个 patch 精确对应 R3/R4/R5 三条发现，均为「在 json 边界加 isinstance 守卫 + 一个 except 元组扩展」，对 dict 正常返回零行为变化（env 分支、JSONDecodeError 分支、status!='1' 分支均保持原语义）。
与其他修复点的交互：
- 与 R8（amap_tag 仅由 amap_key 决定，geocode 全失败仍标「高德交通时长」）同处 suggest 路由但正交——本修复只防 500，不修 source 标签；R8 需另行处理。
- 与 R9/R10（_suggest_destinations/recommend_spots 链式取值 TypeError）同源（畸形 JSON）但是 LLM 返回侧、不同函数，本修复不覆盖。
- 与 R14（_merge_amap_payload 空回退 current）同在 setup amap 链路但不同问题，本修复不改 _merge_amap_payload。
范围外同源旧 bug（未修，仅提示）：
- travel.py:_amap_driving 同样在 data=resp.json() 后直接 data.get('status')，非 dict 会 AttributeError。但其唯一调用方 _compute_transport 在 suggest 路由里被 asyncio.gather(..., return_exceptions=True) 包住，AttributeError 会作为结果被 isinstance(res, TransportInfo) 判否降级，不会 500；且本 Patch 2 只守 _amap_geocode 未守 _amap_driving。如需彻底对称，可同样给 _amap_driving 加 isinstance 守卫，但超出本修复点 spec。
- setup.py:_agent_file_config / _notify_file_config / _brave_file_config / _llm_file_config 同样模式（json.load 后直接返回），但本修复点 findings 仅 R3/R4/R5，未扩展；若后续发现 agent/brave/llm 配置被误改成非 dict，可复用本 patch 形态。
- setup.py:_fetch_llm_models 已有 isinstance(data, dict) 守卫，可作为本仓库既有正确范式参考。"

</details>

---

## 5. [必修] `discover-decouple` — loadTravelPlans 列表刷新与发现面板解耦（R2）

- R2: loadTravelPlans 整体重建 #tab-travel.innerHTML（含 renderDiscoverPanel()），导致 togglePacked / toggleSpotBooked / generateSpots / 保存行程 / 删除 / 推荐行李 成功后丢失发现面板里未点推荐的输入（出发城市/天数/人数/月份/标签），且 discoverCache 为 null 时面板被闭合。共 7 处成功回调走 loadTravelPlans()（行 335/349/369/427/440/452/473）。

**风险**：low　｜　**发现编号**：R2

**补丁 1** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
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
```

新：

```javascript
  travelPlans = data || [];
  container.innerHTML = `
    <div class="section-header"><div><h2>🧳 旅游计划</h2><p class="section-subtitle">发现小众目的地 · 规划行程 · 打包行李</p></div><div class="travel-header-actions"><button class="btn" id="travel-discover-btn">✨ 发现目的地</button><button class="btn btn-primary" id="travel-add">＋ 新建行程</button></div></div>
    ${renderDiscoverPanel()}
    <div class="section-mini-title">我的行程</div>
    <div class="travel-list"></div>`;
  document.getElementById('travel-add').addEventListener('click', () => showTravelForm());
  document.getElementById('travel-discover-btn').addEventListener('click', () => {
    const panel = document.getElementById('discover-panel');
    if (panel) { panel.open = true; document.getElementById('dc-origin')?.focus(); }
  });
  bindDiscoverEvents();
  renderTravelList();
}

// 仅重建行程列表子层（.travel-list）并重绑列表内事件，保留发现面板与其未提交输入（出发城市/天数/标签等）。
// togglePacked / toggleSpotBooked / 保存行程 / 生成玩法 成功后走这里，不再整体重建 #tab-travel。
function renderTravelList() {
  const list = document.querySelector('#tab-travel .travel-list');
  if (!list) return;  // 首次加载失败兜底分支无该节点，忽略
  list.innerHTML = travelPlans.length ? travelPlans.map(renderTravelCard).join('') : '<div class="empty">还没有行程。点上方「✨ 发现目的地」让 AI 按交通方式推荐小众去处，或「＋ 新建行程」手动添加。</div>';
  list.querySelectorAll('[data-travel-action]').forEach((btn) => btn.addEventListener('click', () => handleTravelAction(btn.dataset.travelAction, Number(btn.dataset.id))));
  list.querySelectorAll('.packing-check').forEach((box) => box.addEventListener('change', () => togglePacked(Number(box.dataset.id), Number(box.dataset.index), box.checked)));
  list.querySelectorAll('.spot-check').forEach((box) => box.addEventListener('change', () => toggleSpotBooked(Number(box.dataset.id), Number(box.dataset.index), box.checked)));
}

// 操作（勾选/生成/保存/删除）成功后只刷新列表，不动发现面板与 header
async function refreshTravelList() {
  const { ok, data } = await fetchJSON(API.travelPlans);
  if (!ok) { toast(detailMsg(data, '刷新行程失败'), 'error'); return; }
  travelPlans = data || [];
  renderTravelList();
}
```

> _从 loadTravelPlans 抽出 renderTravelList 只重建 .travel-list 子层并重绑列表事件；新增 refreshTravelList 仅做 fetch+renderTravelList，不碰发现面板与 header。loadTravelPlans 仍在首次渲染时建好骨架（header + discover panel + 空 .travel-list），随后调一次 renderTravelList 填充。失败兜底分支（只渲染新建按钮）保持不变。_

**补丁 2** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
    closeModal(); toast('旅游计划已保存', 'success'); loadTravelPlans();
```

新：

```javascript
    closeModal(); toast('旅游计划已保存', 'success'); refreshTravelList();
```

> _showTravelForm 保存成功后改调 refreshTravelList，不再摧毁发现面板的未提交输入。_

**补丁 3** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
    toast('旅游计划已删除', 'success'); return loadTravelPlans();
```

新：

```javascript
    toast('旅游计划已删除', 'success'); return refreshTravelList();
```

> _handleTravelAction delete 成功后改调 refreshTravelList。_

**补丁 4** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
      toast('行李建议已生成，可继续修改', 'success');
      return loadTravelPlans();
```

新：

```javascript
      toast('行李建议已生成，可继续修改', 'success');
      return refreshTravelList();
```

> _handleTravelAction recommend 成功后改调 refreshTravelList。_

**补丁 5** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
    closeModal(); toast('行李清单已保存', 'success'); loadTravelPlans();
```

新：

```javascript
    closeModal(); toast('行李清单已保存', 'success'); refreshTravelList();
```

> _packing-save 保存成功后改调 refreshTravelList。_

**补丁 6** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
    plan.packing_items[index].packed = !checked;  // 回滚乐观更新
    toast(detailMsg(data, '更新失败'), 'error');
  }
  loadTravelPlans();  // 成功/失败都重新拉取，以服务端为准，避免缓存与库长期不一致
```

新：

```javascript
    plan.packing_items[index].packed = !checked;  // 回滚乐观更新
    toast(detailMsg(data, '更新失败'), 'error');
  }
  refreshTravelList();  // 成功/失败都重新拉取，以服务端为准，避免缓存与库长期不一致
```

> _togglePacked 改调 refreshTravelList（原语义：成功/失败都重拉以服务端为准，仍保留）。_

**补丁 7** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
    plan.spots[index].booked = !checked;  // 回滚乐观更新
    toast(detailMsg(data, '更新失败'), 'error');
  }
  loadTravelPlans();
}
```

新：

```javascript
    plan.spots[index].booked = !checked;  // 回滚乐观更新
    toast(detailMsg(data, '更新失败'), 'error');
  }
  refreshTravelList();
}
```

> _toggleSpotBooked 改调 refreshTravelList。_

**补丁 8** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
    toast('玩法清单已生成，可勾选已安排的项目', 'success');
    return loadTravelPlans();
```

新：

```javascript
    toast('玩法清单已生成，可勾选已安排的项目', 'success');
    return refreshTravelList();
```

> _generateSpots 成功后改调 refreshTravelList。_

**验证**

前端纯静态 JS，无对应 python -m 自检。手动验证步骤：\n1. 启动 uvicorn app.main:app --reload，浏览器打开旅游计划 Tab。\n2. 展开「✨ 发现目的地」面板，在出发城市输入「成都」、天数改 5、勾选「海岛」「温泉」标签，但不要点「AI 推荐目的地」（discoverCache 此时为 null，原 bug 下面板会被闭合）。\n3. 在下方任意行程卡勾选一个行李项（togglePacked）→ 期望：列表勾选状态按服务端更新，发现面板仍展开、出发城市/天数/标签输入值原样保留。\n4. 勾选一个玩法项（toggleSpotBooked）、点重新生成行李（recommend）、点重新生成玩法（spots）、保存行李清单（packing-save）、编辑并保存行程（showTravelForm submit）、删除行程（delete）→ 每一项操作后都应只刷新 .travel-list，发现面板输入与展开状态不变。\n5. 验证首次加载兜底：临时让 GET /api/travel/plans 返回非 200（例如断网后切到旅游 Tab），确认页面只渲染「新建行程」按钮 + 错误提示，不报 JS 错误（renderTravelList 中 list 为 null 时安全 no-op）。\n6. Console 应无未捕获异常；刷新整个 Tab（切走再切回）应仍能完整加载骨架 + 列表 + 发现面板。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

范围：仅 app/static/app.js，7 处成功回调 + 1 处骨架重构。语义保持：原 togglePacked/toggleSpotBooked「成功/失败都重拉以服务端为准」的注释与行为保留（refreshTravelList 仍 fetch 后覆盖 travelPlans）；乐观回滚逻辑未改。\n与其它修复点的交互：与 R7（travel-tags 全角逗号，app.js:319）、R13（readDiscoverRequest days/travelers 把 0 改写，app.js:532）同在 app.js 但无重叠行，可叠加。\n范围外同源旧 bug：发现面板展开状态依赖 discoverCache 而非真实 DOM 状态的根因现在被规避（不再重渲染面板），但若未来又出现「重渲染发现面板」的路径仍会复发；renderDiscoverPanel 内 `<details ... ${discoverCache ? 'open' : ''}>` 这一耦合未动，留给后续清理。\n已知小代价：refreshTravelList 拉取期间不在列表区显示 loading（避免覆盖乐观更新已勾选的视觉态），与原 loadTravelPlans 的全屏 loading 不同；列表很短时无可感知差异。

</details>

---

## 6. [健壮性] `typeerror-excepts` — travel.py suggest/recommend_spots 的 except 元组补 TypeError

- R9: _suggest_destinations（/travel/suggest 调用）line 503 `_response_json(response)["choices"][0]["message"]["content"]` 在 LLM 返回畸形 choices（{choices:null}、message:null、非 list 等）时抛 TypeError，而 suggest 路由 line 529 的 except 只接 (httpx.HTTPError, KeyError, IndexError) → 漏到 500 而非 502。
- R10: recommend_spots line 604 同样的链式取值，line 619 的 except 元组同样缺 TypeError → 500。

**风险**：low　｜　**发现编号**：R9, R10

**补丁 1** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        await _safe_audit(db, raw_text=payload.origin_city, ok=False, stage="travel_suggest", error=str(exc) or exc.__class__.__name__)
        raise HTTPException(502, "模型未返回有效的目的地推荐，请稍后重试") from exc
```

新：

```python
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        await _safe_audit(db, raw_text=payload.origin_city, ok=False, stage="travel_suggest", error=str(exc) or exc.__class__.__name__)
        raise HTTPException(502, "模型未返回有效的目的地推荐，请稍后重试") from exc
```

> _覆盖 R9：LLM 返回畸形 choices（choices=None / message=None / 非下标对象）时抛 TypeError，归入 502 而非 500，与既有 KeyError/IndexError 一致。_

**补丁 2** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise HTTPException(502, "模型未返回有效的玩法清单，请稍后重试") from exc
```

新：

```python
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "模型未返回有效的玩法清单，请稍后重试") from exc
```

> _覆盖 R10：recommend_spots line 604 的链式取值同样可能抛 TypeError，归入 502 与 KeyError/IndexIndex 一致。_

**验证**

跑 `python -m app.modules.travel` 模块自检应通过（不 500、无 TypeError 逃逸）。手动验证：构造一个返回 `{\"choices\": null}` 或 `{\"choices\": [{\"message\": null}]}` 的 mock LLM 响应分别打 /travel/suggest 与 /travel/plans/{id}/spots，确认两者都回 502 中文 detail（而非 500），且 suggest 路由的 _safe_audit 落库 stage=travel_suggest ok=False 记录了 TypeError。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

只给两处 except 元组各加一个 TypeError，不改变控制流与文案，向后兼容。\n范围外同源缺口：travel.py:693 的 /recommend（行李清单）路由用同样的 `_response_json(response)[\"choices\"][0][\"message\"][\"content\"]`（line 677），其 except 元组 (httpx.HTTPError, KeyError, IndexError) 同样不含 TypeError——本修复点未改它，建议作为独立后续修复点处理以保持三处一致（修复方向相同：把 693 行的元组也加上 TypeError）。不影响 R3/R4/R5（非 dict JSON 的 .get/.json AttributeError）与本点无交互，各自独立修补。

</details>

---

## 7. [健壮性] `hours-not-none` — _compute_transport 非自驾分支 hours=0.0 被当缺失（falsy）

- R11: app/modules/travel.py _compute_transport 非自驾分支用 `round(hours, 1) if hours else None`，Python 中 0.0 为 falsy，同城/极近（km≈0）→ hours=0.0 被当缺失，duration_hours 误返回 None，但同一行 distance_km=round(km,1)=0.0 照常返回，前端呈现「时长未知·0.0km」自相矛盾。

**风险**：low　｜　**发现编号**：R11

**补丁** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
        hours = km / speed if speed else None
        return TransportInfo(mode=mode or "不限", duration_hours=round(hours, 1) if hours else None,
                             distance_km=round(km, 1), note=llm_note, accuracy="距离估算")
```

新：

```python
        hours = km / speed if speed else None
        return TransportInfo(mode=mode or "不限", duration_hours=round(hours, 1) if hours is not None else None,
                             distance_km=round(km, 1), note=llm_note, accuracy="距离估算")
```

> _把 `if hours` 改为 `if hours is not None`，让合法的 0.0 小时（同城/极近目的地）正常保留为 0.0，而不是被 falsy 判定误置为 None；只有真正算不出时长（speed=0→hours=None）时才缺失，与同行的 distance_km 行为一致，消除「时长未知·0.0km」矛盾。_

**验证**

跑 `python -m app.modules.travel` 的 __main__ 自检应全绿（含现有 _haversine_km、TransportInfo、DestinationSuggestion 断言）。本修复点对 hours=0.0 行为，可在自检块中临时加一条手工核对（不必落库）：构造 origin_coord == dest_coord（同城）使 km=0.0 → speed 非零 → hours=0.0 → 断言 round(hours,1) if hours is not None else None == 0.0（旧逻辑会得到 None）。跑完删除临时断言即可。生产路径上端到端：在 /travel/suggest 选同城/极近目的地，前端 transport 卡片不再出现「时长未知·0.0km」。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

仅改 _compute_transport 非自驾分支的一处布尔判定，未触碰签名/调用方/数据形状。自驾分支（line 446-447）直接 round(drv[\"duration_hours\"],1)，没用 falsy 短路，故不受同源缺陷影响，无需一并改。范围外同源旧 bug：travel.py 中其它链式取值/非 dict 缺口（R9 _suggest_destinations choices、R10 recommend_spots、R12 DestinationSuggestion.transport、R8 amap_tag 误标、R5 _amap_api_key、R3/R4 非 dict JSON、R6 weather_summary 残留、R7 全角逗号、R13 readDiscoverRequest 改写 0、R14 setup 清空 Key 失败、R1/R2 前端重建失焦）与本修复点无代码交集，各自独立处理。前端相关发现 R1/R2/R7/R13 不在本文件，本补丁不冲突。

</details>

---

## 8. [健壮性] `transport-coerce` — DestinationSuggestion.transport 加 before-coerce：非 dict 不再丢整条候选

- R12: DestinationSuggestion.transport 字段是受校验的 TransportInfo | None，但没有 @field_validator(mode=before)。LLM 偶发返回字符串型 transport（如 "飞机"）时 Pydantic 抛 ValidationError，调用方在 except 中 continue，导致整条候选被丢弃。

**风险**：low　｜　**发现编号**：R12

**补丁 1** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
    @field_validator("highlights", "tags", mode="before")
    @classmethod
    def _coerce_list(cls, value):
        if not isinstance(value, list):
            return []
        return [str(x).strip() for x in value if str(x).strip()][:8]


class SpotItem(BaseModel):
```

新：

```python
    @field_validator("highlights", "tags", mode="before")
    @classmethod
    def _coerce_list(cls, value):
        if not isinstance(value, list):
            return []
        return [str(x).strip() for x in value if str(x).strip()][:8]

    @field_validator("transport", mode="before")
    @classmethod
    def _coerce_transport(cls, value):
        # LLM 偶发返回字符串型 transport，非 dict 时置 None，交给后续 enrichment 重新填充
        return value if isinstance(value, dict) else None


class SpotItem(BaseModel):
```

> _给 transport 加 before-coerce，沿用同模型已有 _coerce_text/_coerce_list 写法：dict 原样透传给 TransportInfo 校验，非 dict（含字符串/数字/列表/None 缺省）一律返回 None，使候选免于被 ValidationError 整条丢弃，由后续 LLM/高德 enrichment 兜底重新填充。_

**补丁 2** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
    ds = DestinationSuggestion.model_validate({
        "name": "海螺沟", "region": "四川甘孜", "vibe": 123, "highlights": "不是列表",
        "tags": ["温泉", 7], "transport_note": None,
    })
    assert ds.vibe == "123" and ds.highlights == [] and ds.tags == ["温泉", "7"] and ds.transport_note == ""
    assert ds.transport is None
```

新：

```python
    ds = DestinationSuggestion.model_validate({
        "name": "海螺沟", "region": "四川甘孜", "vibe": 123, "highlights": "不是列表",
        "tags": ["温泉", 7], "transport_note": None, "transport": "飞机",
    })
    assert ds.vibe == "123" and ds.highlights == [] and ds.tags == ["温泉", "7"] and ds.transport_note == ""
    assert ds.transport is None, "非 dict 型 transport 应被 coerce 为 None，而非抛 ValidationError"
```

> _在已有自检 dict 里追加字符串型 transport，使原有 `ds.transport is None` 断言真正走一遍新 validator：修复前此用例会抛 ValidationError 让自检崩；修复后通过。补一句注释让回归保护意图更清晰。_

**验证**

运行 `python -m app.modules.travel`；自检末尾应打印 `travel.py 自检通过：...`。重点是用例 `DestinationSuggestion.model_validate({..., \"transport\": \"飞机\"})` 必须不抛 ValidationError 且 `ds.transport is None`——修复前这步会因 Pydantic 把字符串塞进 TransportInfo 直接 ValidationError。补一条手动复查：`python -c \"from app.modules.travel import DestinationSuggestion; print(DestinationSuggestion.model_validate({'name':'x','transport':'飞机'}).transport)\"` 应输出 `None`；传 dict `{'mode':'高铁'}` 时应正常构造 TransportInfo。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

仅 DestinationSuggestion 新增一个 before-coerce + 自检扩字段，行为对合法 dict/None 输入完全不变，只把原先会 ValidationError 的畸形输入降级为 None，由下游 enrichment（_suggest_destinations / _compute_transport 等）重新填充。与其他 travel.py 修复点（R3 _amap_geocode、R5 _amap_api_key、R8 amap_tag、R9/R10 链式取值、R11 _compute_transport 0.0 当缺失、R6 weather_summary 残留）互不重叠，可独立合入。范围外同源旧 bug：R11（travel.py:453 `if hours else None` 把 0.0 时长误判为缺失）位于 _compute_transport，与本点同属 transport 鲁棒性主题但函数不同，未在此处理。

</details>

---

## 9. [健壮性] `amap-tag-from-results` — amap_tag 改由实际 enrichment 结果决定，而非仅看 amap_key 是否存在

- R8: travel.py:536 amap_tag = "高德交通时长" if amap_key else "LLM 交通估算" 在 gather 之前、仅凭 amap_key 是否存在判定。当 amap_key 已配置但出发城市 geocode 失败（origin_coord=None）时，_compute_transport 对所有候选都返回 accuracy='LLM 估算'，但 source 仍声称「高德交通时长」，向用户撒谎。

**风险**：low　｜　**发现编号**：R8

**补丁** — `app/modules/travel.py`

旧（当前文件中逐字存在）：

```python
    # 高德交通时长 enrichment：geocode 出发城市一次，并发算各候选
    amap_tag = "高德交通时长" if amap_key else "LLM 交通估算"
    async with httpx.AsyncClient(timeout=15.0) as geo_client:
        origin_coord = None
        if amap_key:
            try:
                origin_coord = await _amap_geocode(geo_client, amap_key, payload.origin_city)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                origin_coord = None
        results = await asyncio.gather(*[
            _compute_transport(geo_client, amap_key, origin_coord, c.get("name") or "",
                               c.get("region") or "", payload.transport_mode, c.get("transport_note") or "")
            for c in candidates
        ], return_exceptions=True)
    for cand, res in zip(candidates, results):
        info = res if isinstance(res, TransportInfo) else TransportInfo(mode=payload.transport_mode, accuracy="LLM 估算")
        cand["transport"] = info.model_dump()
    source = " + ".join([llm_source, amap_tag])
```

新：

```python
    # 高德交通时长 enrichment：geocode 出发城市一次，并发算各候选
    async with httpx.AsyncClient(timeout=15.0) as geo_client:
        origin_coord = None
        if amap_key:
            try:
                origin_coord = await _amap_geocode(geo_client, amap_key, payload.origin_city)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                origin_coord = None
        results = await asyncio.gather(*[
            _compute_transport(geo_client, amap_key, origin_coord, c.get("name") or "",
                               c.get("region") or "", payload.transport_mode, c.get("transport_note") or "")
            for c in candidates
        ], return_exceptions=True)
    for cand, res in zip(candidates, results):
        info = res if isinstance(res, TransportInfo) else TransportInfo(mode=payload.transport_mode, accuracy="LLM 估算")
        cand["transport"] = info.model_dump()
    # amap_tag 由实际结果决定（R8）：origin_coord=None 或所有 geocode 失败时，候选全降级为 LLM 估算，
    # 不能仅凭 amap_key 存在就声称「高德交通时长」。任一候选拿到高德精确/坐标距离估算才算命中高德数据。
    amap_tag = "高德交通时长" if any(
        (c.get("transport") or {}).get("accuracy") in ("高德精确", "距离估算") for c in candidates
    ) else "LLM 交通估算"
    source = " + ".join([llm_source, amap_tag])
```

> _把 amap_tag 的判定从 gather 前（仅看 key 是否存在）挪到 gather 后（看候选 transport.accuracy 的实际值）。origin_coord=None 时 _compute_transport 全返回 accuracy='LLM 估算'，any(...) 为 False，amap_tag 正确降级为 'LLM 交通估算'；只要有一个候选走到 '高德精确'（自驾 driving 命中）或 '距离估算'（高铁/飞机/不限 + 目的地 geocode 命中 + haversine），就保留 '高德交通时长'。检查同时覆盖 '高德精确' 与 '距离估算'，因为两者都消费了 amap geocode 数据；只查 '高德精确' 会导致非自驾模式即便 amap 实际生效也被误标 LLM。c.get('transport') or {} 防御 transport 字段缺失的极端候选。_

**验证**

跑 `python -m app.modules.travel` 自检，确认现有断言（含 TransportInfo 默认 accuracy='LLM 估算'、DestinationSuggestion 容错、haversine 等）全过、无回归。本修复是 source 标签字符串的逻辑变更，自检未直接覆盖 suggest 全链路（需 LLM/amap mock），需配合代码审视：构造 origin_coord=None 的场景（例如 amap_key 配了但出发城市 geocode 失败）→ 所有候选 transport.accuracy='LLM 估算' → source 应为 'LLM + LLM 交通估算' 而非 'LLM + 高德交通时长'。手动核验路径：临时在 _amap_geocode 首行 `return None` 后调 /api/travel/suggest，观察响应 source 字段。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

本修复独立于其他发现：R9/R10（_suggest_destinations / recommend_spots 链式取值 TypeError）、R11（_compute_transport hours=0.0 被当缺失）、R12（DestinationSuggestion.transport 非 dict 整条丢弃）、R3/R4/R5（amap 相关非 dict JSON AttributeError）都在不同函数/不同路径，互不冲突，可并行落地。R11 若修，duration_hours 会正确保留 0.0，但 accuracy 仍为 '距离估算'，不影响本判定。R12 若修，非 dict transport 会被兜底成 TransportInfo 而非丢候选，本处的 (c.get('transport') or {}) 防御已兼容空值。范围外同源旧 bug：recommend_spots (travel.py:631) 的 source='Brave 网络搜索 + LLM' 同样基于 web_results 是否非空而非实际是否被 LLM 采纳，但语义上 Brave 检索成功即为「联网」，不算撒谎，本修复不扩展到该处。

</details>

---

## 10. [打磨] `number-finite-check` — readDiscoverRequest 用 Number.isFinite + 显式判空替换 || 默认值，避免把 0 静默改写

- R13: app/static/app.js:532-533 readDiscoverRequest 的 days/travelers 用 `Number(...) || 3` / `|| 2`，因为 0 在 JS 里是 falsy，用户在天数/人数输入框填 0 时会被静默替换成默认值 3/2；HTML input 的 min=1 只是浏览器软提示，无法阻止提交 0。修复方向：显式判空——`const v = Number(el.value); return Number.isFinite(v) && v >= 1 ? v : 默认`（days 默认 3、travelers 默认 2）。

**风险**：low　｜　**发现编号**：R13

**补丁** — `app/static/app.js`

旧（当前文件中逐字存在）：

```javascript
  const monthVal = document.getElementById('dc-month').value.trim();
  return {
    origin_city: document.getElementById('dc-origin').value.trim(),
    transport_mode: document.getElementById('dc-transport').value,
    days: Number(document.getElementById('dc-days').value) || 3,
    travelers: Number(document.getElementById('dc-people').value) || 2,
```

新：

```javascript
  const monthVal = document.getElementById('dc-month').value.trim();
  const daysVal = Number(document.getElementById('dc-days').value);
  const travelersVal = Number(document.getElementById('dc-people').value);
  return {
    origin_city: document.getElementById('dc-origin').value.trim(),
    transport_mode: document.getElementById('dc-transport').value,
    days: Number.isFinite(daysVal) && daysVal >= 1 ? daysVal : 3,
    travelers: Number.isFinite(travelersVal) && travelersVal >= 1 ? travelersVal : 2,
```

> _Number.isFinite(v) && v >= 1 同时覆盖三种坏值：空串/空白（Number('') === 0，被 >= 1 拦下，回退默认）、非数字文本（Number('abc') === NaN，被 isFinite 拦下）、以及原本被静默改写的 0；合法值 1/2/3… 原样保留。对 0 不再静默改写，符合 R13 的修复方向；default 3/2 与旧逻辑保持一致，不改变其它字段行为。_

**验证**

前端 JS 无 python -m 自检。手动验证（浏览器开 http://127.0.0.1:8000 → 旅游 Tab → 发现面板）：
1) 天数输入框清空 → 提交 → 请求体 days 应为 3（默认回退）。
2) 天数输入 0 → 提交 → days 应为 3（旧逻辑也是 3，但旧是“0 || 3”静默改写，新是显式判空回退，行为等价、语义正确）。
3) 天数输入 1/2/5 → days 应原样为 1/2/5（关键回归点：旧代码同样保留，确认未回归）。
4) 天数输入 abc → days 应为 3（NaN 回退）。
5) 人数同理验证 0→2、1→1、空→2。
可选控制台一行核验：`(({a:b}=readDiscoverRequest()))=>{}` 不便调用时，直接在 DevTools Network 面板看 /api/travel/discover 请求 payload 的 days/travelers 字段。
前端无构建步骤，刷新页面即可生效。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

范围仅 readDiscoverRequest 的 days/travelers 两个字段（R13 指定范围）。同函数内 month 字段使用 `monthVal ? Number(monthVal) : null`——空串回退 null 是预期（month 可空），但若用户输入 '0' 会得到 month=0，月份 1-12 语义上不合法；这属于同源旧 bug 但不在 R13 范围内，未一并修，避免扩大改动面。另 app.js 中 `req.days || 3` / `req.travelers || 2`（HTML input value 默认值，第 500-501 行）同样是 || 对 0 不友好的同源写法，但那里只是回填表单初值、不参与提交逻辑，且用户重新输入会走 readDiscoverRequest 的修复路径，故未改。与其他修复点（R1-R12, R14）无交互，本补丁只动 app.js 的 readDiscoverRequest 函数体。"

</details>

---

## 11. [打磨] `clear-amap-key` — 高德 Key 清空输入框清不掉已存值（_merge_amap_payload 空串回退 current）

- R14: app/modules/setup.py:399 _merge_amap_payload 中 `if not api_key or _masked(api_key)` 把空串提交与掩码提交都当作“保留 current.api_key”，导致用户清空输入框保存时，空串触发回退，再被 _write_json 原样写回（实际走 save_amap_config 的 if api_key 分支重写文件），清空输入框清不掉已存 Key。

**风险**：low　｜　**发现编号**：R14

**补丁 1** — `app/modules/setup.py`

旧（当前文件中逐字存在）：

```python
def _merge_amap_payload(payload: AmapConfigIn) -> dict:
    current = _amap_config()
    api_key = payload.api_key.strip()
    if not api_key or _masked(api_key):
        api_key = current.get("api_key", "")
    return {"api_key": api_key}
```

新：

```python
def _merge_amap_payload(payload: AmapConfigIn) -> dict:
    current = _amap_config()
    api_key = payload.api_key.strip()
    if _masked(api_key):
        # 仅掩码占位才保留已存 Key；空串=用户主动清除（交由 save 路径删文件）
        api_key = current.get("api_key", "")
    return {"api_key": api_key}
```

> _区分两种“非新值”提交：含 * 的掩码串=前端回显占位→保留 current；空串=用户主动清空→不再回退，保持空串流入 save_amap_config，由既有 `elif os.path.isfile(AMAP_CONFIG_FILE): os.remove(...)` 分支真正删除配置文件。_masked("") = ("*" in "") = False，空串不再误触回退。_

**补丁 2** — `app/modules/setup.py`

旧（当前文件中逐字存在）：

```python
        _write_json(AMAP_CONFIG_FILE, {"api_key": "amap-test"})
        assert _amap_file_config()["api_key"] == "amap-test"
```

新：

```python
        _write_json(AMAP_CONFIG_FILE, {"api_key": "amap-test"})
        assert _amap_file_config()["api_key"] == "amap-test"
        # 清空提交=真正清除，掩码提交=保留已存，新值=覆盖
        assert _merge_amap_payload(AmapConfigIn(api_key=""))["api_key"] == ""
        assert _merge_amap_payload(AmapConfigIn(api_key="amap****"))["api_key"] == "amap-test"
        assert _merge_amap_payload(AmapConfigIn(api_key="new-key"))["api_key"] == "new-key"
```

> _为本次行为变更补上 __main__ 自检断言，锁定三种语义（清空/掩码/覆盖），防止后续重构回退成旧 bug。前提：自检环境未设 AMAP_API_KEY 环境变量（env 优先会覆盖文件 current）。_

**验证**

跑 `python -m app.modules.setup`（改了 setup.py 必跑的自检）。新增三条断言直接覆盖修复点：空串→\"\"、掩码→保留 amap-test、新值→new-key。自检通过即说明三种语义正确。\n\n手动复核（可选）：\n1) 启动 uvicorn，设置页先保存一个高德 Key（如 test-key），刷新页面看到输入框显示掩码。\n2) 清空输入框 → 点保存 → 应返回“保存成功，但高德 Key 未配置”，且 data/amap_config.json 被删除（不再含旧 Key）。\n3) 刷新页面，输入框为空、概览徽章变为“未配置”。\n4) 再次填新 Key 保存 → 正常写入并测试通过；填掩码串（如 aaaa****）保存 → 保留旧值不丢。

<details><summary>备注（交互 / 范围外同源旧 bug）</summary>

范围：仅改 setup.py 后端 _merge_amap_payload。app/static/app.js 无需改动——前端 saveAmapConfig 已通过 `.value.trim()` 正确发送空串（line 2530），保存后调用 refreshSetupOverview() 刷新徽章（line 2540）；本 bug 纯属后端把空串误判为“保留”。\n\n与其他修复点交互：与 R4（setup.py:322 _test_amap_connection 非 dict JSON 崩溃）同文件但不同函数，互不影响；本修复不触碰 _test_amap_connection / _amap_config / _mask / _masked。\n\n同源范围外旧 bug（不在本修复点，已知但不动）：_merge_brave_payload（setup.py:391-396）与 _merge_llm_payload（351-364 api_key）/ _merge_notify_payload（367-388 smtp_password）都是同一种 `if not x or _masked(x)` 模式，brave_key/smtp_password 同样清空不掉。任务说明已明确 brave 属范围外；如未来要统一修，应对 brave/llm/notify 三个 merge 函数做同样“仅掩码才保留”的改造，并各自补 __main__ 断言。\n\n行为副作用（改善而非回归）：test_amap_config（setup.py:541）此前对空输入会静默测试已存 Key，修复后明确返回“高德 Key 不能为空”，更符合用户预期，且与 test_brave_config 的空校验语义一致。"}

</details>

---

## 套用核对清单

- [ ] 1. `update-plan-clear-weather` (必修)
- [ ] 2. `tags-fullwidth-comma` (必修)
- [ ] 3. `todo-search-focus` (必修)
- [ ] 4. `amap-nondict-defense` (必修)
- [ ] 5. `discover-decouple` (必修)
- [ ] 6. `typeerror-excepts` (健壮性)
- [ ] 7. `hours-not-none` (健壮性)
- [ ] 8. `transport-coerce` (健壮性)
- [ ] 9. `amap-tag-from-results` (健壮性)
- [ ] 10. `number-finite-check` (打磨)
- [ ] 11. `clear-amap-key` (打磨)
- [ ] `python -m app.modules.travel` 自检通过
- [ ] `python -m app.modules.setup` 自检通过
- [ ] `node --check app/static/app.js` 通过
- [ ] 手动 UI 验证（待办搜索连续输入 / 发现面板输入不丢 / 高德降级 / 改目的地清天气 / 全角逗号标签）
- [ ] 提交 fix commit 并 push