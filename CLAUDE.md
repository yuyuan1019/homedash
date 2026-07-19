# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ⚠️ **先读 `AGENTS.md`**。本仓库以 AI 独立开发为主，`AGENTS.md` 是协作与禁区的权威规则（§0 强制总则、DoD、密钥红线、依赖/架构约束、代码约定、推荐任务提示词）。本文件只做速查索引，**冲突时以 `AGENTS.md` 与运行中代码为准**。

权威顺序：**正在运行的代码 > `AGENTS.md` > `DEVPLAN.md` > `README.md` > `DESIGN.md`（可能过时）**。`DEVPLAN.md` 是待办规格书——标题写「⬜ / 尚未开发」的东西**代码里不存在**，不要当成「修复」当「新建」。

## 常用命令

一律**从仓库根目录**运行。

```bash
# 安装
pip install -r requirements.txt

# 本地开发（http://127.0.0.1:8000）
uvicorn app.main:app --reload

# Docker（默认 :8088）
docker compose up -d --build
```

**没有 pytest。** 验证 = 每个模块的 `__main__` 自检，改了哪个模块就跑哪个：

```bash
python -m app.modules.items          # 改预测必跑
python -m app.modules.todos
python -m app.modules.notify
python -m app.modules.ai_workbench
python -m app.modules.auth
python -m app.modules.users
python -m app.modules.setup
```

跑单个模块就是「跑单个测试」——每个模块文件尾部都有 `if __name__ == "__main__":` 自检块。

## 架构要点（不看多文件读不出来的）

**单体 FastAPI 应用，无 ORM、无前端框架、无构建。**

- **入口 `app/main.py`**：`lifespan` 里 `init_db()`；用 `include_router(prefix="/api")` 挂载各领域模块。一个 `@app.middleware("http")` 统一做面板鉴权：除 `_PUBLIC_API_PATHS`（bootstrap/login/logout）和 `/api/agent/todos*` 外的所有 `/api/*` 都要有效 `homedash_session` Cookie；`/api/setup/*` 与 `/api/admin/*` 还要 `role == "admin"`，否则 401/403（中文 detail）。静态前端用 `StaticFiles` 挂在 `/`。
- **DB 单例 `app/database.py`**：模块级 `_db`，`get_db()` 返回同一个 `aiosqlite.Connection`。**禁止改成 per-request 连接池**。表结构全在 `SCHEMA`（`CREATE TABLE IF NOT EXISTS`，无迁移框架）；旧库加列靠 `_ensure_columns` 的 `ALTER TABLE` 容错（改表结构只动这里，不要写迁移脚本）。
- **领域模块 `app/modules/<name>.py`**：每个一个 `APIRouter`，在 `main.py` 挂载。新业务功能就新建一个模块文件 + 尾部 `__main__` 自检 + 在 `main.py` `include_router`。
- **鉴权 `app/modules/auth.py`**：`hashlib.scrypt` + 每用户随机 salt；会话原始 token 只放 Cookie，库里只存 SHA-256 摘要。`current_user(request)` / `require_admin(request)` 是路由依赖。`/api/agent/todos/*` 走**独立** `AGENT_API_TOKEN`（`X-HomeDash-Token` 或 `Authorization: Bearer`），**不**吃浏览器 Cookie。
- **库存方向（P0 bug）**：`/usage` **减**库存、`/purchase` **加**库存。写反即严重缺陷。
- **AI 工作台两层结构**：`ai_workbench.py`（LLM 调用 + JSON 白名单校验 + 全流程审计）与 `ai_executor.py`（按 `op` 调 items/todos 业务函数写库）。LLM **只产出白名单 actions**，绝不执行任意 SQL；字段名 `name`/`item_name` 在执行器里归一为 `name`。家庭顾问聊天可选调 Brave Search（`BRAVE_API_KEY`）联网。
- **同步 IO 必须包 `asyncio.to_thread`**：SMTP 发信、`hashlib.scrypt` 都在 to_thread 里跑，不得在 async 路由里直接阻塞事件循环。
- **预测 `predict_item`**（`items.py`）：纯函数；相邻 usage 区间 EWMA + 安全库存，冷启动走购买间隔 / 品类先验 / min_stock 兜底。
- **前端 `app/static/*`**：单页 `index.html` + vanilla `app.js` + 浅色 `style.css`。三 Tab：AI 工作台 / 日用品 / 重点待办。改前端只动这三个文件，无打包、无 TS、无框架。

## 硬约束（违反即返工）

- **不引入** ORM、Redis、消息队列、前端框架/打包器/Tailwind、pytest 工程化、本地大模型镜像。新增依赖必须写进 `requirements.txt` + README 说明「为何现有包不够」。
- **零密钥入库**：`.env`、真实 `*.db`、SMTP 授权码/LLM Key / Brave Key **绝不提交**。只改 `.env.example` 的变量名与注释占位。日志/报错/README **不得打印完整 token**；AI 工作台 prompt **不得注入** `.env`、SMTP 密码。compose/文档不写死本机绝对路径，用环境变量占位。
- **一次任务只做一个 DEVPLAN 待办**：不顺手重构无关模块、不塞多个待办的「大爆炸」PR。未在 DEVPLAN 出现的新功能：**先改 DEVPLAN 规格**再写代码。
- **DoD**：代码可运行（不 500）、模块 `__main__` 自检过、文档同步（改了行为/API/配置项就要同步 `README.md` + `DEVPLAN.md` + `AGENTS.md` 模块表 + `.env.example`）、无密钥、用户可见文案与注释用中文。
- **SQL** 用 `?` 占位；HTTP 异常带中文 `detail`，前端 toast 展示。刻意不完美处用 `# ponytail: 原因` 标注，不要写假 TODO 冒充完成。Python 3.12 类型写法 `list[str]` / `X | None`。

## 其它参考文档

| 文件 | 用途 |
|------|------|
| `AGENTS.md` | **强制规则**（§0 总则 / DoD / 密钥 / 禁区 / 代码约定 / 模块地图） |
| `DEVPLAN.md` | 待办规格书（未完成项以它为准；含各待办「明确不做」清单，整节禁止实现） |
| `README.md` | 对外说明，功能状态表与 API 全表（须与代码同步） |
| `DESIGN.md` | 设计背景，**可能过时**，不得单独当作「已实现」依据 |
| `agent-skill/homedash-agent/SKILL.md` | 给外部 Hermes/AI 操作面板用的接口说明 |
