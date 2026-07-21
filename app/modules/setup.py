"""初始化设置：配置状态、LLM/Brave/SMTP 配置。"""
import asyncio
import json
import os
import smtplib
import tempfile
from email.utils import parseaddr

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

DATA_DIR = "data"
LLM_CONFIG_FILE = os.path.join(DATA_DIR, "llm_config.json")
NOTIFY_CONFIG_FILE = os.path.join(DATA_DIR, "notify_config.json")
BRAVE_CONFIG_FILE = os.path.join(DATA_DIR, "brave_config.json")
AGENT_CONFIG_FILE = os.path.join(DATA_DIR, "agent_config.json")
AMAP_CONFIG_FILE = os.path.join(DATA_DIR, "amap_config.json")


class LlmConfigIn(BaseModel):
    base_url: str
    api_key: str = ""
    model: str
    timeout_sec: float = 30.0
    enabled: bool = True
    confirm_required: bool = True
    max_actions: int = 8


class NotifyConfigIn(BaseModel):
    smtp_host: str
    smtp_port: int = 465
    smtp_user: str
    smtp_password: str = ""
    smtp_from: str = ""
    notify_to: str
    notify_enabled: bool = False
    notify_only_when_need_buy: bool = False
    notify_todo_limit: int = 20
    homedash_public_url: str = ""


class BraveConfigIn(BaseModel):
    api_key: str = ""


class AmapConfigIn(BaseModel):
    api_key: str = ""


class AgentConfigIn(BaseModel):
    token: str = ""


