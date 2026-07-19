# HomeDash - 家庭管理面板

> **最后更新：2026-07-19**  
> 本文档提供系统设计背景与架构说明。功能以**代码与 README.md** 为准；本文档可能滞后，冲突时以 `AGENTS.md` 与运行中代码为准。

## 概述

一个轻量自托管 Web 应用，整合以下功能模块：
1. **日用品管理** — 记录消耗/购买，EWMA + 安全库存预测补货
2. **重点待办** — 家庭 to-do；预留 **home agent HTTP 接口** 以便定时提醒投递到 QQ/微信；支持图片附件；并进入 SMTP 周报
3. **AI 工作台** — 自然语言操作家庭数据：LLM 生成白名单动作 → 确认后写库存/待办等；**禁止直接 SQL**。家庭顾问聊天可选调 Brave Search 联网；支持操作撤回与审计
4. **面板登录与用户管理** — 长期 Cookie 会话；管理员/普通用户两级权限
5. **SMTP 周报** — 每周汇总库存需买 + 未完成待办发到 QQ 邮箱
6. **系统设置** — 管理员可在 Web UI 配置 LLM、SMTP、Brave Search、Agent Token，热加载无需重启

> 米家设备控制与 Uptime 监控功能已于 2026-07-19 下线，相关模块、依赖、Tab 全部移除。详见 `DEVPLAN.md` 顶部说明。

## 技术选型

| 层 | 选择 | 理由 |
|----|------|------|
| 后端 | FastAPI + aiosqlite | 轻量、无 ORM、全裸 SQL |
| 前端 | HTML + vanilla JS | 无构建、中文、浅色主题 |
| 部署 | Docker Compose | env 挂载 data 目录 |
| 邮件 | stdlib smtplib + QQ 邮箱 | 周报，无 OAuth |
| AI | httpx → OpenAI-compatible | 白名单 actions 写库，禁止裸 SQL |
| 联网搜索 | Brave Search API（可选） | 家庭顾问回答实时问题 |
| IM 提醒 | 外部 home agent | HomeDash 只提供 `/api/agent/todos/*` |

## 设计原则

1. **家庭内网优先**；面板需登录；敏感文件不进 Git  
2. **领域模块清晰**：认证 / 用户 / 库存 / 待办 / 通知 / AI 分文件  
3. **预测与写库可测**：`predict_item` 纯函数；模块尾部 `__main__` 自检  
4. **AI 不直连 SQL**：只产出白名单 `op`，执行器调现有业务函数  
5. **IM 不进主进程**：HomeDash 不实现微信/QQ 协议，只留 HTTP 给 agent  
6. **开源可部署**：路径用环境变量 + `.env.example`，不写死本机绝对路径  
7. **AI 独立开发友好**：规则写在 `AGENTS.md`（权威顺序、DoD、一次一待办、文档同步义务）；`DEVPLAN` 只写规格不冒充已完成  

## 架构

```
浏览器：AI 工作台 | 日用品 | 重点待办
              │
         FastAPI /api/*
    ┌─────────┼──────────┬─────────────┐
    ▼         ▼          ▼             ▼
  auth      items      todos       ai_workbench / ai_executor
  users     notify     setup        (LLM parse + 白名单执行)
                                       │
                                       ▼
                                    SQLite homedash.db
```

外部：QQ 邮箱 SMTP（周报）· LLM API（AI parse & 聊天）· Brave Search（可选）· home agent（QQ/微信投递）

## 依赖清单

**当前 requirements.txt：**

```
fastapi
python-multipart
uvicorn[standard]
httpx
aiosqlite
python-dotenv
```

无前端框架、无 ORM、无 Redis、无 jinja2。默认不塞进大模型运行时。

## 模块设计

### 0. 模块地图

| 模块 | 状态 | 文件 |
|------|------|------|
| 日用品 | ✅ | `app/modules/items.py` |
| 重点待办 | ✅ | `app/modules/todos.py` |
| SMTP 通知 | ✅ | `app/modules/notify.py` |
| AI 工作台 | ✅ | `ai_workbench.py` + `ai_executor.py` |
| 面板登录 / 用户管理 | ✅ | `auth.py` + `users.py` |
| 系统设置 | ✅ | `setup.py`（LLM / SMTP / Brave） |

