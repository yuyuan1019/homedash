# HomeDash 前端开发计划（Phase 3 + 3.5）

> ⬜ **本文档是待办规格书，不是已完成记录。** 所有内容均未实现，供 opencode 开发使用。
>
> Phase 3：前端页面 `app/static/style.css` + `app/static/app.js`（后端 API 已就绪）
> Phase 3.5：后端新增设备状态查询、粘贴导入、属性控制端点（需改 `devices.py`）
>
> 已有 `app/static/index.html` 骨架，不要改动其结构，只补 CSS 和 JS。

## 约束

- **vanilla JS，无框架，无构建步骤**。不引入 React/Vue/Tailwind。
- **中文 UI**。所有按钮、标签、提示用中文。
- **单页应用**：三个 Tab（设备控制 / 监控状态 / 日用品），Tab 切换不刷新页面。
- **已有 HTML 骨架**：`app/static/index.html` 里已有 `<header>`、`<nav class="tabs">`、三个 `<section id="tab-*">`、`<div id="toast">`、`<div id="modal">`。JS 用这些 ID 挂载。
- 所有 API 调用走 `/api/` 前缀，同源，无 CORS 问题。
- 不新增任何依赖，不新增后端文件。

## 需要创建的文件

```
app/static/
├── index.html    ← 已有，不改动
├── style.css     ← 待创建
└── app.js        ← 待创建
```

## 后端 API 速查（开发时直接对接这些端点）

### 设备控制

| 方法 | 路径 | 请求体 | 返回 |
|------|------|--------|------|
| GET | `/api/devices` | - | `[{name, model, host, token, type}, ...]`（_inst 等下划线字段已过滤） |
| GET | `/api/devices/status` | - | `[{name, online, power, props: {...}}, ...]` 批量状态（并发查询，每台 3s 超时） |
| POST | `/api/devices/{name}/on` | - | `{name, power: "on"}` |
| POST | `/api/devices/{name}/off` | - | `{name, power: "off"}` |
| PUT | `/api/devices/{name}/props` | `{prop: value}` 如 `{"brightness": 65}` | `{name, prop, value}` |
| POST | `/api/devices/{name}/command` | `{command: str, params: []}` | `{name, result: ...}` |

注意：设备用 **name**（不是 id）操作。`/devices` 不返回状态，只返回配置。开关失败返回 503。

`/devices/status` 和 `/devices/{name}/props` 是 Phase 3.5 新增端点：
- `/devices/status`：并发查询所有设备（`asyncio.gather` + 每台 `asyncio.wait_for` 3s 超时），返回 online/power 及可控属性（亮度、温度等）。单台超时不影响其他设备。
- `/devices/{name}/props`：设置单个属性（亮度/温度/模式等），通过 type 查属性命令映射表发送。

**属性命令映射表**（`_PROP_CMDS`，与 `_POWER_CMDS` 同级）：

```python
# type -> {prop_name: (get_cmd, set_cmd, min, max, step)}
# ponytail: 按设备类型查表；新类型加一行即可
_PROP_CMDS = {
    "light": {
        "brightness":   ("get_bright", "set_bright", 1, 100, 1),
        "color_temp":   ("get_ct", "set_ct", 2700, 6500, 100),
    },
    "airconditioner": {
        "temperature":  ("get_temperature", "set_temperature", 16, 30, 1),
        "mode":         ("get_mode", "set_mode", None, ["auto", "cool", "heat", "fan", "dehumidify"]),
    },
    "airpurifier": {
        "mode":         ("get_mode", "set_mode", None, ["auto", "silent", "favorite", "idle"]),
        "level":        ("get_level", "set_level", 1, 3, 1),
    },
}
```

> 未在 `_PROP_CMDS` 中的 type 不显示滑块，只有开关按钮。前端根据 `/devices/status` 返回的 `props` 字段动态渲染控件。

### Uptime 监控

| 方法 | 路径 | 返回 |
|------|------|------|
| GET | `/api/uptime/status` | `{monitors: [{id, name, url, status, msg, ping, time}, ...], available: bool, source: "sqlite"|"unavailable"}` |