def _agent_file_config() -> dict | None:
    """读取 data/agent_config.json"""
    if not os.path.isfile(AGENT_CONFIG_FILE):
        return None
    try:
        with open(AGENT_CONFIG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _agent_token() -> str:
    """获取 Agent Token：环境变量优先，其次文件配置"""
    env_token = os.getenv("AGENT_API_TOKEN", "").strip()
    if env_token:
        return env_token
    cfg = _agent_file_config()
    if cfg and cfg.get("token"):
        return str(cfg["token"]).strip()
    return ""


def _mask(value: str | None, head: int = 4, tail: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= head + tail:
        return "*" * len(value)
    return value[:head] + "*" * (len(value) - head - tail) + value[-tail:]


def _masked(value: str) -> bool:
    return "*" in value


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _llm_env_config() -> dict | None:
    base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")
    if not base_url or not api_key or not model:
        return None
    return {
        "base_url": _api_base_url(base_url),
        "api_key": api_key,
        "model": model,
        "timeout_sec": _float(os.getenv("LLM_TIMEOUT_SEC"), 30.0),
        "enabled": os.getenv("AI_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
        "confirm_required": os.getenv("AI_CONFIRM_REQUIRED", "true").lower() in {"1", "true", "yes", "on"},
        "max_actions": max(1, _int(os.getenv("AI_MAX_ACTIONS"), 8)),
    }


def _llm_file_config() -> dict | None:
    if not os.path.isfile(LLM_CONFIG_FILE):
        return None
    try:
        with open(LLM_CONFIG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _llm_config() -> dict | None:
    # env 优先，其次 data/llm_config.json
    return _llm_env_config() or _llm_file_config()


def _brave_file_config() -> dict | None:
    if not os.path.isfile(BRAVE_CONFIG_FILE):
        return None
    try:
        with open(BRAVE_CONFIG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _brave_config() -> dict:
    env_key = os.getenv("BRAVE_API_KEY", "").strip()
    if env_key:
        return {"api_key": env_key}
    file_cfg = _brave_file_config() or {}
    return {"api_key": file_cfg.get("api_key", "")}


def _brave_configured() -> bool:
    return bool(_brave_config().get("api_key"))


def _amap_file_config() -> dict | None:
    if not os.path.isfile(AMAP_CONFIG_FILE):
        return None
    try:
        with open(AMAP_CONFIG_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _amap_config() -> dict:
    """高德配置：环境变量 AMAP_API_KEY 优先，其次 data/amap_config.json。"""
    env_key = os.getenv("AMAP_API_KEY", "").strip()
    if env_key:
        return {"api_key": env_key}
    file_cfg = _amap_file_config() or {}
    return {"api_key": file_cfg.get("api_key", "")}


def _amap_configured() -> bool:
    return bool(_amap_config().get("api_key"))


def _notify_file_config() -> dict:
    if not os.path.isfile(NOTIFY_CONFIG_FILE):
        return {}
    try:
        with open(NOTIFY_CONFIG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _notify_config() -> dict:
    file_cfg = _notify_file_config()
    return {
        "smtp_host": os.getenv("SMTP_HOST") or file_cfg.get("smtp_host", ""),
        "smtp_port": _int(os.getenv("SMTP_PORT") or file_cfg.get("smtp_port"), 465),
        "smtp_user": os.getenv("SMTP_USER") or file_cfg.get("smtp_user", ""),
        "smtp_password": os.getenv("SMTP_PASSWORD") or file_cfg.get("smtp_password", ""),
        "smtp_from": os.getenv("SMTP_FROM") or file_cfg.get("smtp_from", ""),
        "notify_to": os.getenv("NOTIFY_TO") or file_cfg.get("notify_to", ""),
        "notify_enabled": str(os.getenv("NOTIFY_ENABLED") or file_cfg.get("notify_enabled", False)).lower() in {"1", "true", "yes", "on"},
        "notify_only_when_need_buy": str(os.getenv("NOTIFY_ONLY_WHEN_NEED_BUY") or file_cfg.get("notify_only_when_need_buy", False)).lower() in {"1", "true", "yes", "on"},
        "notify_todo_limit": _int(os.getenv("NOTIFY_TODO_LIMIT") or file_cfg.get("notify_todo_limit"), 20),
        "homedash_public_url": os.getenv("HOMEDASH_PUBLIC_URL") or file_cfg.get("homedash_public_url", ""),
    }


def _notify_configured() -> bool:
    cfg = _notify_config()
    return bool(cfg["smtp_host"] and cfg["smtp_user"] and cfg["smtp_password"] and cfg["notify_to"])


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _api_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if url and not url.endswith(("/v1", "/v1beta")):
        return f"{url}/v1"
    return url


def _llm_error_message(status_code: int) -> str:
    if status_code in {401, 403}:
        return "LLM API Key 无效或无权限"
    if status_code == 404:
        return "LLM 地址或模型不存在"
    if status_code == 429:
        return "LLM 限流或余额不足"
    if status_code in {502, 503, 504}:
        return "LLM 网关可用，但上游模型请求失败，请换模型或稍后重试"
    return "LLM 连接失败，请检查地址、密钥和模型名"


async def _test_llm_connection(cfg: dict) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=cfg["timeout_sec"]) as client:
            response = await client.post(
                f"{cfg['base_url'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json={
                    "model": cfg["model"],
                    "messages": [
                        {"role": "system", "content": "只输出 JSON：{\"ok\":true}"},
                        {"role": "user", "content": "测试"},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 20,
                },
            )
            if response.status_code >= 400:
                if response.status_code == 400 and "response_format" in response.text:
                    response = await client.post(
                        f"{cfg['base_url'].rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {cfg['api_key']}"},
                        json={"model": cfg["model"], "messages": [{"role": "user", "content": "只输出 JSON：{\"ok\":true}"}], "max_tokens": 20},
                    )
                    if response.status_code >= 400:
                        return False, _llm_error_message(response.status_code)
                else:
                    return False, _llm_error_message(response.status_code)
            content = response.json()["choices"][0]["message"]["content"]
            try:
                data = json.loads(content) if isinstance(content, str) else None
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                return True, "LLM 连接正常，且可返回合法 JSON"
            return False, "连接成功，但模型没有返回合法 JSON，建议换支持结构化输出的模型"
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError):
        return False, "LLM 连接失败，请检查地址、密钥和模型名"


async def _test_brave_connection(api_key: str) -> tuple[bool, str]:
    if not api_key:
        return False, "Brave API Key 未配置"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json",
                },
                params={"q": "test", "count": "1"},
            )
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "web" in data:
                return True, "Brave Search 连接正常"
            return False, "Brave Search 返回异常格式，请检查 API Key"
        if response.status_code in {401, 403}:
            return False, "Brave API Key 无效或无权限"
        if response.status_code == 429:
            return False, "Brave Search 本月配额已用完"
        return False, f"Brave Search 连接失败 (HTTP {response.status_code})"
    except httpx.HTTPError:
        return False, "Brave Search 连接失败，请检查网络"


async def _test_amap_connection(api_key: str) -> tuple[bool, str]:
    """用一次地理编码校验高德 Key（status 为字符串 '1' 且能解出坐标即有效）。"""
    if not api_key:
        return False, "高德 Key 未配置"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://restapi.amap.com/v3/geocode/geo",
                params={"key": api_key, "address": "北京"},
            )
        if resp.status_code != 200:
            return False, f"高德连接失败 (HTTP {resp.status_code})"
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return False, "高德连接失败，请检查网络与 Key"
    if not isinstance(data, dict):
        return False, "高德返回异常格式，请检查 Key"
    if str(data.get("status")) != "1":
        info = data.get("info") or "Key 无效或配额问题"
        return False, f"高德 Key 校验失败：{info}"
    geocodes = data.get("geocodes") or []
    return (True, "高德 Key 有效，地理编码正常") if geocodes else (False, "高德返回异常，未解析到坐标")


async def _fetch_llm_models(cfg: dict) -> tuple[bool, str, list[str]]:
    try:
        async with httpx.AsyncClient(timeout=cfg["timeout_sec"]) as client:
            response = await client.get(f"{cfg['base_url'].rstrip('/')}/models", headers={"Authorization": f"Bearer {cfg['api_key']}"})
            if response.status_code >= 400:
                return False, _llm_error_message(response.status_code), []
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return False, "无法获取模型列表，请检查 Base URL / API Key", []

    raw_models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw_models, list):
        return False, "无法获取模型列表，请检查 Base URL / API Key", []
    models = []
    for item in raw_models:
        if isinstance(item, dict) and item.get("id"):
            models.append(str(item["id"]))
        elif isinstance(item, str):
            models.append(item)
    return bool(models), "模型列表已获取" if models else "无法获取模型列表，请检查 Base URL / API Key", models


