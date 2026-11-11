from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.auth import MEDIA_COOKIE_NAME
from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decode_token
from backend.app.models import User
from backend.app.services.image_util import compose_cover_image, resize_image_file

router = APIRouter(prefix="/files", tags=["files"])


class ComposeImageRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=800)
    width: int = Field(default=1080, ge=320, le=2400)
    height: int = Field(default=1440, ge=320, le=3200)
    background_color: str = Field(default="#fafaf8", max_length=16)
    accent_color: str = Field(default="#111111", max_length=16)


class ResizeImageRequest(BaseModel):
    source_file_name: str = Field(min_length=1, max_length=180)
    width: int = Field(default=1080, ge=128, le=2400)
    height: int = Field(default=1440, ge=128, le=3200)
    mode: Literal["cover", "contain"] = "cover"
    format: Literal["png", "jpeg"] = "png"
    quality: int = Field(default=90, ge=40, le=100)


def _export_media_type(file_name: str) -> str:
    if file_name.endswith(".csv"):
        return "text/csv; charset=utf-8"
    return "application/json"


def _media_dir() -> Path:
    from backend.app.core.media_storage import media_dir

    return media_dir()


def _owner_media_prefix(current_user: User) -> str:
    return f"xhs-image-u{current_user.id}-"


def _validate_owner_media_name(file_name: str, current_user: User) -> str:
    if Path(file_name).name != file_name or ".." in file_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
    valid_prefixes = (
        _owner_media_prefix(current_user),
        f"xhs-asset-u{current_user.id}-",
        f"xhs-upload-u{current_user.id}-",
        f"xhs-clip-u{current_user.id}-",
    )
    if not file_name.startswith(valid_prefixes):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
    return file_name


def _media_type(file_name: str) -> str:
    lower = file_name.lower()
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".mp4"):
        return "video/mp4"
    if lower.endswith(".mov"):
        return "video/quicktime"
    if lower.endswith(".avi"):
        return "video/x-msvideo"
    if lower.endswith(".mkv"):
        return "video/x-matroska"
    return "image/png"


def _serialize_media_file(*, file_name: str, width: int, height: int) -> dict:
    # 不返回服务器绝对路径（BE-10 路径信息泄露），客户端一律使用 download_url
    return {
        "file_name": file_name,
        "download_url": f"/api/files/media/{file_name}",
        "width": width,
        "height": height,
        "media_type": _media_type(file_name),
    }


@router.get("/images")
def list_user_images(current_user: User = Depends(get_current_user)):
    prefix = f"xhs-upload-u{current_user.id}-"
    media_dir = _media_dir()
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    entries: list[tuple[float, str, int]] = []
    if media_dir.is_dir():
        # os.scandir + entry.stat()：一次遍历拿全属性，
        # 不像 iterdir()+stat() 那样每个文件两次系统调用
        import os

        try:
            with os.scandir(media_dir) as iterator:
                for entry in iterator:
                    if not entry.name.startswith(prefix):
                        continue
                    if os.path.splitext(entry.name)[1].lower() not in image_exts:
                        continue
                    try:
                        if not entry.is_file():
                            continue
                        st = entry.stat()
                    except OSError:
                        continue
                    entries.append((st.st_mtime, entry.name, st.st_size))
        except OSError:
            entries = []
    entries.sort(key=lambda item: item[0], reverse=True)
    return {
        "items": [
            {"file_name": name, "url": f"/api/files/media/{name}", "size": size}
            for _mtime, name, size in entries
        ]
    }


@router.delete("/images/{file_name}")
def delete_user_image(file_name: str, current_user: User = Depends(get_current_user)):
    # 复用统一归属校验：覆盖 xhs-image-/xhs-asset-/xhs-upload- 三个前缀。
    # 此前只允许 xhs-upload-，下载器生成的 xhs-asset- 素材用户自己都删不掉，
    # media 目录只增不减。
    _validate_owner_media_name(file_name, current_user)
    if file_name.startswith(f"xhs-clip-u{current_user.id}-"):
        # 成片是剪辑工坊的受管资产（可能已关联草稿，删除有业务约束），
        # 必须走 DELETE /api/clip/exports/{id}，不能绕过业务校验直接删文件
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="成片请通过剪辑工坊删除")
    file_path = _media_dir() / file_name
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    file_path.unlink()
    return {"file_name": file_name, "status": "deleted"}


@router.post("/images/compose")
def compose_image(payload: ComposeImageRequest, current_user: User = Depends(get_current_user)):
    file_name = f"{_owner_media_prefix(current_user)}{uuid4().hex}.png"
    output_path = _media_dir() / file_name
    compose_cover_image(
        output_path=output_path,
        title=payload.title,
        body=payload.body,
        width=payload.width,
        height=payload.height,
        background_color=payload.background_color,
        accent_color=payload.accent_color,
    )
    return _serialize_media_file(file_name=file_name, width=payload.width, height=payload.height)


