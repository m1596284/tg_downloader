"""Telethon 封裝：config 讀取、FloodWait 重試、client factory、channel 列舉。"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable

from dotenv import load_dotenv
from rich.console import Console
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import Channel, Chat, User

from models.schemas import ChannelInfo

console = Console()

SESSION_NAME = "tg_downloader"
MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


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
# Client factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def get_client(phone: str | None = None) -> AsyncGenerator[TelegramClient, None]:
    """回傳已啟動的 TelegramClient context manager。"""
    api_id, api_hash, _phone = load_config()
    _phone = phone or _phone
    async with TelegramClient(SESSION_NAME, api_id, api_hash) as client:
        await client.start(phone=_phone)  # type: ignore[arg-type]
        yield client


# ---------------------------------------------------------------------------
# Channel 列舉
# ---------------------------------------------------------------------------


@with_flood_wait
async def _fetch_dialogs(client: TelegramClient) -> list:
    return await client.get_dialogs()


async def fetch_channels(client: TelegramClient) -> list[ChannelInfo]:
    """列出所有已加入的 channel，回傳 list[ChannelInfo]。"""
    dialogs = await _fetch_dialogs(client)
    channels: list[ChannelInfo] = []
    for dialog in dialogs:
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            username = getattr(entity, "username", None)
            channels.append(
                ChannelInfo(
                    id=entity.id,
                    name=entity.title or "(無標題)",
                    username=f"@{username}" if username else None,
                )
            )
    return channels
