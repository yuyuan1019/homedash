"""米家设备控制：WiFi 局域网直控 + BLE Mesh 云端控制。"""
import asyncio
import json
import math
import os
from datetime import datetime
from typing import Any

import yaml
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from miio import Device
from app.database import get_db

load_dotenv()

router = APIRouter()

DEVICES_PATH = os.getenv("DEVICES_PATH", "config/devices.yaml")

# type -> (on_cmd, on_params, off_cmd, off_params)
# ponytail: 按设备类型查表；新类型加一行即可
_POWER_CMDS = {
    "light":          ("set_power", ["on"], "set_power", ["off"]),
    "plug":           ("set_on", [], "set_off", []),
    "outlet":         ("set_on", [], "set_off", []),
    "airconditioner": ("set_power", ["on"], "set_power", ["off"]),
}
_DEFAULT = ("set_power", ["on"], "set_power", ["off"])
_TEMPERATURE_COMMANDS = {"set_temperature"}
_TEMPERATURE_PROPERTIES = {"target_temperature", "temperature"}

# BLE Mesh 设备 MIOT 属性映射：type -> (siid, piid_on)
# ponytail: 按设备类型查表；新类型加一行即可
_MIOT_PROPS = {
    "light": (2, 1),            # siid=2 开关服务, piid=1 on/off
    "switch": (2, 1),
    "outlet": (2, 1),
    "airconditioner": (2, 1),
    "airpurifier": (2, 1),
}

_devices: dict[str, dict] = {}
_target_temperature_cache: dict[str, float] = {}

# ============ 云端 BLE Mesh 控制 ============

_cloud = None  # MiCloud 单例


def reset_cloud() -> None:
    """强制下次请求重新初始化 MiCloud 单例（凭据更新后调用）。"""
    global _cloud
    _cloud = None


def _get_cloud():
    """获取或初始化 MiCloud 单例（优先用 data/xiaomi_cloud.json 凭据）。"""
    global _cloud
    if _cloud is not None:
        return _cloud
    creds_file = "data/xiaomi_cloud.json"
    from micloud import MiCloud
    if os.path.isfile(creds_file):
        with open(creds_file) as f:
            creds = json.load(f)
        _cloud = MiCloud()
        _cloud.user_id = int(creds["user_id"])
        _cloud.service_token = creds["service_token"]
        _cloud.ssecurity = creds.get("ssecurity", "")
        return _cloud
    username = os.getenv("XIAOMI_USERNAME")
    password = os.getenv("XIAOMI_PASSWORD")
    if not username or not password:
        return None
    _cloud = MiCloud(username, password)
    try:
        _cloud.login()
    except Exception:
        _cloud = None
        return None
    return _cloud


def _cloud_miot_set(did: str, siid: int, piid: int, value, country: str = "cn"):
    """通过小米云端 MIOT 设置属性。"""
    cloud = _get_cloud()
    if cloud is None:
        raise HTTPException(503, "小米云端未登录，请检查 XIAOMI_USERNAME / XIAOMI_PASSWORD")
    # ponytail: params 必须是数组格式，否则 API 返回 data type not valid
    payload = {"params": [{"did": did, "siid": siid, "piid": piid, "value": value}]}
    params = {"data": json.dumps(payload)}
    try:
        result = cloud.request_country("/miotspec/prop/set", country, params)
    except Exception as e:
        reset_cloud()
        raise HTTPException(503, f"云端控制失败，请到设置页重新登录小米云端: {e}")
    if result is None:
        raise HTTPException(503, "云端返回空结果")
    return result


def _cloud_miot_get(did: str, siid: int, piid: int, country: str = "cn"):
    """通过小米云端 MIOT 查询属性。"""
    cloud = _get_cloud()
    if cloud is None:
        raise HTTPException(503, "小米云端未登录，请检查 XIAOMI_USERNAME / XIAOMI_PASSWORD")
    payload = {"params": [{"did": did, "siid": siid, "piid": piid}]}
    try:
        return cloud.request_country("/miotspec/prop/get", country, {"data": json.dumps(payload)})
    except Exception as e:
        reset_cloud()
        raise HTTPException(503, f"云端状态查询失败，请到设置页重新登录小米云端: {e}")


