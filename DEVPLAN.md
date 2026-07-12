# HomeDash DEVPLAN（待办规格书）

> ⬜ 本文档是**待办规格书**，不是已完成记录。  
> 已完成基线以**代码**为准：items/devices/uptime 后端、三 Tab 前端（米家风格）、BLE Mesh 云端开关、Docker、设备 power 状态。  
> **本文件中的增强项在落地前均视为未实现**；编码时勿把下文 API/文件名当成仓库里已有。

## AI 实现约束（所有待办通用）

本项目**以 AI 独立开发为主**。执行任一待办前必须：

1. 阅读根目录 **`AGENTS.md` 第 0 节（强制总则 + DoD + 禁区）**  
2. 只实现**一个**待办编号，完成其「验收」后再改文档状态  
3. 遵守该待办下的 **明确不做**  
4. 改行为则同步 **README + 本文件 +（若有新模块）AGENTS 模块表 + `.env.example` 占位**  
5. 无密钥环境下代码可启动；联调密钥由用户本地配置，禁止写入仓库  

权威顺序：代码 > AGENTS.md > 本文件 > README > DESIGN。

---

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

### 8.6 与 AI 工作台（待办 7）

AI 工作台一期即包含 `todo.create` / `todo.complete` / `todo.update` 等 op，与本模块执行器对接。  
表单 CRUD 与 AI 写库**共用**同一套 todos API/内部函数，避免两套逻辑。

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

## 待办 7：AI 工作台（自然语言 → 结构化写库）— **规格，尚未开发**

**难度**：★★★★☆  
**定位（已定）**：不是「仅语音记一笔库存」，而是面板上的 **AI 工作台**：用户用**打字或语音**下指令，大模型理解后生成**白名单结构化动作**，由 HomeDash **校验并写 SQLite**（库存、待办等）。  
**一句话**：人话操作数据库的工作台；**LLM 从不直接执行 SQL**。

### 7.0 与旧描述的关系

| 旧说法 | 现规格 |
|--------|--------|
| 日用品页 🎤 语音记账 | 升级为独立 **「AI」Tab / 工作台**（可从各 Tab 唤起） |
| 只改库存 | **统一动作总线**：items + todos（+ 可扩展） |
| 语音为主 | **文本为主，语音为输入手段之一**（STT → 同一套 parse/apply） |

### 7.1 产品形态（工作台 UI）

建议第五入口或第四之后：`设备 | 监控 | 日用品 | 待办 | **AI**`（实现时 Tab 名「AI」或「助手」）。

**布局（米家浅色一致）：**

```
┌─────────────────────────────────────────┐
│ AI 工作台                    [清空会话]  │
├─────────────────────────────────────────┤
│ 快捷芯片：加库存 | 记消耗 | 新建待办 |    │
│           完成待办 | 查需买 | 查待办      │
├─────────────────────────────────────────┤
│ 对话/指令区（可多轮短上下文，默认近 5 轮）│
│  你：加 10 包方便面，再记一个换滤芯待办  │
│  AI：将执行 2 步… [预览卡片]             │
├─────────────────────────────────────────┤
│ [预览 actions 列表 · 可勾选/改数字]      │
│ [取消]  [确认写入数据库]                 │
├─────────────────────────────────────────┤
│ [输入框…………] [🎤] [发送]                 │
└─────────────────────────────────────────┘
```

**交互原则：**

1. 用户输入（文本或 STT 文本）→ `POST /api/ai/parse`
2. 工作台展示 `display` + 每条 action 的人话说明；**默认可编辑**
3. 用户点 **确认写入** → `POST /api/ai/apply`（可只 apply 勾选的子集）
4. `AI_CONFIRM_REQUIRED=false` 时可自动 apply（仅建议内网 + 高 confidence）
5. 每次 apply 写 **审计日志**（见 7.6），方便回查「AI 改过什么」

**示例指令（必须能覆盖）：**

| 用户说 | 期望动作 |
|--------|----------|
| 加 10 包方便面 | items: purchase / create_and_purchase |
| 用掉 2 卷卫生纸 | items: usage |
| 猫粮改成 3 袋 | items: set_stock |
| 添加待办：周末换净水器滤芯，高优先级，7 月 31 截止 | todos: create |
| 把「换滤芯」标完成 | todos: complete |
| 明天下午 3 点 QQ 提醒我交物业费 | todos: create + remind_at/channels |
| 现在有什么要买的 / 未完成待办 | **只读查询** query_need_buy / query_open_todos（不写库） |

