---
name: homedash-agent
description: "HomeDash 家庭面板 agent 接口：重点待办 CRUD、提醒查询、库存/预测操作。通过 HTTP 调用自托管的 HomeDash API 让 agent 直接操作用户的待办与日用品库存。"
version: 1.1
tags: [homedash, todos, inventory, agent, http]
triggers:
  - 用户提到 HomeDash / 家庭面板 / 重点待办 / 库存
  - 用户想让 agent 帮建待办、查待办、标记完成
  - 用户想查日用品、记消耗/购买、看预测
---

# HomeDash Agent Skill

HomeDash 是用户自托管的家庭管理面板。本 skill 让 agent 通过 HTTP 调用其 API 直接操作**重点待办**与**日用品库存**，无需进面板。

## 0. 部署地址

**HomeDash URL 由用户环境决定**，常见场景：
- 本机部署：`http://127.0.0.1:8088` 或 `http://localhost:8088`
- 内网访问：`http://192.168.x.x:8088`
- 反向代理：`https://homedash.example.com`

**获取方式**：
- 问用户「你的 HomeDash 地址是什么？」
- 如果是本机部署，默认尝试 `http://127.0.0.1:8088`
- 检查环境变量 `HOMEDASH_URL`（如果用户设置了）

下文用 `${HOMEDASH_URL}` 代指实际地址。

## 1. 鉴权

端点分两类：
- **普通端点** `/api/todos/*`、`/api/items/*`：无鉴权（依赖网络隔离）
- **Agent 端点** `/api/agent/*`：需要 header `X-Homedash-Token: ${TOKEN}` 或 `Authorization: Bearer ${TOKEN}`

**Token 来源**：
- HomeDash 部署目录的 `.env` 文件中 `AGENT_API_TOKEN`
- 如果未设置该变量，则跳过校验（不推荐生产环境）
- 问用户「你的 AGENT_API_TOKEN 是什么？」或让用户从 `.env` 中读取

## 2. 重点待办 API

基础：`${HOMEDASH_URL}/api`

| 操作 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 列出待办 | GET | `/todos?status=open` | status: open/done/all |
| 待办摘要 | GET | `/todos/summary` | 含 open_count、overdue_count、top 5 |
| 创建待办 | POST | `/agent/todos` | 见下方 body |
| 列出待办（agent 版） | GET | `/agent/todos/open` | 带 token；可加 `?priority=high` |
| 即将到期 | GET | `/agent/todos/due?within_minutes=15&channel=qq` | 提醒时间 ≤ now+cutoff |
| 标记完成 | POST | `/agent/todos/{id}/done` | |
| 改提醒 | PUT | `/agent/todos/{id}/remind` | body: remind_at/remind_channels/remind_repeat |
| 标记提醒已发 | POST | `/agent/todos/{id}/remind-fired` | body: channel/delivered_at/external_ref |

**创建待办 body（TodoIn）**：

```json
{
  "title": "换净水器滤芯",
  "note": "柜下 3M",
  "priority": "high",
  "due_date": "2026-07-31",
  "assignee": "yuan",
  "remind_at": "2026-07-20T09:00:00",
  "remind_channels": ["qq", "wechat"],
  "remind_repeat": "weekly",
  "external_ref": "qq-msg-123"
}
```

**字段说明**：
- `title`：必填
- `priority`：high/medium/low，默认 medium
- `due_date`：YYYY-MM-DD 或 null
- `remind_at`：ISO 格式（如 `2026-07-20T09:00:00`），缺时区则按服务器时区（通常 Asia/Shanghai）解析
- `remind_channels`：提醒频道标识（如 `qq`/`wechat`/`telegram`），由外部系统投递
- `remind_repeat`：none/once/daily/weekly

**返回字段**：id, title, note, priority, due_date, assignee, status, remind_at, remind_channels, remind_repeat, external_ref, overdue (bool), created_at, updated_at, completed_at.

**提醒消息模板**（`/agent/todos/due` 返回的 `message` 字段）：
```
【HomeDash 待办】{title}
截止 {due_date} · {高/中/低}优先级 · {assignee}
{note}
```

## 3. 日用品库存 API

| 操作 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 列出全部 | GET | `/items` | 每项含 prediction |
| 预测汇总 | GET | `/items/predictions` | 分 need_buy / sufficient |
| 单个详情 | GET | `/items/{id}` | 含 history |
| 新建 | POST | `/items` | body: name/category/unit/current_stock/min_stock/location/expires_at |
| 改库存 | PUT | `/items/{id}` | body: 部分字段 |
| 记消耗 | POST | `/items/{id}/usage` | body: amount, note |
| 记购买 | POST | `/items/{id}/purchase` | body: amount, price, note |
| 历史 | GET | `/items/{id}/history` | 合并 usage+purchase |