### 1. 日用品管理

**数据模型：**

```sql
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- 如：卫生纸、洗洁精、牙膏
    category TEXT,                -- 分类：清洁/洗护/厨房/其他
    unit TEXT DEFAULT '个',       -- 计量单位
    current_stock REAL DEFAULT 0, -- 当前库存
    min_stock REAL DEFAULT 1,     -- 最低库存
    location TEXT,
    expires_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    logged_at TEXT DEFAULT (datetime('now')),
    note TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE TABLE IF NOT EXISTS purchase_logs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    price REAL,
    purchased_at TEXT DEFAULT (datetime('now')),
    note TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);
```

**预测算法（纯函数 `predict_item`）：**

- 主模型：**EWMA 日消耗率**（α≈0.35，近记录权重大）
- 安全库存：`max(min_stock, rate × LEAD_DAYS)`，LEAD_DAYS 默认 3
- 冷启动：品类先验；懒记用量时用购买间隔中位数兜底
- 适用品类：纸品（卫生纸/湿巾）、洗护、宠物、冷冻主食等——同一套模型
- **不做** ARIMA / Prophet / LSTM

**常量：** `BUY_THRESHOLD=7`、`TARGET_DAYS=30`、`EWMA_ALPHA=0.35`、`LEAD_DAYS=3`

**库存方向：** `/usage` 减库存，`/purchase` 加库存。

**API 端点：**

```
GET    /api/items                    - 物品列表 + 预测信息
POST   /api/items                    - 添加物品
PUT    /api/items/{id}               - 编辑物品
DELETE /api/items/{id}               - 删除物品
POST   /api/items/{id}/usage         - 记录消耗（减库存）
POST   /api/items/{id}/purchase      - 记录购买（加库存）
GET    /api/items/{id}/history       - 历史记录
GET    /api/items/predictions        - 全部预测汇总
```

### 2. 重点待办

家庭 to-do CRUD + `/api/agent/todos/*` 供外部 Hermes / AI 查询到点提醒。字段包括标题、备注、优先级、截止日期、图片附件（最多 5 张，每张 10MB，支持 JPG/PNG/GIF/WebP）；提醒时间 / 频道 / 重复策略作为 home agent 的元数据在后端保留，面板表单不再展示。

### 3. AI 工作台

- LLM 只输出白名单 JSON（op ∈ items / todos / query.*）；服务端校验后写库
- 每次 parse / apply 均落 `ai_audit`，含 before/after 快照，支持按条撤回（`/api/ai/revert/{action_id}`）
- 家庭顾问聊天独立入口（`/api/ai/chat`），可选调 Brave Search 联网（`BRAVE_API_KEY`）
- 物品分类预测（`/api/ai/item-category`）、建议快捷片段（`/api/ai/suggested-chips`）

### 4. 面板登录与用户管理

- `hashlib.scrypt` 密码 + 每用户随机 salt
- 会话原始 token 只放 Cookie，DB 保存 SHA-256 摘要
- 首次访问强制创建管理员；管理员在设置页可管理其他用户
- 除 bootstrap/login/logout 与 `/api/agent/todos/*` 外，`/api/*` 均要求会话

### 5. SMTP 周报

- QQ 邮箱 SMTP 授权码，465 走 SSL，其他端口走 STARTTLS
- 汇总未完成重点待办 + 需购买日用品
- 通过面板设置页或 `.env` 配置；`POST /api/notify/weekly` 触发

### 6. 系统设置（setup.py）

管理员专属设置页面（`/api/setup/*`），支持：
- **配置状态总览**：显示 LLM、SMTP、Brave Search、Agent Token 的配置状态
- **LLM 配置**：Base URL、API Key、模型选择、超时设置；支持获取上游模型列表、测试连接
- **SMTP 配置**：SMTP 服务器、端口、授权码、收件人；支持测试登录和试发周报
- **Brave Search 配置**：API Key 配置与测试（可选）
- **Agent Token 配置**：查看掩码状态、保存到 `data/agent_config.json`