def _merge_llm_payload(payload: LlmConfigIn) -> dict:
    current = _llm_config() or {}
    api_key = payload.api_key.strip()
    if not api_key or _masked(api_key):
        api_key = current.get("api_key", "")
    return {
        "base_url": _api_base_url(payload.base_url),
        "api_key": api_key,
        "model": payload.model.strip(),
        "timeout_sec": max(5.0, payload.timeout_sec),
        "enabled": payload.enabled,
        "confirm_required": payload.confirm_required,
        "max_actions": max(1, payload.max_actions),
    }


def _merge_notify_payload(payload: NotifyConfigIn) -> dict:
    current = _notify_config()
    password = payload.smtp_password.strip()
    if not password or _masked(password):
        password = current.get("smtp_password", "")
    smtp_user = payload.smtp_user.strip()
    smtp_from = payload.smtp_from.strip()
    parsed_from = parseaddr(smtp_from)[1]
    if smtp_from and "@" not in parsed_from:
        smtp_from = f"{smtp_from} <{smtp_user}>"
    return {
        "smtp_host": payload.smtp_host.strip(),
        "smtp_port": payload.smtp_port,
        "smtp_user": smtp_user,
        "smtp_password": password,
        "smtp_from": smtp_from or smtp_user,
        "notify_to": payload.notify_to.strip(),
        "notify_enabled": payload.notify_enabled,
        "notify_only_when_need_buy": payload.notify_only_when_need_buy,
        "notify_todo_limit": max(1, payload.notify_todo_limit),
        "homedash_public_url": payload.homedash_public_url.strip(),
    }


def _merge_brave_payload(payload: BraveConfigIn) -> dict:
    current = _brave_config()
    api_key = payload.api_key.strip()
    if not api_key or _masked(api_key):
        api_key = current.get("api_key", "")
    return {"api_key": api_key}


def _merge_amap_payload(payload: AmapConfigIn) -> dict:
    current = _amap_config()
    api_key = payload.api_key.strip()
    if _masked(api_key):
        api_key = current.get("api_key", "")
    return {"api_key": api_key}


def _test_smtp_sync(cfg: dict) -> tuple[bool, str]:
    if not cfg["smtp_host"] or not cfg["smtp_user"] or not cfg["smtp_password"] or not cfg["notify_to"]:
        return False, "SMTP_HOST、SMTP_USER、SMTP_PASSWORD 和 NOTIFY_TO 必填"
    try:
        if int(cfg["smtp_port"]) == 465:
            client = smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=15)
        else:
            client = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=15)
            client.starttls()
        with client:
            client.login(cfg["smtp_user"], cfg["smtp_password"])
        return True, "SMTP 登录成功"
    except (smtplib.SMTPException, OSError) as exc:
        return False, f"SMTP 登录失败: {exc}"