`status` 字段值：`1` 或 `2` 表示 UP，`0` 或 `3` 表示 DOWN（Kuma 的 heartbeat status：1=up, 2=seems-down, 3=down, 0=empty）。判断时 `status == 1` 算 UP，其他算 DOWN。`ping` 单位 ms。后端 60 秒缓存。

### 日用品管理

| 方法 | 路径 | 请求体 | 返回 |
|------|------|--------|------|
| GET | `/api/items` | - | `[{id, name, category, unit, current_stock, min_stock, created_at, prediction: {...}}, ...]` |
| POST | `/api/items` | `{name, category?, unit?, current_stock?, min_stock?}` | `{id}` |
| PUT | `/api/items/{id}` | `{name?, category?, unit?, current_stock?, min_stock?}` | 更新后的 item |
| DELETE | `/api/items/{id}` | - | `{deleted: id}` |
| POST | `/api/items/{id}/usage` | `{amount, note?, logged_at?}` | `{item_id, consumed, current_stock}` |
| POST | `/api/items/{id}/purchase` | `{amount, price?, note?, purchased_at?}` | `{item_id, purchased, current_stock}` |
| GET | `/api/items/{id}/history` | - | `[{type: "usage"|"purchase", id, amount, at, note}, ...]` |
| GET | `/api/items/predictions` | - | `{need_buy: [...], sufficient: [...]}` |

**prediction 结构**（每个 item 自带）：
```json
{
  "daily_rate": 2.0,
  "days_until_empty": 7.0,  // 或 null
  "est_empty_date": "2026-07-19",  // 或 null
  "need_buy": false,
  "suggested_qty": 0
}
```

**库存方向**：`/usage` 减库存，`/purchase` 加库存。前端不需要自己算库存，后端处理了。

## 开发步骤

### 步骤 1：style.css — 全局样式 + 布局

**设计基调**：简洁暗色系（适合自托管面板），移动端友好。

需要覆盖的元素（按 index.html 已有结构）：

1. **全局重置** + `body` 暗色背景（如 `#1a1a2e` 或 `#0f0f1a`），浅色文字
2. **header**：顶部栏，`🏠 HomeDash` 标题 + 刷新按钮，flex 布局
3. **nav.tabs**：Tab 按钮栏，active 状态有高亮下划线或背景色
4. **main**：内容区，max-width 限制（如 800px），居中
5. **section.panel**：默认 `display:none`，`.active` 时 `display:block`
6. **设备卡片**：`.device-card`，每行一个设备，名称 + 开关按钮 + 类型标签
7. **监控列表**：`.monitor-row`，状态圆点（绿=UP/红=DOWN）+ 名称 + 响应时间
8. **日用品**：
   - `.item-card`：物品卡片
   - `.need-buy` 区块：红色/橙色边框警示
   - `.sufficient` 区块：正常显示
   - 状态标签 `.badge`：紧急(红) / 低(橙) / 充足(绿)
9. **toast**：`#toast` 固定底部，操作反馈提示，3 秒后消失
10. **modal**：`#modal` 居中弹窗，用于添加物品、记录消耗/购买、查看历史
11. **表单元素**：input、select、button 统一暗色风格
12. **响应式**：窄屏（手机）Tab 横向滚动，卡片占满宽度

**配色参考**（暗色系）：
```
背景: #1a1a2e
卡片背景: #16213e
边框: #0f3460
主色调(按钮/active): #0f3460 或 #e94560
文字: #eee
次要文字: #999
UP(在线): #2ecc71
DOWN(离线): #e74c3c
```

### 步骤 2：app.js — 框架 + Tab 切换 + 通用工具

```
结构：
- 工具函数：fetchJSON(url, opts)、toast(msg)、showModal(html)、closeModal()
- Tab 切换逻辑（已有 .tab 按钮 + .panel 区块，点击切换 active）
- 页面加载时自动加载三个 Tab 的数据
- 刷新按钮：重新加载当前 Tab
```

**Tab 切换**：点击 `.tab` 按钮 -> 移除所有 `.tab.active` 和 `.panel.active` -> 给当前按钮和对应 panel 加 `.active`。

