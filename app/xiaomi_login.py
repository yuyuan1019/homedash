"""小米云端登录：CLI + API 共用。

CLI 用法：
  第一步：python app/xiaomi_login.py                    → 获取验证码
  第二步：python app/xiaomi_login.py <验证码>           → 完成登录并拉取设备

API 用法（setup.py 调用）：
  result = login_step1(username, password)
  # 若 result['status'] == 'captcha_required':
  result = login_step2(result['state_id'], captcha_code)

凭据保存在 data/xiaomi_cloud.json，BLE 设备列表在 data/ble_devices.json。
"""
import base64
import hashlib
import json
import os
import pickle
import sys
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from micloud.miutils import get_session

DATA_DIR = "data"
SESSION_FILE = os.path.join(DATA_DIR, "xiaomi_session.pkl")
CREDS_FILE = os.path.join(DATA_DIR, "xiaomi_cloud.json")
BLE_FILE = os.path.join(DATA_DIR, "ble_devices.json")
CAPTCHA_FILE = "/tmp/captcha.png"
STATE_TTL_MINUTES = 10


def _state_file(state_id: str) -> str:
    return os.path.join(DATA_DIR, f"xiaomi_login_state_{state_id}.pkl")


def _cleanup_old_states():
    """清理超过 TTL 的登录状态文件。"""
    if not os.path.isdir(DATA_DIR):
        return
    deadline = datetime.now() - timedelta(minutes=STATE_TTL_MINUTES)
    for name in os.listdir(DATA_DIR):
        if not name.startswith("xiaomi_login_state_") or not name.endswith(".pkl"):
            continue
        path = os.path.join(DATA_DIR, name)
        try:
            if datetime.fromtimestamp(os.path.getmtime(path)) < deadline:
                os.remove(path)
        except OSError:
            pass


