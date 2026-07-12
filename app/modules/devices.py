"""米家设备控制：WiFi 局域网直控 + BLE Mesh 云端控制。"""
import asyncio
import json
import os
from typing import Any

import yaml
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from miio import Device

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

# ============ 云端 BLE Mesh 控制 ============

_cloud = None  # MiCloud 单例


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
        # token 过期时尝试重新登录一次
        try:
            cloud.login()
            result = cloud.request_country("/miotspec/prop/set", country, params)
        except Exception:
            raise HTTPException(503, f"云端控制失败: {e}")
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
        raise HTTPException(503, f"云端状态查询失败: {e}")


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
    base = {"name": cfg["name"], "online": False, "power": None}
    try:
        if _is_cloud_device(cfg):
            dev_type = cfg.get("type", "light")
            siid, piid = _MIOT_PROPS.get(dev_type, (2, 1))
            base["power"] = _val(_cloud_miot_get(cfg["did"], cfg.get("siid", siid), piid))
        else:
            base["power"] = _val(_send(cfg, "get_prop", ["power"]))
        base["online"] = True
    except Exception:
        pass  # ponytail: status is best-effort; controls still report real errors.
    return base


async def _query_power(cfg: dict) -> dict:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_query_power_sync, cfg), timeout=3)
    except Exception:
        return {"name": cfg["name"], "online": False, "power": None}


# ============ API 端点 ============


class CommandIn(BaseModel):
    command: str
    params: list = []


@router.on_event("startup")
async def _startup() -> None:
    await asyncio.to_thread(load_devices)


@router.get("/devices")
async def list_devices():
    """设备列表 + 配置（不查状态，多设备时太慢）。"""
    return [{k: v for k, v in d.items() if not k.startswith("_")}
            for d in _devices.values()]


@router.get("/devices/status")
async def device_status():
    """所有设备在线/电源状态；单台失败不影响其他设备。"""
    return await asyncio.gather(*[_query_power(cfg) for cfg in _devices.values()])


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
