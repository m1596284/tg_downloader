"""Textual TUI 主體。"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Label

from core.client import fetch_channels, load_config
from models.schemas import ChannelInfo, FilterOptions


class TgDownloaderApp(App):
    """Telegram Media Downloader TUI。"""

    TITLE = "Telegram Media Downloader"
    SUB_TITLE = "Phase 2"
    BINDINGS = [("q", "quit", "離開")]

    CSS = """
    Screen {
        padding: 1 2;
    }
    Label {
        margin: 0 0 1 0;
    }
    #channel-label {
        color: cyan;
        text-style: bold;
        margin-bottom: 1;
    }
    #scan-label {
        color: yellow;
    }
    #stats-label {
        color: green;
        margin: 1 0;
    }
    DataTable {
        height: 1fr;
        margin: 1 0;
    }
    ProgressBar {
        margin: 1 0;
    }
    Button {
        margin: 1 0;
    }
    ListView {
        height: 1fr;
        border: solid green;
    }
    Select {
        margin-bottom: 1;
    }
    Input {
        margin-bottom: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._client = None
        self._channels: list[ChannelInfo] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label("正在連線到 Telegram...", id="loading-label")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._init_client(), exclusive=True)

    async def _init_client(self) -> None:
        """初始化 Telethon client 並載入 channel 清單。"""
        from telethon import TelegramClient

        api_id, api_hash, phone = load_config()
        self._client = TelegramClient("tg_downloader", api_id, api_hash)
        await self._client.connect()

        if not await self._client.is_user_authorized():
            loading = self.query_one("#loading-label", Label)
            loading.update(
                "[yellow]尚未登入，請先在終端機執行 python main.py --list 完成登入。[/yellow]"
            )
            return

        loading = self.query_one("#loading-label", Label)
        loading.update("正在取得 Channel 清單...")

        self._channels = await fetch_channels(self._client)

        loading.update(f"找到 {len(self._channels)} 個 Channel，請選擇。")
        await self._show_channel_list()

    async def _show_channel_list(self) -> None:
        from tui.screens.channel_list import ChannelListScreen

        def on_channel_selected(channel: ChannelInfo | None) -> None:
            if channel is not None:
                self.run_worker(self._show_filter(channel), exclusive=False)

        await self.push_screen(ChannelListScreen(self._channels), on_channel_selected)

    async def _show_filter(self, channel: ChannelInfo) -> None:
        from tui.screens.filter_screen import FilterScreen

        def on_filters_set(filters: FilterOptions | None) -> None:
            if filters is not None:
                self.run_worker(self._show_download(channel, filters), exclusive=False)

        await self.push_screen(FilterScreen(channel), on_filters_set)

    async def _show_download(
        self, channel: ChannelInfo, filters: FilterOptions
    ) -> None:
        from tui.screens.download_screen import DownloadScreen

        def on_download_done(_) -> None:
            self.run_worker(self._show_channel_list(), exclusive=False)

        await self.push_screen(
            DownloadScreen(channel, filters, self._client), on_download_done
        )

    async def on_unmount(self) -> None:
        if self._client and self._client.is_connected():
            await self._client.disconnect()


def run_tui() -> None:
    """啟動 TUI App。"""
    app = TgDownloaderApp()
    app.run()
