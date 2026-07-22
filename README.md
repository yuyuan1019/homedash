# 🏠 HomeDash

家庭自托管管理面板：**长期登录与用户权限 · 日用品库存预测 · 重点待办 · 旅游计划与 AI 行李推荐 · SMTP 周报 · AI 工作台**。

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
| 日用品库存 | ✅ 已实现 | CRUD + 消耗/购买 + EWMA 预测 + 安全库存 + 购物清单 + 多图 + 表单下拉 |
| 收纳知识库 | ✅ 已实现 | 记录「东西放到哪」（描述+照片），LLM 关联库存物品，AI 工作台可检索 |
| 重点待办 | ✅ 已实现 | 家庭 to-do + home agent 提醒接口 |
| SMTP 周报 | ✅ 已实现 | QQ 邮箱发送待办 + 需购买周报 |
| AI 工作台 | ✅ 已实现 | 自然语言 → 工具调用写库 + 操作溯源（带前后快照）+ 撤回；可查收纳记录 |
| 旅游计划 | ✅ 已实现 | 目的地推荐（按交通方式 / 避开网红 / 度假·性价比）+ 非网红玩法 + 天气行李清单 |
| 面板登录与用户管理 | ✅ 已实现 | 180 天长期会话、普通用户/管理员、管理员专属系统设置 |

### 1. 日用品管理（已实现）

**已实现：**

- 记录消耗 / 购买，自动改库存
- 物品可记录分类、存放地点和到期年月；推荐分类：纸品、洗护、清洁、厨房、宠物、冷冻、药品、其他；新增物品时可由 LLM 按名称自动填默认分类
- **预测**：相邻消耗记录 EWMA 日均（近期权重更高）→ 预计耗尽；库存低于安全库存或预计 `<7` 天时需买；建议量覆盖约 30 天
- **冷启动兜底**：无/少用量记录时按购买间隔中位数、品类先验或最低库存提示；返回信心等级与预测方法
- 购物清单汇总

**集成约定：**

- 微信 / QQ 消息由外部 **home agent（如 Hermes）** 发送，HomeDash 只提供数据与 `remind-fired` 回写
- AI 只通过 **白名单动作总线** 改业务表，不执行任意 SQL

### 2. 重点待办（已实现）

- 独立「重点待办」Tab：新建、编辑、完成、重开、删除，支持优先级、截止日期、备注和图片附件（缩略图；可直接粘贴剪贴板图片）
- 列表支持按标题或内容即时搜索（客户端过滤，无需后端），卡片间距已加大便于区分不同待办
- 面板表单不展示负责人及提醒时间、频道、重复规则；既有 home agent 提醒接口继续保留，避免影响已接入的自动化
- `home agent` 轮询 `/api/agent/todos/due`，转发服务端生成的中文 `message` 后调用 `remind-fired`；HomeDash 不实现 QQ/微信协议
- `AGENT_API_TOKEN` 非空时，agent 路径必须带 `X-HomeDash-Token` 或 `Authorization: Bearer`；未配置仅适用于内网

### 2.1 Hermes / AI 提醒对接

HomeDash 是重点待办和提醒意图的数据源，**不会主动推送** QQ、微信、Telegram 或任何 IM，也不内置 cron、机器人协议或后台轮询。Hermes 或安装了 HomeDash skill 的 AI 应自行在合适的时机查询接口、调用自己的消息通道，并在发送成功后回写状态。

| 接口 | 外部 AI / Hermes 用途 |
|------|------|
| `GET /api/agent/todos/due` | 查询当前到点、应提醒的未完成待办；响应中的 `message` 可直接转发 |
| `GET /api/agent/todos/open?priority=high` | 查询未完成待办，回答“有什么高优先级事项” |
| `POST /api/agent/todos` | 根据用户指令创建待办 |
| `POST /api/agent/todos/{id}/done` | 用户确认完成后回写状态 |
| `PUT /api/agent/todos/{id}/remind` | 修改提醒时间、频道或重复策略 |
| `POST /api/agent/todos/{id}/remind-fired` | 外部消息实际发送成功后回写，防止重复提醒 |

