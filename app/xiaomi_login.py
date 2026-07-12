"""设备发现脚本：从小米云端获取所有设备列表（含 BLE Mesh 设备的 DID）。

用法：
  第一步：python app/xiaomi_login.py          → 获取验证码
  第二步：python app/xiaomi_login.py <验证码>  → 完成登录并拉取设备

凭据保存在 data/xiaomi_cloud.json，BLE 设备列表在 data/ble_devices.json。
"""
import json
import hashlib
import os
import pickle
import sys

from dotenv import load_dotenv
load_dotenv()

from micloud.miutils import get_session

DATA_DIR = "data"
SESSION_FILE = os.path.join(DATA_DIR, "xiaomi_session.pkl")
CREDS_FILE = os.path.join(DATA_DIR, "xiaomi_cloud.json")
BLE_FILE = os.path.join(DATA_DIR, "ble_devices.json")
CAPTCHA_FILE = "/tmp/captcha.png"


def step1_fetch_captcha():
    """获取验证码图片，保存 session。"""
    session = get_session()
    username = os.getenv("XIAOMI_USERNAME")
    password = os.getenv("XIAOMI_PASSWORD")

    # Step 1: get _sign
    resp1 = session.get("https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiio&_json=true")
    j1 = json.loads(resp1.text.replace("&&&START&&&", ""))
    sign = j1.get("_sign", "")

    # Step 2: try login (may need captcha)
    post_data = {
        "sid": "xiaomiio",
        "hash": hashlib.md5(password.encode()).hexdigest().upper(),
        "callback": "https://sts.api.io.mi.com/sts",
        "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
        "user": username,
        "_json": "true",
        "_sign": sign,
    }
    resp2 = session.post("https://account.xiaomi.com/pass/serviceLoginAuth2", data=post_data)
    j2 = json.loads(resp2.text.replace("&&&START&&&", ""))

    if j2.get("result") == "ok" and j2.get("location"):
        _complete_login(session, j2)
        return

    captcha_url = j2.get("captchaUrl", "")
    if captcha_url:
        resp_c = session.get("https://account.xiaomi.com" + captcha_url)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CAPTCHA_FILE, "wb") as f:
            f.write(resp_c.content)
        with open(SESSION_FILE, "wb") as f:
            pickle.dump({"session": session, "sign": sign}, f)
        print(f"验证码已保存到 {CAPTCHA_FILE}")
        print("请查看验证码后运行: python app/xiaomi_login.py <验证码>")
    else:
        print(f"登录失败: code={j2.get('code')} desc={j2.get('description')}")


def step2_submit_captcha(captcha_code: str):
    """用保存的 session 提交验证码。"""
    if not os.path.isfile(SESSION_FILE):
        print("Session 文件不存在，请先运行: python app/xiaomi_login.py")
        return

    with open(SESSION_FILE, "rb") as f:
        saved = pickle.load(f)
    session = saved["session"]
    sign = saved["sign"]
    username = os.getenv("XIAOMI_USERNAME")
    password = os.getenv("XIAOMI_PASSWORD")

    post_data = {
        "sid": "xiaomiio",
        "hash": hashlib.md5(password.encode()).hexdigest().upper(),
        "callback": "https://sts.api.io.mi.com/sts",
        "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
        "user": username,
        "_json": "true",
        "_sign": sign,
        "captCode": captcha_code,
    }
    resp = session.post("https://account.xiaomi.com/pass/serviceLoginAuth2", data=post_data)
    j = json.loads(resp.text.replace("&&&START&&&", ""))

    if j.get("result") == "ok" and j.get("location"):
        _complete_login(session, j)
    else:
        captcha_url = j.get("captchaUrl", "")
        if captcha_url:
            resp_c = session.get("https://account.xiaomi.com" + captcha_url)
            with open(CAPTCHA_FILE, "wb") as f:
                f.write(resp_c.content)
            with open(SESSION_FILE, "wb") as f:
                pickle.dump({"session": session, "sign": sign}, f)
            print(f"验证码错误！新验证码已保存到 {CAPTCHA_FILE}")
            print("请再次运行: python app/xiaomi_login.py <新验证码>")
        else:
            print(f"登录失败: code={j.get('code')} desc={j.get('desc')}")


def _complete_login(session, login_result):
    """完成登录：获取 serviceToken，拉取设备列表。"""
    username = os.getenv("XIAOMI_USERNAME")
    password = os.getenv("XIAOMI_PASSWORD")
    location = login_result.get("location", "")
    resp3 = session.get(location)
    service_token = resp3.cookies.get("serviceToken", "")
    user_id = login_result.get("userId") or login_result.get("cUserId")
    ssecurity = login_result.get("ssecurity", "")

    if not service_token:
        print("登录失败：无 serviceToken")
        return

    creds = {"user_id": user_id, "service_token": service_token, "ssecurity": ssecurity}
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f)
    print(f"登录成功！userId={user_id}")
    print(f"凭据已保存到 {CREDS_FILE}")

    # 获取设备
    from micloud import MiCloud
    mc = MiCloud(username, password)
    mc.user_id = int(user_id)
    mc.service_token = service_token
    mc.ssecurity = ssecurity
    mc.session = session

    devices = mc.get_devices(country="cn")
    if not devices:
        print("获取设备列表失败")
        return

    print(f"\n找到 {len(devices)} 个设备：")
    ble_devices = []
    for d in devices:
        name = d.get("name", "?")
        did = d.get("did", "?")
        model = d.get("model", "?")
        localip = d.get("localip", "")
        tag = "WiFi" if localip else "BLE"
        if not localip:
            ble_devices.append(d)
        print(f"  [{tag:3s}] {name:20s} did={did} model={model}")

    if ble_devices:
        with open(BLE_FILE, "w") as f:
            json.dump(ble_devices, f, ensure_ascii=False, indent=2)
        print(f"\nBLE 设备已保存到 {BLE_FILE} ({len(ble_devices)} 个)")

    # 清理 session 文件
    if os.path.isfile(SESSION_FILE):
        os.remove(SESSION_FILE)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        step2_submit_captcha(sys.argv[1].strip())
    else:
        step1_fetch_captcha()