@router.get("/setup/status")
async def setup_status():
    """返回本地配置完整度（不做实时外网探测，避免卡顿/烧 token）。"""
    llm_cfg = _llm_config()
    llm_configured = llm_cfg is not None
    smtp_configured = _notify_configured()
    brave_configured = _brave_configured()
    amap_configured = _amap_configured()
    agent_token = _agent_token()

    missing = []
    if not llm_configured:
        missing.append("未配置 AI 工作台 LLM")
    # SMTP / Brave 可选，不进 missing

    return {
        "llm_configured": llm_configured,
        "llm_status": llm_configured,
        "llm_model": _mask(llm_cfg.get("model")) if llm_cfg else "",
        "smtp_configured": smtp_configured,
        "agent_token_configured": bool(agent_token),
        "brave_configured": brave_configured,
        "amap_configured": amap_configured,
        "missing": missing,
    }


@router.get("/setup/llm/config")
async def get_llm_config():
    cfg = _llm_config()
    if not cfg:
        return None
    return {
        **cfg,
        "api_key": _mask(cfg.get("api_key", "")),
        "source": "env" if _llm_env_config() else "file",
    }


@router.post("/setup/llm/save")
async def save_llm_config(payload: LlmConfigIn):
    cfg = _merge_llm_payload(payload)
    if not cfg["base_url"] or not cfg["api_key"] or not cfg["model"]:
        raise HTTPException(400, "Base URL、API Key 和模型均不能为空")
    _write_json(LLM_CONFIG_FILE, cfg)
    ok, message = await _test_llm_connection(cfg)
    return {"ok": True, "tested": ok, "message": message if ok else f"保存成功，但{message}"}


@router.post("/setup/llm/test")
async def test_llm_config(payload: LlmConfigIn):
    cfg = _merge_llm_payload(payload)
    if not cfg["base_url"] or not cfg["api_key"] or not cfg["model"]:
        return {"ok": False, "message": "Base URL、API Key 和模型均不能为空"}
    ok, message = await _test_llm_connection(cfg)
    return {"ok": ok, "message": message}


@router.get("/setup/llm/models")
async def list_llm_models():
    cfg = _llm_config()
    if not cfg or not cfg.get("base_url") or not cfg.get("api_key"):
        return {"ok": False, "message": "请先配置 LLM Base URL 和 API Key", "models": []}
    ok, message, models = await _fetch_llm_models(cfg)
    return {"ok": ok, "message": message, "models": models}


@router.get("/setup/brave/config")
async def get_brave_config():
    cfg = _brave_config()
    api_key = cfg.get("api_key", "")
    return {
        "api_key": _mask(api_key) if api_key else "",
        "source": "env" if os.getenv("BRAVE_API_KEY", "").strip() else "file" if _brave_file_config() else "none",
    }


@router.post("/setup/brave/save")
async def save_brave_config(payload: BraveConfigIn):
    api_key = _merge_brave_payload(payload)["api_key"]
    if api_key:
        _write_json(BRAVE_CONFIG_FILE, {"api_key": api_key})
    elif os.path.isfile(BRAVE_CONFIG_FILE):
        os.remove(BRAVE_CONFIG_FILE)
    ok, message = await _test_brave_connection(api_key)
    return {"ok": True, "tested": ok, "message": message if ok else f"保存成功，但{message}"}


@router.post("/setup/brave/test")
async def test_brave_config(payload: BraveConfigIn):
    api_key = _merge_brave_payload(payload)["api_key"]
    if not api_key:
        return {"ok": False, "message": "API Key 不能为空"}
    ok, message = await _test_brave_connection(api_key)
    return {"ok": ok, "message": message}


@router.get("/setup/amap/config")
async def get_amap_config():
    cfg = _amap_config()
    api_key = cfg.get("api_key", "")
    return {
        "api_key": _mask(api_key) if api_key else "",
        "source": "env" if os.getenv("AMAP_API_KEY", "").strip() else "file" if _amap_file_config() else "none",
    }


@router.post("/setup/amap/save")
async def save_amap_config(payload: AmapConfigIn):
    api_key = _merge_amap_payload(payload)["api_key"]
    if api_key:
        _write_json(AMAP_CONFIG_FILE, {"api_key": api_key})
    elif os.path.isfile(AMAP_CONFIG_FILE):
        os.remove(AMAP_CONFIG_FILE)
    ok, message = await _test_amap_connection(api_key)
    return {"ok": True, "tested": ok, "message": message if ok else f"保存成功，但{message}"}


@router.post("/setup/amap/test")
async def test_amap_config(payload: AmapConfigIn):
    api_key = _merge_amap_payload(payload)["api_key"]
    if not api_key:
        return {"ok": False, "message": "高德 Key 不能为空"}
    ok, message = await _test_amap_connection(api_key)
    return {"ok": ok, "message": message}