# ============ 设备加载 ============


def load_devices() -> None:
    """从 YAML 加载设备配置到内存。文件缺失则空列表。"""
    _devices.clear()
    if not os.path.isfile(DEVICES_PATH):
        return
    with open(DEVICES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for d in data.get("devices", []):
        _devices[d["name"]] = d


def _get(name: str) -> dict:
    if name not in _devices:
        raise HTTPException(404, f"设备不存在: {name}")
    return _devices[name]


def _instance(cfg: dict) -> Device:
    # ponytail: 复用单例避免重复握手；token/host 不变所以安全
    inst = cfg.get("_inst")
    if inst is None:
        inst = Device(ip=cfg["host"], token=cfg["token"], model=cfg.get("model"))
        cfg["_inst"] = inst
    return inst


def _send(cfg: dict, command: str, params: list | None = None) -> Any:
    inst = _instance(cfg)
    try:
        return inst.send(command, params or [])
    except Exception as e:
        raise HTTPException(503, f"设备不可达: {e}")


def _is_cloud_device(cfg: dict) -> bool:
    """有 did 但无 host 的设备走云端控制。"""
    return bool(cfg.get("did")) and not cfg.get("host")


def _send_power(cfg: dict, on: bool) -> None:
    """统一开关逻辑：WiFi 设备走局域网，BLE Mesh 走云端。"""
    if _is_cloud_device(cfg):
        dev_type = cfg.get("type", "light")
        siid, piid = _MIOT_PROPS.get(dev_type, (2, 1))
        # 用户可在 config 里覆盖 siid（双键开关：左键=2，右键=3）
        siid = cfg.get("siid", siid)
        _cloud_miot_set(cfg["did"], siid, piid, on)
    else:
        cmds = _POWER_CMDS.get(cfg.get("type"), _DEFAULT)
        if on:
            _send(cfg, cmds[0], cmds[1])
        else:
            _send(cfg, cmds[2], cmds[3])


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _temperature_config(cfg: dict, strict: bool = False) -> dict | None:
    """解析显式温控能力；无效配置默认不暴露，设置时返回中文错误。"""
    raw = cfg.get("temperature")
    if cfg.get("type") != "airconditioner" or not isinstance(raw, dict):
        if strict:
            raise HTTPException(400, "该设备未配置温控能力")
        return None
    try:
        minimum = float(raw["min"])
        maximum = float(raw["max"])
        step = float(raw["step"])
    except (KeyError, TypeError, ValueError):
        if strict:
            raise HTTPException(400, "空调温控配置缺少有效的 min、max 或 step")
        return None
    valid_numbers = all(math.isfinite(value) for value in (minimum, maximum, step))
    if not valid_numbers or minimum >= maximum or step <= 0:
        if strict:
            raise HTTPException(400, "空调温控范围配置无效")
        return None

    config = {"min": minimum, "max": maximum, "step": step}
    if _is_cloud_device(cfg):
        siid = raw.get("siid")
        piid = raw.get("piid")
        if not isinstance(siid, int) or not isinstance(piid, int) or siid <= 0 or piid <= 0:
            if strict:
                raise HTTPException(400, "云端空调温控需要有效的 siid 和 piid")
            return None
        config.update({"siid": siid, "piid": piid})
    else:
        if not cfg.get("host"):
            if strict:
                raise HTTPException(400, "WiFi 空调温控需要配置 host")
            return None
        command = raw.get("command")
        if command not in _TEMPERATURE_COMMANDS:
            if strict:
                raise HTTPException(400, "WiFi 空调温控命令不在白名单")
            return None
        prop = raw.get("property")
        if prop is not None and prop not in _TEMPERATURE_PROPERTIES:
            if strict:
                raise HTTPException(400, "WiFi 空调温度查询属性不在白名单")
            return None
        config.update({"command": command, "property": prop})
    return config


def _temperature_capability(cfg: dict) -> dict | None:
    config = _temperature_config(cfg)
    if not config:
        return None
    return {key: _number(config[key]) for key in ("min", "max", "step")}


def _validate_temperature(config: dict, value: float) -> int | float:
    if not math.isfinite(value):
        raise HTTPException(400, "目标温度必须是有限数字")
    if value < config["min"] or value > config["max"]:
        raise HTTPException(400, f"目标温度必须在 {_number(config['min'])} 到 {_number(config['max'])}℃ 之间")
    steps = (value - config["min"]) / config["step"]
    if not math.isclose(steps, round(steps), abs_tol=1e-7):
        raise HTTPException(400, f"目标温度必须按 {_number(config['step'])}℃ 步长调节")
    return _number(value)


def _send_temperature(cfg: dict, config: dict, value: int | float) -> None:
    if _is_cloud_device(cfg):
        _cloud_miot_set(cfg["did"], config["siid"], config["piid"], value)
    else:
        _send(cfg, config["command"], [value])
    _target_temperature_cache[cfg["name"]] = value


def _query_target_temperature(cfg: dict, config: dict) -> int | float | None:
    try:
        if _is_cloud_device(cfg):
            value = _val(_cloud_miot_get(cfg["did"], config["siid"], config["piid"]))
        elif config.get("property"):
            value = _val(_send(cfg, "get_prop", [config["property"]]))
        else:
            value = _target_temperature_cache.get(cfg["name"])
        numeric = float(value) if value is not None else None
        return _number(numeric) if numeric is not None and math.isfinite(numeric) else None
    except Exception:
        return _target_temperature_cache.get(cfg["name"])


def _val(result):
    """提取 miio/miot 返回里的第一个值。"""
    if isinstance(result, list):
        return result[0] if result else None
    if isinstance(result, dict):
        data = result.get("result") or result.get("params") or []
        if isinstance(data, list) and data:
            return data[0].get("value") if isinstance(data[0], dict) else data[0]
    return result


def _query_power_sync(cfg: dict) -> dict:
    """查询单台设备 power；失败只影响本设备。"""
    base = {"name": cfg["name"], "online": False, "power": None, "updated_at": None, "error": None}
    try:
        if _is_cloud_device(cfg):
            dev_type = cfg.get("type", "light")
            siid, piid = _MIOT_PROPS.get(dev_type, (2, 1))
            base["power"] = _val(_cloud_miot_get(cfg["did"], cfg.get("siid", siid), piid))
        else:
            base["power"] = _val(_send(cfg, "get_prop", ["power"]))
        base["online"] = True
        base["updated_at"] = datetime.now().isoformat(timespec="seconds")
    except HTTPException:
        base["error"] = "状态获取失败"
    except Exception:
        base["error"] = "状态获取失败"
    temperature = _temperature_config(cfg)
    if temperature:
        base["target_temperature"] = _query_target_temperature(cfg, temperature)
    return base


async def _query_power(cfg: dict) -> dict:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_query_power_sync, cfg), timeout=3)
    except Exception:
        return {"name": cfg["name"], "online": False, "power": None, "updated_at": None, "error": "状态获取超时"}


