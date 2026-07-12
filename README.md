# 🏠 HomeDash

家庭自托管管理面板：**米家设备控制 · Uptime 监控 · 日用品库存预测 ·（规划）重点待办 · Gmail 周报 · AI 工作台**。

中文 UI，无前端框架，Docker 可一键部署。

| 文档 | 用途 |
|------|------|
| [`AGENTS.md`](./AGENTS.md) | **AI 独立开发强制规则**（权威顺序、DoD、禁区、提示词） |
| [`DEVPLAN.md`](./DEVPLAN.md) | 待办规格书（⬜ 未完成项） |
| [`DESIGN.md`](./DESIGN.md) | 设计背景（可能滞后，以代码与 AGENTS 为准） |

> **给编码 AI：** 本仓库默认由 agent 独立改代码。开始任何功能前先读完 `AGENTS.md` §0，再读 `DEVPLAN.md` 对应待办；完成时必须自检 + 文档同步 + 无密钥入库。

---

## 功能总览

| 模块 | 状态 | 说明 |
|------|------|------|
| 米家设备 | ✅ 已实现 | WiFi 局域网 `python-miio` + BLE Mesh 云端 MIOT |
| Uptime 监控 | ✅ 已实现 | 只读挂载 Uptime Kuma SQLite，60s 缓存 |
| 日用品库存 | ✅ 已实现 | CRUD + 消耗/购买 + 线性预测 + 购物清单 |
| 设备状态 | ✅ 已实现 | `GET /api/devices/status` best-effort |
| Docker 部署 | ✅ 已实现 | `Dockerfile` + Compose，端口/Kuma 目录可配 |
| 日用品预测升级 | ⬜ 规划中 | EWMA + 安全库存（DEVPLAN 待办 0） |
| 重点待办 | ⬜ 规划中 | 家庭 to-do + home agent 接口（待办 8） |
| Gmail 周报 | ⬜ 规划中 | 待办 + 需购买邮件（待办 6） |
| AI 工作台 | ⬜ 规划中 | 自然语言 → 白名单写库（待办 7） |

### 1. 米家设备控制（已实现）

- **WiFi**：python-miio 局域网直控，不经 HA
- **BLE Mesh**：micloud + 小米云端 MIOT（墙壁开关等）
- 开关 + 自定义命令透传；前端按类型双列卡片（米家浅色风格）
- 云端设备显示「云端」标签；`GET /api/devices/status` 查 online/power

### 2. Uptime 监控（已实现）

- 直读 Kuma `kuma.db`（`mode=ro`，避免锁竞争）
- 60 秒缓存，读失败保留旧数据
- 展示 up/down、延迟

### 3. 日用品管理（已实现 + 规划增强）

**已实现：**

- 记录消耗 / 购买，自动改库存
- **预测（现状）**：全历史线性日均 → 预计耗尽；`<7` 天需买；建议量覆盖约 30 天
- 购物清单汇总

**规划中**（未实现，见 `DEVPLAN.md`）：

| 待办 | 内容 |
|------|------|
| 0 | EWMA + 安全库存 + 品类先验（两口·120㎡） |
| 8 | 重点待办事项 + `/api/agent/todos/*`（供 home agent 投递 QQ/微信） |
| 6 | Gmail 周报 = 重点待办 + 需购买/库存 |
| 7 | **AI 工作台**：人话 → LLM JSON 动作 → 确认后写库存/待办（**禁止直接 SQL**） |

**集成约定：**

- 微信 / QQ 消息由外部 **home agent（如 Hermes）** 发送，HomeDash 只提供数据与 `remind-fired` 回写
- AI 只通过 **白名单动作总线** 改业务表，不执行任意 SQL

---

## 技术栈

### 当前（代码已用）