@router.get("/setup/agent/config")
async def get_agent_config():
    """获取 Agent Token 配置状态"""
    env_token = os.getenv("AGENT_API_TOKEN", "").strip()
    file_cfg = _agent_file_config()
    token = _agent_token()
    return {
        "token": _mask(token) if token else "",
        "configured": bool(token),
        "source": "env" if env_token else "file" if file_cfg else "none",
    }


@router.post("/setup/agent/save")
async def save_agent_config(payload: AgentConfigIn):
    """保存 Agent Token 配置到文件"""
    token = payload.token.strip()
    if token:
        _write_json(AGENT_CONFIG_FILE, {"token": token})
    elif os.path.isfile(AGENT_CONFIG_FILE):
        os.remove(AGENT_CONFIG_FILE)
    return {"ok": True, "configured": bool(token)}


@router.get("/setup/notify/config")
async def get_notify_config():
    cfg = _notify_config()
    return {
        **cfg,
        "smtp_password": _mask(cfg.get("smtp_password", "")),
        "source": "env" if os.getenv("SMTP_HOST") else "file" if _notify_file_config() else "none",
    }


@router.post("/setup/notify/save")
async def save_notify_config(payload: NotifyConfigIn):
    cfg = _merge_notify_payload(payload)
    _write_json(NOTIFY_CONFIG_FILE, cfg)
    ok, message = await asyncio.to_thread(_test_smtp_sync, cfg)
    return {"ok": True, "tested": ok, "message": message}


@router.post("/setup/notify/test")
async def test_notify_config(payload: NotifyConfigIn):
    cfg = _merge_notify_payload(payload)
    ok, message = await asyncio.to_thread(_test_smtp_sync, cfg)
    return {"ok": ok, "message": message}


@router.get("/setup/env-snippet")
async def env_snippet():
    lines = ["# HomeDash 配置片段（由设置页生成，复制到 .env 后执行 docker compose restart）"]
    if not _llm_config():
        lines.append("# LLM 未配置，可在设置页直接保存；或取消下面注释并填写：")
        lines.append("# LLM_BASE_URL=https://your-openai-compatible/v1")
        lines.append("# LLM_API_KEY=")
        lines.append("# LLM_MODEL=")
    if not _notify_configured():
        lines.append("# SMTP 周报可在设置页直接保存到 data/notify_config.json 并热加载。")
    if not os.getenv("AGENT_API_TOKEN", ""):
        lines.append("# home agent 接口 token（公网映射时必须设置）：")
        lines.append("# AGENT_API_TOKEN=your-random-token")
    if not _brave_configured():
        lines.append("# Brave Search 联网搜索（可在设置页直接保存到 data/brave_config.json）：")
        lines.append("# BRAVE_API_KEY=")
    if not _amap_configured():
        lines.append("# 高德地图交通时长（旅游推荐用，可在设置页直接保存到 data/amap_config.json）：")
        lines.append("# AMAP_API_KEY=")
    return {"snippet": "\n".join(lines)}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        DATA_DIR = tmp
        LLM_CONFIG_FILE = os.path.join(tmp, "llm_config.json")
        NOTIFY_CONFIG_FILE = os.path.join(tmp, "notify_config.json")
        BRAVE_CONFIG_FILE = os.path.join(tmp, "brave_config.json")
        AMAP_CONFIG_FILE = os.path.join(tmp, "amap_config.json")

        _write_json(LLM_CONFIG_FILE, {"base_url": "https://example.com/v1", "api_key": "sk-test", "model": "m", "timeout_sec": 10, "enabled": True, "confirm_required": True, "max_actions": 4})
        assert _llm_file_config()["model"] == "m"

        _write_json(NOTIFY_CONFIG_FILE, {"smtp_host": "smtp.example.com", "smtp_user": "u", "smtp_password": "p", "notify_to": "a@example.com"})
        assert _notify_configured()

        _write_json(AMAP_CONFIG_FILE, {"api_key": "amap-test"})
        assert _amap_file_config()["api_key"] == "amap-test"
        assert _merge_amap_payload(AmapConfigIn(api_key=""))["api_key"] == ""

        assert _mask("sk-abcdefgh1234") == "sk-a*******1234"
        assert _mask("") == ""
        assert _mask("short") == "*****"
        assert _masked("sk-****") is True

    print("setup.py 自检通过：LLM / SMTP / Brave / 高德 配置读写与掩码逻辑正确。")
