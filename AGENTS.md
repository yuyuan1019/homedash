# AGENTS.md

家庭自托管面板。  
**已实现模块**：米家设备（WiFi + BLE Mesh）、Uptime Kuma、日用品库存/预测、Docker。  
**规划模块**（仅规格，见 `DEVPLAN.md`）：重点待办 + agent 接口、Gmail 周报、AI 工作台、EWMA 预测。  
中文 UI 与注释。公开说明以 `README.md` 为准。

## 技术栈约束

- Python 3.12（`X | None`）。FastAPI + aiosqlite（**无 ORM，全裸 SQL**）。
- 米家：python-miio（局域网）+ micloud（BLE Mesh 云端 MIOT）。
- 前端：单页 HTML + vanilla JS，**无构建 / 无前端框架**。
- 依赖见 `requirements.txt`，不轻易新增。规划功能：邮件用 stdlib smtplib；AI 用已有 httpx 调 OpenAI-compatible；**禁止**把本地大模型打进默认镜像。
- AI（待办 7）：只允许白名单 JSON actions 写库，**禁止 LLM 直接 SQL**。
- IM（QQ/微信）：HomeDash **不实现**协议；由 home agent 调 `/api/agent/todos/*`。

## 开发命令

**必须从仓库根目录运行**（`config/`、`data/`、`app/static` 相对路径）。

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

改了哪个模块跑哪个；改 `predict_item` 必跑 items。

## 模块地图（实现 vs 规划）

| 模块文件 | 状态 | 职责 |
|----------|------|------|
| `app/modules/devices.py` | ✅ | 米家开关/命令/status/云控 |
| `app/modules/uptime.py` | ✅ | Kuma 只读 + 缓存 |
| `app/modules/items.py` | ✅ | 日用品 + 线性预测 |
| `app/modules/todos.py` | ⬜ | 重点待办 + agent API |
| `app/modules/notify.py` | ⬜ | Gmail 周报 |
| `app/modules/ai_workbench.py` | ⬜ | LLM parse |
| `app/modules/ai_executor.py` | ⬜ | 白名单写库 |
| `app/database.py` | ✅ | 单例 DB；规划扩 todos/ai_audit |
| `app/static/*` | ✅ 三 Tab | 规划加「待办」「AI」 |

## 架构要点（非看文件不可知的）

- **数据库连接是模块级单例**：`app/database.py` 的 `_db` 全局共享，`get_db()` 返回同一连接。不要改成 per-request。
- **items 库存方向**：`/usage` **减**，`/purchase` **加**。改方向就是 bug。
- **预测纯函数** `predict_item(logs, current_stock, today)`：
  - **现状**：全历史均匀平均；`BUY_THRESHOLD=7`、`TARGET_DAYS=30`
  - **目标**：EWMA 等，见 DEVPLAN 待办 0（未实现）
- **devices**：`_POWER_CMDS` 按 type；`_inst` 不下发前端；BLE 走 `_cloud_miot_*`。
- **devices 双重 startup 加载**（main lifespan + devices on_event）无害。
- **uptime**：Kuma `mode=ro` uri，60s 缓存。
- **文档一致性**：README / DEVPLAN / DESIGN / 本文件同一事物描述必须一致；DEVPLAN 开头是待办规格书不是完成记录。

## 配置与环境变量

- `config/devices.yaml`：真实 token，**勿提交**
- `data/homedash.db`、`data/xiaomi_cloud.json` 等：**勿提交敏感文件**
- `.env`：gitignore；模板 `.env.example`
- 当前：`KUMA_DB_PATH` / `KUMA_DATA_DIR` / `DEVICES_PATH` / `HOMEDASH_PORT` / 小米账号（可选）
- 规划：`SMTP_*` `NOTIFY_*` `LLM_*` `AI_*` `AGENT_API_TOKEN`（见 README / DEVPLAN）

## 当前阶段

以**代码**为准；DESIGN 可能滞后，README 已同步规划：

- ✅ Phase 1–3 后端 + 米家风格前端三 Tab + devices status + Docker
- ⬜ DEVPLAN：0 预测 EWMA · 8 待办+agent · 6 Gmail · 7 AI 工作台
- 无 jinja2（以 `requirements.txt` 为准）

## 代码风格约定

- `# ponytail:` 标记刻意简化（非 TODO）
- 新模块保留 `if __name__ == "__main__":` 自检
- SQL 用 `?`；改表直接改 `SCHEMA`（无迁移工具）

## 不要做

- 不要加 ORM、前端框架、pytest fixtures
- 不要提交真实 token / App Password / LLM Key
- 不要让 devices/uptime 同步 IO 堵事件循环（保持 `asyncio.to_thread`）
- 不要让 AI 执行任意 SQL 或默认控制米家开关（一期）
- 不要在 HomeDash 内实现微信/QQ 登录协议