| 层 | 选型 | 说明 |
|----|------|------|
| 语言 / 运行时 | Python 3.12 | 类型写法 `X \| None` |
| Web | FastAPI + Uvicorn | 异步 API |
| 数据库 | SQLite + aiosqlite | **无 ORM**，裸 SQL，`CREATE TABLE IF NOT EXISTS` |
| 米家 WiFi | python-miio | 局域网 `Device.send` |
| 米家 BLE Mesh | micloud | 云端 MIOT prop set/get |
| 配置 | PyYAML + python-dotenv | `devices.yaml`、`.env` |
| HTTP 客户端 | httpx | 预留给 AI/外部 API；现有代码可复用 |
| 前端 | HTML + CSS + vanilla JS | **无构建、无 React/Vue** |
| 部署 | Docker / Compose | 官方 `python:3.12` 镜像 |

**依赖（`requirements.txt`）：**

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

不引入：ORM、前端打包器、Redis、jinja2、pytest（用模块 `__main__` 自检）。

### 规划中将用到的能力（不预先塞进默认镜像）

| 能力 | 方案 | 对应待办 |
|------|------|----------|
| 邮件 | stdlib `smtplib` + Gmail App Password | 6 |
| AI | OpenAI-compatible Chat（`LLM_BASE_URL` + Key），服务端执行器写库 | 7 |
| 语音输入 | 浏览器 Web Speech 或可选 STT；**不是**必须本地大模型 | 7 |
| IM 提醒 | home agent 调 `/api/agent/todos/due` 后发 QQ/微信 | 8 |
| 定时 | Compose 内调度 **或** 宿主机/Hermes cron 调 notify API | 6 / 8 |

---

## 技术方案

### 总体架构

```
浏览器（米家浅色 SPA：设备 / 监控 / 日用品 /〔待办〕/〔AI〕）
        │  HTTP /api/*
        ▼
┌───────────────────────────────────────────────┐
│                 FastAPI (app/main.py)           │
│  devices │ uptime │ items │〔todos〕│〔ai〕│〔notify〕│
└─────┬─────────┬──────────┬────────────────────┘
      │         │          │
      ▼         ▼          ▼
  米家设备   Kuma SQLite   homedash.db
  WiFi/云    (只读挂载)    items/logs/〔todos〕/〔ai_audit〕

外部：
  Gmail SMTP  ←── notify 周报（规划）
  LLM API     ←── AI 工作台 parse（规划）
  home agent  ←── agent/todos due → QQ/微信（规划）
```

### 设计原则

1. **家庭内网优先**，默认无用户登录；敏感文件不进 Git  
2. **领域模块清晰**：设备 / 监控 / 库存 /（规划）待办 / 通知 / AI 分文件  
3. **预测与写库可测**：`predict_item` 纯函数；模块尾部 `__main__` 自检  
4. **AI 不直连 SQL**：只产出白名单 `op`，执行器调现有业务函数  
5. **IM 不进主进程**：HomeDash 不实现微信/QQ 协议，只留 HTTP 给 agent  
6. **开源可部署**：路径用环境变量 + `.env.example`，不写死本机绝对路径  

### 数据流摘要

| 场景 | 路径 |
|------|------|
| 开关灯 | 前端 → `/api/devices/{name}/on|off` → miio 或云端 MIOT |
| 看监控 | 前端 → `/api/uptime/status` → 只读查 Kuma DB（缓存） |
| 记消耗 | 前端 → `/api/items/{id}/usage` → 减库存 + usage_logs → 预测重算 |
| AI 改数据（规划） | 工作台 → `/api/ai/parse` → LLM JSON → 用户确认 → `/api/ai/apply` → 执行器 |
| 到点提醒（规划） | agent 轮询 `/api/agent/todos/due` → 发 QQ/微信 → `remind-fired` |
| 周报（规划） | 定时/cron → 组【待办+需买】→ Gmail SMTP |

---

## 模块与代码地图

### 已实现

