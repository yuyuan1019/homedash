# HomeDash - 家庭管理面板

## 概述

一个轻量自托管 Web 应用，整合功能模块：
1. **米家设备控制** - python-miio 局域网直控灯/空调/插座等
2. **Uptime 监控** - 直读 Uptime Kuma 的 SQLite，展示心跳状态
3. **日用品管理** - 记录消耗/购买，预测补货（现状：线性全历史平均；目标：EWMA + 安全库存，见 DEVPLAN 待办 0）
4. **重点待办** - 家庭 to-do（规划中，DEVPLAN 待办 8）；预留 **home agent HTTP 接口** 以便定时提醒投递到 QQ/微信；并进入 Gmail 周报（待办 6）
5. **AI 工作台** - 自然语言操作家庭数据（规划中，DEVPLAN 待办 7）：LLM 生成白名单动作 → 确认后写库存/待办等；**禁止直接 SQL**

## 当前状态

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 后端骨架 + 数据库 + items 模块 | ✅ 完成 |
| Phase 2 | devices + uptime 模块 | ✅ 完成 |
| Phase 3 | 前端页面 (style.css + app.js) | ✅ 完成（米家风格设备页） |
| Phase 4 | Docker 部署 | ✅ 完成 |
| 增强 | 日用品预测升级 EWMA | ⬜ 待开发（规格在 DEVPLAN 待办 0） |
| 增强 | 重点待办事项 | ⬜ 待开发（to-do + agent 接口，DEVPLAN 待办 8） |
| 增强 | 周报邮件提醒 | ⬜ 待开发（Gmail：待办+需购买，DEVPLAN 待办 6） |
| 增强 | AI 工作台 | ⬜ 待开发（自然语言写库，DEVPLAN 待办 7） |

> 细节与待办以 `DEVPLAN.md` / `AGENTS.md` / 代码为准；本文「预测算法」分现状与目标两段，避免和旧描述混淆。

## 技术选型

| 层 | 选择 | 理由 |
|----|------|------|
| 后端 | FastAPI + aiosqlite | 轻量、无 ORM、全裸 SQL |
| 米家控制 | `python-miio` + `micloud` | WiFi 局域网；BLE Mesh 云端 MIOT |
| Uptime | 直读 Kuma SQLite（只读 uri） | 避开 Socket.IO |
| 前端 | HTML + vanilla JS | 无构建、中文、米家浅色 |
| 部署 | Docker Compose | env 挂载 Kuma 数据目录 |
| 邮件（规划） | stdlib smtplib + Gmail | 周报，无 Gmail API OAuth |
| AI（规划） | httpx → OpenAI-compatible | 白名单 actions 写库，禁止裸 SQL |
| IM 提醒（规划） | 外部 home agent | HomeDash 只提供 `/api/agent/todos/*` |

## 架构

```
浏览器：设备 | 监控 | 日用品 |〔待办〕|〔AI 工作台〕
              │
         FastAPI /api/*
    ┌─────────┼──────────┬─────────────┐
    ▼         ▼          ▼             ▼
  devices   uptime     items      〔todos/notify/ai〕
  miio/云   Kuma ro    SQLite      规划模块
```

外部：Gmail SMTP（周报）· LLM API（AI parse）· home agent（QQ/微信投递）

## 依赖清单

**当前 requirements.txt：**

```
fastapi
uvicorn[standard]
python-miio
pyyaml
httpx
aiosqlite
python-dotenv
micloud
```

无前端框架、无 ORM、无 Redis、无 jinja2。规划功能优先 stdlib / 已有 httpx，不默认塞进大模型运行时。

## 模块设计

### 0. 模块地图

| 模块 | 状态 | 文件 |
|------|------|------|
| 米家设备 | ✅ | `app/modules/devices.py` |
| Uptime | ✅ | `app/modules/uptime.py` |
| 日用品 | ✅ | `app/modules/items.py` |
| 重点待办 | ⬜ | `app/modules/todos.py`（DEVPLAN 8） |
| Gmail 通知 | ⬜ | `app/modules/notify.py`（DEVPLAN 6） |
| AI 工作台 | ⬜ | `ai_workbench.py` + `ai_executor.py`（DEVPLAN 7） |

### 1. 米家设备控制

**方案：** `python-miio` 局域网直控，原始命令透传

**设备配置（YAML）：**
```yaml
devices:
  - name: 客厅灯
    model: yeelink.light.lamp1
    host: 192.168.1.100
    token: <32位hex token>
    type: light
  - name: 卧室空调
    model: zhimi.aircondition.v1
    host: 192.168.1.101
    token: <32位hex token>
    type: airconditioner
  - name: 客厅插座
    model: chuangmi.plug.m1
    host: 192.168.1.102
    token: <32位hex token>
    type: plug
```

