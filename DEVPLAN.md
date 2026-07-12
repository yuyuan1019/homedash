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

### 6.1 产品行为

- **默认频率**：每周一次（建议周日 18:00 或周六 10:00，时区 `Asia/Shanghai`）
- **触发方式**（实现时二选一，优先 A）：
  - **A. 容器内 APScheduler / 后台 asyncio 定时**（自包含，不依赖宿主机 cron）
  - **B. 暴露 `POST /api/notify/weekly` + 宿主机 cron 调**（更透明、更好测）
- **静默策略**：若「需购买」为空且开启 `NOTIFY_ONLY_WHEN_NEED_BUY=true`，可跳过发送（可选）
- **手动试发**：`POST /api/notify/test` 立即发一封测试邮件

### 6.2 邮件内容（中文纯文本 + 简单 HTML 二选一，先纯文本）

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

数据来源：复用现有 `GET /api/items` / `predict_item` 结果，**不重写预测**。

### 6.3 配置（`.env` / `.env.example`，勿写真实密码进仓库）

| 变量 | 示例 | 说明 |
|------|------|------|
| `SMTP_HOST` | `smtp.qq.com` | SMTP 服务器 |
| `SMTP_PORT` | `465` 或 `587` | SSL/STARTTLS |
| `SMTP_USER` | 发件邮箱 | |
| `SMTP_PASSWORD` | 授权码 | **授权码不是登录密码**（QQ/163 等） |
| `SMTP_FROM` | 同 USER 或别名 | 发件人显示 |
| `NOTIFY_TO` | `a@x.com,b@y.com` | 收件人，逗号分隔（夫妻两人） |
| `NOTIFY_CRON` | `0 18 * * 0` | 每周日 18:00 |
| `NOTIFY_TZ` | `Asia/Shanghai` | |
| `NOTIFY_ENABLED` | `true` | 总开关 |
| `NOTIFY_ONLY_WHEN_NEED_BUY` | `false` | 仅有需购买时才发 |

实现用 **stdlib `smtplib` + `email`**，尽量不新增依赖。若用 APScheduler 再加一个轻依赖，或走方案 B 零依赖。

### 6.4 API（建议）

```
POST /api/notify/test     → 立即按当前库存发测试邮件 {ok, to, subject}
POST /api/notify/weekly   → 与定时任务同一套逻辑（供 cron 调）
GET  /api/notify/config   → 返回是否已配置（脱敏：只返回 enabled / has_smtp / to_count，不回密码）
```

### 6.5 实现文件（预估）

- 新建 `app/modules/notify.py`（组信 + SMTP 发送 + 可选路由）
- `app/main.py` 挂载路由；若方案 A，在 lifespan 里启动调度
- `.env.example`、README 增加「邮件提醒」配置说明
- 自检：无 SMTP 配置时不崩溃；`python -m app.modules.notify` 可 dry-run 打印正文

### 6.6 明确不做（本期）

- 不做推送 App / 企业微信 / Telegram（可后续加通道抽象）
- 不做每日本地弹窗
- 不在邮件里放 token 或内网设备控制链接以外的敏感信息

---

## 待办 7：语音记账入库（语音 → 文本 → 库存变更）— **规格，尚未开发**

**难度**：★★★☆☆ 中等（识别环境 + 中文意图解析）  
**目标**：日用品页有一个「按住说话」按钮；例如「加 10 包方便面」→ 有则加库存并记购买，无则新建条目再入库。  
**结论**：**好做，建议分两阶段**；不必一上来接大模型。

### 7.1 用户体验

1. 打开「日用品」Tab → 点/按住 **🎤 语音记账**
2. 说话，例如：
   - `加 10 包方便面` / `方便面加十包` / `+10 方便面`
   - `用掉 2 卷卫生纸` / `卫生纸少了两卷`
   - `猫粮买了 1 袋`
3. 前端展示识别出的文字 + 解析结果预览（物品、数量、动作）
4. **默认二次确认**（「确认写入」）；可后续加「熟练模式」跳过确认
5. 成功 toast：`方便面 +10 包（购买），库存 12`

### 7.2 推荐架构（家庭自托管）

```
浏览器麦克风
    │  MediaRecorder (webm/ogg)
    ▼
POST /api/items/voice   (multipart: audio 文件)
    │
    ├─ 1) STT 语音转文字
    │     路径 A（推荐先做）：浏览器 Web Speech API（Chrome 中文）→ 前端直接拿 text
    │     路径 B：后端 Whisper（本地 faster-whisper 或 OpenAI-compatible STT）
    │
    ├─ 2) 解析 text → 结构化指令
    │     优先：规则 + 轻量正则 / 简单槽位（中文数量词）
    │     可选增强：本地小模型 / 云端 LLM 做纠错（非必须）
    │
    └─ 3) 执行库存动作（复用现有 purchase / usage / create item）
```

**为什么先做路径 A（浏览器识别）？**

| | 浏览器 Web Speech | 后端 Whisper |
|--|------------------|--------------|
| 依赖 | 几乎无（HTTPS 或 localhost） | 模型体积大或需 API Key |
| 中文 | Chrome 可用，Safari/部分环境差 | 一般更稳 |
| Docker/局域网 HTTP | 非 HTTPS 时浏览器可能禁用麦克风 | 不受此限（前端仍要麦克风权限） |
| 实现量 | 小 | 中～大 |

**落地建议：**

