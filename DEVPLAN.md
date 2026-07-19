# HomeDash DEVPLAN（待办规格书）

> ⬜ 本文档是**待办规格书**，不是已完成记录。  
> 已完成基线以**代码**为准：items/todos 后端、三 Tab 前端。
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

## 已下线：米家设备控制、Uptime 监控、小米云端登录（2026-07-19）

**状态**：整块功能已从代码库移除。原因：家庭日常极少使用，维护开销大且带来密钥/依赖风险。以下原有内容不再维护，仅保留在 git 历史里。

- 删除文件：`app/modules/devices.py`、`app/modules/uptime.py`、`app/xiaomi_login.py`、`app/discover_devices.py`、`config/devices.yaml.example`（整个 `config/` 目录亦已删除）
- 删除依赖：`python-miio`、`pyyaml`、`micloud`
- 删除环境变量：`DEVICES_PATH`、`XIAOMI_USERNAME`、`XIAOMI_PASSWORD`、`KUMA_DB_PATH`、`KUMA_DATA_DIR`、`KUMA_PUBLIC_URL`
- 删除表：`device_preferences`（旧库该表可保留，不再引用；后续用户如需清理可手动 `DROP TABLE`）
- 删除 Tab：「设备控制」「设备&网站监控」；前端仅保留「AI 工作台 / 日用品 / 重点待办」三 Tab

原「待办 1（Docker 部署细化验证）」「待办 2（设备属性控制）」「待办 3（设备状态增强）」「待办 3A（设备展示管理与状态说明）」「待办 4（粘贴导入米家设备）」「待办 10（设备页内管理、全局自由排序与空调温控）」**整节废弃**，不要再按其规格实现或修复。

---

## 当前已完成基线

- 后端：`app/modules/items.py`、`app/modules/todos.py`、`app/modules/notify.py`、`app/modules/ai_workbench.py`、`app/modules/ai_executor.py`、`app/modules/auth.py`、`app/modules/users.py`、`app/modules/setup.py`
- 前端：`app/static/index.html`、`app/static/style.css`、`app/static/app.js`
- 部署：`Dockerfile`、`docker-compose.yml`、`.dockerignore`、`.env.example`
- 日用品预测（**现状**）：EWMA + 安全库存、购买间隔与品类先验兜底（见下方「现状 vs 目标」）

## 待办 0：日用品预测升级（EWMA + 安全库存）— **已完成**

**完成情况（2026-07-13）**：`app/modules/items.py` 已实现相邻 usage 区间的 EWMA、最低库存与到货缓冲安全库存、购买间隔中位数兜底、品类冷启动先验、`confidence` / `method` / `safety_stock` 输出；模块 `__main__` 覆盖算法与兼容字段自检。多条 usage 时最早记录仅作时间锚点，不按一天消耗计入 EWMA，避免少量历史造成速率虚高。

**场景假设**：两口之家、约 120㎡ 固定住房、手动记账、自托管。  
**目标**：少数据也能用、结果可解释、覆盖洗护/纸品/宠物/冷冻食品等多品类。  
**约束**：保持 `predict_item` 纯函数；不新增依赖；不引入 ML 框架。

### 0.1 现状 vs 目标

| | 实现前 | 当前实现 |
|--|------------------|----------------------|
| 日消耗率 | 全历史 `总消耗 / 首末日跨度` | ✅ **EWMA**（近记录权重大） |
| 单条记录 | 跨度兜底 1 天 | 保留兜底；≥2 条再信 EWMA |
| 需购买 | 仅 `days_until_empty < 7` | ✅ 天数阈值 **或** 库存 < 安全库存 |
| 冷启动 | 无用量几乎不预测 | ✅ 品类先验 + `min_stock` |
| 懒人模式 | 无 | ✅ 购买间隔中位数兜底 |
| 输出字段 | daily_rate / days / need_buy / suggested_qty | ✅ 同上 + `confidence` + `method` + `safety_stock` |

### 0.2 推荐算法（实现时按此做）

**主路径：EWMA 日消耗率**

```
输入：usage_logs（按时间排序）、current_stock、today、可选 category / min_stock / purchase_logs

1) 将相邻用量记录换成区间日速率：
    r_i = amount_i / max(1, (date_i - date_{i-1}).days)
    多条记录时首条仅作时间锚点；仅单条时 r_0 = amount_0 / 1
    # ponytail: 避免未知跨度的首条记录抬高少样本 EWMA

2) EWMA：
    rate_0 = 第一个有效区间速率 r_1
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

- `app/modules/items.py`：✅ 已重写 `predict_item`；自检用例已按新公式改
- （可选）`predict_item` 增加参数：`purchases`、`category`、`min_stock`
- 前端：可展示 `confidence`（低/中/高）；无字段时不崩
- 文档：完成后把本待办标完成，并同步 README / AGENTS「现状」描述

**自检必须覆盖：**

1. ✅ 多条用量 → EWMA rate 与全历史平均不同（证明权重生效）
2. ✅ 库存 < 安全库存 → need_buy
3. ✅ 无用量 + min_stock → 合理 need_buy / prior
4. ✅ 冷冻食品脉冲消耗（近期高、早期低）→ 更跟近期
5. ✅ 旧调用方字段仍存在（兼容）

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

## 待办 1（已废弃）：Docker 部署细化验证

> 设备与监控功能已下线，本待办的验收命令中的 `/api/devices`、`/api/uptime/status` 均不再存在。此节保留仅供历史参考。

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

## 待办 2（已废弃）：设备属性控制（最小版）

> 米家设备模块已整体移除，本待办不再实现。

**目标**：先只做灯光亮度，不做全设备属性系统。

**新增 API**：

```http
PUT /api/devices/{name}/props
Content-Type: application/json