当设置 `AGENT_API_TOKEN` 时，请求必须携带以下任一请求头；不要把 token 写进 skill、日志或公开文档：

```http
X-HomeDash-Token: <AGENT_API_TOKEN>
```

```text
外部 AI / Hermes 推荐逻辑：
  在用户询问待办时：GET /api/agent/todos/open
  在自身定时任务或被唤醒时：GET /api/agent/todos/due?within_minutes=15
  对每个 item：按自身已有 QQ / 微信等通道发送 item.message
  仅在发送成功后：POST /api/agent/todos/{id}/remind-fired
```

- `once`：回写成功后 HomeDash 清空 `remind_at`，不会再次返回。
- `daily` / `weekly`：回写成功后 HomeDash 分别把提醒时间推进 1 天 / 7 天。
- 发送失败时不要调用 `remind-fired`，下次查询仍会返回该提醒。
- SMTP 周报是独立能力，HomeDash 也只暴露 `POST /api/notify/weekly` 供宿主机或 Hermes 按需调用，不主动调度。

### 3. SMTP 周报（已实现）

- `POST /api/notify/test` 立即试发；`POST /api/notify/weekly` 按 `NOTIFY_ENABLED` 和静默策略发送；`GET /api/notify/config` 仅返回脱敏状态
- 汇总未完成重点待办与需购买日用品；SMTP 465 使用 SSL，其他端口使用 STARTTLS
- QQ 邮箱发件账号与收件人可在「设置」页配置，保存到 `data/notify_config.json` 后热加载；也可继续用本地 `.env` 的 `SMTP_*`、`NOTIFY_TO`
- SMTP 授权码不会经日志输出，设置页回填时只显示掩码

### 4. AI 工作台（已实现）

- 「AI 工作台」Tab 接收中文文本指令，调用 OpenAI-compatible LLM 生成动作预览
- `POST /api/ai/parse` 只解析不写库；`POST /api/ai/apply` 只执行白名单动作；`GET /api/ai/audit` 查询审计
- 支持库存购买、消耗、盘点、新建/更新物品，及重点待办的新建、完成、重开、更新、删除；支持只读查询需买物品和待办
- LLM 不能执行 SQL；非法操作、SQL 关键词、越界数值都会被服务端拒绝
- **字段归一化**：LLM 输出 `name` 或 `item_name` 均归一为 `name`；购买/消耗/盘点/更新缺少物品标识一律拒绝，空名物品无法创建
- **全流程审计**：parse 与 apply 两阶段**无论成败都写 `ai_audit`**，记录 `session_id`、`llm_model`、`reply`、`confidence`、`duration_ms`、`error`，以及每条写操作的 `before_json`/`after_json` 前后快照；前端「操作溯源」区按 session 串联展示，支持按条撤回
- **流式回复**：`POST /api/ai/chat/stream`（SSE）让助手回复逐字呈现，并在工具调用阶段显示「正在执行操作…」；模型若返回 `reasoning_content`（如 DeepSeek 深度思考）会在气泡内弱化展示推理过程。上游不支持流式时前端自动回退到 `POST /api/ai/chat`（非流式），体验不中断

### 4.1 旅游计划与 AI 行李推荐（已实现）

