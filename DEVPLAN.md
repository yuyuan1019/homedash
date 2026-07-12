# HomeDash DEVPLAN（待办规格书）

> ⬜ 本文档是**待办规格书**，不是已完成记录。  
> 已完成基线以代码为准：items/devices/uptime 后端、三 Tab 前端（米家风格设备页）、BLE Mesh 云端开关、Docker 部署、设备 power 状态查询。  
> **本文件里写的预测升级尚未实现，请勿按本文当时代码行为。**

## 当前已完成基线

- 后端：`app/modules/items.py`、`app/modules/devices.py`、`app/modules/uptime.py`
- 前端：`app/static/index.html`、`app/static/style.css`、`app/static/app.js`
- 部署：`Dockerfile`、`docker-compose.yml`、`.dockerignore`、`.env.example`
- 设备状态：`GET /api/devices/status` 返回 `[{name, online, power}]`
- 日用品预测（**现状**）：全历史均匀平均线性模型（见下方「现状 vs 目标」）

## 待办 0：日用品预测升级（EWMA + 安全库存）— **优先规格，尚未开发**

**场景假设**：两口之家、约 120㎡ 固定住房、手动记账、自托管。  
**目标**：少数据也能用、结果可解释、覆盖洗护/纸品/宠物/冷冻食品等多品类。  
**约束**：保持 `predict_item` 纯函数；不新增依赖；不引入 ML 框架。

### 0.1 现状 vs 目标

| | 现状（代码已实现） | 目标（本待办，未实现） |
|--|------------------|----------------------|
| 日消耗率 | 全历史 `总消耗 / 首末日跨度` | **EWMA**（近记录权重大） |
| 单条记录 | 跨度兜底 1 天 | 保留兜底；≥2 条再信 EWMA |
| 需购买 | 仅 `days_until_empty < 7` | 天数阈值 **或** 库存 < 安全库存 |
| 冷启动 | 无用量几乎不预测 | 品类先验 + `min_stock` |
| 懒人模式 | 无 | 可选：购买间隔中位数兜底 |
| 输出字段 | daily_rate / days / need_buy / suggested_qty | 同上 + `confidence` + `method` |

### 0.2 推荐算法（实现时按此做）

**主路径：EWMA 日消耗率**

```
输入：usage_logs（按时间排序）、current_stock、today、可选 category / min_stock / purchase_logs

1) 将相邻用量记录换成区间日速率：
   r_i = amount_i / max(1, (date_i - date_{i-1}).days)
   首条若无前序：r_0 = amount_0 / 1   # ponytail: 与现状单条兜底一致

2) EWMA：
   rate_0 = r_0
   rate_t = α * r_t + (1-α) * rate_{t-1}
   默认 α = 0.35（两口之家稳态消耗）

3) 安全库存：
   lead_days = 3          # 网购到货缓冲；可后改常量
   cover_days = TARGET_DAYS  # 默认 30
   safety_stock = max(min_stock, rate * lead_days)

4) 预测：
   days_until_empty = current_stock / rate   if rate > 0 else None
   need_buy = (
       current_stock <= 0
       or current_stock < safety_stock
       or (days_until_empty is not None and days_until_empty < BUY_THRESHOLD)
   )
   suggested_qty = ceil(rate * cover_days - current_stock) if need_buy else 0
   suggested_qty = max(0, suggested_qty)

5) 信心 confidence：
   记录条数 0 → low（走先验/min_stock）
   1～2 → low
   3～5 → medium
   ≥6 → high

6) method 标记（便于 UI/调试）：
   "ewma" | "purchase_interval" | "category_prior" | "min_stock_only" | "none"
```

**辅路径 A：购买间隔（用量懒得记时）**

```
若 usage 不足（<2 条）且 purchase_logs ≥ 2：
  interval_days = 购买日期间隔的中位数
  days_until_empty ≈ (上次购买日 + interval_days) - today   # 可与库存粗结合
  method = "purchase_interval"
```

**辅路径 B：品类先验（冷启动）**

```
无用量、无足够购买记录时，用 category 默认日消耗先验（见 0.4）。
有 ≥3 条真实 usage 后，先验权重降为 0，完全跟 EWMA。
```

**常量（实现时放 items.py 顶部，可调）：**

