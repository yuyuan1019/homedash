# HomeDash - 家庭管理面板

## 概述

一个轻量自托管 Web 应用，整合三个功能模块：
1. **米家设备控制** - python-miio 局域网直控灯/空调/插座等
2. **Uptime 监控** - 直读 Uptime Kuma 的 SQLite，展示心跳状态
3. **日用品管理** - 记录消耗/购买，预测补货（现状：线性全历史平均；目标：EWMA + 安全库存，见 DEVPLAN 待办 0）

## 当前状态

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 后端骨架 + 数据库 + items 模块 | ✅ 完成 |
| Phase 2 | devices + uptime 模块 | ✅ 完成 |
| Phase 3 | 前端页面 (style.css + app.js) | ✅ 完成（米家风格设备页） |
| Phase 4 | Docker 部署 | ✅ 完成 |
| 增强 | 日用品预测升级 EWMA | ⬜ 待开发（规格在 DEVPLAN） |

> 细节与待办以 `DEVPLAN.md` / `AGENTS.md` / 代码为准；本文「预测算法」分现状与目标两段，避免和旧描述混淆。

## 技术选型

| 层 | 选择 | 理由 |
|----|------|------|
| 后端 | FastAPI + aiosqlite | 轻量、无 ORM、全裸 SQL |
| 米家控制 | `python-miio` + `micloud` | WiFi 局域网直控；BLE Mesh 走云端 MIOT |
| Uptime 对接 | 直读 Kuma SQLite（只读 uri） | 避开 Socket.IO 复杂性，无锁竞争 |
| 前端 | 单页 HTML + vanilla JS | 无构建步骤，无框架，中文 UI |
| 部署 | Docker Compose | `Dockerfile` + 环境变量挂载 Kuma 数据目录 |

## 架构

```
┌─────────────────────────────────────────────┐
│                  浏览器                      │
│  ┌──────────┬──────────┬──────────────────┐ │
│  │ 设备控制  │ Uptime   │ 日用品管理       │ │
│  └────┬─────┴────┬─────┴────┬─────────────┘ │
└───────┼──────────┼──────────┼────────────────┘
        │          │          │
┌───────┼──────────┼──────────┼────────────────┐
│       ▼          ▼          ▼   FastAPI       │
│  ┌─────────┐ ┌────────┐ ┌──────────────────┐ │
│  │miio 控制 │ │Kuma DB │ │ 日用品 CRUD+预测  │ │
│  └────┬────┘ └───┬────┘ └────────┬─────────┘ │
│       │          │               │            │
│       ▼          ▼               ▼            │
│   米家设备    Uptime Kuma     SQLite          │
│  (局域网)     (SQLite 只读)  (homedash.db)    │
└───────────────────────────────────────────────┘
```

## 依赖清单

```
fastapi
uvicorn[standard]
python-miio
pyyaml
httpx
aiosqlite
```

共 6 个依赖。没有前端框架，没有 ORM，没有 Redis，没有 jinja2。

## 模块设计

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
├── requirements.txt
├── config/
│   ├── devices.yaml.example   # 米家设备配置模板
│   └── devices.yaml           # 真实配置（含 token，勿提交）
├── app/
│   ├── main.py                # FastAPI 入口
│   ├── database.py            # SQLite 连接 + 表初始化
│   ├── modules/
│   │   ├── devices.py         # 米家设备控制
│   │   ├── uptime.py          # Uptime Kuma 对接
│   │   └── items.py           # 日用品 CRUD + 预测
│   └── static/
│       ├── index.html         # 单页前端骨架（已有）
│       ├── style.css          # ⬜ 待创建
│       └── app.js             # ⬜ 待创建
└── data/
    └── homedash.db            # SQLite 数据库（首次运行自动建表）
```

## 部署方式（待实现）

通过环境变量配置，不硬编码路径。`KUMA_DB_PATH` 指向 Kuma 的 SQLite 文件，Docker 部署时用只读挂载。

```yaml
# docker-compose.yml
services:
  homedash:
    build: .
    ports:
      - "8088:8000"
    environment:
      - KUMA_DB_PATH=/data/kuma.db       # Kuma 的 SQLite 文件路径
      - DEVICES_PATH=/app/config/devices.yaml
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - /path/to/your/kuma.db:/data/kuma.db:ro   # 改成你的 Kuma DB 路径
    network_mode: host   # 米家设备需要局域网访问
    restart: unless-stopped
```

部署者需要：
1. 找到自己的 Uptime Kuma 数据库文件（通常在 Kuma 容器的 `/app/data/kuma.db`）
2. 只读挂载到 HomeDash 容器，设 `KUMA_DB_PATH` 指向挂载路径
3. 从 `config/devices.yaml.example` 拷贝创建 `config/devices.yaml`，填入米家设备 token

## 配置与环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KUMA_DB_PATH` | `/data/kuma.db` | Uptime Kuma 的 SQLite 路径（容器内） |
| `DEVICES_PATH` | `config/devices.yaml` | 米家设备配置路径 |

## 开发命令

**必须从仓库根目录运行：**

```bash
pip install -r requirements.txt          # 装依赖
uvicorn app.main:app --reload            # 开发服务器，http://127.0.0.1:8000
```

**验证方式 = 各模块的 `__main__` 自检：**

```bash
python -m app.modules.items     # 预测数学断言
python -m app.modules.devices   # 命令映射表 + 配置加载
python -m app.modules.uptime    # 无 DB 文件不报错
```

改了哪个模块就跑哪个；改了 `predict_item` 必跑 items 自检。无 lint/typecheck 配置，无 pytest。