- 「旅游计划」Tab 分两区：上方「✨ 发现目的地」按出发城市、交通方式（高铁/自驾/飞机/不限）、天数、主策略（度假优先/性价比优先/不网红优先/综合）、标签与预算，让 AI 推荐小众、避开网红的真实目的地；下方「我的行程」管理多段行程
- `POST /api/travel/suggest`（无状态）生成候选目的地，每个含「为什么不网红」理由、非网红亮点、人均预算与交通时长；选定后可一键加入行程
- `POST /api/travel/suggest/stream`（SSE）分阶段推送「联网搜索 → AI 生成 → 计算交通时长」进度，缓解长时间空白；流式不可用时前端自动回退到 `POST /api/travel/suggest`
- `POST /api/travel/plans/{id}/spots` 为选定目的地生成非网红具体玩法清单（可逐项勾选已安排）
- 交通时长：配置高德 Key 后**自驾用驾车路径规划（精确）**，高铁/飞机按直线距离估算（高德无跨城铁路/航司时刻）；未配置则整体降级为 LLM 估算，旅游功能仍可用
- `POST /api/travel/plans/{id}/recommend` 复用系统 LLM 生成结构化行李清单；配置 Brave Search 时先搜对应地点和日期的天气资料，否则明确标注为 LLM 季节常识估算；清单可逐项勾选、编辑并持久化到 SQLite
- 天气与玩法仅供参考，临行前仍应查看当地官方预警；药品建议不替代医疗意见

### 5. 登录与用户权限（已实现）

- 全新数据库首次打开时创建首个管理员，不提供默认账号或默认密码
- 用户名密码登录后设置 `HttpOnly` 长期 Cookie，默认 180 天并按活动续期；退出、禁用、删除或重置密码后对应会话立即失效
- 密码使用 Python 标准库 `hashlib.scrypt` + 独立随机 salt，数据库仅保存会话 token 的 SHA-256 摘要
- 普通用户可使用日用品、待办和 AI；右上角三点菜单只显示「退出登录」
- 只有管理员能进入系统设置及 `/api/setup/*`，并可新增普通用户/管理员、启停账户、重置密码和删除用户
- 不能删除、禁用或降级当前管理员，系统始终至少保留一个启用的管理员
- 除登录/初始化接口与 `/api/agent/todos/*` 外，面板业务 API 均要求有效登录会话；agent 接口继续使用 `AGENT_API_TOKEN`

#### 运维备忘：命令行重置某个用户密码

管理员在浏览器 UI 里能直接重置任意用户密码。**只有管理员自己忘记密码把自己锁在外面时**，才需要用下面的命令直接改数据库。散列算法与登录流程完全一致（`hashlib.scrypt` + 每用户随机 salt），并会顺手废止该用户所有旧会话——与 UI 里点「重置密码」一致。

在仓库根目录执行（`docker compose exec` 走容器；`data/homedash.db` 是宿主挂载的持久卷）：

```bash
# 将 USER 换成要重置的用户名，PASS 换成新密码（8–128 位）
USER='要重置的用户名' PASS='新密码_2026' && cd ~/MyProjects/homedash && \
docker compose exec -T -e USER="$USER" -e PASS="$PASS" homedash python - <<'PY'
import os, base64, hashlib, secrets, sqlite3, sys
u = os.environ["USER"]; p = os.environ["PASS"]
if not (8 <= len(p) <= 128):
    sys.exit("密码长度必须为 8 到 128 个字符")
salt = secrets.token_bytes(16)
digest = hashlib.scrypt(p.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
ph = base64.b64encode(digest).decode("ascii")
ps = base64.b64encode(salt).decode("ascii")
c = sqlite3.connect("data/homedash.db")
row = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()
if not row:
    sys.exit(f"用户不存在: {u}")
uid = row[0]
c.execute(
    "UPDATE users SET password_hash=?, password_salt=?, updated_at=datetime('now') WHERE id=?",
    (ph, ps, uid),
)
n = c.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,)).rowcount
c.commit(); c.close()
print(f"✅ 已重置 {u} 的密码，并废止 {n} 个旧会话")
PY
```

要点：

- 通过环境变量传密码而非命令行参数，避免明文进程列表；前面加一个空格再回车（`HISTCONTROL=ignorespace` 时）可跳过 shell history
- `-T` 关闭伪终端，密码不会回显、也不会残留在容器 tty
- 只改自己数据库，**不重启服务**；用户下一次请求即用新密码
- 需要看看当前有哪些账号：

  ```bash
  docker compose exec -T homedash python - <<'PY'
  import sqlite3
  for r in sqlite3.connect("data/homedash.db").execute(
      "SELECT id, username, role, enabled, last_login_at FROM users"
  ):
      print(r)
  PY
  ```