**toast(msg)**：设置 `#toast` 文本，显示，3 秒后隐藏。

**modal**：`showModal(html)` 设置 `#modal` 的 innerHTML 并移除 `.hidden`；`closeModal()` 加回 `.hidden`。modal 内容由调用方决定（HTML 字符串），需包含关闭按钮。

### 步骤 3：设备控制 Tab

**加载**：并发 `GET /api/devices` + `GET /api/devices/status`，按 type 分组渲染。

**按类型分组**（用 collapsible 分区，默认全展开）：

| 分组 | type | 图标 | 可操作 |
|------|------|------|--------|
| 灯光 | light | 💡 | 开关 |
| 空调 | airconditioner | ❄️ | 开关 |
| 空气净化器 | airpurifier | 🌬️ | 开关 |
| 插座 | plug | 🔌 | 开关 |
| 摄像头 | camera | 📷 | 开关 |
| 厨电 | cooker, kettle, waterpuri | 🍳 | 开关（只读状态为主） |
| 宠物 | feeder, petwaterer | 🐱 | 开关 |
| 音箱 | speaker | 🔊 | 开关 |
| 其他 | 兜底 | 📦 | 开关 |

分组布局（每个设备卡片含开关 + 按类型动态属性控件）：
```
┌─ 💡 灯光 (6) ───────────────────────────────────────┐
│  💡 客厅灯     ● 在线  [开][关]                     │
│     亮度 ━━━━━━━●━━━━━ 65%   色温 ━━●━━━━━━━ 3500K  │
│  💡 浴室灯     ● 在线  [开][关]                     │
│  💡 餐厅灯     ○ 离线  [开][关]                     │
└─────────────────────────────────────────────────────┘
┌─ ❄️ 空调 (3) ───────────────────────────────────────┐
│  ❄️ 卧室空调   ● 在线  [开][关]                     │
│     温度 ━━━━━●━━━━━━━ 26°C   模式 [制冷 ▾]         │
│  ❄️ 猫房空调插座 ● 在线  [开][关]                   │
│     温度 ━━━━━━●━━━━━━ 25°C   模式 [送风 ▾]         │
└─────────────────────────────────────────────────────┘
┌─ 🌬️ 空气净化器 (1) ─────────────────────────────────┐
│  🌬️ 芋圆的空气净化器 ● 在线  [开][关]               │
│     档位 ━━●━━━━━━━━━ 2    模式 [自动 ▾]            │
└─────────────────────────────────────────────────────┘
┌─ 🔌 插座 (1) ───────────────────────────────────────┐
│  🔌 主卧左插线板 ● 在线  [开][关]                   │
└─────────────────────────────────────────────────────┘
```

每个设备卡片显示：
- **图标 + 名称**：按 type 匹配 emoji
- **状态指示**：绿色圆点 ● + "在线"，或灰色圆点 ○ + "离线"
- **开关按钮**：`[开][关]`，当前 power 状态高亮（power=on 时"开"按钮高亮）
- **属性控件**（按 type 动态渲染，仅在线设备显示）：
  - light：亮度滑块（1-100）+ 色温滑块（2700-6500K）
  - airconditioner：温度滑块（16-30°C）+ 模式下拉（制冷/制热/自动/送风/除湿）
  - airpurifier：档位滑块（1-3）+ 模式下拉（自动/静音/最爱/待机）
  - 其他 type：只有开关，无滑块
- **滑块交互**：拖动松开后 `PUT /api/devices/{name}/props {"brightness": 65}`，拖动过程实时显示数值，不发请求（防抖）
- **模式切换**：下拉选择后立即发请求
- **操作后**：toast 提示成功/失败

交互细节：
- 开/关按钮：点击 `POST /api/devices/{name}/on` 或 `off`
- 所有按钮点击时禁用 + loading 状态，防止重复点击
- 设备名含特殊字符时用 `encodeURIComponent(name)`
- **没有设备时**显示空状态："未配置设备，请点击「粘贴导入」或编辑 config/devices.yaml"
- `host` 为空的设备显示"⚠ 未配置 IP"标签，开关按钮禁用
- 顶部操作栏：`[📥 粘贴导入]` `[🔄 刷新状态]`
- 刷新状态：重新调 `/devices/status`，只更新状态圆点、按钮高亮和滑块值，不重建列表