@router.post("/images/resize")
def resize_image(payload: ResizeImageRequest, current_user: User = Depends(get_current_user)):
    source_file_name = _validate_owner_media_name(payload.source_file_name, current_user)
    source_path = _media_dir() / source_file_name
    if not source_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")

    extension = "jpg" if payload.format == "jpeg" else "png"
    file_name = f"{_owner_media_prefix(current_user)}{uuid4().hex}.{extension}"
    output_path = _media_dir() / file_name
    resize_image_file(
        source_path=source_path,
        output_path=output_path,
        width=payload.width,
        height=payload.height,
        mode=payload.mode,
        image_format=payload.format,
        quality=payload.quality,
    )
    return _serialize_media_file(file_name=file_name, width=payload.width, height=payload.height)


def _media_viewer_user(
    authorization: Optional[str] = Header(default=None),
    media_token: Optional[str] = Cookie(default=None, alias=MEDIA_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    """媒体读取鉴权：支持 Authorization 头（access token）或 media_token cookie。

    ``<img>`` 标签无法携带 Authorization 头，因此登录/刷新时会下发
    HttpOnly 的 media_token cookie；两种凭证任一有效即可。
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
    )
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token)
        except HTTPException:
            payload = None
        if payload and payload.get("token_type") == "access":
            user = db.get(User, payload["user_id"])
            if user is not None and int(payload.get("ver") or 0) == int(user.token_version or 0):
                return user
    if media_token:
        try:
            payload = decode_token(media_token)
        except HTTPException:
            payload = None
        if payload and payload.get("token_type") == "media":
            user = db.get(User, payload["user_id"])
            # review P2：令牌版本校验，吊销后 media cookie 立即失效
            if user is not None and int(payload.get("ver") or 0) == int(user.token_version or 0):
                return user
    raise credentials_error


@router.get("/media/{file_name}")
def download_media(
    file_name: str,
    viewer: User = Depends(_media_viewer_user),
    db: Session = Depends(get_db),
):
    if Path(file_name).name != file_name or ".." in file_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
    # 应用权限：clip 成片是剪辑工坊受管资产，回收后已获知的 download_url
    # 也不得继续下载（review 第 1 轮 P2）
    if file_name.startswith(f"xhs-clip-u{viewer.id}-"):
        from backend.app.services.app_perms import user_has_access

        if not user_has_access(db, viewer, "clip"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该应用未对当前账号开通")
    # 属主校验：媒体文件名统一携带 xhs-*-u{user_id}- 前缀
    owner_prefixes = (
        f"xhs-image-u{viewer.id}-",
        f"xhs-asset-u{viewer.id}-",
        f"xhs-upload-u{viewer.id}-",
        f"xhs-clip-u{viewer.id}-",
    )
    if not file_name.startswith(owner_prefixes):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
    file_path = _media_dir() / file_name
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
    return FileResponse(file_path, filename=file_name, media_type=_media_type(file_name))


@router.get("/exports/{file_name}")
def download_export(file_name: str, current_user: User = Depends(get_current_user)):
    if Path(file_name).name != file_name or ".." in file_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export file not found")

    owner_prefixes = (f"xhs-notes-u{current_user.id}-", f"xhs-report-u{current_user.id}-")
    if not file_name.startswith(owner_prefixes):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export file not found")

    export_dir = Path(get_settings().storage_dir) / "exports"
    file_path = export_dir / file_name
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export file not found")

    return FileResponse(file_path, filename=file_name, media_type=_export_media_type(file_name))


ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".avi", ".mkv"}
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    content_length: Optional[int] = Header(default=None),
):
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名不能为空")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"不支持的文件格式: {ext}")

    # 预检声明大小（SEC-4）：超限直接 413，不进入分块读取
    declared_size = getattr(file, "size", None) or content_length
    if declared_size is not None and declared_size > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件大小超过 100MB 限制")

    # 流式写盘（SEC-4）：数据落临时文件，内存占用恒定；超限立即中止并清理
    asset_type = "video" if ext in {".mp4", ".mov", ".avi", ".mkv"} else "image"
    file_name = f"xhs-upload-u{current_user.id}-{uuid4().hex}{ext}"
    media_dir = _media_dir()
    media_dir.mkdir(parents=True, exist_ok=True)
    output_path = media_dir / file_name
    total = 0
    try:
        # async 端点里的同步磁盘 IO 会占用事件循环线程（其他端点都跑在线程池），
        # 慢盘/网络盘上会阻塞整个服务。open/write/close 全部走 anyio 工作线程。
        import anyio

        out = await anyio.open_file(output_path, "wb")
        try:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="文件大小超过 100MB 限制",
                    )
                await out.write(chunk)
        finally:
            await out.aclose()
    except HTTPException:
        output_path.unlink(missing_ok=True)
        raise
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    if total == 0:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    return {
        "file_name": file_name,
        "download_url": f"/api/files/media/{file_name}",
        "asset_type": asset_type,
        "size": total,
    }
