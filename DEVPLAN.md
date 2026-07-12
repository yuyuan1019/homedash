# HomeDash DEVPLAN（待办规格书）

> 本文件描述**尚未完成或可继续增强**的开发项。已完成的功能以代码为准：items/devices/uptime 后端、三 Tab 前端、BLE Mesh 云端开关、Docker 基础部署、设备 power 状态查询。

## 当前已完成基线

- 后端：`app/modules/items.py`、`app/modules/devices.py`、`app/modules/uptime.py`
- 前端：`app/static/index.html`、`app/static/style.css`、`app/static/app.js`
- 部署：`Dockerfile`、`docker-compose.yml`、`.dockerignore`、`.env.example`
- 设备状态：`GET /api/devices/status` 返回 `[{name, online, power}]`

## 待办 1：Docker 部署细化验证

**目标**：保证 fresh clone 后只改 `.env` 和 `config/devices.yaml` 即可启动。

**文件**：
- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `README.md`

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

**返回**：
```json
{"name":"客厅灯","props":{"brightness":65}}
```

**后端文件**：`app/modules/devices.py`

**最小实现**：
```python
_PROP_CMDS = {
    "light": {"brightness": ("set_bright", 1, 100)},
}
```

规则：
- 只允许 `_PROP_CMDS` 里声明的属性。
- 数值越界返回 400。
- BLE Mesh 暂不支持属性控制，返回 400。
- 不新增依赖。

**自检**：在 `devices.py __main__` 增加：
```python
assert "brightness" in _PROP_CMDS["light"]
```

## 待办 3：设备状态增强（可选）

**目标**：`/api/devices/status` 现在只返回 power；后续可按需返回亮度等属性。

**扩展返回**：
```json
{"name":"客厅灯","online":true,"power":"on","props":{"brightness":65}}
```

**实现约束**：
- 单台设备 3 秒超时。
- 单台失败不影响其他设备。
- 属性查询失败只跳过该属性，不把整台设备标离线。

## 待办 4：粘贴导入米家设备（推迟）

**状态**：先不做。当前 `config/devices.yaml` 手写足够。

**何时做**：真实设备多到维护 YAML 明显痛苦时。

**目标 API**：
```http
POST /api/devices/import
{"raw":"<Xiaomi Cloud Tokens Extractor 原始输出>"}
```

**核心规则**：
- 有 IP 且 token 长度 32 的 WiFi 设备导入。
- 无 IP 的 BLE/子设备跳过。
- 同名设备跳过，不覆盖已有配置。

## 待办 5：README 状态同步

每次完成上面的任一待办，同步更新：
- `README.md` API 一览
- `AGENTS.md` 当前阶段
- 本文件对应待办状态

不要把本地真实路径、token、账号、`config/devices.yaml` 写进公开文档。