**命令映射表（`_POWER_CMDS`）：** 按 `type` 查开关命令，新设备类型加一行即可。`_DEFAULT` 兜底 `set_power`。

| type | 开 | 关 |
|------|-----|-----|
| light | `set_power ["on"]` | `set_power ["off"]` |
| plug | `set_on []` | `set_off []` |
| outlet | `set_on []` | `set_off []` |
| airconditioner | `set_power ["on"]` | `set_power ["off"]` |
| (其他) | `set_power ["on"]` | `set_power ["off"]` |

**API 端点：**
```
GET  /api/devices                   - 设备列表（不含 _inst 内部字段，不查状态）
POST /api/devices/{name}/on         - 开
POST /api/devices/{name}/off        - 关
POST /api/devices/{name}/command    - 自定义命令 {command, params: []}
```

**注意：**
- `Device` 实例缓存在 cfg dict 的 `_inst` 字段，下划线前缀字段在 `/devices` 列表里被过滤掉。
- 启动双重加载（main.py lifespan + devices.py on_event），无害。
- 获取 Token：推荐用 [Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) 登录小米云导出，详见 README.md。设备必须同一局域网且已绑定米家 App。

### 2. Uptime 监控对接

**方案：** 直读 Uptime Kuma 的 SQLite 数据库文件

```python
# 只读 uri 模式，避免锁竞争
sqlite3.connect(f"file:{KUMA_DB_PATH}?mode=ro", uri=True)
```

查询 `monitor` 表 + 最新 `heartbeat` 记录，60 秒缓存，读失败保留旧缓存。

**API 端点：**
```
GET /api/uptime/status - 返回所有监控项的 up/down + 响应时间 + 可用性标记
```

**环境变量：** `KUMA_DB_PATH`，默认 `/data/kuma.db`（容器内路径）。

### 3. 日用品管理

**数据模型：**

```sql
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- 如：卫生纸、洗洁精、牙膏
    category TEXT,                -- 分类：清洁/洗护/厨房/其他
    unit TEXT DEFAULT '个',       -- 计量单位
    current_stock REAL DEFAULT 0, -- 当前库存
    min_stock REAL DEFAULT 1,     -- 最低库存
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    amount REAL NOT NULL,         -- 本次消耗量
    logged_at TEXT DEFAULT (datetime('now')),
    note TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE TABLE IF NOT EXISTS purchase_logs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    amount REAL NOT NULL,         -- 购买数量
    price REAL,                   -- 花费
    purchased_at TEXT DEFAULT (datetime('now')),
    note TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);
```

**预测算法（纯函数 `predict_item`）：**

**A. 现状（已实现）——全历史均匀线性：**

```
1. 取该物品全部用量记录
2. 日均消耗率 = 总消耗量 / 首末日跨度（单条或同日 → 跨度按 1 天兜底）
3. 预计耗尽天数 = 当前库存 / 日均消耗率
4. 若 < BUY_THRESHOLD(7) → need_buy
5. 建议购买量 = ceil(日均 × TARGET_DAYS(30) - 库存)，仅 need_buy 时非零
6. 无用量记录 → daily_rate=0，基本不预测
```

**B. 目标（未实现，规格见 DEVPLAN 待办 0）——两口·120㎡ 家庭推荐：**

- 主模型：**EWMA 日消耗率**（α≈0.35，近记录权重大）
- 安全库存：`max(min_stock, rate × LEAD_DAYS)`，LEAD_DAYS 默认 3
- 冷启动：品类先验；懒记用量时可用购买间隔中位数兜底
- 适用品类：纸品（卫生纸/湿巾）、洗护（洗发露/肥皂/牙膏等）、宠物（猫砂/猫粮）、冷冻主食（方便面/水饺/汤圆）等——**同一套模型**，差别在 unit 与登记节奏
- **不做** ARIMA / Prophet / LSTM；不按房屋面积进公式

**常量（现状已用）：** `BUY_THRESHOLD=7`、`TARGET_DAYS=30`  
**目标新增常量：** `EWMA_ALPHA=0.35`、`LEAD_DAYS=3`

**库存方向：** `/usage` 减库存，`/purchase` 加库存。