{"brightness": 65}
```

**后端文件**：`app/modules/devices.py`  
**规则**：只允许声明属性；越界 400；BLE Mesh 暂不支持属性控制；不新增依赖。

## 待办 3（已废弃）：设备状态增强（可选）

> 米家设备模块已整体移除，本待办不再实现。

`/api/devices/status` 在 power 之外按需返回亮度等 `props`；单台 3s 超时；单台失败不影响其他设备。

## 待办 3A（已废弃）：设备展示管理与状态说明

> 米家设备模块已整体移除，本待办已废弃。

**完成情况（2026-07-13）**：已新增 `device_preferences` 展示偏好表、设备隐藏/恢复 API 和设备页管理弹窗。隐藏状态持久化于 SQLite，不改 YAML；默认设备列表与状态刷新跳过隐藏设备。状态响应新增 `updated_at` 与脱敏 `error`，并已移除未实现的设备属性和粘贴导入假入口。

> 后续待办 10 已将本待办的管理弹窗替换为设备页内编辑模式，并在原偏好表上增加全局排序。

**目标**：设备页保持现有开关控制，补充可解释的在线状态；用户可隐藏不想在面板展示的设备，并随时恢复。隐藏只影响 HomeDash 展示，绝不修改 `config/devices.yaml`、不删除设备凭据、不下发设备命令。

### 3A.1 数据与接口

- 在 SQLite 增加 `device_preferences(device_name PRIMARY KEY, hidden, updated_at)`，仅保存展示偏好。
- `GET /api/devices` 默认只返回可见设备；`?include_hidden=true` 返回全部，并附 `hidden` 字段。
- `PUT /api/devices/{name}/visibility` body：`{"hidden": true|false}`；名称不存在返回中文 404。
- `GET /api/devices/status` 默认只查询可见设备；`?include_hidden=true` 才查询全部。
- 状态结果保留 `name`、`online`、`power`，新增 `updated_at`；查询失败时新增简短中文 `error`，不得含 token、host、异常栈。
- 隐藏不是权限控制：已有 on/off/command 接口行为不变。

### 3A.2 前端

- 设备页增加「管理设备」弹窗，列出全部 YAML 设备，可隐藏或恢复显示。
- 设备卡片只显示可见设备；工具栏提示隐藏数量。
- 移除尚未实现的亮度、色温、温度、模式等属性控件和“开发中”假入口；灯光及其他设备只保留当前开关控制。

### 3A.3 验收

1. 隐藏后默认设备列表和状态刷新均不出现该设备；`include_hidden=true` 仍可查到并标为 hidden。
2. 恢复显示后设备重新出现；重启后隐藏偏好仍保留。
3. `devices.yaml` 不被修改；隐藏设备的开关接口仍可用。
4. 单台状态失败不影响其他设备，前端可显示状态获取失败提示。

### 3A.4 明确不做

- 不实现灯光亮度、色温和其他设备属性控制。
- 不做粘贴导入设备，不写回 YAML。
- 不做按房间排序、别名等额外设备元数据。

## 待办 4（已废弃）：粘贴导入米家设备

> 米家设备模块已整体移除，本待办不再实现。

**状态**：先不做。当前手写 `config/devices.yaml` 足够。  
真实设备多到维护 YAML 明显痛苦时再做 `POST /api/devices/import`。

---

## 待办 6：周报邮件提醒（库存/需购买 + **重点待办**）— **已完成**

**完成情况（2026-07-13）**：已新增 `app/modules/notify.py` 与 `/api/notify/config`、`/test`、`/weekly`。周报通过 QQ 邮箱 SMTP 汇总重点待办和需购买日用品；465 端口走 SSL，其他端口走 STARTTLS；发送在 `asyncio.to_thread` 中运行。SMTP 凭据与两个收件人仅从 `.env` 读取，接口不返回授权码。

**难度**：★☆☆☆☆ 简单  
**目标**：每周自动发一封中文 SMTP 邮件，汇总：
1）日用品剩余 / 需要购买；  
2）**家庭重点待办事项**（未完成的高优先级 to-do）。  
**场景**：两口之家周末采购 + 家务/杂事提醒，一封邮件看完。  
**邮件通道（已定）**：**QQ 邮箱 SMTP**（授权码，不是 QQ 登录密码）。

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

### 6.3 QQ 邮箱 SMTP 配置（`.env` / `.env.example`）

> 实现前用户需在 QQ 邮箱网页设置开启 SMTP，并生成 **授权码**。
> **禁止**把真实密码写进仓库。

| 变量 | QQ 邮箱推荐值 | 说明 |
|------|--------------|------|
| `SMTP_HOST` | `smtp.qq.com` | 固定 |
| `SMTP_PORT` | `465` | SSL；也兼容 `587` STARTTLS |
| `SMTP_USER` | `your-qq-number@qq.com` | 完整 QQ 邮箱地址 |
| `SMTP_PASSWORD` | - | QQ 邮箱 SMTP 授权码 |
| `SMTP_FROM` | `HomeDash <your-qq-number@qq.com>` | 发件显示名 |
| `NOTIFY_TO` | `person-a@example.com,person-b@example.com` | 两位收件人，英文逗号分隔 |
| `NOTIFY_CRON` | `0 18 * * 0` | 每周日 18:00 |
| `NOTIFY_TZ` | `Asia/Shanghai` | |
| `NOTIFY_ENABLED` | `true` | 总开关 |
| `NOTIFY_ONLY_WHEN_NEED_BUY` | `false` | 名称保留；语义扩展为「需买与待办都空才跳过」时可再加 `NOTIFY_SKIP_IF_EMPTY` |
| `NOTIFY_TODO_LIMIT` | `20` | 邮件最多列几条重点待办 |
| `HOMEDASH_PUBLIC_URL` | `http://192.168.x.x:8088` | 正文面板链接 |

