"""Pydantic schemas for tg_downloader."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class FilterOptions(BaseModel):
    """篩選條件。"""

    media_type: Literal["video", "photo", "all"] = "all"
    since: datetime | None = None
    until: datetime | None = None
    min_size_mb: float | None = None
    max_size_mb: float | None = None
    limit: int = 50
    min_duration_sec: float | None = None  # 最短時長（秒），只對 video 有效
    max_duration_sec: float | None = None  # 最長時長（秒），只對 video 有效
    keywords: list[str] = []  # 關鍵字清單（OR 邏輯，大小寫不敏感）


class ChannelInfo(BaseModel):
    """Channel 基本資訊。"""

    id: int
    name: str
    username: str | None


class DownloadJob(BaseModel):
    """單一下載任務。"""

    id: int | None = None
    channel_id: int
    message_id: int
    file_name: str
    file_size: int | None  # bytes
    media_type: str  # 'video' | 'photo'
    msg_date: datetime
    status: Literal["pending", "downloading", "done", "error"] = "pending"
    local_path: str | None = None
    error_msg: str | None = None
    duration_sec: float | None = None  # 影片時長（秒），photo 或未知為 None
