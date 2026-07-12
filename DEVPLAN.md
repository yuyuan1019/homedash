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

## 待办 6：周报邮件提醒（库存/需购买）— **规格，尚未开发**

**难度**：★☆☆☆☆ 简单  
**目标**：每周自动发一封中文邮件，汇总家里剩余与「需要购买」清单。  
**场景**：两口之家，不想天天打开面板，周末采购前看一眼邮件即可。  
**邮件通道（已定）**：**Gmail SMTP**（应用专用密码 App Password，不是谷歌登录密码）。

### 6.1 产品行为

- **默认频率**：每周一次（建议周日 18:00 或周六 10:00，时区 `Asia/Shanghai`）
- **触发方式**（实现时二选一，优先 B 更易测；A 更省事）：
  - **A. 容器内 APScheduler / 后台 asyncio 定时**（自包含）
  - **B. 暴露 `POST /api/notify/weekly` + 宿主机 cron / Hermes cron 调**
- **静默策略**：若「需购买」为空且开启 `NOTIFY_ONLY_WHEN_NEED_BUY=true`，可跳过发送（可选）
- **手动试发**：`POST /api/notify/test` 立即发一封测试邮件到 `NOTIFY_TO`

### 6.2 邮件内容（先纯文本）

```
主题：HomeDash 周报 · 需购买 N 项 · YYYY-MM-DD

【需要购买】
- 卫生纸：剩余 2 卷，预计 5 天，建议买 10 卷
- 猫砂：剩余 0.5 袋，预计 3 天，建议买 2 袋

【库存一览】（可选，或仅列不足 14 天的）
- 方便面：12 包，预计 40 天
...

打开面板：http://<你的主机>:<端口>/
```

数据来源：复用现有 items + `predict_item`，**不重写预测**。

### 6.3 Gmail 配置（`.env` / `.env.example`）

> 实现前用户需在 Google 账号开启两步验证，并生成 **应用专用密码**（App Password）。  
> **禁止**把真实密码写进仓库；文档只写占位符。

| 变量 | Gmail 推荐值 | 说明 |
|------|--------------|------|
| `SMTP_HOST` | `smtp.gmail.com` | 固定 |
| `SMTP_PORT` | `587` | STARTTLS（推荐）；或 `465` SSL |
| `SMTP_USER` | `you@gmail.com` | 完整 Gmail 地址 |
| `SMTP_PASSWORD` | `xxxx xxxx xxxx xxxx` | **16 位应用专用密码**，不是登录密码 |
| `SMTP_FROM` | 同 USER 或 `HomeDash <you@gmail.com>` | 发件显示名 |
| `NOTIFY_TO` | `you@gmail.com,spouse@gmail.com` | 收件人，逗号分隔 |
| `NOTIFY_CRON` | `0 18 * * 0` | 每周日 18:00 |
| `NOTIFY_TZ` | `Asia/Shanghai` | |
| `NOTIFY_ENABLED` | `true` | 总开关 |
| `NOTIFY_ONLY_WHEN_NEED_BUY` | `false` | 仅有需购买时才发 |
| `HOMEDASH_PUBLIC_URL` | `http://192.168.x.x:8088` | 邮件正文里的面板链接（可选） |

实现：stdlib `smtplib` + `email`。Gmail 注意：

- 必须用 App Password；普通密码会 auth 失败
- 国内网络访问 `smtp.gmail.com` 若不通，需本机已有代理/出网环境（部署时实测；失败要在日志里写清）
- 单日发送量家庭周报完全够用，无需 Gmail API OAuth（SMTP 足够）

`.env.example` 片段（实现时写入）：

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
HOMEDASH_PUBLIC_URL=http://127.0.0.1:8088
```

### 6.4 API（建议）

```
POST /api/notify/test     → 立即发测试邮件 {ok, to, subject}
POST /api/notify/weekly   → 与定时任务同一套逻辑
GET  /api/notify/config   → 脱敏：enabled / has_smtp / to_count / host（不回密码）
```

### 6.5 实现文件（预估）

- 新建 `app/modules/notify.py`
- `app/main.py` 挂载路由；（可选）lifespan 调度
- `.env.example`、README「Gmail 周报」小节
- 自检：未配置时不崩溃；dry-run 打印正文

### 6.6 明确不做（本期）

- 不做 QQ/163 多厂商向导（SMTP 字段通用，但文档与默认示例只写 Gmail）
- 不做 Gmail OAuth / Gmail API
- 不做推送 App / 企业微信（可后续加通道）

---

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
| 2 | 6 Gmail 周报邮件 | 简单；通道已定为 Gmail |
| 3 | 7 语音 + **LLM 解析写库存** | 体验核心；依赖 LLM 端点配置 |
| 4 | 1 Docker 验收 / 2 灯光 props | 按需 |
| 推迟 | 4 粘贴导入 | 仍推迟 |