QQ 邮箱注意：SMTP 授权码；国内出网；家庭周报无需 OAuth。

```env
# --- 邮件周报（QQ 邮箱 SMTP）---
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=your-qq-number@qq.com
SMTP_PASSWORD=your-qq-smtp-authorization-code
SMTP_FROM=HomeDash <your-qq-number@qq.com>
NOTIFY_TO=person-a@example.com,person-b@example.com
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

- `app/modules/notify.py`：✅ 组信（todos + items）+ SMTP
- 依赖待办 8 的查询函数，如 `list_open_todos(limit)`
- `app/main.py`：✅ 挂载；定时调度由宿主机/Hermes cron 调 `/api/notify/weekly`
- `.env.example`、README：✅ 已同步

### 6.6 明确不做（本期）

- 不做每条待办单独每日邮件（周报合并一封）
- 不做 QQ/163 登录向导、OAuth
- 不做推送 App

---

## 待办 8：重点待办事项（家庭 To-Do）— **已完成**

**完成情况（2026-07-13）**：已新增 `todos` 表、`app/modules/todos.py` 面板 CRUD 与 `/api/agent/todos/*` 接口、第四个「重点待办」Tab、`AGENT_API_TOKEN` 配置模板。HomeDash 只提供待办查询、创建和回写接口，不主动推送、不内置调度；QQ/微信实际投递由外部 Hermes 或带 skill 的 AI 自行查询并完成。

**难度**：★★☆☆☆  
**目标**：记录家里**重点待办**（家务、维修、预约、账单等），面板可管理，并进入 **SMTP 周报**（待办 6）。
**不是**软件开发任务列表，是「家里这两周必须盯的事」。

### 8.1 产品范围

**要做：**

- 新增 / 编辑 / 完成 / 删除重点事项
- 当前面板字段：标题、备注、优先级、截止日期、图片附件（缩略图）、状态；负责人及提醒字段不在面板展示
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
                    QQ 通道                          微信通道         SMTP 周报
                 (已有 qqbot)                    (预留/插件)       (待办 6 直发)
```

| 能力 | 谁负责 |
|------|--------|
| 待办 CRUD、截止日、优先级 | **HomeDash** |
| 提醒时间 `remind_at`、频道意图 | **HomeDash** 存；面板可编辑 |
| 定时轮询 / cron「每 5～15 分钟拉 due」 | **外部 home agent / AI** 按自身策略决定是否查询 |
| 发到 QQ / 微信 | **home agent** 调平台 API（不进 HomeDash 进程） |
| 每周汇总邮件 | **HomeDash** SMTP（待办 6），与 IM 并行不互斥 |

**Agent 侧推荐调度伪逻辑（文档给实现者，不写进镜像）：**

```text
在 Hermes / AI 自身的定时任务或被唤醒时（非 HomeDash 主动推送）:
  GET /api/agent/todos/due?within_minutes=15
  for item in items:
    if "qq" in channels:  send_qq(item.message)
    if "wechat" in channels: send_wechat(item.message)  # 通道就绪后
    POST /api/agent/todos/{id}/remind-fired
```

也可由 agent **创建时**直接登记 Hermes cron（把 `external_ref` 写回 todo），到期只发一条；due 查询作兜底。HomeDash 不创建或主动执行 cron。

### 8.5 前端（第四 Tab）

`index.html` 增加 Tab：`日用品 | 待办`（**允许改骨架**）。

- 列表：标题、优先级、截止日期、图片缩略图
- 表单：标题、备注、优先级、截止日期与图片上传/剪贴板粘贴（最多 5 张，每张 10MB）；不展示负责人及提醒相关字段
- 过期标红；点圆圈完成
- 中文 + 米家浅色风格

### 8.6 与 AI 工作台（待办 7）

AI 工作台一期即包含 `todo.create` / `todo.complete` / `todo.update` 等 op，与本模块执行器对接。  
表单 CRUD 与 AI 写库**共用**同一套 todos API/内部函数，避免两套逻辑。

### 8.7 实现文件（预估）

- `app/database.py`：✅ `todos` 表（含 remind_*）
- `app/modules/todos.py`：✅ CRUD + summary + agent 路由 + 拼 `message`
- `app/main.py`：✅ 挂载
- `app/static/*`：✅ 第四 Tab
- `.env.example`：✅ `AGENT_API_TOKEN=`
- README：✅ 增加 home agent 对接说明
- 可选：`docs/agent-todos.md` 给 Hermes 技能引用（若实现时需要再拆）

### 8.8 明确不做（本期）

- **HomeDash 内不实现**微信/QQ 登录协议、iPad 协议、企业微信机器人本体
- 不做子任务 / 看板 / 番茄钟
- 本待办 8 不做多人登录权限（assignee 只是标签）；后续已由独立待办 9 规划，不属于待办 8 的实现范围
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

## 待办 7：AI 工作台（自然语言 → 结构化写库）— **已完成**

**完成情况（2026-07-13）**：已新增 `ai_workbench.py`、`ai_executor.py`、`ai_audit` 表和第五个「AI 工作台」Tab。LLM 仅输出经服务端校验的白名单 JSON；`apply` 仅调用 items/todos 领域函数，禁止任意 SQL 与设备控制。LLM 未配置或 `AI_ENABLED=false` 时 API 优雅拒绝，不影响应用启动。

**加固（2026-07-15）**：修复字段名不归一导致的空名物品创建 bug（LLM 输出 `item_name` 时执行器只读 `name`，建出 `name=''` 物品）。①`_validate` 将 `item_name` 归一为 `name`，并对 purchase/usage/set_stock/update 强制校验物品标识；②`create_item_record` 拒绝空名；③prompt 显式约定字段名为 `name`。同时补齐全流程审计：parse 与 apply **成败均落 `ai_audit`**，新增 `stage/session_id/llm_model/llm_reply/confidence/duration_ms/error/before_json/after_json` 列（`_ensure_columns` 给旧库容错补列），前端新增「操作溯源」视图按 session 串联展示。已修复历史空名物品（id=22 改名「卫生间纸巾」+ 补分类「纸品」）。

**联网搜索（2026-07-19）**：家庭顾问聊天模式新增 Brave Search 联网搜索能力。通过 OpenAI function calling 机制，LLM 可自主决定何时搜索网络获取实时信息（天气、新闻、百科等）。Brave API Key 通过环境变量 `BRAVE_API_KEY` 或设置页面配置（`data/brave_config.json`），未配置时聊天行为不变。搜索最多 3 轮工具调用循环，超时 15 秒，失败不阻断对话。

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

建议独立 Tab：`日用品 | 待办 | **AI**`（实现时 Tab 名「AI」或「助手」）。

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

- `app/modules/ai_workbench.py`：✅ prompt、LLM 调用、校验
- `app/modules/ai_executor.py`：✅ 按 op 调 items/todos 内部函数
- `app/database.py`：✅ `ai_audit` 表
- `app/static/*`：✅ AI Tab 工作台 UI
- `.env.example`、README「AI 工作台」：✅ 已同步
- 自检：✅ 非法 op 拒绝；Docker 验证 apply 改库与审计

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

## 待办 9：面板登录、长期会话与管理员用户管理 — **已完成**

**完成情况（2026-07-17）**：已新增 `users` / `auth_sessions` 表、`app/modules/auth.py`、`app/modules/users.py` 与统一面板 API 鉴权。首次启动创建管理员，密码使用标准库 `scrypt` 散列；会话 Cookie 默认 180 天并滑动续期，数据库只保存 token 摘要。普通用户可使用业务功能但无法访问 `/api/setup/*` 与 `/api/admin/*`；管理员可在设置页新增普通用户/管理员、启停、重置密码和删除用户。右上角已改为三点账户菜单；现有 `/api/agent/todos/*` 继续使用独立 `AGENT_API_TOKEN`。

**目标**：HomeDash 面板不再匿名访问。用户首次用用户名和密码登录后获得长期会话，日常使用基本无需重复登录；区分普通用户与管理员，只有管理员可以进入系统设置并管理用户。

> 本待办只给浏览器面板及其业务 API 增加认证。现有 `/api/agent/todos/*` 继续使用 `AGENT_API_TOKEN`，不要求外部 Hermes / home agent 建立浏览器会话。

### 9.1 角色与权限

| 能力 | 普通用户 `user` | 管理员 `admin` |
|------|-----------------|----------------|
| 登录、退出、查看自己的账户信息 | ✅ | ✅ |
| 使用日用品、重点待办、AI 工作台 | ✅ | ✅ |
| 查看或调用 `/api/setup/*` 系统配置 | ❌ | ✅ |
| 查看用户列表、新增/禁用/删除用户、重置密码 | ❌ | ✅ |
| 创建另一个管理员 | ❌ | ✅ |

- 权限必须在 FastAPI 后端校验；前端隐藏入口只负责交互，不能作为安全边界。
- 未登录访问面板业务 API 返回中文 `401`；普通用户访问管理员 API 返回中文 `403`。
- 普通用户右上角“三个点”菜单只显示「退出登录」；管理员菜单显示「系统设置」「退出登录」。
- 普通用户不渲染设置 Tab；直接请求或构造管理员 URL 仍必须被后端拒绝。
- 管理员权限覆盖现有全部 `/api/setup/*`，包括 LLM、SMTP、Brave 及测试接口。

### 9.2 首个管理员与登录流程

- 数据库无用户时，仅允许进入「创建首个管理员」初始化页；创建成功后关闭公开初始化入口。
- 不内置 `admin/admin` 等默认账号，不在代码、文档、镜像或 `.env.example` 中写默认密码。
- 登录成功设置长期会话 Cookie，默认有效期 **180 天**；正常使用可滑动续期，达到长期免登录效果。
- Cookie 必须使用 `HttpOnly`、`SameSite=Lax`、`Path=/`；HTTPS 部署时启用 `Secure`。前端不得把密码或会话 token 写入 `localStorage` / `sessionStorage`。
- 退出登录、账户被禁用/删除、密码被重置时，立即废止相关会话。
- 前端启动先请求当前用户；未登录显示登录/初始化页面，登录后进入 SPA；任意业务请求收到 `401` 时统一回登录页。

### 9.3 数据模型

在 `app/database.py` 的 `SCHEMA` 新增：

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now')),
    last_seen_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

- `role` 只允许 `user` / `admin`；服务端写入前做白名单校验。
- 密码使用 Python 标准库 `hashlib.scrypt` + 每用户随机 salt；不新增认证 SDK，不保存明文或可逆密码。
- 会话原始 token 使用 `secrets.token_urlsafe` 生成，只放 Cookie；数据库只保存摘要，日志和 API 不得返回原始 token。
- 登录失败统一返回「用户名或密码错误」，不得泄露用户名是否存在。
- 可在读取有效会话时顺便删除过期会话；本期不引入 Redis、定时清理服务或连接池。

### 9.4 API

```http
GET  /api/auth/bootstrap-status       # 是否需要创建首个管理员
POST /api/auth/bootstrap-admin        # 仅 users 为空时可调用
POST /api/auth/login                  # 设置长期 HttpOnly Cookie
POST /api/auth/logout                 # 清除当前会话与 Cookie
GET  /api/auth/me                     # 当前用户 id/username/role

GET    /api/admin/users               # 管理员：用户列表，不返回密码字段
POST   /api/admin/users               # 管理员：新增 user/admin
PUT    /api/admin/users/{id}          # 管理员：角色、启用状态等白名单字段
PUT    /api/admin/users/{id}/password # 管理员：重置密码并废止该用户全部会话
DELETE /api/admin/users/{id}          # 管理员：删除用户并废止会话
```

- 管理员不能删除、禁用或降级自己当前登录的账户。
- 系统始终至少保留一个启用的管理员；删除、禁用或降级最后一个管理员必须返回中文 `400`。
- 用户名去除首尾空白后唯一；长度、允许字符和密码最小长度由后端统一校验，错误返回中文 `detail`。
- `/api/agent/todos/*` 保持现有 token 行为，不接收浏览器 Cookie 作为替代认证。
- 静态登录页可匿名读取；除 bootstrap/login/logout 与必要静态资源外，现有面板 `/api/*` 均要求有效会话，再按管理员权限细分。

### 9.5 前端

- `index.html` 保持单页架构，增加登录态/初始化态容器，不引入前端框架。
- 右上角按钮改为“三个点”菜单；普通用户只有退出，管理员增加系统设置。
- 设置页增加「用户管理」区：用户列表、新增用户/管理员、禁用/启用、重置密码、删除。
- 删除、禁用、重置密码等操作必须有中文确认提示；API 错误通过 toast 展示。
- 不在 HTML、JS、日志或 toast 中展示密码哈希、salt、完整会话 token。

### 9.6 实现文件（预估）

- `app/modules/auth.py`：密码散列、会话、当前用户依赖、登录/退出/初始化 API
- `app/modules/users.py`：管理员用户管理 API
- `app/database.py`：`users` / `auth_sessions` 表与旧库兼容
- `app/main.py`：挂载认证与用户路由，并统一保护面板业务 API
- `app/static/index.html`、`app/static/app.js`、`app/static/style.css`：登录页、账户菜单、用户管理
- README / AGENTS / 本文件：完成后同步实际行为、API、模块地图和状态

### 9.7 验收

1. 全新空数据库只能创建首个管理员；创建后再次调用 bootstrap 返回拒绝。
2. 管理员登录后可刷新页面、重启服务并继续使用；Cookie 中没有明文密码，数据库没有原始 session token。
3. 普通用户可使用业务页面，但看不到系统设置；直接请求任一 `/api/setup/*` 或 `/api/admin/users*` 返回 `403`。
4. 管理员可新增普通用户和另一个管理员；普通用户不能调用用户管理 API。
5. 禁用/删除用户或重置密码后，该用户已有会话立即失效。
6. 不能删除、禁用或降级当前管理员，也不能移除最后一个启用管理员。
7. 退出后原 Cookie 无法再次访问业务 API；错误信息与 UI 文案均为中文。
8. `python -m app.modules.auth` 与 `python -m app.modules.users` 自检覆盖密码校验、会话摘要、角色边界和最后管理员保护。
9. 现有 `AGENT_API_TOKEN` 验收仍通过，外部 agent 接口不因浏览器登录改造而失效。

### 9.8 明确不做

- 不做 OAuth、微信/QQ 扫码登录、短信验证码、邮箱找回密码或第三方 SSO。
- 不做复杂 RBAC、权限组、逐设备/逐物品授权；本期只有 `user` / `admin` 两种角色。
- 不做“记住密码”明文存储，不把 token 放入 localStorage。
- 不引入 ORM、Redis、认证服务器或重量级用户框架。
- 不做用户自助注册；首个管理员创建完成后，只能由管理员新增账户。

---

## 待办 10（已废弃）：设备页内管理、全局自由排序与空调温控

> 米家设备模块已整体移除，本待办已废弃。

**完成情况（2026-07-17）**：设备控制页已取消类型强制分组和管理弹窗，改为单一全局顺序网格；管理模式可在当前页隐藏/恢复，并支持桌面拖动和移动端长按拖动。`device_preferences` 新增 `sort_order`，完整顺序由事务更新，隐藏设备保留原位置。空调只有在 YAML 显式声明温控能力后才显示目标温度、加减和选择控件；WiFi 命令、查询属性及云端 MIOT `siid/piid` 均做白名单/显式校验，越界或步长错误不下发。普通设备列表仅返回安全展示字段，不再返回 token、host、did 或协议参数。

**依赖**：先完成待办 9；设备展示管理与温控对普通用户、管理员均开放，但必须登录。

**目标**：移除现有「管理设备展示」弹窗，直接在设备控制页完成隐藏、恢复和拖动排序；设备不再被类型分组强制排序，而是按全家共享的自由顺序展示。已明确声明温控能力的空调可在卡片上直接调节目标温度。

### 10.1 页面内管理模式

- 设备页「管理设备」按钮切换当前页面进入/退出编辑模式，不打开详情页或管理弹窗。
- 编辑模式中每张卡片显示拖动手柄和「隐藏」按钮；页面下方显示隐藏设备区，可直接恢复。
- 桌面端支持鼠标拖动，移动端支持触摸/长按拖动；不引入前端拖拽库。
- 退出编辑模式后保留正常开关与温控卡片；编辑过程中避免误触开关。
- 隐藏只影响 HomeDash 展示，不删除设备、不写回 `config/devices.yaml`、不改变设备控制 API 的可用性。

### 10.2 全局自由排序

- 扩展 `device_preferences`，新增 `sort_order INTEGER`；旧库通过 `_ensure_columns` 容错补列。
- 排序是**所有用户共享的全局顺序**，不是每用户偏好。
- 取消前端按灯光、空调、插座等类型分组后再固定排序；可把任意类型设备拖到任意位置。
- 松手后一次提交完整设备名称顺序，后端校验名称无重复且与当前设备集合匹配，并在事务中更新。
- 新出现且没有 `sort_order` 的设备排在已有顺序末尾；隐藏设备保留原顺序，恢复后回到原位置。
- `GET /api/devices` 与 `GET /api/devices?include_hidden=true` 均按 `sort_order` 返回；相同/空顺序使用 YAML 原始顺序稳定兜底。

建议接口：

```http
PUT /api/devices/order
Content-Type: application/json

{"device_names":["客厅空调","玄关灯","电视插座"]}
```

### 10.3 空调温控能力

- 只有 `type: airconditioner` 且配置中显式声明温控能力的设备显示调温控件；不得仅凭名称或类型猜 `siid/piid`。
- 建议在 `config/devices.yaml` 的对应设备增加可选配置：

```yaml
temperature:
  min: 16
  max: 30
  step: 1
  siid: 2       # BLE/云端 MIOT 使用
  piid: 3       # BLE/云端 MIOT 使用
  command: set_temperature  # WiFi miio 使用；按实际 model 配置
```

- `min` / `max` / `step` 必须由后端校验；默认值只能在规格明确且设备协议验证后使用，不能静默向未知设备发送命令。
- BLE/云端设备通过已声明 `siid/piid` 调 MIOT 属性；WiFi 设备通过白名单 `command` 调用，并继续放入 `asyncio.to_thread`，不得阻塞事件循环。
- 卡片显示目标温度与 `−` / `+` 控件；状态查询能可靠获取时同步目标温度，暂时不可获取时显示最后一次成功设置值或「温度未知」，不得伪装成实时室温。
- 调温失败只影响当前设备，toast 显示脱敏中文错误，不输出 token、host、did 或异常栈。
- 新增专用白名单接口，不要求前端拼接 `/command` 原始命令：

```http
PUT /api/devices/{name}/temperature
Content-Type: application/json

{"temperature":26}
```

### 10.4 数据与返回字段

- `device_preferences` 最终至少包含 `device_name`、`hidden`、`sort_order`、`updated_at`。
- `/api/devices` 的设备项可新增脱敏后的 `capabilities.temperature`，只包含前端所需的 `min/max/step`，不得返回 WiFi command、MIOT `siid/piid`、token、host 或 did。
- `/api/devices/status` 对支持设备可新增 `target_temperature`；字段缺失时前端必须向后兼容。
- 设备排序和隐藏写入偏好表；空调协议能力继续来自本地 YAML，不写入 SQLite，不提供普通用户编辑协议参数的入口。

### 10.5 实现文件（预估）

- `app/database.py`：为 `device_preferences` 增加 `sort_order`
- `app/modules/devices.py`：排序、能力脱敏序列化、温度范围校验与 WiFi/MIOT 调用
- `app/static/app.js`、`app/static/style.css`：页面内编辑、原生拖动、隐藏区、空调温控
- `config/devices.yaml.example`：仅增加无真实凭据的空调能力示例
- README / AGENTS / 本文件：完成后同步实际行为、API、模块地图和状态

### 10.6 验收

1. 管理设备时不打开弹窗或详情页；可在当前设备页隐藏、恢复设备。
2. 不同类型设备可以自由互换位置；刷新页面、重新登录、重启服务后顺序保持，并对所有用户一致。
3. 隐藏设备不出现在默认列表和默认状态查询中；恢复后回到隐藏前的全局位置。
4. 重复名称、未知名称、缺少当前设备的非法排序请求返回中文 `400`，数据库顺序不发生部分更新。
5. 未声明温控能力的空调仍只有开关，不显示无效温控。
6. 已声明能力的 WiFi/MIOT 空调可在卡片上按 `step` 调温；越界或步长不合法返回中文 `400`，不下发设备命令。
7. 单台空调查询/设置失败不影响其他设备；响应与日志无 token、host、did 等敏感信息。
8. 普通用户与管理员均可排序、隐藏和调温；未登录请求返回 `401`。
9. `python -m app.modules.devices` 自检覆盖稳定排序、隐藏恢复位置、能力脱敏、温度边界与命令路由；无真实设备时优雅跳过联调。

### 10.7 明确不做

- 不做独立设备详情页、独立设备管理页或管理弹窗。
- 不保留按类型强制分组；本期采用全局自由排序。
- 不做每用户独立设备顺序、房间分组、别名或自动场景。
- 不自动探测或猜测未知空调的 MIOT 属性，不向未声明能力的设备发送温控命令。
- 不做空调模式、风速、扫风、睡眠模式、定时等完整遥控器；本期只有开关和目标温度。
- 不允许普通用户编辑 YAML、token、host、did、siid/piid 等系统配置。

---

## 待办 11：旅游计划与 AI 行李推荐 — **已完成**

**完成情况（2026-07-19）：** 新增 `travel_plans` 表、`app/modules/travel.py` 与「旅游计划」Tab。用户可保存目的地、起止日期、人数、活动和备注；复用系统 OpenAI-compatible LLM 配置生成结构化行李清单。配置 Brave Search 时先检索目的地及行期的天气资料，未配置时返回结果明确标注为季节常识估算。清单支持勾选、增删及修改名称、数量、分类、备注并持久化。

**加固（2026-07-19）：** `recommend` 复用 `ai_workbench._chat_completion`（自带 5xx/超时重试与 `response_format=json_object` 兜底）、按物品名保留用户已勾选的 `packed` 状态、单项格式异常跳过而非整张丢弃；Brave 返回非 JSON（验证码/HTML 200）时降级而非冒泡 500；`weather_summary` 为 `null` 不再显示成字面量 `None`；透传 `_response_json` 的「Base URL 像网页地址」等精确提示。`update_plan` 改期后清空旧天气避免误导、先查存在再校验日期（404 优先）；目的地纯空白在服务端拒绝。前端：勾选失败回滚并以服务端为准重载、重新生成前确认、422 错误可读化（`detailMsg`）、`structuredClone` 改为展开拷贝、日期默认用本地时区、弹窗打开时不拦截滑动切 Tab、补显备注、加载失败保留新建入口；修复引用未定义 CSS 变量（`--border`/`--bg` → `--line`）与 `.modal-wide` 被 `.modal-content` 的 `max-width` 压失效的问题。

**验收：**

1. 行程 CRUD 与日期边界返回中文错误；最长 90 天、人数 1–30。
2. 无 LLM 配置时优雅返回中文错误，服务仍可启动，手动清单仍可使用。
3. 联网天气可用时标注 `Brave 网络搜索 + LLM`；不可用时不得伪装成实时天气。
4. LLM 仅返回并写入行李 JSON，不执行 SQL；服务端校验最多 35 条 AI 推荐、100 条用户清单。
5. `python -m app.modules.travel` 自检通过；原有模块自检不回归。

**明确不做：** 地图/路线、酒店机票预订、自动定时刷新天气、天气预警推送、医疗诊断、多人实时协作。

---

## 待办 12：物品多图与共享图片基础设施 — **已完成**

**完成情况（2026-07-19）：** 抽 `app/modules/image_store.py`（sniff/save/unlink/decode/images_lock），todos 迁移复用；items 加 `images` 列 + 3 个图片端点（上传/读取/删除，最多 5 张/10MB）+ 删除清文件；列表回 `has_images`、详情回 `images`。前端复用 `showImagePreview` 放大浏览器，物品表单支持选择/粘贴上传、保存后上传（失败可重试）、详情缩略图、列表 📷 标记。

**验收：** 上传/粘贴/删除/详情放大（item + todo 回归）；列表不渲染缩略图只 📷；`python -m app.modules.{image_store,items,todos}` 自检通过。

**明确不做：** 图片压缩/水印/EXIF、图片字节进 LLM、列表渲染缩略图、重命名 `.todo-image-*` CSS 类（作 legacy 共用）。

---

## 待办 13：收纳知识库（placements）— **已完成**

**完成情况（2026-07-19）：** 新增 `placements` 表（description/location/images/candidate_items/item_ids/confirmed）+ `app/modules/placements.py`（CRUD + 图片端点 + `/suggest` LLM 关联候选 + 自检）。日用品 Tab 加「📍 记录收纳」入口：描述主导表单 + 可选照片 → 保存 → LLM 给候选 → 候选确认弹窗（勾选+confidence+位置+手动搜物品）→ 确认。AI 工作台 `_snapshot` 注入最近 20 条已确认 placements + 新增 `query.placements` 工具（按描述/位置 LIKE 检索）。

**验收：** 记一条「猫粮塞阳台柜」→ `/suggest`（AI 未配置返 503 仍可手动选）→ 勾选确认 → chat 问「猫粮放哪了」命中；`python -m app.modules.placements` 自检通过。

**明确不做：** 图片传 LLM（仅人眼对照）、placements 提醒/周报、多用户协作、OCR、FTS/向量检索（只用 LIKE）、独立列表视图（v1 靠 AI chat 检索）。

---

## 待办 14：物品表单动态下拉（分类/单位/存放地点）— **已完成**

**完成情况（2026-07-19）：** 新增 `GET /api/items/facets`（注册在 `/items/{id}` 前），返回分类/单位/地点（按使用频次降序）+ 默认值。前端 `showItemForm` 改 async 拉取并渲染三个 `<datalist>`，CRUD 后失效缓存。

**验收：** 空库显示默认分类/单位；新建用新分类后下次开表单该分类靠前；自由输入非列表值仍可保存。

**明确不做：** 分类 CRUD 管理界面、别名/同义词、强制选下拉值（保留 free-type）。

---

## 待办 15：旅游行李编辑器美化 + 常用物品快捷添加 — **已完成**

**完成情况（2026-07-19）：** `showPackingEditor` 重写：顶部按分类的常用物品 chip（证件/衣物/洗护/电子/药品/其他，如内衣、充电宝、身份证…），点击即加入清单且防重复（已加置灰）；编辑行放宽、对齐。

**验收：** 点 chip 立即出现一行且可编辑；重复点不叠加；保存正确落库。

**明确不做：** 物品图库/云端模板、拖拽排序。

---

## 修复（2026-07-19，非 DEVPLAN 待办，随本轮提交）

- **AI 操作溯源空记录**：`/ai/chat` 原来每个工具调用写一条几乎空的审计（N 个物品 → N+1 条）；改为循环累计 before/after（`_snapshot_target`）、结束写一条带 `actions/results/before_json/after_json` 的汇总行（对齐 `apply()`），并提取 `TOOL_ITEM_OPS/TOOL_TODO_OPS` 共享映射使该行可撤回；`GET /ai/audit` 过滤历史遗留的空 chat 行。
- **啤酒等物品误报紧急**：单条消耗记录不再被当作「一天用完」虚高日均速率（改用品类先验/最低库存兜底）；「紧急」红标只在库存 ≤ 最低库存时出现，库存高于最低值最多显示「偏低」。

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
| 1 | Hermes / 带 skill 的 AI 按需查询 due → QQ/微信 | HomeDash 接口就绪后配，不属于 HomeDash 主动推送功能 |
| 2 | 1 Docker 验收 / 2 灯光 props | 按需 |
| 推迟 | 4 粘贴导入 | 仍推迟 |
