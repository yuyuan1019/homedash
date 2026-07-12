# 🏠 HomeDash

家庭自托管管理面板，三合一：米家设备控制、Uptime 监控、日用品消耗预测。

## 功能

### 1. 米家设备控制
- python-miio 局域网直控，不经云、不经 HA
- 支持灯、空调、插座等设备开关
- 自定义命令透传（亮度、温度等）
- 新设备类型加一行映射即可

### 2. Uptime 监控
- 直读 Uptime Kuma 的 SQLite 数据库（只读，不锁竞争）
- 60 秒缓存，读失败保留旧数据
- 展示各监控项在线状态、响应时间

### 3. 日用品管理
- 记录消耗/购买，自动更新库存
- 线性预测日均消耗率，计算预计耗尽日期
- 库存低于 7 天阈值时标记"需要购买"
- 自动建议购买数量（覆盖 30 天用量）
- 购物清单汇总

## 技术栈

- Python 3.12 + FastAPI + aiosqlite（无 ORM，全裸 SQL）
- python-miio 局域网直控
- 前端单页 HTML + vanilla JS（无框架、无构建步骤）
- SQLite 存储

## 快速开始

```bash
git clone https://github.com/yuyuan1019/homedash.git
cd homedash
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env（Kuma DB 路径、设备配置路径）

# 配置米家设备
cp config/devices.yaml.example config/devices.yaml
# 编辑 devices.yaml，填入设备 IP 和 token

# 启动
uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000
```

## 配置

### 米家设备（config/devices.yaml）

```yaml
devices:
  - name: 客厅灯
    model: yeelink.light.lamp1
    host: 192.168.1.100
    token: <32位hex token>
    type: light
  - name: 卧室空调
    model: zhimi.aircondition.v1
    host: 192.168.1.101
    token: <32位hex token>
    type: airconditioner
```

**获取 Token：** 推荐用 [Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)，登录小米账号一键导出所有设备的 name/ip/token/model。

此工具不在 PyPI 上，需从 GitHub clone 运行：

```bash
git clone https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor.git
cd Xiaomi-cloud-tokens-extractor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt    # requests pycryptodome charset-normalizer Pillow colorama
python token_extractor.py
# 输入小米账号、密码、服务器区域（中国选 cn）
# 自动列出所有设备 NAME / ID / MAC / TOKEN / MODEL / IP
```

> 备选：`miiocli discover`（仅旧固件）或抓包旧版米家 APK（v5.4.54）。新固件已加密广播包，miiocli 大概率拿不到。

**注意：**
- 有 IP 的设备是 WiFi 直控（python-miio 可控），无 IP 的 BLE 设备（温湿度计、门锁等）不支持局域网直控
- 导出的 token 直接填入 `config/devices.yaml`，或使用前端的"粘贴导入"功能（见 DEVPLAN.md）

设备需已绑定米家 App 且与 HomeDash 在同一局域网。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KUMA_DB_PATH` | `/data/kuma.db` | Uptime Kuma 的 SQLite 文件路径 |
| `DEVICES_PATH` | `config/devices.yaml` | 米家设备配置文件路径 |

## Docker 一键部署

```bash
git clone https://github.com/yuyuan1019/homedash.git
cd homedash

# 1. 配置环境变量
cp .env.example .env

# 2. 配置米家设备
cp config/devices.yaml.example config/devices.yaml
# 编辑 devices.yaml，填入设备 IP 和 token

# 3. 编辑 docker-compose.yml，把 Kuma DB 挂载路径改成你的

# 4. 启动
docker compose up -d
# 打开 http://localhost:8088
```

docker-compose.yml 会自动读取 `.env` 文件注入环境变量，只需改两个文件：
- `.env`：环境变量配置
- `config/devices.yaml`：米家设备配置

## 验证

```bash
python -m app.modules.items     # 预测算法自检
python -m app.modules.devices   # 命令映射表 + 配置加载自检
python -m app.modules.uptime    # 无 DB 文件不报错自检
```

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/devices` | 设备列表 |
| POST | `/api/devices/{name}/on` | 开启设备 |
| POST | `/api/devices/{name}/off` | 关闭设备 |
| POST | `/api/devices/{name}/command` | 自定义命令 |
| GET | `/api/uptime/status` | 监控状态 |
| GET | `/api/items` | 物品列表 + 预测 |
| POST | `/api/items` | 添加物品 |
| PUT | `/api/items/{id}` | 编辑物品 |
| DELETE | `/api/items/{id}` | 删除物品 |
| POST | `/api/items/{id}/usage` | 记录消耗 |
| POST | `/api/items/{id}/purchase` | 记录购买 |
| GET | `/api/items/{id}/history` | 历史记录 |
| GET | `/api/items/predictions` | 购买建议汇总 |

## 项目结构

```
homedash/
├── requirements.txt
├── config/
│   ├── devices.yaml.example   # 设备配置模板
│   └── devices.yaml           # 实际配置（勿提交）
├── app/
│   ├── main.py                # FastAPI 入口
│   ├── database.py            # SQLite 连接 + 建表
│   └── modules/
│       ├── devices.py         # 米家设备控制
│       ├── uptime.py          # Uptime Kuma 对接
│       └── items.py           # 日用品 CRUD + 预测
└── data/
    └── homedash.db            # SQLite 数据库（自动创建）
```

## License

MIT