1. **Phase 7a**：前端 Web Speech → 文本框可编辑 → `POST /api/items/parse_and_apply` 只收文本  
2. **Phase 7b**（可选）：后端 STT，上传音频，解决非 Chrome / 纯 HTTP 场景  

你举例的「+10 包方便面」在 7a 就能闭环。

### 7.3 意图与解析规则（先规则，不上大模型）

**动作 action：**

| 说法 | action | 库存方向 |
|------|--------|----------|
| 加 / 增加 / 买了 / 购入 / + | `purchase` | 加库存 + 写 purchase_logs |
| 用掉 / 吃了 / 消耗 / 少了 / - | `usage` | 减库存 + 写 usage_logs |
| 仅名词+数量且无动词 | 默认 `purchase`（入库更常见） | |

**数量 amount：**

- 阿拉伯数字：`10`、`0.5`、`2.5`
- 中文数字：`十` `两` `三` `半` → 10 / 2 / 3 / 0.5
- 与单位粘连：`10包` `两卷` `一袋`

**单位 unit（可选，新建条目时用）：**

`包|袋|卷|瓶|支|盒|桶|kg|g|升|L|个|提`

**物品名 name：**

- 去掉动作词、数量、单位后的剩余中文，如 `方便面`
- 与已有 items **模糊匹配**：完全相等 > 包含 > 编辑距离（简单即可）
- 匹配到唯一项 → 用已有 id；匹配到多个 → 返回候选让用户选；匹配不到 → **自动创建**（你提的需求）

**新建条目默认：**

```json
{
  "name": "方便面",
  "category": "冷冻",   // 可先 "其他"，或简单关键词表猜：面/饺/汤圆→冷冻，猫→宠物
  "unit": "包",         // 从话术提取，默认「个」
  "current_stock": 0,
  "min_stock": 1
}
```

然后立刻对该 id 做 `purchase(amount=10)`。

### 7.4 API 设计

```http
# 只解析不写库（预览）
POST /api/items/voice/parse
{"text": "加 10 包方便面"}

→ {
  "ok": true,
  "action": "purchase",
  "name": "方便面",
  "amount": 10,
  "unit": "包",
  "matched_item_id": 3,      // 或 null
  "will_create": false,
  "confidence": "high",
  "display": "方便面 +10 包（购买）"
}

# 解析并执行（确认后）
POST /api/items/voice/apply
{"text": "加 10 包方便面"}   // 或直接传 parse 结果结构
→ {"ok": true, "item_id": 3, "current_stock": 12, "created": false}

# 可选：音频 STT（Phase 7b）
POST /api/items/voice/transcribe
Content-Type: multipart/form-data; audio=@blob
→ {"text": "加十包方便面"}
```

### 7.5 前端

- 日用品 Tab 工具栏增加 `🎤 语音记账`
- 支持：按住说话 / 点按开始-结束
- 识别中显示波形或「正在听…」
- 结果进入底部 sheet：可改文字后「确认写入」
- 无麦克风权限、非安全上下文：降级为「手动输入一句话」文本框（同一套 parse/apply）

### 7.6 安全与坑

- 仅家庭内网，不做账号体系；语音接口同样无鉴权（与现有 API 一致）
- 误识别风险：必须有确认步或可撤销（可选：apply 后 10 秒内 undo 上一条）
- Docker 下浏览器访问 `http://IP` 时，**部分浏览器禁止麦克风** → 文档写明：用 Chrome + localhost 反代 HTTPS，或改用「打字一句话」降级
- 不把音频默认落盘；若调试需要，写 `data/voice_debug/` 且 gitignore

### 7.7 实现文件（预估）

- `app/modules/items_voice.py` 或 `items.py` 内新路由：parse / apply
- `app/static/app.js`：麦克风 + UI
- `app/static/style.css`：按钮与 sheet
- 可选 `faster-whisper` 或 OpenAI-compatible HTTP STT（仅 7b，写进可选依赖，不塞进默认 requirements）
- 自检：纯文本用例  
  - `加10包方便面` → purchase 10 方便面  
  - `用掉两卷卫生纸` → usage 2  
  - 无条目时 will_create true  

### 7.8 与「打模型」的关系

你说的「语音打模型转文字」可以拆成：

| 步骤 | 要不要模型 |
|------|------------|
| 语音 → 文字 | STT（浏览器或 Whisper），不是聊天模型 |
| 文字 → 加库存指令 | **规则解析通常够**；只有口语很乱时才上 LLM |
| 写库存 | 现有 API，不需要模型 |

**推荐默认：STT + 规则解析**，成本低、可离线、可测。  
若以后口语复杂（「把昨天吃的那袋猫粮补上」），再加可选 LLM 解析开关 `VOICE_LLM_URL`。

### 7.9 明确不做（本期）

- 不做连续对话式多轮管家
- 不做声纹识别 / 区分夫妻账号
- 不做离线端侧大模型包进默认镜像（镜像会暴涨）

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
| 1 | 0 预测 EWMA | 你先大批量登记后收益最大 |
| 2 | 6 周报邮件 | 简单、立刻减轻开面板负担 |
| 3 | 7a 语音（Web Speech + 文本解析） | 体验提升大，可先不做后端 Whisper |
| 4 | 1 Docker 验收 / 2 灯光 props | 按需 |
| 5 | 7b 后端 STT | 环境需要时再做 |
| 推迟 | 4 粘贴导入 | 仍推迟 |
