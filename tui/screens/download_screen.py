"""Screen 3：下載進度畫面。"""

from __future__ import annotations

import time
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Label, ProgressBar

from models.schemas import ChannelInfo, DownloadJob, FilterOptions

DOWNLOADS_DIR = Path("downloads")
DB_PATH = Path("tg_downloader.db")

# UI 進度更新節流（秒）
_PROGRESS_THROTTLE = 0.5


def _fmt_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "—"
    mb = size_bytes / 1024 / 1024
    return f"{mb:.1f} MB"


def _fmt_eta(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"00:{s:02d}"
    if s < 3600:
        return f"{s // 60:02d}:{s % 60:02d}"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


class DownloadScreen(Screen):
    """掃描 + 下載進度畫面。"""

    BINDINGS = [("escape", "dismiss_screen", "返回")]

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    def __init__(
        self,
        channel: ChannelInfo,
        filters: FilterOptions,
        client,
    ) -> None:
        super().__init__()
        self._channel = channel
        self._filters = filters
        self._client = client
        self._jobs: list[DownloadJob] = []
        self._done_count = 0
        self._total_bytes = 0
        # 每個 job 的開始時間與上次 UI 更新時間（key = job.id）
        self._job_start: dict[int | None, float] = {}
        self._last_ui_update: dict[int | None, float] = {}

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(
            f"[bold cyan]{self._channel.name}[/bold cyan] 下載進度",
            id="title-label",
        )
        yield Label("掃描訊息中...", id="scan-label")
        yield ProgressBar(total=self._filters.limit, id="scan-bar")
        yield Label("", id="stats-label")
        yield DataTable(id="job-table")
        yield Button("完成後返回", variant="success", id="back", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#job-table", DataTable)
        table.add_column("檔名", key="filename")
        table.add_column("大小", key="size")
        table.add_column("狀態", key="status")
        self.run_worker(self._run_all(), exclusive=True)

    # ------------------------------------------------------------------
    # 主流程（在 worker 中執行）
    # ------------------------------------------------------------------

    async def _run_all(self) -> None:
        from core.downloader import download_all, scan_messages

        # — 掃描階段 —
        scan_label = self.query_one("#scan-label", Label)
        scan_bar = self.query_one("#scan-bar", ProgressBar)
        scan_label.update("掃描訊息中...")

        entity = await self._client.get_entity(self._channel.id)

        def on_scan_progress(count: int) -> None:
            scan_bar.advance(1)
            scan_label.update(f"已掃描 {count} 則訊息...")

        safe_name = "".join(
            c if c.isalnum() or c in "-_." else "_" for c in self._channel.name
        )
        dest_dir = DOWNLOADS_DIR / safe_name

        self._jobs = await scan_messages(
            self._client,
            entity,
            self._filters,
            DB_PATH,
            on_progress=on_scan_progress,
        )

        scan_label.update(f"掃描完成，找到 {len(self._jobs)} 個待下載檔案")

        if not self._jobs:
            self._finish()
            return

        # 初始化表格列（全部先顯示 pending）
        table = self.query_one("#job-table", DataTable)
        for job in self._jobs:
            table.add_row(
                job.file_name[:50],
                _fmt_size(job.file_size),
                "pending",
                key=f"job_{job.id}",
            )

        self._update_stats()

        # — 下載階段 —
        def on_file_start(job: DownloadJob) -> None:
            self._job_start[job.id] = time.monotonic()
            self._last_ui_update[job.id] = 0.0
            self._update_row(job, "等待中...")

        def on_progress_cb(idx: int, received: int, total: int) -> None:
            if idx >= len(self._jobs):
                return
            job = self._jobs[idx]
            now = time.monotonic()
            # 節流：每 0.5 秒更新一次 UI
            if now - self._last_ui_update.get(job.id, 0) < _PROGRESS_THROTTLE:
                return
            self._last_ui_update[job.id] = now

            elapsed = now - self._job_start.get(job.id, now)
            speed = received / elapsed if elapsed > 0 else 0  # bytes/sec
            pct = received / total * 100 if total > 0 else 0
            eta = (total - received) / speed if speed > 0 else 0

            recv_mb = received / 1024 / 1024
            total_mb = total / 1024 / 1024
            speed_mb = speed / 1024 / 1024
            self._update_row(
                job,
                f"{pct:.0f}% {recv_mb:.1f}/{total_mb:.1f}MB "
                f"{speed_mb:.1f}MB/s ETA {_fmt_eta(eta)}",
            )

        def on_file_done(job: DownloadJob) -> None:
            self._done_count += 1
            if job.file_size:
                self._total_bytes += job.file_size
            status = "✓ 完成" if job.status == "done" else "✗ 錯誤"
            self._update_row(job, status)
            self._update_stats()

        await download_all(
            self._client,
            self._jobs,
            dest_dir,
            DB_PATH,
            entity=entity,
            on_file_start=on_file_start,
            on_file_done=on_file_done,
            on_progress=on_progress_cb,
        )

        self._finish()

    def _update_row(self, job: DownloadJob, status: str) -> None:
        table = self.query_one("#job-table", DataTable)
        row_key = f"job_{job.id}"
        try:
            table.update_cell(row_key, "status", status)
        except Exception:
            pass

    def _update_stats(self) -> None:
        total = len(self._jobs)
        done = self._done_count
        mb = self._total_bytes / 1024 / 1024
        stats = self.query_one("#stats-label", Label)
        stats.update(f"完成 {done} / 總計 {total} | 已下載 {mb:.1f} MB")

    def _finish(self) -> None:
        self._update_stats()
        back_btn = self.query_one("#back", Button)
        back_btn.disabled = False

    # ------------------------------------------------------------------
    # 按鈕
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.dismiss(None)