如果数据库被清空（`data/` 全删），面板会自动回到「创建首个管理员」页，不需要走这条命令。

---

## 技术栈

### 当前（代码已用）

| 层 | 选型 | 说明 |
|----|------|------|
| 语言 / 运行时 | Python 3.12 | 类型写法 `X \| None` |
| Web | FastAPI + Uvicorn + python-multipart | 异步 API；图片附件表单上传；SSE 流式走 Starlette 内置 `StreamingResponse`，**无新依赖** |
| 数据库 | SQLite + aiosqlite | **无 ORM**，裸 SQL，`CREATE TABLE IF NOT EXISTS` |
| 配置 | python-dotenv | `.env` |
| HTTP 客户端 | httpx | LLM、Brave Search 调用 |
| 前端 | HTML + CSS + vanilla JS | **无构建、无 React/Vue** |
| 部署 | Docker / Compose | 官方 `python:3.12` 镜像 |

**依赖（`requirements.txt`）：**

```
fastapi
python-multipart
uvicorn[standard]
httpx
aiosqlite
python-dotenv
```

不引入：ORM、前端打包器、Redis、jinja2、pytest（用模块 `__main__` 自检）。

### 已实现与可选能力

| 能力 | 方案 | 备注 |
|------|------|------|
| 邮件 | stdlib `smtplib` + QQ 邮箱 SMTP 授权码 | 已实现 |
| AI | OpenAI-compatible Chat（`LLM_BASE_URL` + Key），服务端执行器写库 | 已实现 |
| 联网搜索 | Brave Search API，家庭顾问聊天可选 | 已实现 |
| IM 提醒 | 外部 AI / home agent 查询 `/api/agent/todos/*` 后自行发送 | 部署侧 |
| 定时 | 宿主机 / Hermes 按需调用 notify / due 接口；HomeDash 不内置调度 | 部署侧 |

---

## 技术方案

### 总体架构

```
浏览器（浅色 SPA：AI 工作台 / 日用品 / 重点待办）
        │  HTTP /api/*
        ▼
┌───────────────────────────────────────────────┐
│                 FastAPI (app/main.py)          │
│  auth │ users │ items │ todos │ notify │ ai    │
└─────┬────────────────────────────────────────┬─┘
      │                                        │
      ▼                                        ▼
  homedash.db                            外部：
  items / todos / users / ai_audit         · QQ 邮箱 SMTP（notify 周报）
                                           · LLM API（AI 工作台 parse）
                                           · Brave Search（家庭顾问）
                                           · Hermes / AI（主动查询 agent/todos）
```

### 设计原则

1. **家庭内网优先**；面板使用长期会话，系统设置仅管理员可访问；敏感文件不进 Git
2. **领域模块清晰**：认证 / 用户 / 库存 / 待办 / 通知 / AI 分文件
3. **预测与写库可测**：`predict_item` 纯函数；模块尾部 `__main__` 自检
4. **AI 不直连 SQL**：只产出白名单 `op`，执行器调现有业务函数
5. **IM 不进主进程**：HomeDash 不实现微信/QQ 协议，只留 HTTP 给 agent
6. **开源可部署**：路径用环境变量 + `.env.example`，不写死本机绝对路径

### 数据流摘要

| 场景 | 路径 |
|------|------|
| 记消耗 | 前端 → `/api/items/{id}/usage` → 减库存 + usage_logs → 预测重算 |
| AI 改数据 | 工作台 → `/api/ai/parse` → LLM JSON → 用户确认 → `/api/ai/apply` → 执行器 |
| 到点提醒 | Hermes / AI 主动查询 `/api/agent/todos/due` → 自身通道发 IM → `remind-fired` |
| 周报 | 宿主机/Hermes 按需调用 `/api/notify/weekly` → 组【待办+需买】→ QQ 邮箱 SMTP |

