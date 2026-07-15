# AGENTS.md

> **本仓库以 AI 独立开发为主。**  
> 任何编码 agent（OpenCode / Codex / Claude Code / Hermes 等）**必须先读完本文**，再读 `DEVPLAN.md` 对应待办与相关代码。  
> 用户通常只审结果；agent 对可运行性、文档一致性、不泄密负全责。

家庭自托管面板。  
**已实现模块**：米家设备（WiFi + BLE Mesh）、Uptime Kuma、日用品库存/预测、Docker。  
**规划模块**（仅规格，见 `DEVPLAN.md`）：无；当前待办均按代码状态为准。
中文 UI 与注释。公开说明以 `README.md` 为准。

---

## 0. AI 独立开发总则（强制）

### 0.1 权威顺序（冲突时）

1. **正在运行的代码**（`app/**`）  
2. **`AGENTS.md`（本文）** — 协作与禁区  
3. **`DEVPLAN.md`** — 未完成规格（⬜ 不是已完成）  
4. **`README.md`** — 对外说明，须与代码/DEVPLAN 同步  
5. **`DESIGN.md`** — 背景设计；**可能过时**，不得单独当作「已实现」依据  

**禁止**把 DEVPLAN/DESIGN 里的「目标/规划」当成仓库里已经存在的 API 或文件。

### 0.2 开工前检查清单（每个任务）

- [ ] 读本文 §0–§不要做  
- [ ] 读 `DEVPLAN.md` **对应待办全文**（含验收与「明确不做」）  
- [ ] `git status` / 打开将改文件，确认现状  
- [ ] 分清：✅ 已实现 vs ⬜ 仅规格  
- [ ] 列出将改路径；**最小改动**，不顺手重构无关模块  
- [ ] 无真实密钥可提交（见 §0.5）

### 0.3 一次任务只做一件待办

- 用户说「做邮件」→ 只做 DEVPLAN 待办 6（及文档同步），**不要**顺手写 AI 工作台或重写预测。  
- 跨待办依赖时：先完成被依赖项（如 8 先于 6），或在 PR/说明里写清阻塞。  
- 未在 DEVPLAN 出现的新功能：**先改 DEVPLAN 规格**，再写代码（或明确请用户确认规格）。

### 0.4 完成定义（DoD）— 缺一不可

1. **代码可运行**：相关 API/页面不 500；导入错误当场修  
2. **自检通过**：改动的模块执行 `python -m app.modules.<name>`；改预测必跑 items  
3. **文档同步**（改了行为/API/配置时）：  
   - `README.md` 功能/API/结构/环境变量  
   - `DEVPLAN.md` 待办状态或验收  
   - 本文模块地图若有新文件  
   - `.env.example` 若有新配置项（只写占位符）  
4. **无密钥入库**：diff 中无 token/密码/SMTP 授权码/LLM Key
5. **中文**：用户可见文案、注释、toast、邮件正文用中文  
6. **不扩大范围**：无无关格式化大扫除、无擅自升级依赖大版本  

### 0.5 密钥与隐私（零容忍）

| 禁止提交 | 说明 |
|----------|------|
| `config/devices.yaml` | 含设备 token |
| `.env` | 含密码/Key |
| `data/xiaomi_cloud.json`、`*session*`、真实 `*.db` 内容 | 凭据/隐私 |
| 文档/compose 中的本机绝对路径、真实邮箱密码 | 用占位符 |

- 只改 `.env.example` 的**变量名与注释示例**  
- 日志/报错/README **不得**打印完整 token  
- AI 工作台 prompt **不得**注入 `.env`、SMTP 密码、设备 token  

### 0.6 依赖与架构红线

| 允许 | 禁止（除非用户书面要求） |
|------|--------------------------|
| 沿用 `requirements.txt` 现有包 | 新增 ORM / Redis / 消息队列 |
| stdlib `smtplib` 发信 | 为发信拉重型 SDK |
| httpx 调 OpenAI-compatible | 默认镜像打进本地 7B/CUDA 栈 |
| vanilla JS | React/Vue/Svelte/打包器/Tailwind 工程化 |
| 模块尾 `__main__` 自检 | 强行上 pytest 全家桶 |
| `asyncio.to_thread` 包同步 IO | 在 async 路由里直接阻塞 miio/SMTP/LLM |