| 常量 | 建议值 | 含义 |
|------|--------|------|
| `BUY_THRESHOLD` | 7 | 预计不足该天数 → 需买 |
| `TARGET_DAYS` | 30 | 建议补货覆盖周期 |
| `EWMA_ALPHA` | 0.35 | 近期权重 |
| `LEAD_DAYS` | 3 | 到货缓冲，参与安全库存 |
| `MIN_USAGE_FOR_EWMA` | 2 | 少于此条不单独信 EWMA |

### 0.3 返回结构（向后兼容扩展）

现有字段保留；新增可选字段（前端未用时可忽略）：

```json
{
  "daily_rate": 0.12,
  "days_until_empty": 6.5,
  "est_empty_date": "2026-07-20",
  "need_buy": true,
  "suggested_qty": 4,
  "confidence": "medium",
  "method": "ewma",
  "safety_stock": 0.36
}
```

### 0.4 适用品类与登记建议（两口 · 120㎡）

**可以用这套模型吗？——可以。** 下列品类都适用，差别在单位、登记节奏和先验。

| 分类建议 `category` | 示例 | 推荐 `unit` | 怎么登记消耗 | 模型适配 |
|---------------------|------|-------------|--------------|----------|
| 纸品 | 卫生纸、湿巾 | 卷 / 包 | 用完一包记 1；或每周估剩余 | ✅ 很适合 EWMA |
| 洗护 | 洗发露、沐浴露、肥皂、牙膏、洗衣液 | 瓶 / 支 / 袋 | 用完记 1，或按大致剩余比例记 0.5 | ✅ 适合；α 可偏小（更稳） |
| 清洁 | 洗洁精、垃圾袋、消毒液 | 瓶 / 个 | 同上 | ✅ |
| 宠物 | 猫砂、猫粮 | 袋 / kg / L | 换砂、倒粮时记；猫粮按 kg 更准 | ✅ 适合；消耗比人用品稳 |
| 冷冻主食 | 方便面、水饺、汤圆 | 袋 / 盒 | **开封或吃完**记消耗；囤货用购买记库存 | ✅ 可用；波动比洗护大，靠 EWMA 跟近期 |
| 厨房调味 | 油盐酱醋（若要管） | 瓶 | 换瓶记 1 | ✅ |
| 药品/效期品 | 常备药 | 盒 | **不优先用消耗预测**；更重效期（本期不做） | ⚠️ 本期仅库存提醒 |

**冷冻食品（方便面 / 水饺 / 汤圆）特别说明：**

- 模型仍然适用：本质都是「库存 ÷ 日消耗」。
- 消耗往往「一阵一阵」的（周末多吃），EWMA 比全历史平均更合适。
- 登记建议：
  1. 入库：`购买` + 数量（如水饺 5 袋）
  2. 吃掉：`消耗` + 数量（吃 1 袋记 1）
  3. 不要把「还在冷冻未开封」记成消耗
- 若几乎只记购买、懒记消耗：实现辅路径后可走**购买间隔**兜底。

**猫砂 / 猫粮：**

- 猫砂：按「袋」或「L」；整袋换完记 1 袋最省事。
- 猫粮：优先 **kg** 或 **g**；比「袋」更稳（袋规格常变）。
- 多猫以后只需用量变大，模型不用改。

**两口之家登记节奏建议（不必每天）：**

| 频率 | 做什么 |
|------|--------|
| 购入当天 | 记一次「购买」 |
| 用完 / 开新包装时 | 记一次「消耗」 |
| 每周一次（可选） | 对牙膏、洗发露等估一下剩余，记消耗差额 |
| 冷启动前 2 周 | 多记几次，信心从 low → medium |

### 0.5 品类先验表（冷启动用，实现时可做 dict）

> 数值是两口之家的**粗默认**，仅在无历史时用；有数据后应被 EWMA 覆盖。单位与物品 `unit` 一致时才有意义。

| category | 默认日消耗（约） | 备注 |
|----------|------------------|------|
| 纸品 | 0.15（卷或包） | 卫生纸偏卷；湿巾偏包，可分物品调 |
| 洗护 | 0.03（瓶/支） | 约 1 瓶/月量级，按实际改 |
| 清洁 | 0.05 | 洗洁精/垃圾袋差异大，靠记录纠正 |
| 宠物 | 0.05（袋）或按 kg 自定 | 猫粮建议用户用 kg 并自填 min_stock |
| 冷冻 | 0.1（袋/盒） | 吃得多会很快被 EWMA 拉高 |
| 其他 / 空 | 0 | 只靠 min_stock |

### 0.6 实现范围（开发时）

**改动文件（预估）：**

