"""共享图片原语：sniff 真实类型、流式落盘、best-effort 删除、JSON 解码、进程级锁。
items / todos / placements 共用，避免每个领域模块各写一份重复实现。"""
import asyncio
import json
from pathlib import Path

from fastapi import HTTPException, UploadFile

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
EXT_TO_TYPE = {ext: ctype for ctype, ext in IMAGE_TYPES.items()}
MAX_IMAGES_PER_ROW = 5
MAX_IMAGE_SIZE = 10 * 1024 * 1024
# 串行化 images 列的读-改-写：单连接 aiosqlite 只串行单条语句，
# 无法覆盖「读 images → 写文件 → 整列覆写」之间的 await 间隙。
_IMAGES_LOCK = asyncio.Lock()


def images_lock() -> asyncio.Lock:
    """进程级锁，供 upload/delete 整行变更时串行化读-改-写，防止并发覆写丢图。"""
    return _IMAGES_LOCK


def decode_images(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        images = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(images, list):
        return []
    return [image for image in images if isinstance(image, dict) and image.get("id") and image.get("filename")]


def sniff_image(data: bytes) -> str | None:
    """按文件头判定真实图片类型并返回扩展名；不信任客户端声明的 content_type。"""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


async def safe_unlink(path: Path) -> None:
    """best-effort 删除：吞 OSError（Windows 文件被占用等），不掩盖业务异常、不阻断流程。"""
    try:
        await asyncio.to_thread(path.unlink, missing_ok=True)
    except OSError:
        pass


async def save_upload(upload: UploadFile, path: Path) -> str:
    """流式写盘并在写入过程中校验大小与真实图片类型，返回 sniff 出的扩展名。

    全程不把整张图缓存进内存；任意失败（含 open 处的取消、超大、非图片、IO 错）都清掉半成品文件。
    """
    file = None
    extension: str | None = None
    try:
        file = await asyncio.to_thread(path.open, "wb")
        total = 0
        while chunk := await upload.read(1024 * 1024):
            if extension is None:
                extension = sniff_image(chunk)
                if not extension:
                    raise HTTPException(400, "仅支持 JPG、PNG、GIF 或 WebP 图片")
            total += len(chunk)
            if total > MAX_IMAGE_SIZE:
                raise HTTPException(400, "单张图片不能超过 10MB")
            await asyncio.to_thread(file.write, chunk)
    except BaseException:
        # close 与 unlink 各自兜底：一个失败不能掩盖原始业务异常或跳过另一个。
        if file is not None:
            try:
                await asyncio.to_thread(file.close)
            except OSError:
                pass
        await safe_unlink(path)
        raise
    try:
        await asyncio.to_thread(file.close)
    except OSError:
        pass
    if extension is None:
        # 空上传：没有数据块进入循环
        await safe_unlink(path)
        raise HTTPException(400, "图片内容为空")
    return extension


if __name__ == "__main__":
    assert sniff_image(b"\xff\xd8\xff\xe0") == ".jpg"
    assert sniff_image(b"\x89PNG\r\n\x1a\n") == ".png"
    assert sniff_image(b"GIF89a") == ".gif"
    assert sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    assert sniff_image(b"<html><script>x</script>") is None
    assert EXT_TO_TYPE[".png"] == "image/png"
    assert decode_images('[{"id":"image-1","filename":"test.png"}]')[0]["id"] == "image-1"
    assert decode_images("invalid") == []
    assert decode_images(None) == []
    assert MAX_IMAGES_PER_ROW == 5 and MAX_IMAGE_SIZE == 10 * 1024 * 1024
    print("image_store.py 自检通过：sniff/decode/ext-map 与常量正确。")
