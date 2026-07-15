# AI 工作台报错排查与明日修复计划

日期：2026-07-14

## 现象

用户在「AI 工作台」点击「生成操作预览」后，前端提示 AI 解析失败。

容器日志中对应请求：

```text
POST /api/ai/parse HTTP/1.1 502 Bad Gateway
```

当前 LLM 配置状态：

```json
{
  "base_url": "https://speedtest.yuans.me:16998",
  "model": "gpt-5.5",
  "source": "file"
}
```

`/api/setup/status` 显示 `llm_configured=true`、`llm_status=true`，说明设置页的轻量连接测试通过；失败发生在 AI 工作台实际解析阶段。

## 当前代码路径

AI 工作台解析入口：

```python
POST /api/ai/parse
app/modules/ai_workbench.py:145
```

当前逻辑：

1. 读取 LLM 配置：`LLM_*` 环境变量优先，其次 `data/llm_config.json`。
2. 拼系统 prompt 和当前 items/todos 快照。
3. 请求：`{base_url}/chat/completions`。
4. 读取：`response.json()["choices"][0]["message"]["content"]`。
5. 直接 `json.loads(content)`。
6. 任何 HTTP 错误、字段缺失、JSON 解析失败都会统一返回 502：`AI 解析失败，未写入任何数据`。

## 初步判断的原因

最可能原因：模型返回内容不是纯 JSON。

虽然 prompt 要求“只能输出 JSON”，但当前请求没有使用 OpenAI-compatible 的结构化输出约束，例如：

```json
{"response_format": {"type": "json_object"}}
```

因此模型可能返回以下任一种内容，都会触发 502：

- Markdown 包裹：```json ... ```
- 先解释后 JSON：`好的，我将执行：{...}`
- 返回空内容或拒答
- 网关返回的 `message.content` 不是字符串
- 上游模型名填错，但轻量测试没有覆盖实际 JSON 解析能力

第二个可能原因：模型名虽然能响应 `Hi`，但不适合严格 JSON 工具解析。

当前设置页测试只发短文本 `Hi`，只判断 HTTP 200，不能证明模型会按 HomeDash 的 action JSON 协议返回。

## 明日修复目标

1. AI 工作台报错能显示更具体原因，便于用户修改配置。
2. 增加“获取上游模型列表”接口，避免手填模型名错误。
3. 设置页提供模型下拉/刷新按钮。
4. AI parse 请求尽量强制 JSON 输出；模型不支持时做兼容解析。

## 后端修复计划

### 1. 增加模型列表接口

新增接口：

```http
GET /api/setup/llm/models
```

行为：

1. 读取当前 LLM 配置。
2. 请求：`GET {base_url}/models`。
3. 兼容 OpenAI-compatible 响应：

```json
{
  "data": [
    {"id": "gpt-4o-mini"},
    {"id": "gpt-5.5"}
  ]
}
```

4. 返回：

```json
{
  "ok": true,
  "models": ["gpt-4o-mini", "gpt-5.5"]
}
```

失败时返回中文错误：

```json
{
  "ok": false,
  "message": "无法获取模型列表，请检查 Base URL / API Key"
}
```

### 2. 设置页 LLM 测试升级为“结构化测试”

当前测试只发 `Hi`，改为测试模型是否能返回 JSON：

```text
只输出 JSON：{"ok":true}
```

并检查返回内容是否可解析为 JSON。

### 3. `POST /api/ai/parse` 增强错误信息

当前所有异常都是：

```text
AI 解析失败，未写入任何数据
```

建议拆分：

- HTTP 401/403：`LLM API Key 无效或无权限`
- HTTP 404：`LLM 地址或模型不存在`
- HTTP 429：`LLM 限流或余额不足`
- JSON 解析失败：`模型未返回合法 JSON，请换支持结构化输出的模型或重试`
- 字段缺失：`上游响应格式不是 OpenAI Chat Completions`

注意：错误信息不得输出完整 API Key。

### 4. 请求增加 JSON 输出约束

在 `/chat/completions` 请求体中增加：

```json
"response_format": {"type": "json_object"}
```

如果上游不支持该参数，可能返回 400。处理方式：

1. 先带 `response_format` 请求。
2. 若 400 且错误提示参数不支持，则 fallback 到不带 `response_format` 再试一次。

### 5. 兼容 Markdown JSON 代码块

增加最小 JSON 提取逻辑：

1. 优先 `json.loads(content)`。
2. 失败时尝试去掉 ```json / ``` 包裹。
3. 再失败时从第一个 `{` 到最后一个 `}` 截取。
4. 仍失败才返回中文错误。

不要引入新依赖。

## 前端修复计划

### 1. 设置页增加“获取模型”按钮

位置：AI 工作台配置表单。

新增按钮：

```text
获取模型列表
```

点击后：

1. 调 `/api/setup/llm/models`。
2. 成功后显示 `<select>` 或 datalist。
3. 用户点击模型名后填入 `#llm-model`。

### 2. 保存并测试时使用结构化测试

失败时展示更明确文案，例如：

```text
连接成功，但模型没有返回合法 JSON，建议换模型或点击“获取模型列表”。
```

### 3. AI 工作台 parse 失败展示后端 detail

当前已有 toast 展示 `data.detail`，后端错误信息细化后前端无需大改。

## 验收命令

从仓库根目录运行：

```bash
python -m app.modules.setup
python -m app.modules.ai_workbench
node --check app/static/app.js
docker compose build
docker compose up -d
curl -s http://127.0.0.1:8088/api/setup/llm/models
```

手工验收：

1. 设置页点击“获取模型列表”能列出上游模型。
2. 选择模型后保存并测试。
3. AI 工作台输入：`加 1 包方便面`。
4. 页面应显示 `item.purchase` 预览，而不是 502。
5. 若模型返回非 JSON，应显示明确中文错误。

## 明确不做

- 不新增模型供应商 SDK。
- 不引入前端框架。
- 不让 LLM 直接执行 SQL。
- 不把 API Key、SMTP 密码、米家 token 写入日志或前端响应。
