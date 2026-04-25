"""Telegram Media Downloader - Phase 2

進入點：同時支援 CLI 和 TUI 模式。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from core.client import fetch_channels, get_client
from core.db import DB_PATH, init_db
from core.downloader import download_all, scan_messages
from models.schemas import FilterOptions

console = Console()

DOWNLOADS_DIR = Path("downloads")


# ---------------------------------------------------------------------------
# CLI 命令
# ---------------------------------------------------------------------------


async def cmd_list() -> None:
    """列出所有已加入的 channel/group。"""
    console.print("[cyan]正在取得對話清單...[/cyan]")
    async with get_client() as client:
        channels = await fetch_channels(client)

    table = Table(title="已加入的 Channels / Groups", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("名稱", style="bold")
    table.add_column("帳號", style="dim")

    for ch in channels:
        table.add_row(str(ch.id), ch.name, ch.username or "private")

    console.print(table)


async def cmd_download(
    channel: str,
    filters: FilterOptions,
) -> None:
    """下載指定 channel 的媒體（CLI 模式）。"""
    async with get_client() as client:
        # 解析 channel（username 或數字 ID）
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
        safe_name = "".join(
            c if c.isalnum() or c in "-_." else "_" for c in channel_name
        )
        dest_dir = DOWNLOADS_DIR / safe_name

        await init_db(DB_PATH)

        console.print(
            f"[cyan]掃描 [bold]{channel_name}[/bold] 最近 {filters.limit} 則訊息"
            f"（類型：{filters.media_type}）...[/cyan]"
        )

        scanned = 0

        def on_scan(count: int) -> None:
            nonlocal scanned
            scanned = count
            if count % 10 == 0:
                console.print(f"[dim]已掃描 {count} 則...[/dim]")

        jobs = await scan_messages(
            client, entity, filters, DB_PATH, on_progress=on_scan
        )

        if not jobs:
            console.print("[yellow]沒有找到符合條件的媒體訊息。[/yellow]")
            return

        console.print(
            f"[green]找到 {len(jobs)} 個待下載檔案，開始並行下載（最多 3 條）...[/green]"
        )

        from rich.progress import (
            BarColumn,
            DownloadColumn,
            Progress,
            TextColumn,
            TimeRemainingColumn,
            TransferSpeedColumn,
        )

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
            task_map: dict[int, object] = {}

            def on_file_start(job) -> None:
                tid = progress.add_task(
                    "download",
                    filename=job.file_name[:40],
                    total=job.file_size or 0,
                )
                task_map[id(job)] = tid

            def on_file_done(job) -> None:
                tid = task_map.get(id(job))
                if tid is not None:
                    t = progress.tasks[tid]  # type: ignore[index]
                    progress.update(tid, completed=t.total or 0)
                status_color = "green" if job.status == "done" else "red"
                console.print(
                    f"[{status_color}]{'完成' if job.status == 'done' else '失敗'}："
                    f"{job.file_name}[/{status_color}]"
                )

            def on_progress_cb(idx: int, received: int, total: int) -> None:
                job = jobs[idx]
                tid = task_map.get(id(job))
                if tid is not None:
                    progress.update(tid, completed=received, total=total)

            await download_all(
                client,
                jobs,
                dest_dir,
                DB_PATH,
                on_file_start=on_file_start,
                on_file_done=on_file_done,
                on_progress=on_progress_cb,
            )

        done_count = sum(1 for j in jobs if j.status == "done")
        console.print(
            f"\n[bold green]下載完成：{done_count}/{len(jobs)} 個檔案成功。[/bold green]"
        )


# ---------------------------------------------------------------------------
# 參數解析
# ---------------------------------------------------------------------------


def _parse_date(date_str: str) -> datetime:
    """將 YYYY-MM-DD 解析為 UTC aware datetime。"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        console.print(f"[red]日期格式錯誤：'{date_str}'，請使用 YYYY-MM-DD。[/red]")
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg-downloader",
        description="Telegram Media Downloader - Phase 2",
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
    group.add_argument(
        "--tui",
        action="store_true",
        help="啟動 Textual TUI 互動介面",
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
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="只下載此日期之後的訊息（UTC）",
    )
    parser.add_argument(
        "--until",
        metavar="YYYY-MM-DD",
        help="只下載此日期之前的訊息（UTC）",
    )
    parser.add_argument(
        "--min-size",
        type=float,
        metavar="MB",
        help="最小檔案大小（MB）",
    )
    parser.add_argument(
        "--max-size",
        type=float,
        metavar="MB",
        help="最大檔案大小（MB）",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        metavar="SECONDS",
        help="影片最短時長（秒），只對 video 有效",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        metavar="SECONDS",
        help="影片最長時長（秒），只對 video 有效",
    )
    parser.add_argument(
        "--keyword",
        metavar="KEYWORD[,KEYWORD...]",
        help="關鍵字篩選，多個用逗號分隔（大小寫不敏感，OR 邏輯）",
    )
    return parser


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        await cmd_list()
        return

    if args.channel:
        filters = FilterOptions(
            media_type=args.media_type,
            since=_parse_date(args.since) if args.since else None,
            until=_parse_date(args.until) if args.until else None,
            min_size_mb=args.min_size,
            max_size_mb=args.max_size,
            limit=args.limit,
            min_duration_sec=args.min_duration,
            max_duration_sec=args.max_duration,
            keywords=args.keyword.split(",") if args.keyword else [],
        )
        await cmd_download(args.channel, filters)


def main_sync() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.tui:
        from tui.app import run_tui

        run_tui()
    else:
        asyncio.run(main())


if __name__ == "__main__":
    main_sync()