新增依赖必须：写进 `requirements.txt` + README 技术栈一句说明 + 能说明「为何现有包不够」。

### 0.7 代码与接口约定（给 AI 写码用）

- **路径**：一律从仓库根运行；相对路径 `config/`、`data/`、`app/static`  
- **DB**：`get_db()` 模块级单例，禁止改成 per-request 连接池花样  
- **库存方向**：`usage` 减、`purchase` 加 — 写反即 P0 bug  
- **SQL**：`?` 占位；改表只改 `database.py` 的 `SCHEMA`（`IF NOT EXISTS`，无迁移框架）  
- **路由**：新业务放 `app/modules/<name>.py` 的 `APIRouter`，在 `main.py` `include_router`  
- **前端**：改 `app/static/*`；Tab/文案中文；风格跟随现有米家浅色 CSS 变量  
- **错误**：HTTP 异常带中文 `detail`；前端 toast 展示  
- **简化标记**：刻意不完美处用 `# ponytail: 原因与上限`，不要写假 TODO 冒充完成  
- **类型**：Python 3.12，`list[str]` / `X | None`  
- **开源路径**：compose/文档禁止写死 `/home/yuan/...`，用 env 占位  

### 0.8 实现 DEVPLAN 待办时的额外规则

1. 标题含「尚未开发 / ⬜」→ 代码中**还不存在**，需新建而非「修复」  
2. 先实现 **验收命令/用例** 中列出的路径，再考虑可选增强  
3. 「明确不做」整节 **禁止实现**（如 AI 一期不准控灯、不准裸 SQL）  
4. 做完后在 DEVPLAN 该待办顶部把状态改为已完成，或移入「已完成基线」，并改 README 状态表  
5. 需要用户密钥才能测的（SMTP/LLM）：代码 + dry-run/自检要能在无密钥时**优雅跳过**，不能 import 即崩

### 0.9 与「面板内 AI 工作台」的区分

| 概念 | 含义 |
|------|------|
| **编码 agent**（读本文的你） | 改 HomeDash 源码与文档的开发者 AI |
| **面板 AI 工作台**（待办 7） | 终端用户在浏览器里用自然语言改库存/待办的产品功能 |

编码 agent **实现**工作台时：LLM 只产出白名单 JSON，`ai_executor` 写库。  
编码 agent **自己**改库存数据：优先走业务函数/API，不要手写与方向相反的 SQL。

### 0.10 输出给用户的说明习惯

- 用中文简述：改了什么、怎么验证、还缺什么（如需用户填 SMTP 授权码）
- 不要谎称「已测试邮件/LLM」若实际无密钥未联调  
- 不要把「写了规格」说成「功能已上线」  

---

## 技术栈约束

- Python 3.12（`X | None`）。FastAPI + aiosqlite（**无 ORM，全裸 SQL**）。
- 米家：python-miio（局域网）+ micloud（BLE Mesh 云端 MIOT）。
- 前端：单页 HTML + vanilla JS，**无构建 / 无前端框架**。
- 依赖见 `requirements.txt`，不轻易新增。规划：邮件 stdlib smtplib；AI 用 httpx；**禁止**默认镜像内置本地大模型。
- 产品 AI（待办 7）：白名单 actions 写库，**禁止 LLM 直接 SQL**。
- IM（QQ/微信）：HomeDash **不实现**协议、不主动推送、不内置调度；Hermes 或带 skill 的 AI 按需调 `/api/agent/todos/*`。

## 开发命令

