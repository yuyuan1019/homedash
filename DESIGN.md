# HomeDash - 家庭管理面板

## 概述

一个轻量自托管 Web 应用，整合三个功能模块：
1. **米家设备控制** — 局域网直控灯/空调等
2. **Uptime 监控** — 对接已有 Uptime Kuma，展示心跳状态
3. **日用品管理** — 记录消耗/购买，预测下次购买时间

## 技术选型

| 层 | 选择 | 理由 |
|----|------|------|
| 后端 | FastAPI + SQLite | 轻量、用户偏好 SQLite |
| 米家控制 | `python-miio` | 局域网直控，不走云，无需 HA |
| Uptime 对接 | 读 Uptime Kuma SQLite 或调 Push API | 避开 Socket.IO 复杂性 |
| 前端 | 单页 HTML + vanilla JS | 无构建步骤，中文化 |
| 部署 | Docker Compose 单容器 | 与现有 homelab 统一 |

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
│  │miio 控制 │ │Kuma API│ │ 日用品 CRUD+预测  │ │
│  └────┬────┘ └───┬────┘ └────────┬─────────┘ │
│       │          │               │            │
│       ▼          ▼               ▼            │
│   米家设备    Uptime Kuma     SQLite          │
│  (局域网)     (HTTP API)    (homedash.db)     │
└───────────────────────────────────────────────┘
```

## 模块设计

### 1. 米家设备控制

**方案：** `python-miio` 局域网直控

**设备配置（YAML）：**
```yaml
devices:
  - name: 客厅灯
    model: yeelink.light.lamp1
    host: 192.168.1.100
    token: <32位hex token>
    type: light
    actions: [power, brightness, color_temp]
  - name: 卧室空调
    model: zhimi.aircondition.v1
    host: 192.168.1.101
    token: <32位hex token>
    type: airconditioner
    actions: [power, temperature, mode]
```

**API 端点：**
```
GET  /api/devices          — 设备列表 + 当前状态
POST /api/devices/{id}/on  — 开
POST /api/devices/{id}/off — 关
POST /api/devices/{id}     — 自定义命令 (亮度/温度等)
```

**获取 Token 方式：** 使用 `miiocli` 工具或米家 APK 提取

**注意：** 设备必须在同一局域网，且已绑定米家 App（token 从中提取）

### 2. Uptime 监控对接

**方案：** 调用 Uptime Kuma 的 REST API

已有 Uptime Kuma 运行中，两种对接方式：

| 方式 | 优点 | 缺点 |
|------|------|------|
| **A. HTTP 健康检查** | 最简单，直接 curl 各监控目标的 status | 无法获取 Kuma 内部状态 |
| **B. 读 Kuma SQLite** | 数据最全 | 文件锁竞争风险 |

**推荐方案 A：** 用 Kuma 的 status page API（如果开了公开状态页）或 Prometheus metrics 端点

```
GET /api/uptime/status — 返回所有监控项的 up/down + 响应时间
```

后端定期（每 60s）轮询 Uptime Kuma 状态页，缓存结果

### 3. 日用品管理（核心功能）

**数据模型：**

```sql
-- 日用品清单
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- 如：卫生纸、洗洁精、牙膏
    category TEXT,                -- 分类：清洁/洗护/厨房/其他
    unit TEXT DEFAULT '个',       -- 计量单位
    current_stock REAL DEFAULT 0, -- 当前库存
    min_stock REAL DEFAULT 1,     -- 最低库存（低于此值提醒）
    created_at TEXT DEFAULT (datetime('now'))
);

-- 用量记录（每周/不定期填写）
CREATE TABLE usage_logs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    amount REAL NOT NULL,         -- 本次消耗量
    logged_at TEXT DEFAULT (datetime('now')),  -- 消耗日期
    note TEXT,                    -- 备注
    FOREIGN KEY (item_id) REFERENCES items(id)
);