**状态查询设计**（后端 `/devices/status`）：
```python
# 并发查所有设备，每台 3s 超时
def _query_props_sync(cfg):
    """查询设备 power + 按 type 查 _PROP_CMDS 里的属性。"""
    result = {"power": None, "props": {}}
    props_map = _PROP_CMDS.get(cfg.get("type"), {})
    try:
        inst = _instance(cfg)
        # 查 power
        power = inst.send("get_prop", ["power"])
        result["power"] = power[0] if isinstance(power, list) else power
        # 查各属性
        for prop_name, (get_cmd, _, _, _, _) in props_map.items():
            try:
                val = inst.send(get_cmd, [])
                result["props"][prop_name] = val[0] if isinstance(val, list) else val
            except Exception:
                pass  # 该属性不支持，跳过
        result["online"] = True
    except Exception:
        result["online"] = False
    return {"name": cfg["name"], **result}

async def _query_one(cfg):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_query_props_sync, cfg),
            timeout=3.0
        )
    except Exception:
        return {"name": cfg["name"], "online": False, "power": None, "props": {}}

@router.get("/devices/status")
async def device_status():
    tasks = [_query_one(cfg) for cfg in _devices.values() if cfg.get("host")]
    return await asyncio.gather(*tasks)
```

**属性设置端点**（后端 `PUT /devices/{name}/props`）：
```python
class PropIn(BaseModel):
    # 动态键值对，如 {"brightness": 65} 或 {"temperature": 26}
    # pydantic 不预定义字段，用 model_dump 接收任意键
    pass

@router.put("/devices/{name}/props")
async def set_prop(name: str, payload: dict):
    cfg = _get(name)
    props_map = _PROP_CMDS.get(cfg.get("type"), {})
    results = {}
    for prop, value in payload.items():
        if prop not in props_map:
            raise HTTPException(400, f"不支持的属性: {prop}")
        _, set_cmd, *_ = props_map[prop]
        await asyncio.to_thread(_send, cfg, set_cmd, [value])
        results[prop] = value
    return {"name": name, "props": results}
```
> ponytail: `get_prop`/`set_bright` 等是多数 miio 设备通用命令，不同型号可能不同。属性查询/设置是 best-effort，不支持的不显示控件，不影响开关操作。

### 步骤 4：监控状态 Tab

**加载**：`GET /api/uptime/status` -> 渲染监控列表。

每行：
```
●  TeslaMate        UP      99.8%   23ms
✕  Beszel           DOWN    -       -
```

- 状态圆点：`status == 1` 绿色 ●，否则红色 ✕
- 名称：`monitor.name`
- 响应时间：`monitor.ping`（ms），DOWN 时显示 `-`
- `available: false` 或 `source: "unavailable"` 时显示："Uptime Kuma 数据库未连接，请检查 KUMA_DB_PATH 配置"
- `monitors` 为空数组时显示："暂无监控数据"
- 可选：点击行展开 `monitor.msg`（错误信息）

### 步骤 5：日用品 Tab — 列表 + 预测

**加载**：`GET /api/items` -> 分组渲染。

布局：
```
┌─ 需要购买 (3) ───────────────────────────┐
│  ⚠ 卫生纸   剩余 2 卷  预计 5 天  建议 10 │
│  ⚠ 洗洁精   剩余 0.3    预计 3 天  建议 2  │
└──────────────────────────────────────────┘
┌─ 库存充足 (8) ───────────────────────────┐
│  ✓ 垃圾袋   剩余 30 个  预计 45 天        │
│  ✓ 洗衣液   剩余 1.5 L  预计 38 天        │
└──────────────────────────────────────────┘
[+ 添加物品]  [📋 购物清单]
```

- 按 `prediction.need_buy` 分两组
- need_buy 组按 `days_until_empty` 升序（最紧急的排前面）
- 每张卡片显示：名称、库存（`current_stock` + `unit`）、预计耗尽天数（`days_until_empty`，无数据时显示 "—"）
- need_buy 的卡片额外显示建议购买量（`suggested_qty` + `unit`）
- 卡片可点击 -> 打开物品详情 modal（步骤 6）