# ============ API 端点 ============


class CommandIn(BaseModel):
    command: str
    params: list = []


class VisibilityIn(BaseModel):
    hidden: bool


class DeviceOrderIn(BaseModel):
    device_names: list[str]


class TemperatureIn(BaseModel):
    temperature: float


async def _preferences(db) -> dict[str, dict]:
    cur = await db.execute("SELECT device_name, hidden, sort_order FROM device_preferences")
    return {row["device_name"]: dict(row) for row in await cur.fetchall()}


async def _devices_with_visibility(db, include_hidden: bool) -> list[dict]:
    return _serialize_devices(await _preferences(db), include_hidden)


def _ordered_configs(preferences: dict[str, dict]) -> list[dict]:
    yaml_order = {name: index for index, name in enumerate(_devices)}
    return sorted(
        _devices.values(),
        key=lambda cfg: (
            preferences.get(cfg["name"], {}).get("sort_order") is None,
            preferences.get(cfg["name"], {}).get("sort_order") or 0,
            yaml_order[cfg["name"]],
        ),
    )


def _serialize_devices(preferences: dict[str, dict], include_hidden: bool) -> list[dict]:
    out = []
    for cfg in _ordered_configs(preferences):
        preference = preferences.get(cfg["name"], {})
        hidden = bool(preference.get("hidden"))
        if not include_hidden and hidden:
            continue
        temperature = _temperature_capability(cfg)
        item = {
            "name": cfg["name"],
            "type": cfg.get("type", "other"),
            "connection": "cloud" if _is_cloud_device(cfg) else "wifi" if cfg.get("host") else "unknown",
            "hidden": hidden,
            "capabilities": {"temperature": temperature} if temperature else {},
        }
        out.append(item)
    return out


