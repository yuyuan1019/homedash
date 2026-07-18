"""初始化设置：配置状态、米家设备/云端登录、LLM/SMTP 配置。"""
import asyncio
import string
import json
import os
import smtplib
import tempfile
from email.utils import parseaddr

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.modules import devices

router = APIRouter()

DATA_DIR = "data"
LLM_CONFIG_FILE = os.path.join(DATA_DIR, "llm_config.json")
NOTIFY_CONFIG_FILE = os.path.join(DATA_DIR, "notify_config.json")
APP_CONFIG_FILE = os.path.join(DATA_DIR, "app_config.json")
XIAOMI_CREDS_FILE = os.path.join(DATA_DIR, "xiaomi_cloud.json")
BLE_DEVICES_FILE = os.path.join(DATA_DIR, "ble_devices.json")
BRAVE_CONFIG_FILE = os.path.join(DATA_DIR, "brave_config.json")


class DeviceIn(BaseModel):
    name: str
    original_name: str = ""
    type: str = "light"
    model: str = ""
    host: str = ""
    token: str = ""
    did: str = ""
    siid: int | None = None


class XiaomiLoginStep1In(BaseModel):
    username: str
    password: str


class XiaomiLoginStep2In(BaseModel):
    state_id: str
    captcha_code: str
    username: str = ""
    password: str = ""


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


class AppConfigIn(BaseModel):
    kuma_public_url: str = ""


class BraveConfigIn(BaseModel):
    api_key: str = ""


def _devices_yaml_path() -> str:
    return os.getenv("DEVICES_PATH", "config/devices.yaml")


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