- `app/modules/items.py`：重写 `predict_item`；自检用例按新公式改
- （可选）`predict_item` 增加参数：`purchases`、`category`、`min_stock`
- 前端：可展示 `confidence`（低/中/高）；无字段时不崩
- 文档：完成后把本待办标完成，并同步 README / AGENTS「现状」描述

**自检必须覆盖：**

1. 多条用量 → EWMA rate 与全历史平均不同（证明权重生效）
2. 库存 < 安全库存 → need_buy
3. 无用量 + min_stock → 合理 need_buy / prior
4. 冷冻食品脉冲消耗（近期高、早期低）→ 更跟近期
5. 旧调用方字段仍存在（兼容）

**明确不做（本期）：**

- 不做 ARIMA / Prophet / LSTM
- 不做效期管理、营养热量
- 不做条码扫描、电商自动同步
- 不按房屋面积自动乘系数（120㎡ 只作场景说明，不进公式）

### 0.7 用户现在可以先做什么（不改代码）

在现有系统里先把物品建好，预测升级后会自动变准：

**建议先录入的清单（示例名，可改）：**

1. 纸品：卫生纸、湿巾  
2. 洗护：洗发露、沐浴露、肥皂、牙膏、洗衣液  
3. 宠物：猫砂、猫粮  
4. 冷冻：方便面、水饺、汤圆  
5. 其他常用：垃圾袋、洗洁精  

每条建议填：`name`、`category`（上表）、`unit`、`current_stock`、`min_stock`（至少 1）。  
有历史购买的，尽量补几条「购买」；用掉了就记「消耗」。  
**现在就可以登记**——不必等预测代码升级。

---

## 待办 1：Docker 部署细化验证

**目标**：保证 fresh clone 后只改 `.env` 和 `config/devices.yaml` 即可启动。

**验收**：

```bash
cp .env.example .env
mkdir -p data config
cp config/devices.yaml.example config/devices.yaml
docker compose config --quiet
docker compose build
docker compose up -d
curl -fsS http://127.0.0.1:${HOMEDASH_PORT:-8088}/api/items
curl -fsS http://127.0.0.1:${HOMEDASH_PORT:-8088}/api/devices
curl -fsS http://127.0.0.1:${HOMEDASH_PORT:-8088}/api/uptime/status
docker compose down
```

**注意**：默认 Docker bridge 网络即可按 IP 控制米家设备；只有要做局域网广播发现时才考虑 host 网络。

## 待办 2：设备属性控制（最小版）

**目标**：先只做灯光亮度，不做全设备属性系统。

**新增 API**：

```http
PUT /api/devices/{name}/props
Content-Type: application/json

{"brightness": 65}
```

**后端文件**：`app/modules/devices.py`  
**规则**：只允许声明属性；越界 400；BLE Mesh 暂不支持属性控制；不新增依赖。

## 待办 3：设备状态增强（可选）

`/api/devices/status` 在 power 之外按需返回亮度等 `props`；单台 3s 超时；单台失败不影响其他设备。

## 待办 4：粘贴导入米家设备（推迟）

**状态**：先不做。当前手写 `config/devices.yaml` 足够。  
真实设备多到维护 YAML 明显痛苦时再做 `POST /api/devices/import`。

---

## 待办 6：周报邮件提醒（库存/需购买 + **重点待办**）— **规格，尚未开发**

**难度**：★☆☆☆☆ 简单  
**目标**：每周自动发一封中文 Gmail，汇总：  
1）日用品剩余 / 需要购买；  
2）**家庭重点待办事项**（未完成的高优先级 to-do）。  
**场景**：两口之家周末采购 + 家务/杂事提醒，一封邮件看完。  
**邮件通道（已定）**：**Gmail SMTP**（App Password，不是谷歌登录密码）。

> **重点待办**的完整数据模型与页面见 **待办 8**。本待办负责「邮件怎么带上它们」；实现顺序建议 **先 8 再 6**，或同一次做：有 todos 表才能写进周报。

### 6.1 产品行为

- **默认频率**：每周一次（建议周日 18:00 或周六 10:00，时区 `Asia/Shanghai`）
- **触发方式**（实现时二选一，优先 B 更易测；A 更省事）：
  - **A. 容器内 APScheduler / 后台 asyncio 定时**（自包含）
  - **B. 暴露 `POST /api/notify/weekly` + 宿主机 cron / Hermes cron 调**
- **静默策略**（可选，默认 false 仍发送）：
  - `NOTIFY_ONLY_WHEN_NEED_BUY=true` 且「需购买」为空 **且**「未完成重点待办」为空 → 跳过