**预测字段**（每个 item 的 `prediction`）：

| 字段 | 含义 |
|------|------|
| daily_rate | EWMA 日均消耗 |
| days_until_empty | 当前库存可撑天数 |
| est_empty_date | 预计用完日期 |
| need_buy | 是否建议购买 |
| suggested_qty | 建议购买量（覆盖 30 天） |
| confidence | 预测可信度 high/medium/low |
| method | ewma/purchase_interval/category_prior/min_stock_only/none |
| safety_stock | 安全库存（含 3 天缓冲） |

**库存方向**：`usage` 减库存，`purchase` 加库存。**写反是 P0 bug**。

## 4. HTTP 请求模板

**列未完成的待办（带 token）**：
```bash
curl -s -H "X-Homedash-Token: ${TOKEN}" '${HOMEDASH_URL}/api/agent/todos/open' | jq
```

**创建高优先级待办，明天 9 点提醒**：
```bash
curl -s -X POST \
  -H "X-Homedash-Token: ${TOKEN}" \
  -H 'Content-Type: application/json' \
  '${HOMEDASH_URL}/api/agent/todos' \
  -d '{
    "title": "洗车",
    "priority": "high",
    "due_date": "2026-07-16",
    "remind_at": "2026-07-16T09:00:00",
    "remind_channels": ["qq"]
  }'
```

**查库存预警**：
```bash
curl -s '${HOMEDASH_URL}/api/items/predictions' | jq '.need_buy | length'
```

**记一笔消耗（洗手液用了 0.5 瓶）**：
```bash
curl -s -X POST \
  -H 'Content-Type: application/json' \
  '${HOMEDASH_URL}/api/items/3/usage' \
  -d '{"amount": 0.5, "note": "洗手"}'
```

## 5. 常见 agent 对话 → API 映射

| 用户说 | 动作 |
|--------|------|
| 「帮我建个待办：周五前换滤芯，优先级高」 | POST `/agent/todos` with title, due_date=本周五, priority=high |
| 「提醒我明早 9 点吃药」 | POST `/agent/todos` with title=吃药, remind_at=明天 09:00, remind_channels=[qq] |
| 「我有哪些待办」 | GET `/agent/todos/open` |
| 「有没有快到期/过期的待办」 | GET `/agent/todos/due?within_minutes=1440` |
| 「那个待办做完了」 | POST `/agent/todos/{id}/done` |
| 「家里的纸/洗衣液还有多少」 | GET `/items`，按 name 匹配 |
| 「哪些东西要买了」 | GET `/items/predictions`，读 need_buy |
| 「刚买了 2 瓶洗手液」 | POST `/items/{id}/purchase` with amount=2 |
| 「用了 1 卷纸」 | POST `/items/{id}/usage` with amount=1 |

## 6. 陷阱与注意事项

- **时间格式**：`remind_at` 必须 ISO（`2026-07-20T09:00:00`），缺时区则按服务器时区解析
- **due_date**：必须 `YYYY-MM-DD`，不能带时间
- **priority**：只能 high/medium/low，写错返回 400
- **remind_channels**：是 list[str]，存 JSON 字符串。可填任意标识，由外部系统投递
- **库存方向**：usage 减、purchase 加。**不要自己写 SQL**
- **物品 ID**：创建后返回 `{id: N}`，后续操作需这个 id。如果用户只给名字，先 GET `/items` 找 id
- **agent 端点 vs 普通端点**：`/agent/*` 要 token；普通 `/todos`、`/items` 不要。优先用 `/agent/*`（语义更明确、支持过滤）
- **服务未启动时**：`curl` 会 connection refused。先确认 HomeDash 是否运行

## 7. 与定时任务配合

典型场景：每天早上 8 点推送今日待办。

```bash
# 查询今日到期的待办
curl -s -H "X-Homedash-Token: ${TOKEN}" \
  '${HOMEDASH_URL}/api/agent/todos/due?within_minutes=1440&channel=qq'

# 如果有 items，逐条推送给用户；如果没有，静默
```

## 8. 自检

**健康检查**：
```bash
curl -sf '${HOMEDASH_URL}/api/todos/summary' | jq .
```

**Token 可用性**：
```bash
curl -sf -H "X-Homedash-Token: ${TOKEN}" \
  '${HOMEDASH_URL}/api/agent/todos/open' | jq .
```

---

_最后更新：2026-07-15 · v1.1 通用化版本 · 基于 HomeDash 代码现状（todos.py / items.py）_