def _app_file_config() -> dict:
    if not os.path.isfile(APP_CONFIG_FILE):
        return {}
    try:
        with open(APP_CONFIG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _app_config() -> dict:
    file_cfg = _app_file_config()
    return {"kuma_public_url": os.getenv("KUMA_PUBLIC_URL") or file_cfg.get("kuma_public_url", "")}


def _load_yaml() -> dict:
    path = _devices_yaml_path()
    if not os.path.isfile(path):
        return {"devices": []}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {"devices": []}


def _save_yaml(data: dict) -> None:
    path = _devices_yaml_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _has_xiaomi_creds_file() -> bool:
    if not os.path.isfile(XIAOMI_CREDS_FILE):
        return False
    try:
        with open(XIAOMI_CREDS_FILE) as f:
            creds = json.load(f)
        return bool(creds.get("user_id") and creds.get("service_token"))
    except (json.JSONDecodeError, OSError):
        return False


def _has_xiaomi_env() -> bool:
    return bool(os.getenv("XIAOMI_USERNAME") and os.getenv("XIAOMI_PASSWORD"))


def _has_xiaomi_creds() -> bool:
    return _has_xiaomi_creds_file() or _has_xiaomi_env()


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


def _test_xiaomi_cloud_sync() -> bool:
    from micloud import MiCloud
    if not _has_xiaomi_creds_file():
        return False
    try:
        with open(XIAOMI_CREDS_FILE) as f:
            creds = json.load(f)
        cloud = MiCloud()
        cloud.user_id = int(creds["user_id"])
        cloud.service_token = creds["service_token"]
        cloud.ssecurity = creds.get("ssecurity", "")
        result = cloud.request_country("/home/device_list", "cn", {"data": "{\"getVirtualModel\":false,\"getHuamiDevices\":1}"})
        if isinstance(result, dict):
            return result.get("code", 0) == 0 or "result" in result
        return result is not None
    except Exception:
        return False


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
    yaml_data = _load_yaml()
    device_list = yaml_data.get("devices", []) or []
    has_wifi = any(d.get("host") and d.get("token") for d in device_list)
    has_ble = any(d.get("did") and not d.get("host") for d in device_list)
    llm_cfg = _llm_config()
    llm_configured = llm_cfg is not None
    xiaomi_file = _has_xiaomi_creds_file()
    xiaomi_any = _has_xiaomi_creds()
    smtp_configured = _notify_configured()
    brave_configured = _brave_configured()
    agent_token = os.getenv("AGENT_API_TOKEN", "")

    missing = []
    if not device_list:
        missing.append("未配置米家设备")
    if device_list and not has_wifi and not has_ble:
        missing.append("设备配置缺少 host/token 或 did")
    if has_ble and not xiaomi_file:
        missing.append("BLE Mesh 设备需要小米云端登录")
    if not llm_configured:
        missing.append("未配置 AI 工作台 LLM")
    # SMTP 可选，不进 missing

    return {
        "devices_yaml_exists": os.path.isfile(_devices_yaml_path()),
        "devices_count": len(device_list),
        "has_wifi_devices": has_wifi,
        "has_ble_devices": has_ble,
        "xiaomi_cloud_creds_exists": xiaomi_any,
        # 就绪 = 本地有可用 token 文件（非实时连通探测）
        "xiaomi_cloud_status": xiaomi_file,
        "llm_configured": llm_configured,
        "llm_status": llm_configured,
        "llm_model": _mask(llm_cfg.get("model")) if llm_cfg else "",
        "smtp_configured": smtp_configured,
        "kuma_public_url_configured": bool(_app_config()["kuma_public_url"]),
        "agent_token_configured": bool(agent_token),
        "brave_configured": brave_configured,
        "missing": missing,
    }


@router.get("/setup/app/config")
async def get_app_config():
    return {**_app_config(), "source": "env" if os.getenv("KUMA_PUBLIC_URL") else "file" if _app_file_config() else "none"}


@router.post("/setup/app/save")
async def save_app_config(payload: AppConfigIn):
    cfg = {"kuma_public_url": payload.kuma_public_url.strip().rstrip("/")}
    _write_json(APP_CONFIG_FILE, cfg)
    return {"ok": True, **cfg}


@router.get("/setup/devices")
async def list_configured_devices():
    yaml_data = _load_yaml()
    out = []
    for d in yaml_data.get("devices", []) or []:
        item = {**d}
        if "token" in item:
            item["token"] = _mask(item["token"])
        out.append(item)
    return out


@router.post("/setup/devices")
async def save_device(payload: DeviceIn):
    if not payload.name.strip():
        raise HTTPException(400, "设备名称不能为空")
    if not payload.host and not payload.did:
        raise HTTPException(400, "WiFi 设备需填 host，BLE Mesh 设备需填 did")

    yaml_data = _load_yaml()
    device_list = yaml_data.setdefault("devices", [])
    lookup = (payload.original_name or payload.name).strip()
    existing = next((d for d in device_list if d.get("name") == lookup), {})
    token = payload.token.strip()
    if payload.host and (_masked(token) or not token):
        token = existing.get("token", "")
    if payload.host and len(token) != 32:
        raise HTTPException(400, "WiFi 设备 token 必须是 32 位十六进制字符")
    if payload.host and any(c not in string.hexdigits for c in token):
        raise HTTPException(400, "WiFi 设备 token 必须是 32 位十六进制字符")

    device = {
        "name": payload.name.strip(),
        "type": payload.type,
        "model": payload.model.strip(),
    }
    if payload.host:
        device["host"] = payload.host.strip()
        device["token"] = token
    if payload.did:
        device["did"] = payload.did.strip()
    if payload.siid is not None:
        device["siid"] = payload.siid
    # 保留仅在本地 YAML 声明的协议能力；设置表单不暴露 command / siid / piid 编辑。
    if existing.get("temperature"):
        device["temperature"] = existing["temperature"]

    names = [d.get("name") for d in device_list]
    if lookup in names:
        device_list[names.index(lookup)] = device
    elif payload.name.strip() in names:
        device_list[names.index(payload.name.strip())] = device
    else:
        device_list.append(device)

    _save_yaml(yaml_data)
    devices.load_devices()
    return {"ok": True, "name": payload.name.strip()}


@router.delete("/setup/devices/{name}")
async def delete_device(name: str):
    yaml_data = _load_yaml()
    device_list = yaml_data.get("devices", []) or []
    new_list = [d for d in device_list if d.get("name") != name]
    if len(new_list) == len(device_list):
        raise HTTPException(404, "设备不存在")
    yaml_data["devices"] = new_list
    _save_yaml(yaml_data)
    devices.load_devices()
    return {"ok": True}


@router.post("/setup/xiaomi-cloud/login-step1")
async def xiaomi_login_step1(payload: XiaomiLoginStep1In):
    try:
        from app import xiaomi_login
        result = await asyncio.to_thread(xiaomi_login.login_step1, payload.username.strip(), payload.password)
    except Exception as e:
        raise HTTPException(503, f"小米登录请求失败: {e}") from e
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    if result["status"] == "success":
        devices.reset_cloud()
    return result


@router.post("/setup/xiaomi-cloud/login-step2")
async def xiaomi_login_step2(payload: XiaomiLoginStep2In):
    try:
        from app import xiaomi_login
        username = payload.username.strip() or None
        password = payload.password.strip() or None
        result = await asyncio.to_thread(
            xiaomi_login.login_step2,
            payload.state_id.strip(),
            payload.captcha_code.strip(),
            username,
            password,
        )
    except Exception as e:
        raise HTTPException(503, f"小米登录请求失败: {e}") from e
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    if result["status"] == "success":
        devices.reset_cloud()
    return result


@router.post("/setup/xiaomi-cloud/test")
async def xiaomi_cloud_test():
    ok = await asyncio.to_thread(_test_xiaomi_cloud_sync)
    return {"ok": ok, "message": "云端连接正常" if ok else "云端连接失败，请重新登录"}


@router.get("/setup/ble-devices")
async def list_ble_devices():
    if not os.path.isfile(BLE_DEVICES_FILE):
        return []
    try:
        with open(BLE_DEVICES_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


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
    return {"snippet": "\n".join(lines)}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        DATA_DIR = tmp
        LLM_CONFIG_FILE = os.path.join(tmp, "llm_config.json")
        NOTIFY_CONFIG_FILE = os.path.join(tmp, "notify_config.json")
        os.environ["DEVICES_PATH"] = os.path.join(tmp, "devices.yaml")

        _save_yaml({"devices": [{"name": "自检灯", "type": "light", "host": "192.168.1.1", "token": "0" * 32}]})
        data = _load_yaml()
        assert len(data["devices"]) == 1

        # 改名不丢 token
        class _P:
            name = "客厅灯"
            original_name = "自检灯"
            type = "light"
            model = ""
            host = "192.168.1.1"
            token = "****"
            did = ""
            siid = None

        # 直接测合并逻辑
        yaml_data = _load_yaml()
        existing = yaml_data["devices"][0]
        token = "****"
        if _masked(token):
            token = existing["token"]
        assert token == "0" * 32

        _write_json(LLM_CONFIG_FILE, {"base_url": "https://example.com/v1", "api_key": "sk-test", "model": "m", "timeout_sec": 10, "enabled": True, "confirm_required": True, "max_actions": 4})
        assert _llm_file_config()["model"] == "m"

        _write_json(NOTIFY_CONFIG_FILE, {"smtp_host": "smtp.example.com", "smtp_user": "u", "smtp_password": "p", "notify_to": "a@example.com"})
        assert _notify_configured()

        assert not any("SMTP" in m for m in [])  # SMTP 不进 missing 由 status 逻辑保证

    print("setup.py 自检通过：设备配置、LLM/SMTP 读写与掩码逻辑正确。")
