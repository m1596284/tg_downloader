"""下載佇列、並行控制、篩選邏輯。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    Document,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    Photo,
)

from core.db import init_db, is_downloaded, update_job_status, upsert_job
from models.schemas import DownloadJob, FilterOptions

DOWNLOAD_SEMAPHORE = asyncio.Semaphore(3)

VIDEO_MIME_PREFIXES = ("video/",)
IMAGE_MIME_PREFIXES = ("image/",)


# ---------------------------------------------------------------------------
# 媒體型別判斷與檔名產生
# ---------------------------------------------------------------------------


def _is_video_document(doc: Document) -> bool:
    mime = getattr(doc, "mime_type", "") or ""
    return mime.startswith(VIDEO_MIME_PREFIXES)


def _is_image_document(doc: Document) -> bool:
    mime = getattr(doc, "mime_type", "") or ""
    return mime.startswith(IMAGE_MIME_PREFIXES)


def _get_media_type(msg: Message) -> str | None:
    """回傳 'video' / 'photo'，若非媒體則回傳 None。"""
    if isinstance(msg.media, MessageMediaPhoto) and isinstance(msg.photo, Photo):
        return "photo"
    if isinstance(msg.media, MessageMediaDocument) and isinstance(
        msg.document, Document
    ):
        doc: Document = msg.document
        if _is_video_document(doc):
            return "video"
        if _is_image_document(doc):
            return "photo"
    return None


def _get_file_size(msg: Message) -> int | None:
    """取得檔案大小（bytes），Photo 無法直接取得回傳 None。"""
    if isinstance(msg.media, MessageMediaDocument) and isinstance(
        msg.document, Document
    ):
        return getattr(msg.document, "size", None)
    return None


def _get_video_duration(doc: Document) -> float | None:
    """取得影片時長（秒），無時長資訊回傳 None。"""
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeVideo):
            return float(attr.duration)
    return None


def _matches_keyword(msg: Message, keywords: list[str]) -> bool:
    """訊息 caption 是否包含任一關鍵字（大小寫不敏感，OR 邏輯）。"""
    if not keywords:
        return True
    text = (msg.message or "").lower()
    return any(kw.lower() in text for kw in keywords)


def _get_filename(msg: Message) -> str:
    """從訊息產生下載檔名。"""
    msg_id = msg.id
    date_str = msg.date.strftime("%Y%m%d_%H%M%S") if msg.date else "unknown"

    if isinstance(msg.media, MessageMediaDocument) and isinstance(
        msg.document, Document
    ):
        for attr in msg.document.attributes:
            filename = getattr(attr, "file_name", None)
            if filename:
                return f"{msg_id}_{filename}"
        mime = getattr(msg.document, "mime_type", "") or ""
        if mime.startswith("video/"):
            ext = mime.split("/")[-1] if "/" in mime else "mp4"
            return f"{msg_id}_{date_str}.{ext}"
        if mime.startswith("image/"):
            ext = mime.split("/")[-1] if "/" in mime else "jpg"
            return f"{msg_id}_{date_str}.{ext}"

    return f"{msg_id}_{date_str}.jpg"


# ---------------------------------------------------------------------------
# 篩選邏輯
# ---------------------------------------------------------------------------


def _passes_filters(
    msg: Message, media_type: str | None, filters: FilterOptions
) -> bool:
    """判斷訊息是否通過所有篩選條件。"""
    if media_type is None:
        return False

    # 媒體類型篩選
    if filters.media_type != "all" and media_type != filters.media_type:
        return False

    # 日期篩選（Telegram msg.date 是 UTC aware datetime）
    if filters.since is not None and msg.date < filters.since:
        return False
    if filters.until is not None and msg.date > filters.until:
        return False

    # 關鍵字篩選（大小寫不敏感，OR 邏輯）
    if not _matches_keyword(msg, filters.keywords):
        return False

    # 大小篩選（只對有大小資訊的 document 有效）
    file_size = _get_file_size(msg)
    if file_size is not None:
        if (
            filters.min_size_mb is not None
            and file_size < filters.min_size_mb * 1024 * 1024
        ):
            return False
        if (
            filters.max_size_mb is not None
            and file_size > filters.max_size_mb * 1024 * 1024
        ):
            return False

    # 時長篩選（只對 video 有效；gif 等無 DocumentAttributeVideo 者視為通過）
    if (
        media_type == "video"
        and isinstance(msg.media, MessageMediaDocument)
        and isinstance(msg.document, Document)
    ):
        duration = _get_video_duration(msg.document)
        if duration is not None:
            if (
                filters.min_duration_sec is not None
                and duration < filters.min_duration_sec
            ):
                return False
            if (
                filters.max_duration_sec is not None
                and duration > filters.max_duration_sec
            ):
                return False

    return True


# ---------------------------------------------------------------------------
# 掃描訊息
# ---------------------------------------------------------------------------


async def scan_messages(
    client: TelegramClient,
    entity,
    filters: FilterOptions,
    db_path: Path,
    on_progress: Callable[[int], None] | None = None,
) -> list[DownloadJob]:
    """列舉訊息，篩選後存入 DB，回傳 pending jobs。跳過已 done 的。"""
    await init_db(db_path)

    channel_id: int = entity.id
    jobs: list[DownloadJob] = []
    scanned = 0

    async for msg in client.iter_messages(entity, limit=filters.limit):
        scanned += 1
        if on_progress:
            on_progress(scanned)

        media_type = _get_media_type(msg)
        if not _passes_filters(msg, media_type, filters):
            await asyncio.sleep(0)
            continue

        # 跳過已成功下載
        if await is_downloaded(channel_id, msg.id, db_path):
            continue

        file_name = _get_filename(msg)
        file_size = _get_file_size(msg)

        # 取得影片時長（只有 video document 才有）
        duration_sec: float | None = None
        if (
            media_type == "video"
            and isinstance(msg.media, MessageMediaDocument)
            and isinstance(msg.document, Document)
        ):
            duration_sec = _get_video_duration(msg.document)

        job = DownloadJob(
            channel_id=channel_id,
            message_id=msg.id,
            file_name=file_name,
            file_size=file_size,
            media_type=media_type,  # type: ignore[arg-type]
            msg_date=msg.date,
            status="pending",
            duration_sec=duration_sec,
        )
        job_id = await upsert_job(job, db_path)
        jobs.append(job.model_copy(update={"id": job_id}))

        await asyncio.sleep(0.3)  # 避免觸發 FloodWait

    return jobs


# ---------------------------------------------------------------------------
# 下載單一 job
# ---------------------------------------------------------------------------


async def download_job(
    client: TelegramClient,
    job: DownloadJob,
    dest_dir: Path,
    db_path: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """下載單一 job，更新 DB 狀態。"""
    async with DOWNLOAD_SEMAPHORE:
        dest_path = dest_dir / job.file_name

        if dest_path.exists() and job.status == "done":
            return

        # 設為 downloading
        if job.id is not None:
            await update_job_status(job.id, "downloading", db_path=db_path)

        def _progress_callback(received: int, total: int) -> None:
            if on_progress:
                on_progress(received, total)

        try:
            entity = await client.get_entity(job.channel_id)
            msg = await client.get_messages(entity, ids=job.message_id)
            await client.download_media(
                msg,
                file=str(dest_path),
                progress_callback=_progress_callback,
            )
            if job.id is not None:
                await update_job_status(
                    job.id, "done", local_path=str(dest_path), db_path=db_path
                )
        except FloodWaitError as e:
            wait_sec = e.seconds + 1
            await asyncio.sleep(wait_sec)
            if dest_path.exists():
                dest_path.unlink()
            if job.id is not None:
                await update_job_status(
                    job.id,
                    "error",
                    error_msg=f"FloodWait {e.seconds}s",
                    db_path=db_path,
                )
            raise
        except Exception as exc:
            if dest_path.exists():
                dest_path.unlink()
            if job.id is not None:
                await update_job_status(
                    job.id, "error", error_msg=str(exc), db_path=db_path
                )
            raise


# ---------------------------------------------------------------------------
# 並行下載全部 jobs
# ---------------------------------------------------------------------------


async def download_all(
    client: TelegramClient,
    jobs: list[DownloadJob],
    dest_dir: Path,
    db_path: Path,
    on_file_start: Callable[[DownloadJob], None] | None = None,
    on_file_done: Callable[[DownloadJob], None] | None = None,
    on_progress: Callable[[int, int, int], None] | None = None,
) -> None:
    """並行下載所有 jobs（最多 3 條同時）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)

    async def _run(idx: int, job: DownloadJob) -> None:
        if on_file_start:
            on_file_start(job)

        def _prog(received: int, total: int) -> None:
            if on_progress:
                on_progress(idx, received, total)

        final_status = "error"
        try:
            await download_job(client, job, dest_dir, db_path, on_progress=_prog)
            final_status = "done"
        except Exception:
            pass  # 錯誤已記錄到 DB，繼續下一個

        if on_file_done:
            on_file_done(job.model_copy(update={"status": final_status}))

    await asyncio.gather(*[_run(i, job) for i, job in enumerate(jobs)])