**配置热加载**：LLM/SMTP/Brave 配置保存到 `data/*.json`，立即生效无需重启容器。环境变量优先级高于文件配置。

## 前端页面布局

```
┌──────────────────────────────────────────────┐
│  🏠 HomeDash                    [•••] [🔄]    │
├──────────────────────────────────────────────┤
│  [AI 工作台]  [日用品]  [重点待办]             │ ← Tab 切换
├──────────────────────────────────────────────┤
│  ┌─ Tab 1: AI 工作台 ─────────────────────┐  │
│  │  快捷芯片：加库存 / 记消耗 / 新建待办  │  │
│  │  对话区（家庭顾问 + 结构化写库）        │  │
│  │  [预览 actions] → [确认写入]           │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ Tab 2: 日用品 ────────────────────────┐  │
│  │  📦 需要购买 (3) …                      │  │
│  │  ✅ 库存充足 (8) …                       │  │
│  │  [+ 添加物品]  [📋 购物清单]            │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ Tab 3: 重点待办 ──────────────────────┐  │
│  │  优先级 / 截止 / 图片附件               │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

## 项目结构

```
homedash/
├── README.md / DEVPLAN.md / DESIGN.md / AGENTS.md
├── requirements.txt
├── Dockerfile / docker-compose.yml / .env.example
├── app/
│   ├── main.py
│   ├── database.py
│   ├── modules/
│   │   ├── auth.py               # ✅
│   │   ├── users.py              # ✅
│   │   ├── items.py              # ✅
│   │   ├── todos.py              # ✅
│   │   ├── notify.py             # ✅
│   │   ├── ai_workbench.py       # ✅
│   │   ├── ai_executor.py        # ✅
│   │   └── setup.py              # ✅
│   └── static/
│       ├── index.html
│       ├── style.css             # ✅ 浅色主题
│       └── app.js                # ✅ 三 Tab
└── data/                         # 运行时
```

## 部署方式（已实现）

见仓库根目录 `docker-compose.yml` 与 `README.md` Docker 章节。要点：

- 端口：`${HOMEDASH_PORT:-8088}:8000`
- 挂载：`./data:/app/data`（持久化 SQLite 与配置 JSON）
- 不写死本机绝对路径；用 `.env` + `.env.example`

## 配置与环境变量

| 变量 | 说明 |
|------|------|
| `HOMEDASH_PORT` | 对外端口 |
| `TZ` | 容器时区，默认 `Asia/Shanghai`；容器基础镜像默认 UTC，须显式设置以保证时间戳按本地时区 |
| `SMTP_*` / `NOTIFY_*` | QQ 邮箱 SMTP 周报（可在设置页配置） |
| `LLM_*` / `AI_*` | AI 工作台（可在设置页配置） |
| `BRAVE_API_KEY` | 家庭顾问联网搜索（可在设置页配置，可选） |
| `AGENT_API_TOKEN` | home agent 接口（环境变量优先，也可在设置页查看/配置文件） |
| `HOMEDASH_PUBLIC_URL` | 邮件里的面板链接 |

完整注释模板见 `.env.example`。

### 配置方式优先级

1. **环境变量**（`.env` 文件）— 优先级最高，需要重启服务
2. **文件配置**（`data/*.json`）— 设置页保存，热加载无需重启

管理员可在设置页面配置 LLM、SMTP、Brave、Agent Token，保存后立即生效。环境变量与文件配置并存时，环境变量优先。

## 开发命令

**必须从仓库根目录运行：**

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**自检：**

```bash
python -m app.modules.items
python -m app.modules.todos
python -m app.modules.notify
python -m app.modules.ai_workbench
python -m app.modules.auth
python -m app.modules.users
python -m app.modules.setup
```

改了哪个模块跑哪个；改 `predict_item` 必跑 items。无 lint/typecheck，无 pytest。公开文档以 **README.md** 为入口，待办规格以 **DEVPLAN.md** 为准。
