"""应用权限服务：目录种子、可见性、按账号分配。

默认全量开通 + 显式回收（见 models/app_perms.py 模块注释）。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AppRegistry, User, UserAppPermission

# 应用目录种子：与 frontend/src/apps/registry.ts 保持同名同序。
# 迁移里内联了相同数据（迁移不 import 应用代码，属有意复制，改动需同步）。
DEFAULT_APPS: list[dict] = [
    {
        "app_key": "xhs",
        "name": "小红书运营",
        "description": "采集、内容管理、创作与发布的一站式运营工作台",
        "sort_order": 0,
    },
    {
        "app_key": "douyin",
        "name": "抖音运营",
        "description": "多账号采集参考、审核发布与真实数据复盘",
        "sort_order": 1,
    },
    {
        "app_key": "clip",
        "name": "剪辑工坊",
        "description": "从内容库选素材，剪辑成片并送入小红书或抖音发布",
        "sort_order": 2,
    },
]


def ensure_apps_seeded(db: Session) -> None:
    """幂等补齐目录种子（迁移已种则跳过；覆盖 create_all 的全新库）。

    并发首调可能撞 app_key 唯一约束：回滚重读即可（对端为已提交数据）。
    """
    from sqlalchemy.exc import IntegrityError

    existing = {
        row.app_key
        for row in db.scalars(select(AppRegistry)).all()
    }
    if set(spec["app_key"] for spec in DEFAULT_APPS) <= existing:
        return
    added = False
    try:
        for spec in DEFAULT_APPS:
            if spec["app_key"] in existing:
                continue
            db.add(AppRegistry(enabled=True, **spec))
            added = True
        if added:
            db.commit()
    except IntegrityError:
        db.rollback()


def _registry_row(db: Session, app_key: str) -> Optional[AppRegistry]:
    return db.scalar(select(AppRegistry).where(AppRegistry.app_key == app_key))


def user_has_access(db: Session, user: User, app_key: str) -> bool:
    """账号可进入应用？管理员始终放行；目录未登记的 key 一律拒绝。"""
    if user.is_admin:
        return True
    # 生产库由迁移种子化；全新 create_all 库（测试）在此兜底
    ensure_apps_seeded(db)
    row = _registry_row(db, app_key)
    if row is None or not row.enabled:
        return False
    denied = db.scalar(
        select(UserAppPermission.granted).where(
            UserAppPermission.user_id == user.id,
            UserAppPermission.app_key == app_key,
        )
    )
    return denied is not False


def visible_apps(db: Session, user: User) -> list[dict]:
    """应用中心列表：目录中已开放且该账号可进入的应用。"""
    ensure_apps_seeded(db)
    rows = db.scalars(
        select(AppRegistry)
        .where(AppRegistry.enabled == True)  # noqa: E712
        .order_by(AppRegistry.sort_order.asc(), AppRegistry.id.asc())
    ).all()
    deny_map = {
        row.app_key: row.granted
        for row in db.scalars(
            select(UserAppPermission).where(UserAppPermission.user_id == user.id)
        ).all()
    }
    items: list[dict] = []
    for row in rows:
        if not user.is_admin and deny_map.get(row.app_key) is False:
            continue
        items.append(
            {
                "app_key": row.app_key,
                "name": row.name,
                "description": row.description,
                "enabled": row.enabled,
                "sort_order": row.sort_order,
                "accessible": True,
            }
        )
    return items


def catalog(db: Session) -> list[dict]:
    """管理视图：全部应用（含禁用）。"""
    ensure_apps_seeded(db)
    rows = db.scalars(
        select(AppRegistry).order_by(AppRegistry.sort_order.asc(), AppRegistry.id.asc())
    ).all()
    return [
        {
            "app_key": row.app_key,
            "name": row.name,
            "description": row.description,
            "enabled": row.enabled,
            "sort_order": row.sort_order,
            # 管理员始终可进入（字段与 visible_apps 对齐，前端可统一消费）
            "accessible": True,
        }
        for row in rows
    ]


def set_app_enabled(db: Session, app_key: str, enabled: bool) -> Optional[AppRegistry]:
    row = _registry_row(db, app_key)
    if row is None:
        return None
    row.enabled = bool(enabled)
    db.commit()
    db.refresh(row)
    return row


def user_access_map(db: Session, user_id: int) -> list[str]:
    """该账号当前可进入的应用 key 列表（含默认放行）。"""
    ensure_apps_seeded(db)
    enabled_keys = db.scalars(
        select(AppRegistry.app_key).where(AppRegistry.enabled == True)  # noqa: E712
    ).all()
    deny_rows = db.scalars(
        select(UserAppPermission).where(
            UserAppPermission.user_id == user_id,
            UserAppPermission.granted == False,  # noqa: E712
        )
    ).all()
    denied = {row.app_key for row in deny_rows}
    return [key for key in enabled_keys if key not in denied]


def set_user_access(db: Session, user_id: int, accessible_keys: list[str]) -> None:
    """显式落全量分配记录（PUT 语义）：集合内的 granted=True，其余已开放应用 False。

    只管理**已开放**的应用：禁用中的应用其既有授权行原样保留——
    否则管理员在应用关闭期间做任何一次分配保存，都会把该应用重开
    后的既有授权静默清掉（review 第 2 轮 P1）。
    """
    ensure_apps_seeded(db)
    wanted = {key for key in accessible_keys if isinstance(key, str)}
    existing = {
        row.app_key: row
        for row in db.scalars(
            select(UserAppPermission).where(UserAppPermission.user_id == user_id)
        ).all()
    }
    from sqlalchemy.exc import IntegrityError

    for row in db.scalars(
        select(AppRegistry).where(AppRegistry.enabled == True)  # noqa: E712
    ).all():
        record = existing.get(row.app_key)
        granted = row.app_key in wanted
        if record is None:
            db.add(
                UserAppPermission(
                    user_id=user_id, app_key=row.app_key, granted=granted
                )
            )
        elif record.granted != granted:
            record.granted = granted
    try:
        db.commit()
    except IntegrityError:
        # 并发双 PUT 撞 uq_user_app_permissions：回滚后按库内现状重放一次
        db.rollback()
        refreshed = {
            row.app_key: row
            for row in db.scalars(
                select(UserAppPermission).where(UserAppPermission.user_id == user_id)
            ).all()
        }
        for row in db.scalars(
            select(AppRegistry).where(AppRegistry.enabled == True)  # noqa: E712
        ).all():
            record = refreshed.get(row.app_key)
            granted = row.app_key in wanted
            if record is None:
                db.add(
                    UserAppPermission(
                        user_id=user_id, app_key=row.app_key, granted=granted
                    )
                )
            elif record.granted != granted:
                record.granted = granted
        db.commit()


def list_users(db: Session) -> list[dict]:
    rows = db.scalars(select(User).order_by(User.id.asc())).all()
    return [
        {"id": row.id, "username": row.username, "is_admin": bool(row.is_admin)}
        for row in rows
    ]