**必须从仓库根目录运行。**

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload            # http://127.0.0.1:8000
# 或：docker compose up -d --build       # 默认 :8088
```

**验证 = 模块 `__main__` 自检（无 pytest）：**

```bash
python -m app.modules.items
python -m app.modules.devices
python -m app.modules.uptime
# 规划：python -m app.modules.todos | notify | ai_workbench ...
```

## 模块地图（实现 vs 规划）

| 模块文件 | 状态 | 职责 |
|----------|------|------|
| `app/modules/devices.py` | ✅ | 米家开关/命令/status/云控/展示隐藏 |
| `app/modules/uptime.py` | ✅ | Kuma 只读 + 缓存 |
| `app/modules/items.py` | ✅ | 日用品 + EWMA / 安全库存预测 |
| `app/modules/todos.py` | ✅ | 重点待办 CRUD + agent API |
| `app/modules/notify.py` | ✅ | SMTP 周报（库存 + 重点待办） |
| `app/modules/ai_workbench.py` | ✅ | LLM parse、校验、字段归一、全流程审计（parse/apply 成败均落库 + before/after 快照） |
| `app/modules/ai_executor.py` | ✅ | 白名单写库；`_item_name` 归一 name/item_name |
| `app/modules/setup.py` | ✅ | 配置状态、米家设备/云端登录、LLM 配置 |
| `app/database.py` | ✅ | 单例 DB；`_ensure_columns` 给旧库容错补列 |
| `app/static/*` | ✅ 六 Tab | 米家浅色：设备、监控、日用品、重点待办、AI、设置 |

## 架构要点（非看文件不可知）

- **DB 单例**：`_db` 全局；不要 per-request 新连接玩法。  
- **库存方向**：`/usage` 减，`/purchase` 加。  
- **predict_item**：相邻 usage 区间 EWMA；安全库存取 `max(min_stock, rate * LEAD_DAYS)`；无/少 usage 时依次走购买间隔、品类先验、最低库存兜底。
- **devices**：`_POWER_CMDS`；`_inst` 不下发；BLE `_cloud_miot_*`；展示隐藏仅存 `device_preferences`，不改 YAML；双重 startup 加载无害。
- **uptime**：`mode=ro`，60s 缓存。  
- **文档一致性**：同一 API/状态改一处必须改 README + DEVPLAN + 本文相关句。

## 配置与环境变量

- 秘密只进 `.env` / 本地 data，**gitignore 已覆盖的勿 force add**  
- 模板：`.env.example`（可含规划变量注释）  
- 当前：`KUMA_*` `DEVICES_PATH` `HOMEDASH_PORT` `XIAOMI_*`  
- 规划：`SMTP_*` `NOTIFY_*` `LLM_*` `AI_*` `AGENT_API_TOKEN`

## 当前阶段

- ✅ Phase 1–3 + status + Docker + 米家浅色五 Tab + EWMA 预测 + 重点待办 + SMTP 周报 + AI 工作台 + 设备展示管理
- ⬜ DEVPLAN：无未完成核心待办
- 以**代码**与 **README 状态表**为准；DESIGN 仅作设计背景  

## 代码风格

- `# ponytail: ...` 刻意简化  
- 新模块必须有 `__main__` 自检  
- 中文 UI / 中文 API 错误信息  

## 不要做（汇总）

- ORM、前端框架、无必要新依赖、pytest 工程化  
- 提交密钥、真实 devices.yaml、本机绝对路径写进公开 compose  
- 阻塞事件循环的同步 IO  
- LLM 任意 SQL；AI 一期控制米家开关  
- HomeDash 内实现微信/QQ 协议  
- 把 DEVPLAN 规划误当成已上线功能  
- 一次 PR 塞多个无关待办「大爆炸」  
- 假称测试通过、假称文档已同步  

## 推荐任务提示词（用户可复制给 AI）

```text
你是 HomeDash 的编码 agent。先完整阅读 AGENTS.md 第 0 节与 DEVPLAN.md 待办 N。
只实现待办 N：按验收命令自检；同步 README/DEVPLAN/AGENTS/.env.example；
禁止提交密钥；禁止做「明确不做」列表里的事；完成后用中文说明改动与验证结果。
从仓库根目录运行命令。
```