- **手动试发**：`POST /api/notify/test` 立即发测试邮件到 `NOTIFY_TO`

### 6.2 邮件内容（先纯文本）

```
主题：HomeDash 周报 · 待办 A 项 · 需买 B 项 · YYYY-MM-DD

【重点待办】（未完成，按优先级+截止日期排序）
- [高] 换净水器滤芯 · 截止 2026-07-20 · 负责人: 双方
- [中] 给猫打疫苗 · 截止 2026-08-01
- （无则写：本周无未完成重点待办）

【需要购买】
- 卫生纸：剩余 2 卷，预计 5 天，建议买 10 卷
- 猫砂：剩余 0.5 袋，预计 3 天，建议买 2 袋
- （无则写：暂无需要购买的日用品）

【库存摘要】（可选：仅预计 <14 天或 need_buy）
- 方便面：12 包，预计 40 天

打开面板：http://<主机>:<端口>/
```

**排序规则（重点待办进邮件）：**

1. 仅 `status != done`（未完成）
2. 优先级 high → medium → low
3. 有 `due_date` 的靠前；过期的标 `⚠ 已过期`
4. 最多列出 N 条（默认 20），超出写「另有 M 项见面板」

数据来源：

- 日用品：现有 items + `predict_item`
- 重点待办：`todos` 表（待办 8）

### 6.3 Gmail 配置（`.env` / `.env.example`）

> 实现前用户需在 Google 账号开启两步验证，并生成 **应用专用密码**。  
> **禁止**把真实密码写进仓库。

| 变量 | Gmail 推荐值 | 说明 |
|------|--------------|------|
| `SMTP_HOST` | `smtp.gmail.com` | 固定 |
| `SMTP_PORT` | `587` | STARTTLS（推荐）；或 `465` SSL |
| `SMTP_USER` | `you@gmail.com` | 完整 Gmail 地址 |
| `SMTP_PASSWORD` | `xxxx xxxx xxxx xxxx` | **16 位 App Password** |
| `SMTP_FROM` | `HomeDash <you@gmail.com>` | 发件显示名 |
| `NOTIFY_TO` | `you@gmail.com,spouse@gmail.com` | 收件人 |
| `NOTIFY_CRON` | `0 18 * * 0` | 每周日 18:00 |
| `NOTIFY_TZ` | `Asia/Shanghai` | |
| `NOTIFY_ENABLED` | `true` | 总开关 |
| `NOTIFY_ONLY_WHEN_NEED_BUY` | `false` | 名称保留；语义扩展为「需买与待办都空才跳过」时可再加 `NOTIFY_SKIP_IF_EMPTY` |
| `NOTIFY_TODO_LIMIT` | `20` | 邮件最多列几条重点待办 |
| `HOMEDASH_PUBLIC_URL` | `http://192.168.x.x:8088` | 正文面板链接 |

Gmail 注意：App Password；国内出网；家庭周报无需 Gmail API OAuth。

```env
# --- 邮件周报（Gmail）---
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=HomeDash <you@gmail.com>
NOTIFY_TO=you@gmail.com
NOTIFY_ENABLED=false
NOTIFY_CRON=0 18 * * 0
NOTIFY_TZ=Asia/Shanghai
NOTIFY_ONLY_WHEN_NEED_BUY=false
NOTIFY_TODO_LIMIT=20
HOMEDASH_PUBLIC_URL=http://127.0.0.1:8088
```

### 6.4 API（建议）

```
POST /api/notify/test     → 立即发测试邮件（含当前待办+库存摘要）
POST /api/notify/weekly   → 与定时任务同一套逻辑
GET  /api/notify/config   → 脱敏：enabled / has_smtp / to_count / host
```

### 6.5 实现文件（预估）

- `app/modules/notify.py`：组信（todos + items）+ SMTP
- 依赖待办 8 的查询函数，如 `list_open_todos(limit)`
- `app/main.py` 挂载；（可选）调度
- `.env.example`、README

### 6.6 明确不做（本期）

- 不做每条待办单独每日邮件（周报合并一封）
- 不做 QQ/163 向导、Gmail OAuth
- 不做推送 App

---

## 待办 8：重点待办事项（家庭 To-Do）— **规格，尚未开发**

**难度**：★★☆☆☆  
**目标**：记录家里**重点待办**（家务、维修、预约、账单等），面板可管理，并进入 **Gmail 周报**（待办 6）。  
**不是**软件开发任务列表，是「家里这两周必须盯的事」。