@router.on_event("startup")
async def _startup() -> None:
    await asyncio.to_thread(load_devices)


@router.get("/devices")
async def list_devices(include_hidden: bool = False, db=Depends(get_db)):
    """设备列表 + 配置（不查状态，多设备时太慢）。"""
    return await _devices_with_visibility(db, include_hidden)


@router.get("/devices/status")
async def device_status(include_hidden: bool = False, db=Depends(get_db)):
    """所有设备在线/电源状态；单台失败不影响其他设备。"""
    preferences = await _preferences(db)
    configs = [
        cfg for cfg in _ordered_configs(preferences)
        if include_hidden or not bool(preferences.get(cfg["name"], {}).get("hidden"))
    ]
    return await asyncio.gather(*[_query_power(cfg) for cfg in configs])


@router.put("/devices/order")
async def set_device_order(payload: DeviceOrderIn, db=Depends(get_db)):
    expected = list(_devices)
    names = payload.device_names
    if len(names) != len(set(names)):
        raise HTTPException(400, "设备顺序中存在重复名称")
    if set(names) != set(expected) or len(names) != len(expected):
        raise HTTPException(400, "设备顺序必须完整包含当前全部设备")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        await db.execute("BEGIN")
        for index, name in enumerate(names):
            await db.execute(
                "INSERT INTO device_preferences(device_name,sort_order,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(device_name) DO UPDATE SET sort_order=excluded.sort_order, updated_at=excluded.updated_at",
                (name, index, now),
            )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"device_names": names}


@router.put("/devices/{name}/visibility")
async def set_visibility(name: str, payload: VisibilityIn, db=Depends(get_db)):
    _get(name)
    await db.execute(
        "INSERT INTO device_preferences(device_name,hidden,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(device_name) DO UPDATE SET hidden=excluded.hidden, updated_at=excluded.updated_at",
        (name, int(payload.hidden), datetime.now().isoformat(timespec="seconds")),
    )
    await db.commit()
    return {"name": name, "hidden": payload.hidden}


@router.put("/devices/{name}/temperature")
async def set_temperature(name: str, payload: TemperatureIn):
    cfg = _get(name)
    config = _temperature_config(cfg, strict=True)
    value = _validate_temperature(config, payload.temperature)
    try:
        await asyncio.to_thread(_send_temperature, cfg, config, value)
    except HTTPException as exc:
        if exc.status_code == 400:
            raise
        raise HTTPException(503, "温度设置失败，请检查设备连接或温控配置") from None
    except Exception:
        raise HTTPException(503, "温度设置失败，请检查设备连接或温控配置") from None
    return {"name": name, "target_temperature": value}


@router.post("/devices/{name}/on")
async def turn_on(name: str):
    cfg = _get(name)
    await asyncio.to_thread(_send_power, cfg, True)
    return {"name": name, "power": "on"}


