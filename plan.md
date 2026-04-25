# Telegram Media Downloader — 完整計畫

## Context

使用者加入了多個 Telegram channel，需要批次下載其中的影片與照片。
採 MVP 優先策略：先跑通最小可行版本確認 API 可用，再逐步完備功能。

---

## Telegram API Rate Limits

官方未公開具體數字，靠 FloodWaitError 動態控制（社群實測）：

| 操作 | 大概限制 | 觸發後等待 |
|---|---|---|
| 列出 dialogs | ~10 次/分鐘 | 幾秒~幾分鐘 |
| 列舉訊息 | ~100-300 則後觸發 | 5~30 秒 |
| 下載媒體 | 速度被限制，較少觸發 | 少見 |
| 登入嘗試 | 5 次/24小時 | 24 小時封鎖 |

**關鍵規則**：
- FloodWait 的 `error.seconds` 必須完整等完，提早重試會讓等待翻倍
- 訊息間加 sleep(0.5~1s) 可大幅降低觸發機率
- 帳號越新，門檻越低

---

## 其他重要限制

- **Forward Protection**：部分 channel 禁止轉發/儲存，但 MTProto API 仍可下載（UI 層限制）
- **帳號安全**：User API 以你自己帳號操作，過度頻繁可能觸發安全驗證
- **Session 檔**：`*.session` 等同帳號存取金鑰，必須 gitignore
- **並行建議**：最多 3 條並行下載，不建議同時操作多個 channel

---

## 技術選型

| 元件 | 選擇 |
|---|---|
| Telegram 客戶端 | Telethon（最成熟的 Python MTProto 實作） |
| TUI 框架 | Textual（Phase 2 加入） |
| 本地資料庫 | SQLite + aiosqlite（Phase 2 加入） |
| 設定管理 | python-dotenv + .env |

---

## Phase 1 — MVP（先跑通，確認可用）

**目標**：能連線、列出 channel、下載少量媒體，驗證整條技術路線

### 專案結構（MVP）

```
tg_downloader/
├── .env              # api_id, api_hash, phone（gitignore）
├── .env.example      # 範本
├── .gitignore
├── pyproject.toml
├── plan.md           # 本文件
└── main.py           # MVP 全部邏輯
```

### MVP 功能

1. 讀取 `.env` 的 credentials（api_id, api_hash, phone）
2. Telethon 登入：首次互動式輸入 OTP，之後 session 自動保存
3. 列出你加入的所有 channel 名稱 + ID
4. 命令列指定 channel username 或 ID
5. 下載該 channel 最新 N 則訊息中的所有媒體（影片 + 照片）
6. FloodWait 自動重試（等待後繼續）
7. 存到 `./downloads/<channel_name>/`
8. 檔名格式：`{message_id}_{original_filename}` 或 `{message_id}_{date}.mp4`

### MVP 執行方式

```bash
# 列出所有 channel
python main.py --list

# 下載指定 channel 最新 50 則訊息的媒體
python main.py --channel my_channel --limit 50
```

### MVP 驗證標準

- [ ] 能列出 channel 清單
- [ ] 能成功下載至少一個影片檔案
- [ ] FloodWait 時不崩潰，自動等待後繼續
- [ ] 已存在的檔案不重複下載

---

## Phase 2 — 功能完備（MVP 確認可用後）

### 新增功能

- SQLite 追蹤下載狀態（斷點續傳）
- 日期範圍篩選（--since, --until）
- 檔案大小篩選（--min-size, --max-size）
- 並行下載（asyncio.Semaphore，最多 3 條）
- Textual TUI 介面（channel 選擇 → 篩選 → 進度畫面）

### 最終專案結構

```
tg_downloader/
├── .env
├── .env.example
├── .gitignore
├── pyproject.toml
├── plan.md
├── main.py
├── core/
│   ├── client.py      # Telethon 封裝 + FloodWait 重試
│   ├── downloader.py  # 下載佇列、並行控制
│   └── db.py          # SQLite schema + CRUD（aiosqlite）
├── models/
│   └── schemas.py     # Pydantic: FilterOptions, DownloadJob
└── tui/
    ├── app.py
    └── screens/
        ├── login.py
        ├── channel_list.py
        ├── filter.py
        └── download.py
```

### SQLite Schema（Phase 2）

```sql
CREATE TABLE scan_progress (
    channel_id   INTEGER PRIMARY KEY,
    last_msg_id  INTEGER,
    total_found  INTEGER,
    updated_at   TEXT
);

CREATE TABLE download_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER,
    message_id   INTEGER,
    file_name    TEXT,
    file_size    INTEGER,
    media_type   TEXT,      -- 'video' | 'photo' | 'document'
    msg_date     TEXT,
    status       TEXT,      -- 'pending' | 'downloading' | 'done' | 'error'
    local_path   TEXT,
    created_at   TEXT,
    UNIQUE(channel_id, message_id)
);
```

### TUI 流程（Phase 2）

```
啟動
 │
 ├─ 有 session？─ 否 → [登入畫面] 手機號 + OTP
 │               是 ↓
 └──────────────→ [Channel 清單] 已加入的 channel
                      │ 選擇
                  [篩選畫面] 類型 / 日期 / 大小
                      │ 確認
                  [下載畫面] 掃描進度 + 下載進度表格
```