### 8.1 产品范围

**要做：**

- 新增 / 编辑 / 完成 / 删除重点事项
- 字段：标题、备注、优先级、截止日期、负责人（可选）、状态
- 前端独立 Tab 或日用品旁入口（建议第四 Tab：**待办**，或「日用品」页上方区块；实现时优先 **第四 Tab「重点待办」**，信息架构更清晰）
- 列表默认只显示未完成；可切换「已完成」
- 与邮件：未完成项进入周报【重点待办】区

**示例条目：**

- 换净水器滤芯（高，截止本月底）
- 给猫打疫苗（高）
- 交物业费（中，截止日）
- 清理阳台（低）

### 8.2 数据模型

在 `app/database.py` 的 `SCHEMA` 增加（`CREATE TABLE IF NOT EXISTS`，无迁移工具）：

```sql
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,              -- 简短标题
    note TEXT,                        -- 备注
    priority TEXT DEFAULT 'medium',   -- high | medium | low
    status TEXT DEFAULT 'open',       -- open | done
    due_date TEXT,                    -- YYYY-MM-DD，可空
    assignee TEXT,                    -- 可选：我 / 配偶 / 双方 / 自由文本
    -- 给 home agent / 外部调度用的提醒元数据（可空 = 不单独 IM 提醒）
    remind_at TEXT,                   -- ISO 本地时间，如 2026-07-20T09:00:00
    remind_channels TEXT,             -- JSON 数组字符串：["qq","wechat","email"]；空=跟随默认
    remind_repeat TEXT,               -- none | daily | weekly | once（once 触发后清 remind_at 或标 fired）
    external_ref TEXT,                -- 外部系统 id（Hermes cron job id 等），可空
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
```

**约束：**

- `priority` ∈ {high, medium, low}
- `status` ∈ {open, done}
- 完成时：`status=done` 且 `completed_at=now`；重新打开则清空 `completed_at`
- `remind_channels` 存 JSON 文本，如 `'["qq","wechat"]'`；非法 JSON 读写时当空

### 8.3 API（面板 + **home agent 稳定接口**）

> **设计原则**：HomeDash 管「待办事实与提醒意图」；**不内置**微信/QQ 协议机器人。  
> **Hermes / home agent** 通过下列 HTTP 接口拉取待办、登记提醒、回写完成；真正发到 QQ/微信由 agent 的既有通道（qqbot、telegram、后续 wechat 插件等）完成。

#### 8.3.1 面板 CRUD

```
GET    /api/todos?status=open|done|all   默认 open
POST   /api/todos                        创建（可带 remind_* 字段）
GET    /api/todos/{id}
PUT    /api/todos/{id}                   编辑字段
POST   /api/todos/{id}/done              标记完成
POST   /api/todos/{id}/reopen            重新打开
DELETE /api/todos/{id}
GET    /api/todos/summary                {open_count, overdue_count, top: [...]}
```

**POST /api/todos body 示例：**

```json
{
  "title": "换净水器滤芯",
  "note": "柜下 3M，备件在储物间",
  "priority": "high",
  "due_date": "2026-07-31",
  "assignee": "双方",
  "remind_at": "2026-07-30T09:00:00",
  "remind_channels": ["qq", "wechat"],
  "remind_repeat": "once"
}
```

排序：`open` = priority DESC，`due_date` ASC NULLS LAST，`id` DESC。

#### 8.3.2 Agent 专用接口（预留，实现时必须有）

