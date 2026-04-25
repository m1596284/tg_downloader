"""Telegram Media Downloader - Phase 1 MVP"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    Channel,
    Chat,
    Document,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    Photo,
    User,
)

console = Console()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SESSION_NAME = "tg_downloader"
DOWNLOADS_DIR = Path("downloads")


def load_config() -> tuple[int, str, str]:
    """讀取 .env 並回傳 (api_id, api_hash, phone)。"""
    load_dotenv()

    api_id_raw = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    phone = os.getenv("PHONE")

    missing: list[str] = []
    if not api_id_raw:
        missing.append("API_ID")
    if not api_hash:
        missing.append("API_HASH")
    if not phone:
        missing.append("PHONE")

    if missing:
        console.print(
            f"[red]錯誤：.env 缺少以下必要欄位：{', '.join(missing)}[/red]"
        )
        console.print("[yellow]請複製 .env.example 為 .env 並填入正確的值。[/yellow]")
        sys.exit(1)

    try:
        api_id = int(api_id_raw)  # type: ignore[arg-type]
    except ValueError:
        console.print("[red]錯誤：API_ID 必須是整數。[/red]")
        sys.exit(1)

    return api_id, api_hash, phone  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# FloodWait 重試裝飾器
# ---------------------------------------------------------------------------

MAX_RETRIES = 5


def with_flood_wait(func: Callable) -> Callable:
    """捕捉 FloodWaitError，等待後重試，最多 MAX_RETRIES 次。"""

    async def wrapper(*args, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except FloodWaitError as e:
                wait_seconds = e.seconds + 1
                if attempt < MAX_RETRIES - 1:
                    console.print(
                        f"[yellow]遇到限制，等待 {wait_seconds} 秒後繼續...[/yellow]"
                    )
                    await asyncio.sleep(wait_seconds)
                else:
                    console.print(
                        f"[red]已達最大重試次數 ({MAX_RETRIES})，放棄操作。[/red]"
                    )
                    raise
        return None

    return wrapper


# ---------------------------------------------------------------------------
# 媒體類型判斷
# ---------------------------------------------------------------------------

VIDEO_MIME_PREFIXES = ("video/",)
IMAGE_MIME_PREFIXES = ("image/",)


def _is_video_document(doc: Document) -> bool:
    mime = getattr(doc, "mime_type", "") or ""
    return mime.startswith(VIDEO_MIME_PREFIXES)


def _is_image_document(doc: Document) -> bool:
    mime = getattr(doc, "mime_type", "") or ""
    return mime.startswith(IMAGE_MIME_PREFIXES)


def _should_download(msg: Message, media_type: str) -> bool:
    """判斷訊息是否符合下載條件。"""
    if not msg.media:
        return False

    if isinstance(msg.media, MessageMediaPhoto) and isinstance(msg.photo, Photo):
        return media_type in ("photo", "all")

    if isinstance(msg.media, MessageMediaDocument) and isinstance(msg.document, Document):
        doc: Document = msg.document
        if media_type in ("video", "all") and _is_video_document(doc):
            return True
        if media_type in ("photo", "all") and _is_image_document(doc):
            return True

    return False


# ---------------------------------------------------------------------------
# 檔案命名
# ---------------------------------------------------------------------------

def _get_filename(msg: Message) -> str:
    """從訊息產生下載檔名。"""
    msg_id = msg.id
    date_str = msg.date.strftime("%Y%m%d_%H%M%S") if msg.date else "unknown"

    # 嘗試從 document 取得原始檔名
    if isinstance(msg.media, MessageMediaDocument) and isinstance(msg.document, Document):
        for attr in msg.document.attributes:
            filename = getattr(attr, "file_name", None)
            if filename:
                return f"{msg_id}_{filename}"
        # document 但無檔名：依 mime type 決定副檔名
        mime = getattr(msg.document, "mime_type", "") or ""
        if mime.startswith("video/"):
            ext = mime.split("/")[-1] if "/" in mime else "mp4"
            return f"{msg_id}_{date_str}.{ext}"
        if mime.startswith("image/"):
            ext = mime.split("/")[-1] if "/" in mime else "jpg"
            return f"{msg_id}_{date_str}.{ext}"

    # Photo
    return f"{msg_id}_{date_str}.jpg"


# ---------------------------------------------------------------------------
# 命令：列出 channels
# ---------------------------------------------------------------------------

@with_flood_wait
async def _fetch_dialogs(client: TelegramClient) -> list:
    return await client.get_dialogs()


async def cmd_list(client: TelegramClient) -> None:
    """列出所有已加入的 channel/group。"""
    console.print("[cyan]正在取得對話清單...[/cyan]")
    dialogs = await _fetch_dialogs(client)

    table = Table(title="已加入的 Channels / Groups", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("名稱", style="bold")
    table.add_column("帳號 / 類型", style="dim")

    for dialog in dialogs:
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            entity_id = str(entity.id)
            name = entity.title or "(無標題)"
            username = f"@{entity.username}" if getattr(entity, "username", None) else "private"
            table.add_row(entity_id, name, username)
        elif isinstance(entity, User):
            # 略過個人對話
            continue

    console.print(table)


# ---------------------------------------------------------------------------
# 命令：下載媒體
# ---------------------------------------------------------------------------

async def cmd_download(
    client: TelegramClient,
    channel: str,
    limit: int,
    media_type: str,
) -> None:
    """下載指定 channel 的媒體。"""
    # 解析 channel（可能是 username 或數字 ID）
    try:
        entity_input: str | int = int(channel)
    except ValueError:
        entity_input = channel

    try:
        entity = await client.get_entity(entity_input)
    except Exception as exc:
        console.print(f"[red]無法取得 channel '{channel}'：{exc}[/red]")
        return

    channel_name: str = (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or str(channel)
    )
    # 清理檔案路徑非法字元
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in channel_name)
    dest_dir = DOWNLOADS_DIR / safe_name
    dest_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        f"[cyan]掃描 [bold]{channel_name}[/bold] 最近 {limit} 則訊息"
        f"（類型：{media_type}）...[/cyan]"
    )

    # 收集符合條件的訊息
    target_messages: list[Message] = []
    async for msg in client.iter_messages(entity, limit=limit):
        if _should_download(msg, media_type):
            target_messages.append(msg)
        await asyncio.sleep(0.5)

    if not target_messages:
        console.print("[yellow]沒有找到符合條件的媒體訊息。[/yellow]")
        return

    console.print(f"[green]找到 {len(target_messages)} 個媒體檔案，開始下載...[/green]")

    with Progress(
        TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:

        for msg in target_messages:
            filename = _get_filename(msg)
            dest_path = dest_dir / filename

            if dest_path.exists():
                console.print(f"[dim]已存在，跳過：{dest_path}[/dim]")
                continue

            task_id: TaskID = progress.add_task(
                "download",
                filename=filename,
                total=None,
            )

            def make_progress_callback(tid: TaskID) -> Callable[[int, int], None]:
                def callback(received: int, total: int) -> None:
                    progress.update(tid, completed=received, total=total)

                return callback

            try:
                await client.download_media(
                    msg,
                    file=str(dest_path),
                    progress_callback=make_progress_callback(task_id),
                )
                progress.update(task_id, completed=progress.tasks[task_id].total or 0)
                console.print(f"[green]完成：{dest_path}[/green]")
            except FloodWaitError as e:
                wait_sec = e.seconds + 1
                console.print(f"[yellow]遇到限制，等待 {wait_sec} 秒後繼續...[/yellow]")
                await asyncio.sleep(wait_sec)
                # 移除未完成的 task，繼續下一個
                progress.remove_task(task_id)
                if dest_path.exists():
                    dest_path.unlink()
                continue
            except Exception as exc:
                console.print(f"[red]下載失敗 {filename}：{exc}[/red]")
                progress.remove_task(task_id)
                if dest_path.exists():
                    dest_path.unlink()
                continue


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg-downloader",
        description="Telegram Media Downloader - Phase 1 MVP",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--list",
        action="store_true",
        help="列出所有已加入的 channel/group",
    )
    group.add_argument(
        "--channel",
        metavar="USERNAME_OR_ID",
        help="指定要下載媒體的 channel（username 或數字 ID）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="掃描最近幾則訊息（預設 50）",
    )
    parser.add_argument(
        "--type",
        dest="media_type",
        choices=["video", "photo", "all"],
        default="all",
        help="下載類型：video、photo 或 all（預設 all）",
    )
    return parser


async def main() -> None:
    api_id, api_hash, phone = load_config()
    parser = build_parser()
    args = parser.parse_args()

    async with TelegramClient(SESSION_NAME, api_id, api_hash) as client:
        # 首次登入：互動式 OTP
        await client.start(phone=phone)  # type: ignore[arg-type]

        if args.list:
            await cmd_list(client)
        elif args.channel:
            await cmd_download(
                client,
                channel=args.channel,
                limit=args.limit,
                media_type=args.media_type,
            )


def main_sync() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