---

## 模块与代码地图

### 已实现

| 路径 | 职责 |
|------|------|
| `app/main.py` | FastAPI 入口、lifespan 建库、面板 API 统一鉴权、挂载路由与静态资源 |
| `app/database.py` | aiosqlite 单例、`SCHEMA`（业务表 + users / auth_sessions） |
| `app/modules/auth.py` | 首个管理员、登录/退出、scrypt 密码散列与长期会话 |
| `app/modules/users.py` | 管理员用户管理、角色边界与会话废止 |
| `app/modules/items.py` | 日用品 CRUD、消耗/购买、EWMA + 安全库存预测、`predict_item`、predictions |
| `app/modules/todos.py` | 重点待办 CRUD、提醒意图与 `/api/agent/todos/*` |
| `app/modules/notify.py` | SMTP 周报组信与发送 |
| `app/modules/ai_workbench.py` | LLM 解析、动作校验、审计 API、家庭顾问聊天（可选 Brave Search） |
| `app/modules/ai_executor.py` | AI 白名单动作执行器 |
| `app/modules/setup.py` | LLM / SMTP / Brave / 高德 配置读写与连通测试 |
| `app/modules/travel.py` | 旅游计划 CRUD；目的地推荐引擎（交通方式/策略）+ 非网红玩法 + 天气行李清单 + 高德交通时长（可选） |
| `app/static/index.html` | 页面骨架（AI / 日用品 / 重点待办 三 Tab） |
| `app/static/style.css` | 浅色主题 |
| `app/static/app.js` | 前端逻辑 |
| `Dockerfile` / `docker-compose.yml` | 容器构建与运行 |

---

## 快速开始（本地）

```bash
git clone https://github.com/yuyuan1019/homedash.git
cd homedash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000
```

首次打开会要求创建管理员账户；系统不提供默认用户名或密码。后续管理员可在右上角「••• → 系统设置 → 用户管理」中新增普通用户或其他管理员。

## Docker 部署

```bash
git clone https://github.com/yuyuan1019/homedash.git
cd homedash

cp .env.example .env
# 编辑：HOMEDASH_PORT 等

docker compose up -d --build
# 默认 http://localhost:8088
```

只需改：

- `.env`（勿提交）

---

## 配置

### 设置页（推荐新手）

部署后打开面板，以管理员账户点击右上角 **••• → 系统设置**：

- **配置总览**：实时显示 AI 工作台、SMTP、Brave Search、高德地图、Agent Token 的状态与缺失项。
- **AI 工作台**：填写 LLM Base URL、API Key、模型，保存后写入 `data/llm_config.json` 并立即生效；可从上游 `/models` 获取模型列表，**无需重启容器**。
- **Brave Search**：可选，配置后家庭顾问可联网搜索；保存到 `data/brave_config.json`，未配置不影响聊天。
- **高德地图**：可选，用于旅游推荐的精确交通时长；保存到 `data/amap_config.json`，未配置则降级为 LLM 估算。
- **SMTP 周报**：填写 SMTP Host、授权码、收件人，保存后写入 `data/notify_config.json` 并立即生效，支持页面测试登录和试发周报。
- **Agent Token**：仍需写入宿主机 `.env` 后执行 `docker compose restart`。

### 环境变量

**当前已用：**

| 变量 | 默认 / 示例 | 说明 |
|------|-------------|------|
| `HOMEDASH_PORT` | `8088` | 对外端口 |
| `TZ` | `Asia/Shanghai` | 容器时区；影响库存/待办时间戳与前端展示，改地区改此项 |

**已用或预留：**