统一前缀：`/api/agent/todos`  
鉴权：内网默认可先用共享头（见下）；**密钥只放 `.env`**。

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/agent/todos/due` | 拉取**到点应提醒**的未完成待办 |
| GET | `/api/agent/todos/open` | 拉取全部 open（可选 `priority=high`） |
| POST | `/api/agent/todos` | agent 代建待办（同 POST /api/todos） |
| POST | `/api/agent/todos/{id}/remind-fired` | 标记本次提醒已投递（防重复刷屏） |
| POST | `/api/agent/todos/{id}/done` | agent 代用户完成 |
| PUT | `/api/agent/todos/{id}/remind` | 只改提醒字段（改点/频道/周期） |

**`GET /api/agent/todos/due` 查询参数：**

| 参数 | 说明 |
|------|------|
| `now` | 可选，ISO 时间；默认服务器本地 now（`NOTIFY_TZ`） |
| `within_minutes` | 默认 15；`remind_at ∈ (now-window, now+window]` 或 `remind_at <= now` 且未 fired |
| `channel` | 可选过滤：`qq` / `wechat` / `email` |

**响应示例：**

```json
{
  "server_time": "2026-07-20T09:00:00",
  "items": [
    {
      "id": 12,
      "title": "换净水器滤芯",
      "note": "柜下 3M",
      "priority": "high",
      "due_date": "2026-07-31",
      "assignee": "双方",
      "remind_at": "2026-07-20T09:00:00",
      "remind_channels": ["qq", "wechat"],
      "remind_repeat": "once",
      "overdue": false,
      "message": "【HomeDash 待办】换净水器滤芯\n截止 2026-07-31 · 高优先级 · 双方\n柜下 3M"
    }
  ]
}
```

`message` 由服务端拼好，**agent 可直接转发**到 QQ/微信，减少 agent 侧模板逻辑。

**`POST .../remind-fired` body（可选）：**

```json
{
  "channel": "qq",
  "delivered_at": "2026-07-20T09:00:05",
  "external_ref": "hermes-cron-job-xxx"
}
```

行为：

- `remind_repeat=once` → 清空 `remind_at` 或写 `remind_at` 为 null，避免下周再火
- `daily` / `weekly` → 把 `remind_at` 推到下一周期（服务端算好）
- 可记 `external_ref` 方便对账

#### 8.3.3 鉴权（agent 调用）

| 变量 | 说明 |
|------|------|
| `AGENT_API_TOKEN` | 非空时：请求头 `X-HomeDash-Token: <token>` 或 `Authorization: Bearer <token>` |
| 为空 | 仅建议绑定在局域网 / 不映射公网端口（现状家庭内网模式） |

面板浏览器 API 可暂不强制 token（与现有 items 一致）；**agent 路径在 token 配置后必须校验**。

### 8.4 与 home agent 的分工（重点）

```
┌─────────────┐     HTTP (due/open/CRUD)      ┌──────────────────┐
│  HomeDash   │ ◄──────────────────────────► │ Hermes/home agent│
│  todos 真相  │     remind-fired / done       │  调度 + 发 IM     │
└─────────────┘                               └────────┬─────────┘
                                                       │
                       ┌───────────────────────────────┼────────────────┐
                       ▼                               ▼                ▼
                    QQ 通道                          微信通道         Gmail 周报
                 (已有 qqbot)                    (预留/插件)       (待办 6 直发)
```

| 能力 | 谁负责 |
|------|--------|
| 待办 CRUD、截止日、优先级 | **HomeDash** |
| 提醒时间 `remind_at`、频道意图 | **HomeDash** 存；面板可编辑 |
| 定时轮询 / cron「每 5～15 分钟拉 due」 | **home agent**（Hermes cron 等） |
| 发到 QQ / 微信 | **home agent** 调平台 API（不进 HomeDash 进程） |
| 每周汇总邮件 | **HomeDash** SMTP（待办 6），与 IM 并行不互斥 |

**Agent 侧推荐调度伪逻辑（文档给实现者，不写进镜像）：**

```text
每 10 分钟:
  GET /api/agent/todos/due?within_minutes=15
  for item in items:
    if "qq" in channels:  send_qq(item.message)
    if "wechat" in channels: send_wechat(item.message)  # 通道就绪后
    POST /api/agent/todos/{id}/remind-fired
