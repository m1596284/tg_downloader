# tg-downloader

從你加入的 Telegram channel 批次下載影片與照片的 CLI 工具。

使用 [Telethon](https://github.com/LonamiWebs/Telethon) 透過 MTProto User API 操作，以你自己的帳號身份存取所有已加入的 channel。

---

## 功能

- 列出所有已加入的 channel / group
- 依 channel username 或數字 ID 下載媒體
- 支援影片、照片或全部類型篩選
- 自動處理 Telegram FloodWait 限制（等待後繼續）
- 已存在的檔案自動跳過，不重複下載
- rich 進度條顯示即時下載速度與剩餘時間

---

## 安裝

需要 Python 3.11 以上。

```bash
git clone https://github.com/m1596284/tg_downloader.git
cd tg_downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 設定 Telegram API

1. 前往 [my.telegram.org](https://my.telegram.org) 並登入
2. 點選 **API development tools**
3. 建立一個 App（名稱、平台隨意填）
4. 取得 `App api_id`（數字）與 `App api_hash`（字串）

建立 `.env` 檔案：

```bash
cp .env.example .env
```

編輯 `.env`，填入你的資訊：

```
API_ID=12345678
API_HASH=abc123def456abc123def456abc123de
PHONE=+886912345678
```

> `.env` 和 `*.session` 已在 `.gitignore` 中排除，不會被 commit。

---

## 使用方式

**首次執行**會要求輸入 Telegram 傳送給你的 OTP 驗證碼，之後自動儲存 session，不需重新登入。

### 列出所有 channel

```bash
python main.py --list
```

輸出範例：

```
              已加入的 Channels / Groups
┌─────────────┬──────────────────┬──────────────┐
│ ID          │ 名稱             │ 帳號 / 類型  │
├─────────────┼──────────────────┼──────────────┤
│ 1234567890  │ 我的頻道         │ @mychannel   │
│ 9876543210  │ 私人群組         │ private      │
└─────────────┴──────────────────┴──────────────┘
```

### 下載媒體

```bash
# 下載最近 50 則訊息中的所有媒體（預設）
python main.py --channel mychannel

# 只下載影片，掃描最近 200 則
python main.py --channel mychannel --limit 200 --type video

# 只下載照片
python main.py --channel mychannel --type photo

# 用數字 ID 指定 channel
python main.py --channel 1234567890 --type video
```

檔案會下載到 `./downloads/<channel_name>/`，檔名格式為 `{message_id}_{原始檔名}` 或 `{message_id}_{日期}.mp4`。

---

## 參數說明

| 參數 | 說明 | 預設 |
|---|---|---|
| `--list` | 列出所有已加入的 channel | — |
| `--channel` | 指定下載的 channel（username 或數字 ID） | — |
| `--limit N` | 掃描最近 N 則訊息 | 50 |
| `--type` | `video` / `photo` / `all` | `all` |

---

## Telegram API 限制說明

Telegram 對 MTProto API 有動態 rate limit，透過 `FloodWaitError` 執行。工具會自動處理：

| 操作 | 大概限制 |
|---|---|
| 列出 dialogs | ~10 次/分鐘 |
| 列舉訊息 | ~100-300 則後觸發，等 5~30 秒 |
| 下載媒體 | 相對寬鬆，但速度受限 |

- 遇到限制時，工具會等待指定秒數後自動繼續，不需要手動干預
- 建議 `--limit` 不要一次設太大，分批執行更穩定

---

## 路線圖

- [x] Phase 1：CLI MVP（列出 channel、下載媒體、FloodWait 處理）
- [ ] Phase 2：SQLite 斷點續傳、日期/大小篩選、並行下載
- [ ] Phase 3：Textual TUI 互動介面

---

## 依賴

- [Telethon](https://github.com/LonamiWebs/Telethon) — MTProto 客戶端
- [rich](https://github.com/Textualize/rich) — 終端機進度顯示
- [python-dotenv](https://github.com/theskumar/python-dotenv) — 環境變數管理