def _save_state(sign: str, session) -> str:
    """保存 session 状态并返回 state_id。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    _cleanup_old_states()
    state_id = uuid.uuid4().hex[:16]
    with open(_state_file(state_id), "wb") as f:
        pickle.dump({"session": session, "sign": sign, "created_at": datetime.now().isoformat()}, f)
    return state_id


def _load_state(state_id: str):
    """加载并删除 session 状态。"""
    path = _state_file(state_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _fetch_captcha_image(session, captcha_url: str) -> bytes:
    if captcha_url.startswith("http://") or captcha_url.startswith("https://"):
        url = captcha_url
    else:
        url = "https://account.xiaomi.com" + captcha_url
    return session.get(url).content


def _build_post_data(username: str, password: str, sign: str, captcha_code: str | None = None) -> dict:
    data = {
        "sid": "xiaomiio",
        "hash": hashlib.md5(password.encode()).hexdigest().upper(),
        "callback": "https://sts.api.io.mi.com/sts",
        "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
        "user": username,
        "_json": "true",
        "_sign": sign,
    }
    if captcha_code is not None:
        data["captCode"] = captcha_code
    return data


def _parse_login_response(text: str) -> dict:
    return json.loads(text.replace("&&&START&&&", ""))


def _complete_login(session, login_result: dict, username: str | None = None, password: str | None = None, save_devices: bool = False) -> dict:
    """完成登录并保存凭据。返回 {'status':'success', 'user_id':...}。"""
    location = login_result.get("location", "")
    resp3 = session.get(location)
    service_token = resp3.cookies.get("serviceToken", "")
    user_id = login_result.get("userId") or login_result.get("cUserId")
    ssecurity = login_result.get("ssecurity", "")

    if not service_token:
        return {"status": "error", "message": "登录失败：无 serviceToken"}

    creds = {"user_id": user_id, "service_token": service_token, "ssecurity": ssecurity}
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f)

    if save_devices and username and password:
        _save_device_list(session, username, password, user_id, service_token, ssecurity)

    return {"status": "success", "user_id": user_id, "message": "登录成功"}


def _save_device_list(session, username: str, password: str, user_id, service_token: str, ssecurity: str):
    from micloud import MiCloud
    mc = MiCloud(username, password)
    mc.user_id = int(user_id)
    mc.service_token = service_token
    mc.ssecurity = ssecurity
    mc.session = session

    devices = mc.get_devices(country="cn")
    if not devices:
        return

    ble_devices = [d for d in devices if not d.get("localip")]
    with open(BLE_FILE, "w") as f:
        json.dump(ble_devices, f, ensure_ascii=False, indent=2)


def login_step1(username: str, password: str) -> dict:
    """API 第一步：尝试登录，需要验证码时返回图片。"""
    if not username or not password:
        return {"status": "error", "message": "用户名和密码不能为空"}

    session = get_session()
    resp1 = session.get("https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiio&_json=true")
    j1 = _parse_login_response(resp1.text)
    sign = j1.get("_sign", "")

    resp2 = session.post(
        "https://account.xiaomi.com/pass/serviceLoginAuth2",
        data=_build_post_data(username, password, sign),
    )
    j2 = _parse_login_response(resp2.text)

    if j2.get("result") == "ok" and j2.get("location"):
        return _complete_login(session, j2, username, password, save_devices=True)

    captcha_url = j2.get("captchaUrl", "")
    if captcha_url:
        image_bytes = _fetch_captcha_image(session, captcha_url)
        state_id = _save_state(sign, session)
        return {
            "status": "captcha_required",
            "state_id": state_id,
            "captcha_base64": "data:image/png;base64," + base64.b64encode(image_bytes).decode(),
            "message": "需要验证码",
        }

    return {"status": "error", "message": f"登录失败: code={j2.get('code')} desc={j2.get('description')}"}


def login_step2(state_id: str, captcha_code: str, username: str | None = None, password: str | None = None) -> dict:
    """API 第二步：提交验证码。"""
    state = _load_state(state_id)
    if state is None:
        return {"status": "error", "message": "验证码会话已过期，请重新获取验证码"}

    session = state["session"]
    sign = state["sign"]

    # API 调用时传入；CLI 模式从环境变量读
    if username is None:
        username = os.getenv("XIAOMI_USERNAME", "")
    if password is None:
        password = os.getenv("XIAOMI_PASSWORD", "")
    if not username or not password:
        return {"status": "error", "message": "用户名和密码不能为空"}

    resp = session.post(
        "https://account.xiaomi.com/pass/serviceLoginAuth2",
        data=_build_post_data(username, password, sign, captcha_code),
    )
    j = _parse_login_response(resp.text)

    if j.get("result") == "ok" and j.get("location"):
        return _complete_login(session, j, username, password, save_devices=True)

    captcha_url = j.get("captchaUrl", "")
    if captcha_url:
        image_bytes = _fetch_captcha_image(session, captcha_url)
        new_state_id = _save_state(sign, session)
        return {
            "status": "captcha_required",
            "state_id": new_state_id,
            "captcha_base64": "data:image/png;base64," + base64.b64encode(image_bytes).decode(),
            "message": "验证码错误，请重新输入",
        }

    return {"status": "error", "message": f"登录失败: code={j.get('code')} desc={j.get('desc')}"}


def _cli_step1():
    """CLI 第一步：打印验证码路径和后续命令。"""
    username = os.getenv("XIAOMI_USERNAME")
    password = os.getenv("XIAOMI_PASSWORD")
    result = login_step1(username, password)
    if result["status"] == "success":
        print(f"登录成功！userId={result.get('user_id')}")
        print(f"凭据已保存到 {CREDS_FILE}")
    elif result["status"] == "captcha_required":
        # CLI 仍然用原来的 session 文件路径，兼容旧用法
        state = _load_state(result["state_id"])
        if state:
            with open(SESSION_FILE, "wb") as f:
                pickle.dump({"session": state["session"], "sign": state["sign"]}, f)
        image_bytes = base64.b64decode(result["captcha_base64"].split(",")[1])
        with open(CAPTCHA_FILE, "wb") as f:
            f.write(image_bytes)
        print(f"验证码已保存到 {CAPTCHA_FILE}")
        print("请查看验证码后运行: python app/xiaomi_login.py <验证码>")
    else:
        print(result["message"])


def _cli_step2(captcha_code: str):
    """CLI 第二步：兼容旧的 session 文件。"""
    if os.path.isfile(SESSION_FILE):
        with open(SESSION_FILE, "rb") as f:
            saved = pickle.load(f)
        state_id = _save_state(saved["sign"], saved["session"])
        os.remove(SESSION_FILE)
        result = login_step2(state_id, captcha_code)
    else:
        # 如果 SESSION_FILE 不存在，尝试无状态用环境变量再走一遍
        result = login_step2("", captcha_code)

    if result["status"] == "success":
        print(f"登录成功！userId={result.get('user_id')}")
        print(f"凭据已保存到 {CREDS_FILE}")
    elif result["status"] == "captcha_required":
        image_bytes = base64.b64decode(result["captcha_base64"].split(",")[1])
        with open(CAPTCHA_FILE, "wb") as f:
            f.write(image_bytes)
        print(f"验证码错误！新验证码已保存到 {CAPTCHA_FILE}")
        print("请再次运行: python app/xiaomi_login.py <新验证码>")
    else:
        print(result["message"])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _cli_step2(sys.argv[1].strip())
    else:
        _cli_step1()