```

也可由 agent **创建时**直接登记 Hermes cron（把 `external_ref` 写回 todo），到期只发一条；due 轮询作兜底。

### 8.5 前端（第四 Tab）

`index.html` 增加 Tab：`设备 | 监控 | 日用品 | 待办`（**允许改骨架**）。

- 列表：标题、优先级、截止日期、负责人、**下次提醒时间**（有则显示）
- 表单增加可选：提醒时间、提醒频道（多选：QQ / 微信 / 仅邮件周报）
- 过期标红；点圆圈完成
- 中文 + 米家浅色风格

### 8.6 与语音 / LLM（可选二期）

待办 7 可扩展：`create_todo` / `complete_todo` / `set_remind`。本期不强制。

### 8.7 实现文件（预估）

- `app/database.py`：`todos` 表（含 remind_*）
- `app/modules/todos.py`：CRUD + summary + agent 路由 + 拼 `message`
- `app/main.py`：挂载
- `app/static/*`：第四 Tab
- `.env.example`：`AGENT_API_TOKEN=`
- README 增加「home agent 对接」小节（示例 curl）
- 可选：`docs/agent-todos.md` 给 Hermes 技能引用（若实现时需要再拆）

### 8.8 明确不做（本期）

- **HomeDash 内不实现**微信/QQ 登录协议、iPad 协议、企业微信机器人本体
- 不做子任务 / 看板 / 番茄钟
- 不做多人登录权限（assignee 只是标签）
- 不做 Google Calendar 同步
- 不在公网裸奔无 token 的 agent API

### 8.9 验收（含 agent 接口）

```bash
# 创建带 QQ 提醒的待办
curl -s -X POST http://127.0.0.1:8088/api/todos \
  -H 'Content-Type: application/json' \
  -d '{"title":"测试提醒","priority":"high","remind_at":"<两分钟后 ISO>","remind_channels":["qq"],"remind_repeat":"once"}'

# agent 拉取
curl -s http://127.0.0.1:8088/api/agent/todos/due \
  -H "X-HomeDash-Token: $AGENT_API_TOKEN"

# 标记已投递
curl -s -X POST http://127.0.0.1:8088/api/agent/todos/1/remind-fired \
  -H "X-HomeDash-Token: $AGENT_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"channel":"qq"}'
```

面板能完成 CRUD；due 在到点返回且 fired 后不再重复（once）。

## 待办 7：语音 / 自然语言记账（STT + **LLM 解析** → 库存变更）— **规格，尚未开发**

**难度**：★★★☆☆  
**目标**：日用品页「🎤 语音记账」；说话或打字后，由 **LLM** 理解意图并生成结构化操作，用于**新增 / 修改库存**（购买、消耗、必要时新建条目）。  
**已定方案**：**LLM 负责意图与槽位解析**（不是可有可无）；STT 仍可先用浏览器或后端。

### 7.1 用户体验

1. 日用品 Tab → **🎤 语音记账**（或「输入一句话」降级）
2. 示例：
   - `加 10 包方便面` → 匹配或新建「方便面」，purchase +10
   - `用掉 2 卷卫生纸` → usage -2
   - `猫粮还剩大概 3 袋，改成 3` → 直接改 `current_stock`（set）
   - `把湿巾的单位改成包` → 改字段（可选，二期）
3. 展示：识别文本 + LLM 解析预览（可编辑）→ **确认写入**
4. toast：`方便面 +10 包（购买），库存 12`

### 7.2 架构（已定：LLM 解析）

```
麦克风 / 文本框
    │
    ▼
[STT] 语音 → 文字
    │  优先：浏览器 Web Speech API（Chrome 中文）
    │  备选：后端 Whisper / OpenAI-compatible STT
    ▼
[LLM] 文字 + 当前物品清单 → 结构化 JSON 指令
    │  OpenAI-compatible Chat Completions
    │  （可用用户已有的 New API / 任意兼容端点）
    ▼
[预览确认] 前端展示 actions[]
    ▼
[执行] 服务端按 JSON 调 create / purchase / usage / patch stock
```

**职责划分：**

| 步骤 | 谁做 | 说明 |
|------|------|------|
| 语音→文字 | STT | 不要求聊天模型做 ASR（除非端点同时支持 audio） |
| 文字→改库存意图 | **LLM（必选）** | 中文口语、别名、多物品一句话 |
| 真正写库 | HomeDash 后端 | **LLM 不直连数据库**；只产出 JSON，服务端校验后执行 |

### 7.3 LLM 输入 / 输出约定

**请求侧塞给模型的上下文（每次）：**

- 用户原话 `text`
- 现有物品精简列表：`[{id, name, unit, category, current_stock}, ...]`（控制 token，名称优先）
- 系统提示：只允许输出 JSON；动作枚举见下；匹配已有名称优先；没有则 `create: true`

**模型输出 JSON Schema（服务端严格校验）：**

```json
{
  "actions": [
    {
      "action": "purchase | usage | set_stock | create_and_purchase",
      "item_id": 3,
      "name": "方便面",
      "amount": 10,
      "unit": "包",
      "category": "冷冻",
      "note": "可选",
      "create": false
    }
  ],
  "display": "方便面 +10 包（购买）",
  "confidence": "high | medium | low"
}
```

**动作语义：**

| action | 行为 |
|--------|------|
| `purchase` | 已有物品：加库存 + purchase_logs |
| `usage` | 已有物品：减库存 + usage_logs |
| `set_stock` | 直接把 `current_stock` 设为 amount（盘点：「改成 3 袋」） |
| `create_and_purchase` | 新建物品再 purchase；`create: true` |

**服务端硬校验（防胡写）：**

- `action` 必须在白名单
- `amount` 必须为有限正数（`set_stock` 允许 0）
- `item_id` 若给了必须存在；不存在则按 `name` 再匹配
- 单次 `actions` 最多 N 条（如 5），防止一次清空库存
- LLM 超时 / 非 JSON → 返回错误，**不写库**
- 可选：规则解析做 fallback（LLM 挂了还能用简单句）；默认仍以 LLM 为主

### 7.4 配置（OpenAI-compatible）

| 变量 | 说明 |
|------|------|
| `LLM_BASE_URL` | 如 `https://api.openai.com/v1` 或家中 New API 地址 |
| `LLM_API_KEY` | Bearer Key |
| `LLM_MODEL` | 如 `gpt-4o-mini` / 用户自选小模型 |
| `LLM_TIMEOUT_SEC` | 默认 30 |
| `VOICE_CONFIRM_REQUIRED` | 默认 `true`（必须确认再 apply） |

依赖：已有 `httpx`，足够调 Chat Completions；**不**把大模型打进 Docker 镜像。

### 7.5 API

```http
# 预览：STT 后的 text，或用户手打
POST /api/items/voice/parse
{"text": "加 10 包方便面"}

→ {
  "ok": true,
  "source": "llm",
  "raw_text": "加 10 包方便面",
  "actions": [...],
  "display": "方便面 +10 包（购买）",
  "confidence": "high"
}

# 确认执行（可回传 parse 的 actions，避免二次 LLM）
POST /api/items/voice/apply
{"actions": [...], "raw_text": "..."}
→ {"ok": true, "results": [{"item_id": 3, "current_stock": 12, "created": false}]}

# 可选 STT
POST /api/items/voice/transcribe  (multipart audio)
→ {"text": "..."}
```

前端也可：Web Speech 得到 text → 只调 `parse` / `apply`。

### 7.6 前端

- 🎤 按钮 + 识别中状态
- 解析预览 sheet：展示 LLM `display` 与可编辑 JSON/表单项
- 确认后 `apply`
- 无麦克风：同一套「打一句话」
- LLM 未配置时：按钮提示「未配置 LLM_BASE_URL」，不静默失败

### 7.7 安全与坑

- 家庭内网无登录；LLM Key 只放服务端 `.env`
- **禁止**把完整 `.env`、SMTP 密码、设备 token 塞进 LLM 上下文；只传物品名/库存等必要字段
- 默认确认写入；`confidence=low` 时强制确认
- Gmail 与 LLM 都依赖出网；透明代理环境需保证容器能访问 `smtp.gmail.com` 与 `LLM_BASE_URL`
- 局域网 HTTP 麦克风限制：文档说明 + 文本降级

### 7.8 实现文件（预估）

- `app/modules/voice_llm.py`：拼 prompt、调 LLM、校验 JSON
- `app/modules/items.py` 或独立路由：parse / apply 执行器
- `app/static/app.js` + `style.css`：🎤 UI
- `.env.example`：Gmail + LLM 变量
- 自检：mock LLM 返回固定 JSON 时 apply 路径正确；非法 action 拒绝

### 7.9 明确不做（本期）

- 不做多轮闲聊管家
- 不做声纹 / 多用户权限
- 不做默认镜像内置本地 7B 模型
- LLM **不**直接执行 SQL

---

## 待办 5：README / AGENTS 状态同步

每次完成上面任一待办，同步更新：

- `README.md` 功能与 API 描述
- `AGENTS.md` 当前阶段与预测说明
- 本文件对应待办状态

不要把本地真实路径、token、账号、`config/devices.yaml` 写进公开文档。

## 待办优先级（建议）

| 顺序 | 待办 | 原因 |
|------|------|------|
| 1 | 0 预测 EWMA | 大批量登记后收益最大 |
| 2 | **8 重点待办 + agent 接口** | 周报与 QQ/微信提醒的数据源；`/api/agent/todos/due` |
| 3 | **6 Gmail 周报**（库存 + 重点待办） | 依赖 8；通道 Gmail |
| 4 | 7 语音 + LLM 解析写库存 | 体验核心；可二期挂 create_todo |
| 5 | home agent 侧 cron 调 due → QQ/微信 | HomeDash 接口就绪后，在 Hermes 配定时任务 |
| 6 | 1 Docker 验收 / 2 灯光 props | 按需 |
| 推迟 | 4 粘贴导入 | 仍推迟 |