-- 购买记录
CREATE TABLE purchase_logs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    amount REAL NOT NULL,         -- 购买数量
    price REAL,                   -- 花费
    purchased_at TEXT DEFAULT (datetime('now')),
    note TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);
```

**预测算法：**

```
1. 取该物品最近 N 条用量记录（默认全部）
2. 计算日均消耗率 = 总消耗量 / 跨度天数
3. 预计耗尽日期 = 当前日期 + 当前库存 / 日均消耗率
4. 若预计耗尽日期 < 7天 → 标记"需要购买"
5. 建议购买数量 = 日均消耗率 × 目标周期(如30天) - 当前库存
   （向上取整到常见包装规格）
```

**算法特点：** 线性回归，够用就行。不搞 ARIMA/LSTM。

**API 端点：**
```
GET    /api/items                    — 物品列表 + 预测信息
POST   /api/items                    — 添加物品
PUT    /api/items/{id}               — 编辑物品
DELETE /api/items/{id}               — 删除物品
POST   /api/items/{id}/usage         — 记录消耗
POST   /api/items/{id}/purchase      — 记录购买
GET    /api/items/{id}/history       — 历史（用量+购买）
GET    /api/items/predictions        — 全部预测汇总 + 购买建议
```

**前端交互流程：**
```
[物品列表页]
  ├─ 每个物品卡片：名称 | 库存 | 预计耗尽 | 状态标签(充足/低/紧急)
  ├─ 点击物品 → 详情页（历史曲线 + 记录入口）
  ├─ [记录消耗] 按钮 → 输入数量 → 自动更新库存和预测
  ├─ [记录购买] 按钮 → 输入数量+价格 → 自动更新库存
  └─ [购买清单] 页 → 汇总所有需要买的物品 + 建议数量

[每周提醒]（可选 cron）
  └─ 每周日推送"本周需要补货的物品"清单
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
│  │  ✕ Beszel         DOWN    —            │  │
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
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── config/
│   └── devices.yaml          # 米家设备配置
├── app/
│   ├── main.py               # FastAPI 入口
│   ├── database.py           # SQLite 连接 + 表初始化
│   ├── modules/
│   │   ├── devices.py        # 米家设备控制
│   │   ├── uptime.py         # Uptime Kuma 对接
│   │   └── items.py          # 日用品 CRUD + 预测
│   └── static/
│       ├── index.html        # 单页前端
│       ├── style.css
│       └── app.js
└── data/
    └── homedash.db           # SQLite 数据库（挂载）
```

## 依赖清单

```
fastapi
uvicorn[standard]
python-miio
pyyaml
httpx          # 调 Kuma API
jinja2         # 模板（可选，也可纯静态）
```

共 6 个依赖，没有前端框架，没有 ORM，没有 Redis。

## 部署方式

```yaml
# docker-compose.yml
services:
  homedash:
    build: .
    ports:
      - "8088:8000"
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    network_mode: host   # 米家设备需要局域网访问
    restart: unless-stopped
```

`network_mode: host` 是为了 python-miio 能直接发现和控制局域网设备。

## 开发分工建议

| 任务 | 推荐工具 | 理由 |
|------|---------|------|
| 架构设计/需求细化 | Claude Code | 擅长架构 |
| 后端 API 开发 | Codex CLI | 性价比高 |
| 前端页面 | 手写或 Codex | 单页无需复杂工具 |

## 待确认

1. **米家设备型号和数量** — 需要 token 获取方式说明？
2. **Uptime Kuma 是否已开公开状态页？** — 决定对接方式
3. **日用品预测精度** — 线性回归够用？还是需要考虑季节性？
4. **界面风格偏好** — 简洁暗色 / 简洁亮色 / 其他？
5. **是否需要多用户？** — 还是纯家庭单用户即可？
6. **通知方式** — 需要推送到 Telegram/QQ？还是只看面板？
