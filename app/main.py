"""HomeDash FastAPI 入口：挂载路由、初始化数据库、托管静态前端。"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.modules import ai_workbench, devices, items, notify, setup, todos, uptime


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await asyncio.to_thread(devices.load_devices)
    yield


app = FastAPI(title="HomeDash - 家庭管理面板", lifespan=lifespan)
app.include_router(items.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(ai_workbench.router, prefix="/api")
app.include_router(notify.router, prefix="/api")
app.include_router(todos.router, prefix="/api")
app.include_router(uptime.router, prefix="/api")
app.include_router(setup.router, prefix="/api")

# 静态前端（Phase 2 提供；目录不存在则跳过，不阻塞 API）
if os.path.isdir("app/static"):
    app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