| 路径 | 职责 |
|------|------|
| `app/main.py` | FastAPI 入口、lifespan 建库/加载设备、挂载路由与静态资源 |
| `app/database.py` | aiosqlite 单例、`SCHEMA`（items / usage_logs / purchase_logs） |
| `app/modules/devices.py` | 设备 YAML 加载、开关、命令、status、BLE 云控 |
| `app/modules/uptime.py` | Kuma SQLite 只读查询 + 缓存 |
| `app/modules/items.py` | 日用品 CRUD、消耗/购买、`predict_item`、predictions |
| `app/xiaomi_login.py` | 小米登录（验证码）→ `data/xiaomi_cloud.json` |
| `app/discover_devices.py` | 云端设备列表辅助脚本 |
| `app/static/index.html` | 页面骨架（Tab） |
| `app/static/style.css` | 米家浅色主题 |
| `app/static/app.js` | 三 Tab 前端逻辑 |
| `Dockerfile` / `docker-compose.yml` | 容器构建与运行 |

### 规划中（DEVPLAN，实现时新增）

| 路径（预估） | 职责 | 待办 |
|--------------|------|------|
| `app/modules/todos.py` | 重点待办 CRUD + `/api/agent/todos/*` | 8 |
| `app/modules/notify.py` | Gmail 周报组信与发送 | 6 |
| `app/modules/ai_workbench.py` | LLM parse、prompt、校验 | 7 |
| `app/modules/ai_executor.py` | 白名单 `op` 执行写库 | 7 |
| `app/database.py` 扩展 | `todos`、`ai_audit` 表 | 7/8 |
| `app/static/*` | 「待办」「AI」Tab UI | 7/8 |

---

## 快速开始（本地）

```bash
git clone https://github.com/yuyuan1019/homedash.git
cd homedash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp config/devices.yaml.example config/devices.yaml
# 编辑 devices.yaml：WiFi 填 host+token；BLE Mesh 填 did

uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000
```

## Docker 部署

```bash
git clone https://github.com/yuyuan1019/homedash.git
cd homedash

cp .env.example .env
# 编辑：HOMEDASH_PORT、KUMA_DATA_DIR（宿主机 Kuma 数据目录）等

cp config/devices.yaml.example config/devices.yaml
# 编辑设备

docker compose up -d --build
# 默认 http://localhost:8088
```

只需改：

- `.env`（勿提交）
- `config/devices.yaml`（勿提交）

默认 bridge 网络即可按 IP 控米家设备；局域网广播发现再考虑 host 网络。

---

## 配置

### 米家设备（`config/devices.yaml`）

**WiFi（局域网）：**

```yaml
devices:
  - name: 猫房空调插座
    model: lumi.acpartner.mcn02
    host: 192.168.1.31
    token: <32位hex token>
    type: airconditioner
```

**BLE Mesh（云端）：**

```yaml
devices:
  - name: 客厅灯
    model: bean.switch.bl02
    host: ""
    did: "1088104207"
    token: <32位hex token>
    type: light
    # siid: 3   # 双键开关右键可选
```

### 获取 Token / DID

**方式一：内置登录脚本（推荐）**

```bash
python app/xiaomi_login.py              # 下载验证码 → /tmp/captcha.png
python app/xiaomi_login.py <验证码>     # 登录并拉取设备
# 生成 data/xiaomi_cloud.json、data/ble_devices.json
```

