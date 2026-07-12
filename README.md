# 🏠 HomeDash

家庭自托管管理面板，三合一：米家设备控制、Uptime 监控、日用品消耗预测。

## 功能

### 1. 米家设备控制
- **WiFi 设备**：python-miio 局域网直控，不经云、不经 HA
- **BLE Mesh 设备**：通过小米云端 MIOT API 控制（墙壁开关等蓝牙 Mesh 设备）
- 支持灯、空调、插座等设备开关
- 自定义命令透传（亮度、温度等）
- 新设备类型加一行映射即可
- 前端按类型分组显示，BLE Mesh 设备显示「☁ 云端控制」标签

### 2. Uptime 监控
- 直读 Uptime Kuma 的 SQLite 数据库（只读，不锁竞争）
- 60 秒缓存，读失败保留旧数据
- 展示各监控项在线状态、响应时间

### 3. 日用品管理
- 记录消耗/购买，自动更新库存
- **现状**：全历史线性日均消耗 → 预计耗尽日期；不足 7 天标记需购买；建议量覆盖约 30 天
- **规划中**（未实现，见 `DEVPLAN.md`）：
  - 待办 0：两口·120㎡ **EWMA + 安全库存**（纸品/洗护/猫砂猫粮/方便面水饺汤圆等）
  - 待办 6：**每周邮件**汇总剩余与需购买
  - 待办 7：**语音记账**（如「加 10 包方便面」→ 匹配或新建并加库存）
- 购物清单汇总
- 现在就可以先录入物品与消耗；预测/语音/邮件升级后无需重新建账

## 技术栈

- Python 3.12 + FastAPI + aiosqlite（无 ORM，全裸 SQL）
- python-miio 局域网直控 + micloud 云端 MIOT 控制
- 前端单页 HTML + vanilla JS（无框架、无构建步骤）
- SQLite 存储

## 快速开始

```bash
git clone https://github.com/yuyuan1019/homedash.git
cd homedash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 配置米家设备（WiFi 设备需要 IP + token）
cp config/devices.yaml.example config/devices.yaml
# 编辑 devices.yaml，填入设备 IP 和 token

# 启动
uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000
```

## 配置

### 米家设备（config/devices.yaml）

设备分两种控制方式：

**WiFi 设备（局域网直控）** — 需要 `host`（IP）和 `token`：

```yaml
devices:
  - name: 猫房空调插座
    model: lumi.acpartner.mcn02
    host: 192.168.1.31
    token: <32位hex token>
    type: airconditioner
```

**BLE Mesh 设备（云端控制）** — 需要 `did`（小米云端设备 ID），`host` 留空：

```yaml
devices:
  - name: 客厅灯
    model: bean.switch.bl02
    host: ""
    did: "1088104207"
    token: <32位hex token>
    type: light
```

双键墙壁开关（`bean.switch.bl02`）有左右两键，默认控制左键（siid=2）。如需控制右键，加 `siid: 3`。

### 获取设备 Token 和 DID

**方式一：一键登录获取（推荐）**

内置登录脚本，自动获取所有设备的 token 和 BLE Mesh 设备的 DID：

```bash
# 第一步：获取验证码图片
python app/xiaomi_login.py

# 第二步：查看 /tmp/captcha.png 验证码，输入
python app/xiaomi_login.py <验证码>

# 成功后自动保存：
# - data/xiaomi_cloud.json  （云端凭据，BLE Mesh 控制必需）
# - data/ble_devices.json   （BLE Mesh 设备列表，含 did）
```

> **验证码说明**：小米登录会触发图形验证码。脚本第一步下载验证码图片到 `/tmp/captcha.png`，你需要查看图片内容（用图片查看器打开或 `xdg-open /tmp/captcha.png`），然后作为参数传给第二步。验证码有时效，过期需重新运行第一步。
>
> **二次验证**：如果小米账号开启了「登录保护」（二次验证），需要先在 https://account.xiaomi.com 的安全设置里临时关闭，登录成功后可重新开启。

**方式二：Xiaomi Cloud Tokens Extractor**

```bash
git clone https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor.git
cd Xiaomi-cloud-tokens-extractor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python token_extractor.py
# 输入小米账号、密码、服务器区域（中国选 cn）
# 自动列出所有设备 NAME / ID / MAC / TOKEN / MODEL / IP
```

> BLE Mesh 设备（墙壁开关等）在此工具输出里没有 IP，需用方式一获取 DID 后手动填入 `config/devices.yaml`。

**方式三：手动编辑** — 从上述工具输出中挑可控设备，按 YAML 格式填入 `config/devices.yaml`。

设备需已绑定米家 App 且与 HomeDash 在同一局域网（WiFi 设备）或已通过小米云端绑定（BLE Mesh 设备）。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KUMA_DB_PATH` | `/data/kuma.db` | Uptime Kuma 的 SQLite 文件路径 |
| `DEVICES_PATH` | `config/devices.yaml` | 米家设备配置文件路径 |
| `XIAOMI_USERNAME` | - | 小米账号（可选，BLE Mesh 设备登录用） |
| `XIAOMI_PASSWORD` | - | 小米密码（可选，BLE Mesh 设备登录用） |

> `XIAOMI_USERNAME`/`XIAOMI_PASSWORD` 只在首次获取云端凭据时需要。成功登录后凭据保存在 `data/xiaomi_cloud.json`，后续运行不再需要账号密码。建议登录完成后从 `.env` 中删除。

## Docker 部署

```bash
git clone https://github.com/yuyuan1019/homedash.git
cd homedash

# 1. 配置环境变量
cp .env.example .env
# 编辑 .env；如需 Uptime Kuma，设置 KUMA_DATA_DIR 为宿主机 Kuma 数据目录

# 2. 配置米家设备
cp config/devices.yaml.example config/devices.yaml
# 编辑 devices.yaml，填入设备信息

# 3. 启动
docker compose up -d
# 打开 http://localhost:8088
```

Docker Compose 只需要改两个文件：
- `.env`：端口、Kuma DB 宿主机路径等环境变量
- `config/devices.yaml`：米家设备配置

> 默认使用 Docker bridge 网络，适合按 IP 直连米家设备；如果后续要做局域网自动发现，再改成 host 网络。

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
| GET | `/api/devices/status` | 设备在线/电源状态（best-effort） |
| POST | `/api/devices/{name}/on` | 开启设备（WiFi 局域网 / BLE Mesh 云端） |
| POST | `/api/devices/{name}/off` | 关闭设备 |
| POST | `/api/devices/{name}/command` | 自定义命令（仅 WiFi 设备） |
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
├── .env                        # 小米账号密码（勿提交）
├── config/
│   ├── devices.yaml.example    # 设备配置模板
│   └── devices.yaml            # 实际配置（勿提交）
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── database.py             # SQLite 连接 + 建表
│   ├── xiaomi_login.py         # 小米云端登录（验证码交互）
│   ├── discover_devices.py     # 设备发现脚本
│   ├── modules/
│   │   ├── devices.py          # 米家设备控制（WiFi + BLE Mesh）
│   │   ├── uptime.py           # Uptime Kuma 对接
│   │   └── items.py            # 日用品 CRUD + 预测
│   └── static/
│       ├── index.html          # 页面骨架
│       ├── style.css           # 暗色主题样式
│       └── app.js              # 前端逻辑（三 Tab 全功能）
└── data/
    ├── homedash.db             # SQLite 数据库（自动创建）
    └── xiaomi_cloud.json       # 小米云端凭据（勿提交）
```

## License

MIT
