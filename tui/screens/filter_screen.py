"""Screen 2：篩選條件設定。"""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select

from models.schemas import ChannelInfo, FilterOptions


class FilterScreen(Screen):
    """讓使用者設定下載篩選條件。"""

    BINDINGS = [("escape", "app.pop_screen", "返回")]

    def __init__(self, channel: ChannelInfo) -> None:
        super().__init__()
        self._channel = channel

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(
            f"[bold cyan]Channel：{self._channel.name}[/bold cyan]",
            id="channel-label",
        )
        yield Label("媒體類型")
        yield Select(
            [("全部", "all"), ("影片", "video"), ("照片", "photo")],
            value="all",
            id="media-type",
        )
        yield Label("掃描筆數（limit）")
        yield Input(value="50", placeholder="50", id="limit")
        yield Label("起始日期 since（YYYY-MM-DD，可留空）")
        yield Input(placeholder="2024-01-01", id="since")
        yield Label("結束日期 until（YYYY-MM-DD，可留空）")
        yield Input(placeholder="2024-12-31", id="until")
        yield Label("最小大小 MB（可留空）")
        yield Input(placeholder="10", id="min-size")
        yield Label("最大大小 MB（可留空）")
        yield Input(placeholder="500", id="max-size")
        yield Label("最短時長（秒，可留空，只對影片有效）")
        yield Input(placeholder="60", id="min-duration")
        yield Label("最長時長（秒，可留空，只對影片有效）")
        yield Input(placeholder="3600", id="max-duration")
        yield Label("關鍵字（可留空，多個用逗號分隔，OR 邏輯，大小寫不敏感）")
        yield Input(placeholder="教學,tutorial", id="keyword")
        yield Button("開始下載", variant="primary", id="start")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "start":
            return

        # 解析 limit
        limit_input = self.query_one("#limit", Input).value.strip()
        try:
            limit = int(limit_input) if limit_input else 50
        except ValueError:
            self.notify("掃描筆數必須是整數", severity="error")
            return

        # 解析日期
        since_str = self.query_one("#since", Input).value.strip()
        until_str = self.query_one("#until", Input).value.strip()
        try:
            since = (
                datetime.strptime(since_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if since_str
                else None
            )
            until = (
                datetime.strptime(until_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if until_str
                else None
            )
        except ValueError:
            self.notify("日期格式錯誤，請使用 YYYY-MM-DD", severity="error")
            return

        # 解析大小
        min_str = self.query_one("#min-size", Input).value.strip()
        max_str = self.query_one("#max-size", Input).value.strip()
        try:
            min_size = float(min_str) if min_str else None
            max_size = float(max_str) if max_str else None
        except ValueError:
            self.notify("大小必須是數字（MB）", severity="error")
            return

        # 解析時長
        min_dur_str = self.query_one("#min-duration", Input).value.strip()
        max_dur_str = self.query_one("#max-duration", Input).value.strip()
        try:
            min_duration = float(min_dur_str) if min_dur_str else None
            max_duration = float(max_dur_str) if max_dur_str else None
        except ValueError:
            self.notify("時長必須是數字（秒）", severity="error")
            return

        # 解析關鍵字
        keyword_str = self.query_one("#keyword", Input).value.strip()
        keywords = (
            [kw.strip() for kw in keyword_str.split(",") if kw.strip()]
            if keyword_str
            else []
        )

        # 取得媒體類型
        media_type_select = self.query_one("#media-type", Select)
        media_type = str(media_type_select.value) if media_type_select.value else "all"

        filters = FilterOptions(
            media_type=media_type,  # type: ignore[arg-type]
            since=since,
            until=until,
            min_size_mb=min_size,
            max_size_mb=max_size,
            limit=limit,
            min_duration_sec=min_duration,
            max_duration_sec=max_duration,
            keywords=keywords,
        )
        self.dismiss(filters)
