"""SQLite CRUD with aiosqlite — 斷點續傳支援。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from models.schemas import DownloadJob

DB_PATH = Path("tg_downloader.db")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS download_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL,
    message_id   INTEGER NOT NULL,
    file_name    TEXT NOT NULL,
    file_size    INTEGER,
    media_type   TEXT NOT NULL,
    msg_date     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    local_path   TEXT,
    error_msg    TEXT,
    duration_sec REAL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE(channel_id, message_id)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db(db_path: Path = DB_PATH) -> None:
    """建立 schema（若不存在），並自動遷移舊版 DB。"""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_TABLE_SQL)
        await db.commit()
        # 遷移：為舊版 DB 補上 duration_sec 欄位
        try:
            await db.execute("ALTER TABLE download_jobs ADD COLUMN duration_sec REAL")
            await db.commit()
        except Exception:
            pass  # 欄位已存在，忽略


async def upsert_job(job: DownloadJob, db_path: Path = DB_PATH) -> int:
    """Insert or ignore（已存在則不覆蓋），回傳 rowid。"""
    now = _now_iso()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO download_jobs
                (channel_id, message_id, file_name, file_size, media_type,
                 msg_date, status, local_path, error_msg, duration_sec,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.channel_id,
                job.message_id,
                job.file_name,
                job.file_size,
                job.media_type,
                job.msg_date.isoformat(),
                job.status,
                job.local_path,
                job.error_msg,
                job.duration_sec,
                now,
                now,
            ),
        )
        await db.commit()
        # 若 INSERT OR IGNORE 因重複而跳過，lastrowid 為 0；查詢真實 id
        if cursor.lastrowid and cursor.lastrowid > 0:
            return cursor.lastrowid
        row = await (
            await db.execute(
                "SELECT id FROM download_jobs WHERE channel_id=? AND message_id=?",
                (job.channel_id, job.message_id),
            )
        ).fetchone()
        return row[0] if row else 0


async def update_job_status(
    job_id: int,
    status: str,
    local_path: str | None = None,
    error_msg: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """更新任務狀態。"""
    now = _now_iso()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE download_jobs
               SET status=?, local_path=?, error_msg=?, updated_at=?
             WHERE id=?
            """,
            (status, local_path, error_msg, now, job_id),
        )
        await db.commit()


async def get_pending_jobs(
    channel_id: int, db_path: Path = DB_PATH
) -> list[DownloadJob]:
    """取得指定 channel 尚未完成（pending / error）的任務。"""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await (
            await db.execute(
                """
                SELECT * FROM download_jobs
                 WHERE channel_id=? AND status IN ('pending', 'error')
                 ORDER BY message_id
                """,
                (channel_id,),
            )
        ).fetchall()
    return [_row_to_job(r) for r in rows]


async def is_downloaded(
    channel_id: int, message_id: int, db_path: Path = DB_PATH
) -> bool:
    """判斷指定訊息是否已成功下載（status=done）。"""
    async with aiosqlite.connect(db_path) as db:
        row = await (
            await db.execute(
                "SELECT 1 FROM download_jobs WHERE channel_id=? AND message_id=? AND status='done'",
                (channel_id, message_id),
            )
        ).fetchone()
    return row is not None


def _row_to_job(row: aiosqlite.Row) -> DownloadJob:
    """將資料庫列轉換為 DownloadJob。"""
    return DownloadJob(
        id=row["id"],
        channel_id=row["channel_id"],
        message_id=row["message_id"],
        file_name=row["file_name"],
        file_size=row["file_size"],
        media_type=row["media_type"],
        msg_date=datetime.fromisoformat(row["msg_date"]),
        status=row["status"],
        local_path=row["local_path"],
        error_msg=row["error_msg"],
        duration_sec=row["duration_sec"],
    )
