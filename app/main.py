"""HomeDash FastAPI 入口：挂载路由、初始化数据库、托管静态前端。"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.database import get_db
from app.modules import ai_workbench, auth, items, notify, placements, setup, todos, travel, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="HomeDash - 家庭管理面板", lifespan=lifespan)
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(items.router, prefix="/api")
app.include_router(ai_workbench.router, prefix="/api")
app.include_router(notify.router, prefix="/api")
app.include_router(todos.router, prefix="/api")
app.include_router(setup.router, prefix="/api")
app.include_router(travel.router, prefix="/api")
app.include_router(placements.router, prefix="/api")

_PUBLIC_API_PATHS = {
    "/api/auth/bootstrap-status",
    "/api/auth/bootstrap-admin",
    "/api/auth/login",
    "/api/auth/logout",
}


@app.middleware("http")
async def panel_authentication(request: Request, call_next):
    """统一保护面板 API；agent 路径继续使用自身的 AGENT_API_TOKEN。"""
    path = request.url.path
    protected = (
        request.method != "OPTIONS"
        and path.startswith("/api/")
        and path not in _PUBLIC_API_PATHS
        and not path.startswith("/api/agent/todos")
    )
    token = request.cookies.get(auth.COOKIE_NAME, "")
    renew = False
    if protected:
        db = await get_db()
        user, renew = await auth.session_user(db, token)
        if not user:
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        request.state.user = user
        if (path.startswith("/api/setup/") or path.startswith("/api/admin/")) and user["role"] != "admin":
            return JSONResponse({"detail": "当前账户无权执行此操作"}, status_code=403)
    response = await call_next(request)
    if protected and renew and token:
        auth.set_session_cookie(response, token, request)
    return response

# 静态前端（Phase 2 提供；目录不存在则跳过，不阻塞 API）
if os.path.isdir("app/static"):
    app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