**添加物品按钮**：打开 modal，表单字段：名称(必填)、分类、单位(默认"个")、当前库存、最低库存。提交 `POST /api/items`，成功后刷新列表。

**购物清单按钮**：`GET /api/items/predictions`，只显示 `need_buy` 部分 + 建议数量，格式化为可复制的购物清单文本。

### 步骤 6：物品详情 modal

点击物品卡片打开，内容：
1. 物品信息（名称、分类、库存、单位）
2. 操作按钮：[记录消耗] [记录购买] [编辑] [删除]
3. 历史记录列表：`GET /api/items/{id}/history`

**记录消耗**：modal 内表单，字段：数量(必填)、备注(可选)、日期(可选，默认今天)。提交 `POST /api/items/{id}/usage`。成功后刷新详情 + 列表。

**记录购买**：modal 内表单，字段：数量(必填)、价格(可选)、备注(可选)、日期(可选)。提交 `POST /api/items/{id}/purchase`。成功后刷新。

**编辑**：表单预填当前值，提交 `PUT /api/items/{id}`。

**删除**：二次确认后 `DELETE /api/items/{id}`，关闭 modal，刷新列表。

**历史记录**：按时间倒序显示，每条标注类型（消耗🔴/购买🟢）、数量、日期、备注。`history` 返回的 `at` 字段是 ISO 时间字符串，前端格式化显示。

### 步骤 7：交互细节与收尾

1. **全局 loading 状态**：每个 Tab 加载时显示 "加载中..."，加载完成替换为内容
2. **错误处理**：API 返回非 2xx 时 toast 显示错误信息（后端返回的 detail 字段）
3. **防抖**：刷新按钮点击后禁用 2 秒
4. **空状态**：每个 Tab 在无数据时都有友好的空状态提示
5. **自动刷新**（可选）：监控状态 Tab 每 60 秒自动刷新一次
6. **数字格式化**：库存和数量保留合理小数位（如 0.3 而非 0.30000），days_until_empty 取整数天显示
7. **确认操作**：删除物品需二次确认

## 验收标准

```bash
# 1. 后端自检全通过
python -m app.modules.items
python -m app.modules.devices
python -m app.modules.uptime

# 2. 启动开发服务器
uvicorn app.main:app --reload

# 3. 浏览器打开 http://127.0.0.1:8000
#    - 三个 Tab 可切换
#    - 设备 Tab：无设备时显示空状态提示（因为没有 devices.yaml）
#    - 监控 Tab：无 Kuma DB 时显示未连接提示
#    - 日用品 Tab：可添加物品、记录消耗/购买、看到预测、删除物品
#    - 所有操作有 toast 反馈
#    - 页面暗色风格、中文、移动端可用
```

## 粘贴导入米家设备（Phase 3.5）

从 Xiaomi Cloud Tokens Extractor 导出的设备列表，直接粘贴到前端，自动解析并写入 `config/devices.yaml`。免手动编辑 YAML。

### 输入格式（token_extractor.py 原始输出）

```
Devices found for server "cn" @ home "602001027218":
   ---------
   NAME:     客厅灯
   ID:       1088104207
   MAC:      C8:5C:CC:D1:78:DF
   IP:       192.168.1.166
   TOKEN:    f862d7f1327141cea0115060d590d659
   MODEL:    bean.switch.bl02
   ---------
   NAME:     猫房温湿度计
   ID:       blt.3.1opcm68cs4g00
   BLE KEY:  226835f92ca8195235b53a8a9fd80119
   MAC:      A4:C1:38:19:38:4C
   TOKEN:    a8c6fc0de7c25fc74e27e298
   MODEL:    miaomiaoce.sensor_ht.t9
   ---------
```

### 后端新增端点

```
POST /api/devices/import
  请求体: {"raw": "<token_extractor 原始输出文本>"}
  返回: {"imported": 3, "skipped": 5, "skipped_list": [...]}
```