### 7.2 架构（工具型写库，不是 ChatOps 裸 SQL）

```
用户（文本 / 语音 STT）
        │
        ▼
┌───────────────────┐
│  AI 工作台前端     │
└─────────┬─────────┘
          │ parse / apply
          ▼
┌───────────────────┐     OpenAI-compatible
│  app/modules/ai_workbench.py
│  - 拼系统提示 + 当前快照（items/todos 摘要）
│  - 调 LLM → 仅允许 JSON actions
│  - Schema 校验 + 业务校验
└─────────┬─────────┘
          │ apply
          ▼
┌───────────────────┐
│  领域执行器（白名单）│
│  items CRUD/logs    │
│  todos CRUD/remind  │
│  （禁止任意 SQL）    │
└───────────────────┘
          │
          ▼
     SQLite homedash.db
```

| 步骤 | 谁做 |
|------|------|
| 语音→文字 | STT（可选） |
| 文字→结构化意图 | **LLM（工作台核心）** |
| 真正改库 | **服务端执行器**，只跑白名单 action |
| 设备开关 miio | **默认不进 AI 工作台一期**（误触风险高；二期再加 confirm 双确认） |

### 7.3 统一 Action 协议（跨库存 + 待办）

LLM **只输出**如下 JSON（服务端 `json.loads` + 字段白名单）：

```json
{
  "reply": "将为你加 10 包方便面，并新建待办「换滤芯」。",
  "confidence": "high | medium | low",
  "actions": [
    {
      "op": "item.purchase",
      "name": "方便面",
      "item_id": null,
      "amount": 10,
      "unit": "包",
      "category": "冷冻",
      "create_if_missing": true,
      "note": null
    },
    {
      "op": "todo.create",
      "title": "换净水器滤芯",
      "priority": "high",
      "due_date": "2026-07-31",
      "assignee": "双方",
      "remind_at": null,
      "remind_channels": ["qq"],
      "note": "柜下 3M"
    }
  ]
}
```

#### 7.3.1 写操作白名单（一期）

| op | 含义 | 执行 |
|----|------|------|
| `item.purchase` | 入库/购买 | 匹配或创建 item → +stock + purchase_log |
| `item.usage` | 消耗 | 匹配 item → -stock + usage_log |
| `item.set_stock` | 盘点改库存 | 匹配 item → 直接设 current_stock |
| `item.create` | 只建条目不改数量 | insert items |
| `item.update` | 改 name/unit/category/min_stock | update 白名单列 |
| `todo.create` | 新建重点待办 | insert todos（可含 remind_*） |
| `todo.complete` | 完成 | status=done |
| `todo.reopen` | 重开 | status=open |
| `todo.update` | 改标题/优先级/截止/提醒 | update 白名单列 |
| `todo.delete` | 删除 | 需 `confidence=high` 且默认仍要用户确认 |

#### 7.3.2 只读操作（可直接返回，不必 apply）

| op | 含义 |
|----|------|
| `query.need_buy` | 需购买日用品列表 |
| `query.items` | 按名称搜库存 |
| `query.open_todos` | 未完成待办 |
| `query.overdue_todos` | 过期待办 |

只读 op 在 `parse` 响应里可带 `results` 快照；**不进入 apply 写库**。

#### 7.3.3 硬校验（防胡写库）

- `op` 必须在白名单；未知 op → 整单拒绝或剥离该条
- 单次 `actions` 最多 **8** 条
- `amount` 有限数字；usage/purchase > 0；set_stock ≥ 0
- `item_id` / `todo_id` 存在性校验；名称模糊匹配唯一性（多候选 → 返回 `needs_disambiguation`，不写库）
- **禁止** LLM 输出 SQL / 表名 / 路径
- 超时、非 JSON、缺字段 → 不写库，工作台显示错误
- `todo.delete`、批量 usage 清空类：强制确认

### 7.4 上下文快照（给模型，控制 token）

每次 parse 服务端组装 **只读摘要**（截断）：