验证码有时效。若账号开启登录保护，需在 [小米账号安全设置](https://account.xiaomi.com) 临时关闭后再登。

**方式二：[Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)**  
BLE 无 IP 时需方式一补 DID。

**方式三：** 手动把导出结果写入 `devices.yaml`。

### 环境变量

**当前已用：**

| 变量 | 默认 / 示例 | 说明 |
|------|-------------|------|
| `KUMA_DB_PATH` | 容器内如 `/kuma-data/kuma.db` | Kuma SQLite 路径 |
| `KUMA_DATA_DIR` | 宿主机目录 | Compose 挂载到容器（见 `.env.example`） |
| `DEVICES_PATH` | `config/devices.yaml` | 设备配置 |
| `HOMEDASH_PORT` | `8088` | 对外端口 |
| `XIAOMI_USERNAME` / `XIAOMI_PASSWORD` | - | 仅首次云端登录；成功后可删，凭据在 `data/xiaomi_cloud.json` |

**规划中（实现对应功能时写入 `.env.example`）：**

| 变量组 | 用途 |
|--------|------|
| `SMTP_*` / `NOTIFY_*` | Gmail 周报 |
| `LLM_*` / `AI_*` | AI 工作台 |
| `AGENT_API_TOKEN` | home agent 调 `/api/agent/*` |
| `HOMEDASH_PUBLIC_URL` | 邮件里的面板链接 |

**切勿**把真实密码、token、App Password 写进仓库或公开文档。

---

## 验证

```bash
python -m app.modules.items     # 预测数学
python -m app.modules.devices   # 命令映射 + 配置加载
python -m app.modules.uptime    # 无 DB 不崩
```

规划模块上线后同样提供 `python -m app.modules.<name>` 自检（无 pytest）。

---

## API 一览

### 已实现

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/devices` | 设备列表（无内部 `_inst`） |
| GET | `/api/devices/status` | online / power（best-effort） |
| POST | `/api/devices/{name}/on` | 开 |
| POST | `/api/devices/{name}/off` | 关 |
| POST | `/api/devices/{name}/command` | 自定义命令（仅 WiFi） |
| GET | `/api/uptime/status` | 监控状态 |
| GET | `/api/items` | 物品 + 预测 |
| POST | `/api/items` | 添加 |
| PUT | `/api/items/{id}` | 编辑 |
| DELETE | `/api/items/{id}` | 删除 |
| POST | `/api/items/{id}/usage` | 消耗（减库存） |
| POST | `/api/items/{id}/purchase` | 购买（加库存） |
| GET | `/api/items/{id}/history` | 历史 |
| GET | `/api/items/predictions` | 需买 / 充足汇总 |

静态页：`/`、`/app.js`、`/style.css`。

### 规划中（规格见 DEVPLAN，路径可能微调）

| 前缀 | 说明 |
|------|------|
| `/api/todos`、`/api/agent/todos/*` | 重点待办 + agent 提醒 |
| `/api/notify/*` | Gmail 试发 / 周报 |
| `/api/ai/parse`、`/api/ai/apply` | AI 工作台 |

---

## 项目结构

```
homedash/
├── README.md                 # 本文件
├── DEVPLAN.md                # 待办规格书（未完成项以它为准）
├── DESIGN.md                 # 设计说明
├── AGENTS.md                 # 给编码 agent 的约束
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .dockerignore
├── config/
│   ├── devices.yaml.example
│   └── devices.yaml          # 本地真实配置（gitignore）
├── app/
│   ├── main.py
│   ├── database.py
│   ├── xiaomi_login.py
│   ├── discover_devices.py
│   ├── modules/
│   │   ├── devices.py        # ✅ 米家
│   │   ├── uptime.py         # ✅ Kuma
│   │   ├── items.py          # ✅ 日用品
│   │   ├── todos.py          # ⬜ 规划
│   │   ├── notify.py         # ⬜ 规划
│   │   ├── ai_workbench.py   # ⬜ 规划
│   │   └── ai_executor.py    # ⬜ 规划
│   └── static/
│       ├── index.html
│       ├── style.css         # 米家浅色
│       └── app.js
└── data/                     # 运行时（gitignore 敏感文件）
    ├── homedash.db
    ├── xiaomi_cloud.json
    └── ...
```

---

## 文档索引

| 文件 | 用途 |
|------|------|
| [AGENTS.md](./AGENTS.md) | **AI 独立开发强制规则**（§0：权威顺序、开工清单、DoD、密钥、禁区、提示词） |
| [DEVPLAN.md](./DEVPLAN.md) | **待办规格书**（⬜ 未完成；文首有 AI 通用约束） |
| [DESIGN.md](./DESIGN.md) | 设计背景（可能滞后；冲突时以代码与 AGENTS 为准） |

改功能时：**代码 + README 状态/API + DEVPLAN 待办状态 + AGENTS 模块表** 保持一致。  
**禁止**把 DEVPLAN 规划写成 README「已实现」。

---

## License

MIT