| 变量组 | 用途 |
|--------|------|
| `SMTP_*` / `NOTIFY_*` | QQ 邮箱 SMTP 周报 |
| `LLM_*` / `AI_*` | AI 工作台 |
| `BRAVE_API_KEY` | 家庭顾问联网搜索（可选） |
| `AMAP_API_KEY` | 高德地图交通时长（旅游推荐，可选） |
| `AGENT_API_TOKEN` | home agent 调 `/api/agent/*`；为空仅适合内网 |
| `HOMEDASH_PUBLIC_URL` | 邮件里的面板链接 |

**切勿**把真实密码、token、SMTP 授权码写进仓库或公开文档。

---

## 验证

```bash
python -m app.modules.items        # 预测数学
python -m app.modules.todos        # 待办提醒格式与时间解析
python -m app.modules.notify       # 周报文本与收件人解析
python -m app.modules.ai_workbench # AI 白名单校验
python -m app.modules.auth         # 密码散列、会话摘要与用户名校验
python -m app.modules.users        # 角色校验与管理员保护
python -m app.modules.setup        # LLM / SMTP / Brave 配置读写与掩码
```

各模块均提供 `python -m app.modules.<name>` 自检（无 pytest）。

---

## API 一览

除首个管理员初始化、登录/退出和 `/api/agent/todos/*` 外，下列面板 API 均要求浏览器携带有效的 `homedash_session` Cookie；`/api/setup/*` 与 `/api/admin/*` 还要求管理员角色。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET / POST | `/api/auth/bootstrap-status`、`/bootstrap-admin` | 首个管理员初始化 |
| POST | `/api/auth/login`、`/logout` | 登录并设置长期 Cookie、退出并废止会话 |
| GET | `/api/auth/me` | 当前登录用户 |
| GET / POST | `/api/admin/users` | 管理员查看或新增用户/管理员 |
| PUT / DELETE | `/api/admin/users/{id}` | 管理员修改角色/状态或删除用户 |
| PUT | `/api/admin/users/{id}/password` | 管理员重置密码并废止该用户会话 |
| GET | `/api/items` | 物品 + 预测 |
| POST | `/api/items` | 添加 |
| PUT | `/api/items/{id}` | 编辑 |
| DELETE | `/api/items/{id}` | 删除 |
| POST | `/api/items/{id}/usage` | 消耗（减库存） |
| POST | `/api/items/{id}/purchase` | 购买（加库存） |
| GET | `/api/items/{id}/history` | 历史 |
| GET | `/api/items/predictions` | 需买 / 充足汇总 |
| GET | `/api/items/facets` | 表单下拉候选：分类/单位/地点（按频次）+ 默认值 |
| POST | `/api/items/{id}/images` | 上传物品图片（JPG/PNG/GIF/WebP，最多 5 张，每张 10MB） |
| GET / DELETE | `/api/items/{id}/images/{image_id}` | 读取或移除物品图片 |
| GET | `/api/todos?status=open\|done\|all` | 重点待办列表 |
| POST | `/api/todos` | 新建重点待办 |
| GET / PUT / DELETE | `/api/todos/{id}` | 查看、编辑、删除重点待办 |
| POST | `/api/todos/{id}/done`、`/reopen` | 完成或重新打开 |
| GET | `/api/todos/summary` | 未完成、过期与优先事项摘要 |
| GET / POST | `/api/agent/todos/due`、`/open` | agent 拉取到点或未完成待办 |
| POST / PUT | `/api/agent/todos/*/remind-fired`、`/remind` | agent 回写提醒或修改提醒 |
| POST | `/api/todos/{id}/images` | 上传待办图片（JPG/PNG/GIF/WebP，最多 5 张，每张 10MB） |
| GET / DELETE | `/api/todos/{id}/images/{image_id}` | 读取或移除待办图片 |
| GET / POST | `/api/placements` | 收纳记录列表（?confirmed=all\|pending\|confirmed）/ 新建（描述+位置+备注） |
| GET / PATCH / DELETE | `/api/placements/{id}` | 查看、修改、删除收纳记录 |
| POST | `/api/placements/{id}/images` | 上传收纳照片（最多 5 张，每张 10MB） |
| GET / DELETE | `/api/placements/{id}/images/{image_id}` | 读取或移除收纳照片 |
| POST | `/api/placements/{id}/suggest` | LLM 关联库存物品候选（AI 未配置返回 503） |
| PUT | `/api/placements/{id}/confirm` | 确认关联（item_ids + 可选位置） |
| GET / POST | `/api/travel/plans` | 旅游行程列表 / 新建（含出发城市、交通方式、策略等偏好） |
| PUT / DELETE | `/api/travel/plans/{id}` | 编辑、删除行程 |
| PUT | `/api/travel/plans/{id}/packing` | 保存行李清单 |
| POST | `/api/travel/plans/{id}/recommend` | LLM 生成行李清单（结合 Brave 天气） |
| POST / PUT | `/api/travel/plans/{id}/spots` | 生成 / 保存非网红玩法清单 |
| POST | `/api/travel/suggest` | 按交通方式/策略推荐候选目的地（AI 未配置 503） |
| POST | `/api/travel/suggest/stream` | 同上，SSE 分阶段推送进度（前端在流式不可用时自动回退） |
| GET / POST | `/api/notify/config`、`/test`、`/weekly` | SMTP 配置状态、试发、周报 |
| POST | `/api/ai/parse`、`/apply` | AI 解析预览、确认写入 |
| POST | `/api/ai/chat` | 家庭顾问聊天（可选联网搜索） |
| POST | `/api/ai/chat/stream` | 同上，SSE 逐 token 流式回复（前端在流式不可用时自动回退） |
| POST | `/api/ai/item-category` | LLM 预测物品分类 |
| GET | `/api/ai/audit` | AI 写库审计记录 |
| GET | `/api/ai/suggested-chips` | 获取建议操作快捷片段 |
| POST | `/api/ai/revert/{action_id}` | 撤回某条 AI 写操作 |
| GET | `/api/setup/status` | 配置总览（LLM/SMTP/Brave/高德/Agent 状态） |
| GET / POST | `/api/setup/llm/config`、`/save`、`/test` | LLM 配置读取、保存、测试连接 |
| GET | `/api/setup/llm/models` | 获取上游可用模型列表 |
| GET / POST | `/api/setup/brave/config`、`/save`、`/test` | Brave Search 配置 |
| GET / POST | `/api/setup/amap/config`、`/save`、`/test` | 高德地图配置（旅游交通时长，可选） |
| GET / POST | `/api/setup/agent/config`、`/save` | Agent Token 配置 |
| GET / POST | `/api/setup/notify/config`、`/save`、`/test` | SMTP 配置（热加载） |
| GET | `/api/setup/env-snippet` | 生成 .env 配置片段 |

静态页：`/`、`/app.js`、`/style.css`。

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
├── app/
│   ├── main.py
│   ├── database.py
│   ├── modules/
│   │   ├── auth.py           # ✅ 登录与长期会话
│   │   ├── users.py          # ✅ 管理员用户管理
│   │   ├── items.py          # ✅ 日用品
│   │   ├── todos.py          # ✅ 重点待办
│   │   ├── notify.py         # ✅ SMTP 周报
│   │   ├── ai_workbench.py   # ✅ AI 解析与审计
│   │   ├── ai_executor.py    # ✅ 白名单执行器
│   │   └── setup.py          # ✅ LLM / SMTP / Brave 配置
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
└── data/                     # 运行时（gitignore 敏感文件）
    ├── homedash.db
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

## Agent Skill

`agent-skill/homedash-agent/SKILL.md` 是 Hermes / 其他 agent 操作 HomeDash 的标准接口说明：

- 重点待办 CRUD（含提醒频道、周期提醒、完成标记）
- 库存查询、EWMA 预测、消耗/购买记账
- 所有端点、字段、curl 模板、常见对话映射

Agent 加载该 skill 后即可直接通过 `http://127.0.0.1:8088/api/*` 操作面板，无需进 UI。
