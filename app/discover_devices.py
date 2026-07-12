"""设备发现脚本：从小米云端获取所有设备列表（含 BLE Mesh 设备的 DID）。

用法：source venv/bin/activate && python -m app.discover_devices

输出格式：
- WiFi 设备：有 localip，可直控
- BLE Mesh 设备：无 localip，需通过云端控制，需要 did
- 输出 YAML 格式，可直接复制到 config/devices.yaml
"""
import json
import os
import sys

from dotenv import load_dotenv
from micloud import MiCloud

load_dotenv()


def main():
    username = os.getenv("XIAOMI_USERNAME")
    password = os.getenv("XIAOMI_PASSWORD")
    if not username or not password:
        print("错误：请在 .env 中设置 XIAOMI_USERNAME 和 XIAOMI_PASSWORD")
        sys.exit(1)

    print(f"正在登录小米账号: {username} ...")
    mc = MiCloud(username, password)
    try:
        mc.login()
    except Exception as e:
        print(f"登录失败: {e}")
        sys.exit(1)
    print("登录成功！")

    # 获取设备列表
    print("正在获取设备列表...")
    try:
        devices = mc.get_devices(country="cn")
    except Exception as e:
        print(f"获取设备列表失败: {e}")
        sys.exit(1)

    if not devices:
        print("未找到任何设备")
        sys.exit(0)

    print(f"\n找到 {len(devices)} 个设备：\n")

    # 分类：WiFi 设备（有 IP）和 BLE Mesh 设备（无 IP）
    wifi_devices = []
    ble_mesh_devices = []

    for d in devices:
        name = d.get("name", "未知")
        model = d.get("model", "")
        did = d.get("did", "")
        localip = d.get("localip", "")
        token = d.get("token", "")
        parent_id = d.get("parent_id", "")

        if localip:
            wifi_devices.append(d)
        else:
            ble_mesh_devices.append(d)

    # 输出 WiFi 设备
    print("=" * 60)
    print(f"WiFi 设备（有 IP，可直控）：{len(wifi_devices)} 个")
    print("=" * 60)
    for d in wifi_devices:
        print(f"  {d.get('name'):20s} | IP: {d.get('localip'):15s} | Model: {d.get('model')}")

    # 输出 BLE Mesh 设备
    print("\n" + "=" * 60)
    print(f"BLE Mesh 设备（无 IP，需云端控制）：{len(ble_mesh_devices)} 个")
    print("=" * 60)
    for d in ble_mesh_devices:
        print(f"  {d.get('name'):20s} | DID: {d.get('did'):12s} | Model: {d.get('model')}")

    # 生成 YAML 配置建议
    print("\n" + "=" * 60)
    print("配置建议（复制到 config/devices.yaml）：")
    print("=" * 60)
    print("\n# BLE Mesh 设备（需要云端控制）")
    print("# 确保 .env 中已设置 XIAOMI_USERNAME 和 XIAOMI_PASSWORD")
    print("devices:")
    for d in ble_mesh_devices:
        name = d.get("name", "未知")
        model = d.get("model", "")
        did = d.get("did", "")
        # 推断 type
        dev_type = _guess_type(model)
        print(f"  - name: {name}")
        print(f"    model: {model}")
        print(f"    did: \"{did}\"")
        print(f"    type: {dev_type}")
        print(f"    token: \"\"  # BLE Mesh 设备不需要 token")
        print()

    # 也输出完整的 JSON 供调试
    print("\n" + "=" * 60)
    print("完整设备列表（JSON）：")
    print("=" * 60)
    print(json.dumps(devices, ensure_ascii=False, indent=2))


def _guess_type(model: str) -> str:
    """根据 model 推断 type。"""
    if not model:
        return "plug"
    m = model.lower()
    if "light" in m or "switch" in m:
        return "light"
    if "plug" in m or "outlet" in m:
        return "plug"
    if "airc" in m:
        return "airconditioner"
    if "airpurifier" in m:
        return "airpurifier"
    if "camera" in m:
        return "camera"
    if "cooker" in m:
        return "cooker"
    if "kettle" in m:
        return "kettle"
    if "waterpuri" in m:
        return "waterpuri"
    if "feeder" in m:
        return "feeder"
    if "pet_waterer" in m:
        return "petwaterer"
    if "speaker" in m:
        return "speaker"
    return "plug"


if __name__ == "__main__":
    main()