**API 端点：**
```
GET    /api/items                    - 物品列表 + 预测信息
POST   /api/items                    - 添加物品
PUT    /api/items/{id}               - 编辑物品
DELETE /api/items/{id}               - 删除物品
POST   /api/items/{id}/usage         - 记录消耗（减库存）
POST   /api/items/{id}/purchase      - 记录购买（加库存）
GET    /api/items/{id}/history       - 历史记录（用量+购买，按时间排序）
GET    /api/items/predictions        - 全部预测汇总 {need_buy, sufficient}
```

## 前端页面布局

```
┌──────────────────────────────────────────────┐
│  🏠 HomeDash                    [设置] [刷新] │
├──────────────────────────────────────────────┤
│  [设备控制]  [监控状态]  [日用品]             │ ← Tab 切换
├──────────────────────────────────────────────┤
│                                              │
│  ┌─ Tab 1: 设备控制 ──────────────────────┐  │
│  │  客厅灯     [💡 开] 亮度 ━━━●━━ 65%   │  │
│  │  卧室灯     [💡 关]                      │  │
│  │  卧室空调   [❄️ 关]                     │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ Tab 2: 监控状态 ──────────────────────┐  │
│  │  ● TeslaMate      99.8%   23ms         │  │
│  │  ● LubeLogger     100%    12ms         │  │
│  │  ● New API        99.5%   45ms         │  │
│  │  ● Uptime Kuma    100%    8ms          │  │
│  │  ✕ Beszel         DOWN    -            │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ Tab 3: 日用品 ────────────────────────┐  │
│  │  📦 需要购买 (3)                        │  │
│  │  ⚠ 卫生纸   剩余2卷  预计5天  建议10卷  │  │
│  │  ⚠ 洗洁精   剩余0.3   预计3天  建议2瓶  │  │
│  │  ⚠ 牙膏     剩余0.2   预计7天  建议2支  │  │
│  │                                          │  │
│  │  ✅ 库存充足 (8)                         │  │
│  │  · 垃圾袋   剩余30个  预计45天          │  │
│  │  · 洗衣液   剩余1.5L  预计38天          │  │
│  │  ...                                     │  │
│  │                                          │  │
│  │  [+ 添加物品]  [📋 购物清单]            │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

## 项目结构

```
homedash/
├── README.md / DEVPLAN.md / DESIGN.md / AGENTS.md
├── requirements.txt
├── Dockerfile / docker-compose.yml / .env.example
├── config/
│   ├── devices.yaml.example
│   └── devices.yaml              # 勿提交
├── app/
│   ├── main.py
│   ├── database.py
│   ├── xiaomi_login.py / discover_devices.py
│   ├── modules/
│   │   ├── devices.py            # ✅
│   │   ├── uptime.py             # ✅
│   │   ├── items.py              # ✅
│   │   ├── todos.py              # ⬜ 规划
│   │   ├── notify.py             # ⬜ 规划
│   │   ├── ai_workbench.py       # ⬜ 规划
│   │   └── ai_executor.py        # ⬜ 规划
│   └── static/
│       ├── index.html
│       ├── style.css             # ✅ 米家浅色
│       └── app.js                # ✅ 三 Tab；规划扩待办/AI
└── data/                         # 运行时
```

## 部署方式（已实现）

见仓库根目录 `docker-compose.yml` 与 `README.md` Docker 章节。要点：

- 端口：`${HOMEDASH_PORT:-8088}:8000`
- Kuma：挂载**数据目录** `KUMA_DATA_DIR` → 容器 `/kuma-data`，`KUMA_DB_PATH=/kuma-data/kuma.db`
- 默认 bridge 网络；按 IP 控米家即可
- 不写死本机绝对路径；用 `.env` + `.env.example`

## 配置与环境变量

| 变量 | 说明 |
|------|------|
| `KUMA_DB_PATH` / `KUMA_DATA_DIR` | Kuma 库路径 / 宿主机目录 |
| `DEVICES_PATH` | 设备 YAML |
| `HOMEDASH_PORT` | 对外端口 |
| `XIAOMI_*` | 可选，首次云端登录 |
| `SMTP_*` / `NOTIFY_*` | ⬜ Gmail 周报（规划） |
| `LLM_*` / `AI_*` | ⬜ AI 工作台（规划） |
| `AGENT_API_TOKEN` | ⬜ home agent（规划） |

完整注释模板见 `.env.example`。

## 开发命令

**必须从仓库根目录运行：**

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**自检：**

```bash
python -m app.modules.items
python -m app.modules.devices
python -m app.modules.uptime
```

改了哪个模块跑哪个；改 `predict_item` 必跑 items。无 lint/typecheck，无 pytest。公开文档以 **README.md** 为入口，待办规格以 **DEVPLAN.md** 为准。
