# AGENTS.md

家庭自托管面板，三模块：米家设备控制（WiFi 局域网直控 + BLE Mesh 云端控制）、Uptime Kuma 监控、日用品消耗/购买预测。中文 UI 与注释。

## 技术栈约束

- Python 3.12（代码用 `X | None` 语法）。FastAPI + aiosqlite（**无 ORM，全裸 SQL**）。python-miio 走局域网直控，micloud 走小米云端 MIOT 控制 BLE Mesh 设备。
- 前端单页 HTML + vanilla JS，**无构建步骤**。不要引入前端框架/打包工具。
- 依赖见 `requirements.txt`，不轻易新增。

## 开发命令

**必须从仓库根目录运行**（路径 `config/`、`data/`、`app/static` 都是相对路径）。

```bash
pip install -r requirements.txt          # 装依赖
uvicorn app.main:app --reload            # 开发服务器，http://127.0.0.1:8000
```

**验证方式 = 各模块的 `__main__` 自检，不是 pytest（项目未装 pytest）：**

```bash
python -m app.modules.items     # 预测数学断言
python -m app.modules.devices   # 命令映射表 + 配置加载
python -m app.modules.uptime    # 无 DB 文件不报错
```

改了哪个模块就跑哪个；改了 `predict_item` 必跑 items 自检。无 lint/typecheck 配置。

## 架构要点（非看文件不可知的）

- **数据库连接是模块级单例**：`app/database.py` 的 `_db` 全局共享，`get_db()` 返回同一连接。不要改成 per-request。
- **items 模块库存方向**：`/usage` 端点**减**库存，`/purchase` 端点**加**库存。改方向就是 bug。
- **预测是纯函数** `predict_item(logs, current_stock, today)`，可脱离 DB 测试。常量 `BUY_THRESHOLD=7`（天）、`TARGET_DAYS=30`（建议购买覆盖周期）。无用量记录时返回空预测，不报错。
- **devices 模块**：`_POWER_CMDS` 按 `type` 查开关命令，新设备类型加一行即可；`_DEFAULT` 兜底 `set_power`。`Device` 实例缓存在 cfg dict 的 `_inst` 字段（下划线前缀字段在 `/devices` 列表里被过滤掉，别返回给前端）。
- **BLE Mesh 云端控制**：有 `did` 无 `host` 的设备走云端 MIOT API（`_cloud_miot_set`），凭据从 `data/xiaomi_cloud.json` 读取（`_get_cloud` 单例）。`_send_power` 统一分发：WiFi 走局域网，BLE Mesh 走云端。`_MIOT_PROPS` 按 type 查 siid/piid，config 里可覆盖 siid（双键开关左=2 右=3）。
- **devices 启动会双重加载**：`main.py` lifespan 和 `devices.py` 的 `on_event("startup")` 都调 `load_devices()`，无害，别删其中一个以为在去重。
- **uptime 模块**：直读 Kuma 的 SQLite（`file:...?mode=ro` uri 只读，避免锁竞争），60s 缓存，读失败保留旧缓存。不调 Kuma 的 Socket.IO。

## 配置与环境变量

- `config/devices.yaml`：米家设备配置，从 `config/devices.yaml.example` 拷贝改 token。**真实 devices.yaml 含 token，勿提交**。
- `data/homedash.db`：SQLite 数据库，首次运行自动建表。
- `data/xiaomi_cloud.json`：小米云端凭据（serviceToken + ssecurity），由 `app/xiaomi_login.py` 生成。**含敏感凭据，勿提交**。
- `.env`：小米账号密码（`XIAOMI_USERNAME`/`XIAOMI_PASSWORD`），已在 `.gitignore`。
- `KUMA_DB_PATH`：Uptime Kuma 的 SQLite 路径，默认 `/data/kuma.db`（容器内路径）。
- `DEVICES_PATH`：设备配置路径，默认 `config/devices.yaml`。

## 当前阶段（重要，别被 DESIGN.md 误导）

DESIGN.md 是初版设计，**与代码有出入，以代码为准**：

- 后端 Phase 1+2+3 已完成（items/devices/uptime 三模块 API 全通，BLE Mesh 云端控制已加）。
- 前端 Phase 3 已完成：`app/static/style.css`（暗色主题）+ `app/static/app.js`（三 Tab 全功能）。设备 Tab 支持 BLE Mesh 云端控制。
- **有 docker-compose.yml 但无 Dockerfile**，Docker 部署尚未可用。
- `requirements.txt` 里**没有 jinja2**（DESIGN 列了但实际没装）。

## 代码风格约定

- 用 `# ponytail:` 注释标记**刻意**的简化或已知上限（如“单条记录跨度按 1 天兜底”），不是 TODO，是“我知道这不够通用但够用”。新增简化处沿用此标记，写明上限和升级路径。
- 模块文件尾部带 `if __name__ == "__main__":` 自检块，新增模块应保持此惯例。
- SQL 用 `?` 占位符，`datetime('now')` 做默认值。表结构在 `app/database.py` 的 `SCHEMA` 里，用 `CREATE TABLE IF NOT EXISTS`，改 schema 直接改 SCHEMA（无迁移工具）。

## 不要做

- 不要加 ORM、不要加前端框架、不要加 pytest/fixtures（自检块就是测试）。
- 不要把 `config/devices.yaml` 的真实 token 提交进 git。
- 不要让 devices/uptime 模块的同步 IO 阻塞事件循环——现有代码用 `asyncio.to_thread` 包裹，保持。