@router.post("/devices/{name}/off")
async def turn_off(name: str):
    cfg = _get(name)
    await asyncio.to_thread(_send_power, cfg, False)
    return {"name": name, "power": "off"}


@router.post("/devices/{name}/command")
async def send_command(name: str, payload: CommandIn):
    cfg = _get(name)
    if _is_cloud_device(cfg):
        raise HTTPException(400, "BLE Mesh 设备不支持原始命令")
    result = await asyncio.to_thread(_send, cfg, payload.command, payload.params)
    return {"name": name, "result": result}


if __name__ == "__main__":
    # 自检：命令映射表完整性
    for dtype, (on_c, on_p, off_c, off_p) in _POWER_CMDS.items():
        assert on_c and off_c, f"{dtype} 命令缺失"
    assert _DEFAULT[0] == "set_power"
    assert _val(["on"]) == "on"
    assert _val({"result": [{"value": True}]}) is True
    original_devices = dict(_devices)
    _devices.clear()
    _devices.update({
        "客厅灯": {"name": "客厅灯", "type": "light", "host": "192.0.2.1", "token": "0" * 32},
        "空调": {"name": "空调", "type": "airconditioner", "host": "192.0.2.2", "token": "1" * 32,
                 "temperature": {"min": 16, "max": 30, "step": 1, "command": "set_temperature"}},
        "隐藏": {"name": "隐藏", "type": "plug", "host": "192.0.2.3", "token": "2" * 32},
    })
    prefs = {"空调": {"sort_order": 0, "hidden": 0}, "客厅灯": {"sort_order": 1, "hidden": 0}, "隐藏": {"sort_order": 2, "hidden": 1}}
    assert [item["name"] for item in _serialize_devices(prefs, False)] == ["空调", "客厅灯"]
    all_devices = _serialize_devices(prefs, True)
    assert all_devices[2]["hidden"] is True
    assert all_devices[0]["capabilities"]["temperature"] == {"min": 16, "max": 30, "step": 1}
    assert "host" not in all_devices[0] and "token" not in all_devices[0]
    assert _validate_temperature(_temperature_config(_devices["空调"], strict=True), 26) == 26
    try:
        _validate_temperature(_temperature_config(_devices["空调"], strict=True), 30.5)
        raise AssertionError("越界温度应拒绝")
    except HTTPException as exc:
        assert exc.status_code == 400
    sent = []
    original_send = _send
    original_cloud_set = _cloud_miot_set
    _send = lambda cfg, command, params=None: sent.append(("wifi", command, params))
    _cloud_miot_set = lambda did, siid, piid, value, country="cn": sent.append(("cloud", siid, piid, value))
    _send_temperature(_devices["空调"], _temperature_config(_devices["空调"], strict=True), 25)
    cloud_air = {"name": "云空调", "type": "airconditioner", "did": "example",
                 "temperature": {"min": 16, "max": 30, "step": 1, "siid": 2, "piid": 3}}
    _send_temperature(cloud_air, _temperature_config(cloud_air, strict=True), 24)
    assert sent == [("wifi", "set_temperature", [25]), ("cloud", 2, 3, 24)]
    _send = original_send
    _cloud_miot_set = original_cloud_set
    _target_temperature_cache.clear()
    _devices.clear()
    _devices.update(original_devices)
    load_devices()  # 无文件不报错，有文件正常加载
    # ponytail: 有配置文件时验证加载正确，无配置文件时验证空列表
    if os.path.isfile(DEVICES_PATH):
        assert len(_devices) > 0, "有配置文件应加载到设备"
        # 验证 BLE Mesh 设备有 did 字段
        for name, cfg in _devices.items():
            if not cfg.get("host") and cfg.get("did"):
                assert cfg["did"], f"{name} BLE Mesh 设备需有 did"
        print(f"devices.py 自检通过：加载了 {len(_devices)} 个设备（含 BLE Mesh）。")
    else:
        assert _devices == {}, "无配置文件应返回空"
        print("devices.py 自检通过：命令映射正确，无配置文件。")
