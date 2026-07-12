"""米家设备控制：python-miio 局域网直控，原始命令透传。"""
import asyncio
import os
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from miio import Device

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

_devices: dict[str, dict] = {}


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


@router.post("/devices/{name}/on")
async def turn_on(name: str):
    cfg = _get(name)
    on_cmd, on_params, _, _ = _POWER_CMDS.get(cfg.get("type"), _DEFAULT)
    await asyncio.to_thread(_send, cfg, on_cmd, on_params)
    return {"name": name, "power": "on"}


@router.post("/devices/{name}/off")
async def turn_off(name: str):
    cfg = _get(name)
    _, _, off_cmd, off_params = _POWER_CMDS.get(cfg.get("type"), _DEFAULT)
    await asyncio.to_thread(_send, cfg, off_cmd, off_params)
    return {"name": name, "power": "off"}


@router.post("/devices/{name}/command")
async def send_command(name: str, payload: CommandIn):
    result = await asyncio.to_thread(_send, _get(name), payload.command, payload.params)
    return {"name": name, "result": result}


if __name__ == "__main__":
    # 自检：命令映射表完整性
    for dtype, (on_c, on_p, off_c, off_p) in _POWER_CMDS.items():
        assert on_c and off_c, f"{dtype} 命令缺失"
    assert _DEFAULT[0] == "set_power"
    load_devices()  # 无文件不报错
    assert _devices == {}, "无配置文件应返回空"
    print("devices.py 自检通过：命令映射正确。")
