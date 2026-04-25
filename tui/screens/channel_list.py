"""Screen 1：Channel 選擇清單。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView

from models.schemas import ChannelInfo


class ChannelListScreen(Screen):
    """顯示已加入的 Telegram channel 清單，讓使用者選擇。"""

    BINDINGS = [("escape", "app.pop_screen", "返回")]

    def __init__(self, channels: list[ChannelInfo]) -> None:
        super().__init__()
        self._channels = channels

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        if not self._channels:
            yield Label("[yellow]找不到任何 Channel，請先確認已加入並執行 --list。[/yellow]")
        else:
            items: list[ListItem] = []
            for ch in self._channels:
                display = f"{ch.name}"
                if ch.username:
                    display += f"  {ch.username}"
                display += f"  (ID: {ch.id})"
                items.append(ListItem(Label(display), id=f"ch_{ch.id}"))
            yield ListView(*items, id="channel-list")
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """使用者按 Enter 選擇 channel。"""
        item_id = event.item.id or ""
        if item_id.startswith("ch_"):
            ch_id = int(item_id[3:])
            selected = next((c for c in self._channels if c.id == ch_id), None)
            if selected:
                self.dismiss(selected)