```json
{
  "items": [{"id":1,"name":"方便面","unit":"包","stock":2,"category":"冷冻"}, ...],  // 最多 80 条，优先名称命中
  "todos_open": [{"id":3,"title":"换滤芯","priority":"high","due_date":"2026-07-31"}, ...],  // 最多 30
  "today": "2026-07-13",
  "tz": "Asia/Shanghai"
}
```

**禁止**进入 prompt：`.env`、SMTP 密码、LLM key、设备 token、`devices.yaml`、xiaomi 凭据。

系统提示要点：

- 你是 HomeDash 家庭数据操作助手
- 只能输出规定 JSON
- 优先匹配已有 id；没有则 create_if_missing
- 不闲聊；`reply` 一两句中文说明将执行的操作

### 7.5 HTTP API

```http
# 解析（不写库）
POST /api/ai/parse
{
  "text": "加 10 包方便面，并添加待办换滤芯",
  "session_id": "optional-uuid"
}

→ {
  "ok": true,
  "reply": "...",
  "confidence": "high",
  "actions": [ ... ],
  "read_results": null,
  "needs_disambiguation": null
}

# 确认执行（写库）
POST /api/ai/apply
{
  "actions": [ ... ],          // 前端可改过的最终列表
  "raw_text": "...",
  "session_id": "optional-uuid"
}

→ {
  "ok": true,
  "results": [
    {"op":"item.purchase","ok":true,"item_id":1,"current_stock":12},
    {"op":"todo.create","ok":true,"todo_id":9}
  ]
}

# 可选：语音转文字（再走 parse）
POST /api/ai/transcribe  multipart audio → {"text":"..."}

# 可选：审计
GET /api/ai/audit?limit=50
```

兼容别名（若已有文档引用）：`/api/items/voice/parse` 可 308 到 `/api/ai/parse` 或薄封装只允许 item.* ops。

### 7.6 审计表（建议）

```sql
CREATE TABLE IF NOT EXISTS ai_audit (
    id INTEGER PRIMARY KEY,
    raw_text TEXT,
    actions_json TEXT,
    results_json TEXT,
    ok INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 7.7 配置

| 变量 | 说明 |
|------|------|
| `LLM_BASE_URL` | OpenAI-compatible，如家中 New API |
| `LLM_API_KEY` | |
| `LLM_MODEL` | |
| `LLM_TIMEOUT_SEC` | 默认 30 |
| `AI_CONFIRM_REQUIRED` | 默认 `true` |
| `AI_MAX_ACTIONS` | 默认 8 |
| `AI_ENABLED` | 默认 true；false 时工作台提示未开启 |

依赖：现有 `httpx`；不把模型打进镜像。

### 7.8 实现文件（预估）

- `app/modules/ai_workbench.py`：prompt、LLM 调用、校验
- `app/modules/ai_executor.py`：按 op 调 items/todos 内部函数
- `app/database.py`：`ai_audit` 表
- `app/static/*`：AI Tab 工作台 UI
- `.env.example`、README「AI 工作台」
- 自检：mock LLM JSON → apply 改库断言；非法 op 拒绝

### 7.9 明确不做（一期）

- **不做** LLM 直接 `execute_sql` / ORM 任意查询
- **不做** 用 AI 关灯开空调（设备控制另议）
- 不做多用户权限 / 声纹
- 不做镜像内置本地 7B
- 不做无限多轮闲聊（短上下文即可）

### 7.10 验收话术

```text
1. 工作台输入：加 10 包方便面
   → 预览 item.purchase → 确认 → 库存 +10，有 purchase 记录

2. 输入：添加高优先级待办「给猫打疫苗」截止下月底
   → todo.create → 确认 → /api/todos 可见

3. 输入：现在有什么要买的
   → query.need_buy 只读展示，无 apply 写库

4. 模型返回非法 op 或 SQL 字符串 → 拒绝，库不变
```

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
| 4 | **7 AI 工作台**（自然语言写库存/待办） | 统一人话操作 DB；白名单 action，非裸 SQL |
| 5 | home agent 侧 cron 调 due → QQ/微信 | HomeDash 接口就绪后配 |
| 6 | 1 Docker 验收 / 2 灯光 props | 按需 |
| 推迟 | 4 粘贴导入 | 仍推迟 |
