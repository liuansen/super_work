"""应用目录与权限管理接口。

- ``GET /api/apps``：登录用户的可进入应用（应用中心数据源）
- ``GET /api/apps/admin/catalog`` / ``PATCH /api/apps/admin/catalog/{app_key}``：
  全局开关（后台应用管理）
- ``GET /api/apps/admin/users``、``GET/PUT /api/apps/admin/users/{user_id}/apps``：
  按账号分配应用

管理端点一律 require_admin；非管理员 403。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user, require_admin
from backend.app.models import User
from backend.app.services import app_perms

router = APIRouter(prefix="/apps", tags=["apps"])


class AppToggleRequest(BaseModel):
    enabled: bool


class UserAppsRequest(BaseModel):
    app_keys: list[str] = Field(default_factory=list)


def _require_user_exists(db: Session, user_id: int) -> None:
    from backend.app.models import User as _User

    if db.get(_User, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")


def _check_known_app(db: Session, app_key: str) -> None:
    # 管理操作可能先于任何用户请求触达，目录种子必须先兜底
    app_perms.ensure_apps_seeded(db)
    if app_perms._registry_row(db, app_key) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="应用不存在")


@router.get("")
def list_my_apps(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """应用中心数据源。

    管理员返回管理视图（含禁用应用，保证管理入口可达）；
    普通用户只返回已开放且未被回收的应用。
    """
    items = app_perms.catalog(db) if current_user.is_admin else app_perms.visible_apps(db, current_user)
    return {"items": items}


@router.get("/admin/catalog")
def get_admin_catalog(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": app_perms.catalog(db)}


@router.patch("/admin/catalog/{app_key}")
def toggle_app(
    app_key: str,
    payload: AppToggleRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _check_known_app(db, app_key)
    row = app_perms.set_app_enabled(db, app_key, payload.enabled)
    return {"app_key": app_key, "enabled": bool(row.enabled)}


@router.get("/admin/users")
def list_users(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": app_perms.list_users(db)}


@router.get("/admin/users/{user_id}/apps")
def get_user_apps(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _require_user_exists(db, user_id)
    return {"user_id": user_id, "app_keys": app_perms.user_access_map(db, user_id)}


@router.put("/admin/users/{user_id}/apps")
def set_user_apps(
    user_id: int,
    payload: UserAppsRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _require_user_exists(db, user_id)
    app_perms.set_user_access(db, user_id, payload.app_keys)
    return {"user_id": user_id, "app_keys": app_perms.user_access_map(db, user_id)}
