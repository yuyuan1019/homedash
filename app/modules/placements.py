"""收纳知识库：记录「把 X 放到了 Y」并由 LLM 关联库存物品，供 AI 工作台检索。"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.database import get_db
from app.modules import image_store
from app.modules.ai_workbench import (
    _chat_completion, _enabled, _llm_config, _llm_error_message,
    _loads_json_object, _response_json, _safe_audit,
)

router = APIRouter()
_PLACEMENT_IMAGES_DIR = Path("data/placement_images")
_MAX_CANDIDATES = 8


class PlacementIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    location: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("description")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("描述不能为空")
        return value


class PlacementPatch(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class PlacementConfirmIn(BaseModel):
    item_ids: list[int] = Field(default_factory=list)
    location: str | None = Field(default=None, max_length=100)


class PlacementCandidate(BaseModel):
    item_id: int | None = None
    item_name: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


def _decode_int_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [int(x) for x in value if isinstance(x, int)]


def _placement_dict(row) -> dict:
    data = dict(row)
    data["images"] = image_store.decode_images(data.get("images"))
    data["item_ids"] = _decode_int_list(data.get("item_ids"))
    try:
        data["candidate_items"] = json.loads(data.get("candidate_items") or "[]")
    except json.JSONDecodeError:
        data["candidate_items"] = []
    return data


async def _get_placement(db, pid: int):
    cur = await db.execute("SELECT * FROM placements WHERE id=?", (pid,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "收纳记录不存在")
    return row


@router.get("/placements")
async def list_placements(confirmed: str = "all", db=Depends(get_db)):
    if confirmed not in {"all", "pending", "confirmed"}:
        raise HTTPException(400, "confirmed 只能是 all、pending 或 confirmed")
    where = "" if confirmed == "all" else f"WHERE confirmed={1 if confirmed == 'confirmed' else 0}"
    cur = await db.execute(f"SELECT * FROM placements {where} ORDER BY id DESC LIMIT 200")
    return [_placement_dict(row) for row in await cur.fetchall()]


@router.post("/placements")
async def create_placement(payload: PlacementIn, db=Depends(get_db)):
    cur = await db.execute(
        "INSERT INTO placements(description,location,note) VALUES(?,?,?)",
        (payload.description, (payload.location or "").strip() or None, (payload.note or "").strip() or None),
    )
    await db.commit()
    return _placement_dict(await _get_placement(db, cur.lastrowid))


@router.get("/placements/{pid}")
async def get_placement(pid: int, db=Depends(get_db)):
    return _placement_dict(await _get_placement(db, pid))


@router.patch("/placements/{pid}")
async def patch_placement(pid: int, payload: PlacementPatch, db=Depends(get_db)):
    await _get_placement(db, pid)
    fields = {k: (v.strip() if isinstance(v, str) else v) for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "无更新字段")
    sets = ", ".join(f"{k}=?" for k in fields)
    await db.execute(
        f"UPDATE placements SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
        (*fields.values(), pid),
    )
    await db.commit()
    return _placement_dict(await _get_placement(db, pid))


@router.put("/placements/{pid}/confirm")
async def confirm_placement(pid: int, payload: PlacementConfirmIn, db=Depends(get_db)):
    await _get_placement(db, pid)
    # 校验所有 item_id 都存在，避免脏关联
    for iid in payload.item_ids:
        cur = await db.execute("SELECT 1 FROM items WHERE id=?", (iid,))
        if not await cur.fetchone():
            raise HTTPException(400, f"物品 id {iid} 不存在")
    now = datetime.now().isoformat(timespec="seconds")
    # 占位符顺序须与 SQL 完全一致：item_ids、[location]、confirmed_at、updated_at、id
    if payload.location is not None:
        sql = ("UPDATE placements SET item_ids=?, confirmed=1, location=?, "
               "confirmed_at=?, updated_at=? WHERE id=?")
        params = [json.dumps(payload.item_ids, ensure_ascii=False), payload.location.strip() or None, now, now, pid]
    else:
        sql = "UPDATE placements SET item_ids=?, confirmed=1, confirmed_at=?, updated_at=? WHERE id=?"
        params = [json.dumps(payload.item_ids, ensure_ascii=False), now, now, pid]
    await db.execute(sql, params)
    await db.commit()
    return _placement_dict(await _get_placement(db, pid))


@router.delete("/placements/{pid}")
async def delete_placement(pid: int, db=Depends(get_db)):
    async with image_store.images_lock():
        placement = _placement_dict(await _get_placement(db, pid))
        await db.execute("DELETE FROM placements WHERE id=?", (pid,))
        await db.commit()
    # DB 已提交，文件删除 best-effort（同 todos/items）
    for image in placement["images"]:
        await image_store.safe_unlink(_PLACEMENT_IMAGES_DIR / image["filename"])
    return {"deleted": pid}


# ---- 图片端点（镜像 items/todos，仅目录不同） ----

@router.post("/placements/{pid}/images")
async def upload_placement_image(pid: int, image: UploadFile = File(...), db=Depends(get_db)):
    await _get_placement(db, pid)
    content_type = (image.content_type or "").lower()
    if content_type not in image_store.IMAGE_TYPES:
        raise HTTPException(400, "仅支持 JPG、PNG、GIF 或 WebP 图片")
    await asyncio.to_thread(_PLACEMENT_IMAGES_DIR.mkdir, parents=True, exist_ok=True)
    image_id = uuid4().hex
    tmp_path = _PLACEMENT_IMAGES_DIR / f"{pid}_{image_id}.upload"
    extension = await image_store.save_upload(image, tmp_path)
    final_filename = f"{pid}_{image_id}{extension}"
    final_path = _PLACEMENT_IMAGES_DIR / final_filename
    committed = False
    try:
        if tmp_path != final_path:
            try:
                await asyncio.to_thread(tmp_path.rename, final_path)
            except OSError:
                await image_store.safe_unlink(tmp_path)
                raise HTTPException(400, "图片保存失败，请重试")
        async with image_store.images_lock():
            placement = _placement_dict(await _get_placement(db, pid))
            if len(placement["images"]) >= image_store.MAX_IMAGES_PER_ROW:
                raise HTTPException(400, f"每条收纳最多上传 {image_store.MAX_IMAGES_PER_ROW} 张图片")
            images = [*placement["images"], {"id": image_id, "filename": final_filename,
                                             "content_type": image_store.EXT_TO_TYPE[extension]}]
            await db.execute("UPDATE placements SET images=?, updated_at=datetime('now','localtime') WHERE id=?",
                             (json.dumps(images, ensure_ascii=False), pid))
            await db.commit()
            committed = True
    except BaseException:
        if not committed:
            await image_store.safe_unlink(final_path)
        raise
    return _placement_dict(await _get_placement(db, pid))


@router.get("/placements/{pid}/images/{image_id}")
async def get_placement_image(pid: int, image_id: str, db=Depends(get_db)):
    cur = await db.execute("SELECT images FROM placements WHERE id=?", (pid,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "收纳记录不存在")
    image = next((i for i in image_store.decode_images(row["images"]) if i["id"] == image_id), None)
    if not image:
        raise HTTPException(404, "图片不存在")
    path = _PLACEMENT_IMAGES_DIR / image["filename"]
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError:
        raise HTTPException(404, "图片文件不存在")
    except OSError:
        raise HTTPException(500, "读取图片失败")
    return Response(content=data, media_type=image.get("content_type") or "application/octet-stream",
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"})


@router.delete("/placements/{pid}/images/{image_id}")
async def delete_placement_image(pid: int, image_id: str, db=Depends(get_db)):
    async with image_store.images_lock():
        placement = _placement_dict(await _get_placement(db, pid))
        target = next((i for i in placement["images"] if i["id"] == image_id), None)
        if not target:
            raise HTTPException(404, "图片不存在")
        remaining = [i for i in placement["images"] if i["id"] != image_id]
        await db.execute("UPDATE placements SET images=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (json.dumps(remaining, ensure_ascii=False), pid))
        await db.commit()
        filename = target["filename"]
        updated = _placement_dict(await _get_placement(db, pid))
    await image_store.safe_unlink(_PLACEMENT_IMAGES_DIR / filename)
    return updated


# ---- LLM 关联候选 ----

@router.post("/placements/{pid}/suggest")
async def suggest_placement_items(pid: int, db=Depends(get_db)):
    if not _enabled():
        raise HTTPException(503, "AI 功能未开启")
    placement = _placement_dict(await _get_placement(db, pid))
    base_url, api_key, model, timeout_sec = _llm_config()
    cur = await db.execute("SELECT id,name,category,location,current_stock FROM items ORDER BY id LIMIT 200")
    inventory = [dict(r) for r in await cur.fetchall()]
    prompt = (
        "你是家庭物品收纳助手。用户刚描述了一条收纳记录，请根据描述推断可能涉及的库存物品候选。"
        "只输出一个 JSON 对象，不要 Markdown："
        '{"candidates":[{"item_id":数字或null,"item_name":"名称或null","confidence":0到1的小数,"reason":"简短中文理由"}]}。'
        "item_id 必须来自上下文中的库存物品列表；若都不匹配，返回空数组或 item_id 为 null 的候选。"
        f"最多 {_MAX_CANDIDATES} 个候选，按 confidence 从高到低。不要编造库存中不存在的 item_id。"
    )
    user = json.dumps({
        "描述": placement["description"],
        "位置": placement.get("location") or "(未填)",
        "备注": placement.get("note") or "(无)",
        "库存物品": inventory,
    }, ensure_ascii=False)
    started = datetime.now()
    try:
        # 推理模型生成候选约需数十秒：超时放宽到至少 90s；json_mode=False 同 travel，避免
        # 长输出 + response_format 触发上游 500（prompt 已要求只输出 JSON，_loads_json_object 容错解析）
        async with httpx.AsyncClient(timeout=max(timeout_sec, 90)) as client:
            response = await _chat_completion(client, base_url, api_key, {
                "model": model,
                "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                "temperature": 0.2,
            }, json_mode=False)
        if response.status_code >= 400:
            raise HTTPException(502, _llm_error_message(response.status_code))
        data = _loads_json_object(_response_json(response)["choices"][0]["message"]["content"])
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        await _safe_audit(db, raw_text=placement["description"], ok=False, stage="placement_suggest",
                          llm_model=model, error=str(exc) or exc.__class__.__name__)
        raise HTTPException(502, "模型未返回有效的候选清单，请稍后重试") from exc
    except ValueError as exc:
        # 透传 _response_json / _loads_json_object 的中文提示（如 Base URL 像网页地址）
        await _safe_audit(db, raw_text=placement["description"], ok=False, stage="placement_suggest",
                          llm_model=model, error=str(exc))
        raise HTTPException(502, str(exc) or "模型未返回有效的候选清单") from exc
    # 校验：item_id 必须在 inventory 中存在；非法候选降级（保留文本但不绑不存在的 id）
    valid_ids = {row["id"] for row in inventory}
    candidates: list[dict] = []
    for raw in (data.get("candidates") or []):
        if len(candidates) >= _MAX_CANDIDATES:
            break
        try:
            candidate = PlacementCandidate.model_validate(raw).model_dump()
        except (ValueError, TypeError):
            continue
        if candidate["item_id"] is not None and candidate["item_id"] not in valid_ids:
            candidate["item_id"] = None
        candidates.append(candidate)
    await db.execute(
        "UPDATE placements SET candidate_items=?, updated_at=datetime('now','localtime') WHERE id=?",
        (json.dumps(candidates, ensure_ascii=False), pid),
    )
    await db.commit()
    duration_ms = int((datetime.now() - started).total_seconds() * 1000)
    await _safe_audit(db, raw_text=placement["description"], ok=True, stage="placement_suggest",
                      llm_model=model, actions=candidates, duration_ms=duration_ms)
    return _placement_dict(await _get_placement(db, pid))


if __name__ == "__main__":
    # 解码与 Pydantic 校验（不触网/不调 LLM）
    assert _decode_int_list(None) == []
    assert _decode_int_list("not json") == []
    assert _decode_int_list("[3, 7, 9]") == [3, 7, 9]
    assert _decode_int_list('[3, "x", 7]') == [3, 7]  # 非整数丢弃
    p = PlacementIn(description="  把猫粮备用装塞到阳台柜  ", location="阳台柜上层")
    assert p.description == "把猫粮备用装塞到阳台柜"
    for blank in ("", "   "):
        try:
            PlacementIn(description=blank)
        except ValidationError:
            continue
        raise AssertionError(f"空白描述必须被拒绝: {blank!r}")
    c = PlacementCandidate(item_id=3, item_name="猫粮", confidence=0.85, reason="名称匹配")
    assert c.confidence == 0.85
    try:
        PlacementCandidate(confidence=1.5)
    except ValidationError:
        pass
    else:
        raise AssertionError("confidence > 1 必须被拒绝")
    print("placements.py 自检通过：解码、Pydantic 校验与候选模型正确。")
