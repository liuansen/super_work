from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClipAssetSelection(BaseModel):
    kind: Literal["note_asset", "draft_asset", "upload"]
    id: Optional[int] = None
    file_name: Optional[str] = None


class ClipSessionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    assets: list[ClipAssetSelection] = Field(min_length=1, max_length=50)