**解析逻辑**（`app/modules/devices.py` 新增 `parse_tokens_output(raw: str) -> list[dict]`）：

1. 按 `---------` 分割成多个设备块
2. 每块用正则提取 `NAME:`、`MODEL:`、`TOKEN:`、`IP:` 字段
3. **过滤规则**：
   - 无 `IP:` 的设备（BLE 设备：温湿度计、门锁、打印机等）跳过，python-miio 局域网直控不支持
   - TOKEN 长度 != 32 的跳过（子设备 token 是 16 位，不可直控，如 `.s2`/`.s3` 后缀的）
4. **type 自动推断**（按 model 前缀匹配，匹配不到默认 `plug`）：

```python
# model -> type 映射，新类型加一行
_MODEL_TYPE = {
    "bean.switch":      "light",      # 墙壁开关
    "znsn.switch":      "light",
    "yeelink.light":    "light",
    "lumi.acpartner":   "airconditioner",  # 空调伴侣
    "xiaomi.airc":      "airconditioner",
    "zhimi.airpurifier":"airpurifier",
    "cuco.plug":        "plug",
    "chuangmi.plug":    "plug",
    "chuangmi.camera":  "camera",
    "yunmi.waterpuri":  "waterpuri",
    "chunmi.cooker":    "cooker",
    "xiaomi.feeder":    "feeder",
    "yunmi.kettle":     "kettle",
    "xiaomi.pet_waterer":"petwaterer",
    "xiaomi.wifispeaker":"speaker",
}
# ponytail: 按 model 前缀匹配，新增类型加一行即可
```

5. 解析后合并到现有 `_devices` dict（同名跳过），然后写回 `config/devices.yaml`
6. 返回导入数、跳过数、跳过原因列表

**写回 YAML**：`yaml.dump({"devices": [...]}, allow_unicode=True)`，保留现有设备（去重合并）。

### 前端交互

设备 Tab 顶部加 `[📥 粘贴导入]` 按钮（在 `[+ 添加物品]` 同级位置）：

1. 点击 -> 打开 modal
2. modal 内容：一个大 `<textarea>` + 说明文字
   - 说明："粘贴 Xiaomi Cloud Tokens Extractor 的输出。自动过滤 BLE 设备和子设备，只导入有 IP 的 WiFi 设备。"
3. 底部 `[导入]` 按钮 -> `POST /api/devices/import {raw: textarea内容}`
4. 返回后 toast 显示 "导入 N 台，跳过 M 台"
5. 展开跳过列表（折叠的 `<details>`，显示跳过的设备名和原因）
6. 成功后刷新设备列表

### 自检（devices.py `__main__` 新增）

```python
# 粘贴导入解析自检
SAMPLE = '''---------
   NAME:     客厅灯
   IP:       192.168.1.166
   TOKEN:    f862d7f1327141cea0115060d590d659
   MODEL:    bean.switch.bl02
   ---------
   NAME:     猫房温湿度计
   BLE KEY:  226835f92ca8195235b53a8a9fd80119
   MAC:      A4:C1:38:19:38:4C
   TOKEN:    a8c6fc0de7c25fc74e27e298
   MODEL:    miaomiaoce.sensor_ht.t9
   ---------
   NAME:     浴室灯
   ID:       1088105042.s3
   TOKEN:    1QDShFsRTIRypEbI
   MODEL:    bean.switch.bl02
   ---------'''

parsed = parse_tokens_output(SAMPLE)
assert len(parsed) == 1, f"应只导入1台(有IP的)，实际{len(parsed)}"
assert parsed[0]["name"] == "客厅灯"
assert parsed[0]["type"] == "light"
assert parsed[0]["host"] == "192.168.1.166"
# 猫房温湿度计无IP跳过，浴室灯token非32位跳过
print("devices.py 粘贴导入自检通过。")
```

## 不做

- 不做用户认证/登录（纯家庭内网）
- 不做多语言切换（只有中文）
- 不做 PWA/离线支持
- 不做图表/数据可视化（历史记录用列表展示即可）
- 不做通知推送（只看面板）
- 不改 index.html 的结构（只补 CSS 和 JS）
