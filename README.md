# TikDown Turbo — Tài Liệu Kỹ Thuật Toàn Diện

> **Phiên bản:** v10.5.0-full-featured  
> **Stack:** Python 3 / Flask · Vanilla JS · HTML5  
> **Cổng mặc định:** `2110`  
> **Phát triển bởi:** EYECORE AI

---

## Mục Lục

1. [Tổng Quan Hệ Thống](#1-tổng-quan-hệ-thống)
2. [Kiến Trúc & Cấu Trúc File](#2-kiến-trúc--cấu-trúc-file)
3. [Cài Đặt & Khởi Chạy](#3-cài-đặt--khởi-chạy)
4. [Cấu Hình Nâng Cao](#4-cấu-hình-nâng-cao)
5. [Hệ Thống Tài Khoản & Phân Quyền](#5-hệ-thống-tài-khoản--phân-quyền)
6. [Engine Tải Video](#6-engine-tải-video)
7. [Xử Lý FFmpeg](#7-xử-lý-ffmpeg)
8. [Hệ Thống Batch (Tải Hàng Loạt)](#8-hệ-thống-batch-tải-hàng-loạt)
9. [Kho Lưu Trữ Người Dùng](#9-kho-lưu-trữ-người-dùng)
10. [Hàng Chờ (Queue Manager)](#10-hàng-chờ-queue-manager)
11. [Background Persist](#11-background-persist)
12. [THUNDERWAVE™ Protocol](#12-thunderwave-protocol)
13. [EYECORE KeepLink™](#13-eyecore-keeplink)
14. [AI Chatbot](#15-ai-chatbot)
15. [Bảo Mật](#16-bảo-mật)
16. [Thống Kê & Monitoring](#17-thống-kê--monitoring)
17. [API Reference Đầy Đủ](#18-api-reference-đầy-đủ)
18. [Giao Diện Frontend](#19-giao-diện-frontend)
19. [Dashboard Admin](#20-dashboard-admin)
20. [Lưu Ý Tương Thích iOS & Safari](#21-lưu-ý-tương-thích-ios--safari)

---

## 1. Tổng Quan Hệ Thống

TikDown Turbo là ứng dụng web tải video TikTok không watermark, tốc độ cao, hỗ trợ xử lý hàng loạt. Server chạy Flask đơn tiến trình, đa luồng, không cần database — tất cả trạng thái được lưu trong memory + JSON files.

### Tính Năng Chính

| Tính năng | Mô tả |
|-----------|-------|
| Tải đơn lẻ | Một URL → xử lý async → SSE stream → tải về |
| Tải hàng loạt | Tối đa 100 URL/batch, song song + ordered delivery |
| Thêm logo | Overlay PNG/JPG lên video, kéo thả vị trí |
| Xóa âm thanh | Tùy chọn tải video không tiếng |
| Kho lưu trữ | 3GB/user, TTL 15 ngày, quản lý theo thư mục |
| Hàng chờ | Queue tuần tự, lưu server-side, resume sau reload |
| Background persist | Tiếp tục xử lý dù browser đóng |
| AI Chatbot | Trợ lý hỗ trợ Claude Haiku (có fallback FAQ) |
| Dashboard Admin | Monitor real-time: CPU/RAM/Network/Downloads |
| Lưu lượng tích lũy | Track tổng Down/Up bền vững qua restart |
| URL Info Cache | Cache 10 phút, giảm gọi API ngoài |
| THUNDERWAVE™ | Parallel byte-range HTTP streaming |
| KeepLink™ | Duy trì kết nối adaptive ping/pong |

---

## 2. Kiến Trúc & Cấu Trúc File

```
tikdown/
├── app.py                  # Server Flask chính (~10.200 dòng)
├── index.html              # Frontend SPA (~10.300 dòng)
├── users.json              # Database tài khoản (auto-tạo)
├── visitors.json           # Log visitor (auto-tạo)
├── traffic_stats.json      # Tổng lưu lượng tích lũy (auto-tạo)
├── requirements.txt        # Phụ thuộc (auto-generate sau update)
├── cookies.json            # TikTok cookies (tuỳ chọn)
├── cookies.txt             # Netscape cookie format (tuỳ chọn)
├── pending_persist/        # Checkpoint background jobs
├── user_storage/           # Kho lưu trữ per-user
│   └── {username}/
│       ├── _meta.json      # Metadata per-file
│       └── *.mp4
├── logs/
│   ├── error.log           # Rotate mỗi giờ, giữ 48h
│   ├── process.log
│   └── access.log
└── image/
    └── 2.ico               # Favicon
```

### Stack Kỹ Thuật

```
Backend:  Flask 3.x · Python 3.11+
Worker:   threading (multi-thread, single process)
Encode:   FFmpeg (auto-detect hw encoder: NVENC / VideoToolbox / AMF / QSV / VAAPI / libx264)
Storage:  JSON files (atomic write với .tmp → replace)
Session:  Flask session (cookie, SHA-256 PBKDF2 password)
Frontend: Vanilla JS (không framework, không build step)
CSS:      Neo-Brutalism Light theme, CSS custom properties
```

---

## 3. Cài Đặt & Khởi Chạy

### Yêu Cầu Hệ Thống

- Python 3.10+
- FFmpeg (bắt buộc cho xử lý video)
- 512MB RAM trống (khuyến nghị 2GB+)
- Hệ điều hành: Windows / Linux / macOS

### Cài Đặt Nhanh

```bash
# 1. Clone / copy file
cd /path/to/tikdown

# 2. Cài thư viện Python
pip install flask flask-cors flask-compress requests httpx yt-dlp psutil

# 3. (Tuỳ chọn) TikTokApi cho fallback
pip install TikTokApi

# 4. Chạy server
python app.py
```

Server tự động:
- Kiểm tra & update thư viện lỗi thời (background thread)
- Phát hiện hardware encoder tốt nhất
- Tạo tài khoản admin mặc định (`admin` / `admin123`)
- Mở terminal dashboard riêng

### Truy Cập

| URL | Mô tả |
|-----|-------|
| `http://localhost:2110` | Giao diện chính |
| `http://{LAN_IP}:2110` | Truy cập LAN |
| `http://localhost:2110/dashboard` | Admin dashboard |

---

## 4. Cấu Hình Nâng Cao

### Biến Môi Trường

| Biến | Mô tả | Mặc định |
|------|-------|---------|
| `TIKTOK_PROXY` | Proxy URL (vd: `http://user:pass@host:port`) | Không |
| `ANTHROPIC_API_KEY` | Key cho AI Chatbot Claude Haiku | Không (dùng FAQ fallback) |

### Cấu Hình Trong Code (`app.py`)

```python
CUSTOM_TMPDIR = r"C:\Users\...\temp"  # "" = auto-detect
# Linux RAM disk: CUSTOM_TMPDIR = "/dev/shm"
# Để trống: tự chọn /dev/shm (Linux) hoặc %TEMP% (Windows)

_GUEST_DAILY_LIMIT = 10   # Lần tải/ngày cho guest
_DEFAULT_QUOTA_BYTES = 3 * 1024**3  # 3GB quota/user
_STORAGE_TTL_DAYS = 15              # File tự xóa sau N ngày
STATUS_INTERVAL = 10                # Giây giữa các lần in stats
PORT = 2110                         # Cổng Flask
```

### Cookie TikTok (Bypass Rate Limit)

Đặt file `cookies.json` hoặc `cookies.txt` (Netscape format) cùng thư mục với `app.py`. Cookie giúp bypass xác thực và tăng rate limit khi tải.

```bash
# Reload cookie không restart server
curl -X POST http://localhost:2110/api/reload_cookies
```

---

## 5. Hệ Thống Tài Khoản & Phân Quyền

### Vai Trò

| Role | Quyền |
|------|-------|
| `guest` | Tải tối đa 10 video/ngày, không lưu kho, không batch |
| `user` | Tải không giới hạn, lưu kho 3GB, batch, hàng chờ |
| `admin` | Tất cả quyền + quản lý users, dashboard, set quota |

### Tài Khoản Mặc Định

```
Username: admin
Password: admin123
```
⚠️ **Đổi mật khẩu ngay sau khi deploy!**

### Password Hashing

- Thuật toán: PBKDF2-HMAC-SHA256, 100.000 iterations
- Salt: 32 bytes random per user
- So sánh: `hmac.compare_digest` (chống timing attack)

### Hạn Chế User (Admin Kiểm Soát)

```json
"restrictions": {
  "no_audio_remove": false,  // Không được xóa âm thanh
  "no_logo": false,          // Không được thêm logo
  "no_batch": false          // Không được tải hàng loạt
}
```

### Guest Daily Limit

- IP-based, reset lúc 00:00 mỗi ngày
- Lưu trong `users.json → guest_downloads`
- Còn `N` lượt hiển thị trong thanh trạng thái

---

## 6. Engine Tải Video

### Nguồn API (Thứ Tự Race)

Hệ thống race **5 nguồn song song**, lấy kết quả nhanh nhất:

| # | Nguồn | Mô tả |
|---|-------|-------|
| 1 | Mobile API (5 endpoints) | TikTok internal API, nhanh nhất |
| 2 | tikwm.com | API công khai, ổn định |
| 3 | ssstik.io | Hỗ trợ video mới, no-watermark |
| 4 | ttdownloader.com | Backup, token-based |
| 5 | snaptik | HD support |
| 6 | yt-dlp | Delayed 4s, fallback mạnh nhất |

### URL Info Cache (v10.5)

```python
_URL_CACHE_TTL = 600   # 10 phút
# Cache hit → trả ngay, KHÔNG gọi API ngoài
# Cache miss → race APIs → lưu vào cache
# Max 500 entries, tự dọn 20% cũ nhất khi đầy
```

**Lợi ích:**
- Batch 100 URL giống nhau: chỉ fetch 1 lần API
- Giảm 80-95% lượng gọi ra ngoài trong trường hợp tải lặp
- Thread-safe, decay tự động

### Session Pool

- 10 `requests.Session` objects dùng round-robin
- Mỗi session có random User-Agent và headers riêng
- Tránh bị rate-limit theo session

### Mobile API Endpoints

```python
MOBILE_API_ENDPOINTS = [
    "https://api16-normal-c-useast1a.tiktokv.com",
    "https://api19-normal-c-useast1a.tiktokv.com",
    "https://api22-normal-c-useast1a.tiktokv.com",
    "https://api-normal-c-alisg.tiktokv.com",
    "https://api21-normal-c-useast1a.tiktokv.com",
]
```

### Parallel Range Download (`_stream_url_to_file`)

1. Probe kích thước + Range support (1 request)
2. Nếu file nhỏ (<512KB) hoặc không hỗ trợ Range → single stream
3. Nếu hỗ trợ Range → chia **N chunks** (adaptive theo hardware tier)
4. Pre-allocate file, mỗi thread write tại offset riêng (no lock needed)
5. Retry 2 lần/chunk nếu lỗi
6. Fallback single-stream nếu chunk fail

| Hardware Tier | Workers | Buffer Size |
|--------------|---------|-------------|
| WEAK (≤2 core) | 3 | 256 KB |
| MEDIUM (3-4 core) | 6 | 512 KB |
| STRONG (≥5 core) | 10 | 1 MB |

### Method Rotation Retry

Khi validate video fail sau download:

```
tikwm → mobile_api → ssstik → ttdownloader → snaptik → ytdlp
```

Tối đa 5 lần rotation per video trong batch.

---

## 7. Xử Lý FFmpeg

### Auto-Detect Hardware Encoder

Thứ tự ưu tiên (10-50x nhanh hơn software):

| Encoder | Platform | Ghi chú |
|---------|----------|---------|
| `h264_nvenc` | NVIDIA GPU | preset p1, low-latency |
| `h264_videotoolbox` | macOS Apple Silicon/Intel | realtime=1 |
| `h264_amf` | AMD GPU (Windows) | quality speed |
| `h264_qsv` | Intel Quick Sync | look_ahead=0 |
| `h264_vaapi` | Linux AMD/Intel | /dev/dri/renderD128 |
| `libx264` | CPU fallback | ultrafast, crf=23 |

### Pipeline Xử Lý Video (`_process_video_file`)

```
Raw file
   │
   ├─ Probe (_probe_once): width, height, fps, has_audio, duration
   │
   ├─ [Nếu cần] Sanitize: codec=none, pix_fmt lạ
   │
   ├─ [Tuỳ chọn] Upscale → 720p (lanczos, nếu video < 720p)
   │
   ├─ [Tuỳ chọn] Xóa audio (5 strategies, ưu tiên stream copy)
   │
   ├─ [Tuỳ chọn] Overlay logo (filter_complex, uniform scale)
   │
   ├─ Adaptive CRF (0.0 tĩnh → CRF 32; 1.0 action → CRF 23)
   │
   ├─ _ensure_valid_mp4: ffprobe check → re-encode nếu fail
   │
   └─ Output: H264 + AAC, faststart, yuv420p
```

### Validate Video (3 lớp)

1. **ffprobe** check codec, width, height
2. **Size check**: output ≥ 10KB và ≥ 25% input
3. **Duration check**: không truncate > 75% nếu input > 20s

### Audio Merge API

**POST `/api/audio/merge_video`** (multipart)

- `video`: file video (mp4/mov/avi/mkv/webm/flv/ts)
- `audio`: file audio (mp3/wav/ogg/flac/m4a/aac/opus)
- Server tự loop audio nếu video dài hơn
- Output: mp4 với audio gốc bị xóa hoàn toàn, audio mới được encode AAC 192kbps

---

## 8. Hệ Thống Batch (Tải Hàng Loạt)

### Luồng Hoạt Động

```
POST /api/batch_start
     │
     ├─ Tạo BatchJob object
     ├─ Lưu vào BATCH_STORE
     └─ job.start() → background thread

GET /api/batch_stream/{batch_id}   ← SSE stream
     │
     ├─ events: progress, result, result_retry, heartbeat, batch_done
     └─ Fallback polling: GET /api/batch_status/{batch_id}?since=N
```

### Class BatchJob

```python
class BatchJob:
    MAX_DL_RETRIES     = 3    # Lần thử download ban đầu
    MAX_ROTATION_RETRY = 5    # Rotation khi validate fail

    # Pipeline song song:
    # Phase 1: N workers download đồng thời
    # Phase 2: retry các item fail (nếu có)
```

### Pipeline Song Song

- Download N video đồng thời (adaptive workers theo hardware tier)
- Kết quả được **deliver theo thứ tự** (ordered SSE events)
- Phase 2 tự động retry các video fail với API rotation

### iOS Polling Mode

iOS Safari không ổn định với SSE → tự động switch sang polling:

```javascript
if (_isIOS) {
    // Poll GET /api/batch_status/{id}?since={cursor}
    // Interval: 100ms (active) / 50ms (done)
    // Restart khi tab resume sau background freeze
}
```

### Download File trên iOS (v10.5)

Thay vì `window.open/_blank` (chỉ play video):

```javascript
fetch(dlUrl) → blob → URL.createObjectURL → <a download> → click
// iOS Safari 13+ lưu vào app Files tự động
// Fallback: window.open nếu fetch fail
```

---

## 9. Kho Lưu Trữ Người Dùng

### Cấu Trúc

```
user_storage/
└── {username}/
    ├── _meta.json        # Metadata tất cả files
    └── tikdown_xxx.mp4   # Video files
```

### Metadata Per File (`_meta.json`)

```json
{
  "tikdown_abc123.mp4": {
    "title": "TikTok Video Title",
    "url": "https://tiktok.com/...",
    "size": 12345678,
    "saved_at": "2025-05-16 10:30:00",
    "saved_at_ts": 1747381800.0,
    "expires_at": "2025-05-31 10:30:00",
    "expires_ts": 1748985800.0,
    "group_id": "batch_abc",
    "group_name": "Batch 16/05",
    "folder_id": "folder_xyz",
    "status": "ready"
  }
}
```

### Quota & TTL

| Role | Quota | TTL |
|------|-------|-----|
| `user` | 3 GB | 15 ngày |
| `admin` | 100 GB (unlimited thực tế) | 15 ngày |

- Auto-cleanup chạy mỗi giờ (background daemon)
- Ghi `_meta.json` atomic (`.tmp` → `replace`)

### Chế Độ Lưu

| Mode | `download_direct` | `save_to_storage` | Kết quả |
|------|:---:|:---:|---------|
| Tải thẳng | ✅ | ❌ | File về máy ngay |
| Lưu kho | ❌ | ✅ | Lưu server, tải sau |
| Cả hai | ✅ | ✅ | Về máy + lưu server |

---

## 10. Hàng Chờ (Queue Manager)

Queue Manager là hệ thống JS client-side kết hợp server-side persistence.

### Client-Side (JavaScript)

```javascript
// Thêm item
QM.addItem(urls[], name)

// Chạy tuần tự
QM.start()   // → gọi startDownload() cho từng item

// Tạm dừng / tiếp tục
QM.pause() / QM.resume()

// Đếm giờ giữa items
// Delay mặc định: 3 giây
```

### Server-Side Queue API

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/api/queue/save` | POST | Lưu toàn bộ queue lên server |
| `/api/queue/load` | GET | Lấy lại queue sau reload |
| `/api/queue/clear` | POST | Xóa queue server |
| `/api/queue/run_all` | POST | Server tự xử lý queue dù browser đóng |

---

## 11. Background Persist

Khi browser đóng giữa chừng, server tiếp tục xử lý:

```
1. Trước khi tải: POST /api/persist/submit (checkpoint URLs)
2. browser.beforeunload → sendBeacon /api/persist/mark_done (nếu xong)
                       → sendBeacon /api/queue/run_all (nếu còn pending)
3. Khi server restart: GET /api/persist/resume → tiếp tục các job dở
```

### API Persist

| Endpoint | Mô tả |
|----------|-------|
| `POST /api/persist/submit` | Lưu checkpoint JSON vào `pending_persist/` |
| `POST /api/persist/mark_done` | Đánh dấu checkpoint hoàn thành |
| `POST /api/persist/resume` | Khởi động lại các job chưa done |
| `GET /api/persist/status` | Danh sách pending jobs |

---

## 12. THUNDERWAVE™ Protocol

EYECORE Ultra-Fast Parallel Delivery — tăng tốc tải video bằng byte-range parallel streaming.

### Cơ Chế

```
Client request manifest
       │
       ▼
GET /api/thunderwave/manifest/{task_id}
       │
       ▼ JSON: { chunks: [{start, end, url}], workers: N, file_size, ... }
       │
       ▼
Client mở N fetch song song (mỗi fetch 1 chunk)
       │
       ▼
In-browser reassembly → Blob → Download
```

### Manifest Response

```json
{
  "protocol": "THUNDERWAVE/3.0",
  "file_size": 52428800,
  "filename": "tikdown_xxx.mp4",
  "workers": 10,
  "chunk_size": 5242880,
  "chunks": [
    {"index": 0, "start": 0, "end": 5242879, "url": "/api/get_result/{id}"},
    ...
  ]
}
```

### Storage THUNDERWAVE

`GET /api/thunderwave/manifest/storage/{filename}` — tương tự nhưng cho file trong kho.

---

## 13. EYECORE KeepLink™

Hệ thống duy trì kết nối client-server liên tục.

### Endpoints

| Endpoint | Mô tả |
|----------|-------|
| `GET /api/keeplink/ping` | Ping kiểm tra liveness |
| `GET /api/keeplink/stream` | SSE stream liên tục |

### Ping Response

```json
{
  "pong": true,
  "ts": 1747381800000,
  "latency_hint": 12,
  "server_load": 23
}
```

### Adaptive Reconnect

- Disconnect → backoff: 1s → 2s → 4s → max 30s
- Tab visible lại → reconnect ngay sau 2s debounce

---

## 14. AI Chatbot

### Endpoint

**POST `/api/chat`**

```json
// Request
{
  "messages": [
    {"role": "user", "content": "Cách tải video?"}
  ]
}

// Response
{
  "reply": "..."
}
```

### Model

- Sử dụng **Claude Haiku** (`claude-haiku-4-5-20251001`)
- Tối đa 12 tin nhắn gần nhất mỗi request
- `max_tokens`: 400

### Fallback (Không Có API Key)

Semantic FAQ matching với normalization diacritics — trả lời cố định cho ~8 chủ đề:
- Hướng dẫn sử dụng, thư mục kho, thêm logo, hàng chờ, xử lý lỗi, dark mode, AI Eye-Protection, chất lượng video.

---

## 15. Bảo Mật

### BehavioralGuard (AI Bot Detection)

Phát hiện và block bot/scraper dựa trên hành vi:

```python
# Nguyên tắc: User đăng nhập → KHÔNG BAO GIỜ bị block
# Chỉ tính điểm cho anonymous request

Signals:
  +40: User-Agent rõ ràng là bot (python-requests, curl, scrapy...)
  +20: Request rate > 120/60s
  +15: Download > 5 lần/60s (anonymous)

Ngưỡng:
  score ≥ 150 → soft_block 30 phút
  score ≥ 400 → hard_block 1 giờ
  score ≥ 800 → permanent block
```

### Session Security

```python
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_NAME']     = 'tikdown_session'
# Lifetime: 30 ngày
```

### CORS

Hỗ trợ `*` origin với `supports_credentials=True`.

### Admin Unblock

```bash
curl -X POST http://localhost:2110/api/security/unblock \
  -H "Content-Type: application/json" \
  -d '{"ip": "1.2.3.4"}'
```

---

## 16. Thống Kê & Monitoring

### Terminal Stats (In Mỗi 10 Giây)

```
[10:30:45] ⚡STATS  CPU: 23.1% │ RAM:2.1/8.0GB(26%) │ 🌐↑1.2MB/s ↓4.5MB/s │ Tasks:2 Batch:1
```

### Tổng Lưu Lượng (v10.5 — Persistent)

Lưu vào `traffic_stats.json`, tích lũy qua mọi lần restart:

```json
{
  "total_sent_bytes": 10737418240,
  "total_recv_bytes": 53687091200,
  "session_sent_bytes": 1073741824,
  "session_recv_bytes": 5368709120,
  "last_updated": "2025-05-16 10:30:00"
}
```

**API:** `GET /api/traffic_stats` → JSON đầy đủ + formatted strings

### Visitor Tracking

- Lưu `visitors.json`: IP, device, OS, browser, geo (ip-api.com async)
- Visit history: 50 lượt gần nhất/visitor
- Không track localhost/127.0.0.1

### Log Files

| File | Nội dung | Rotate |
|------|----------|--------|
| `logs/error.log` | Lỗi + traceback | Mỗi giờ, giữ 48h |
| `logs/process.log` | Tiến trình download/encode | Mỗi giờ, giữ 48h |
| `logs/access.log` | HTTP access + session | Mỗi giờ, giữ 48h |

---

## 17. API Reference Đầy Đủ

### Trang Web

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/` | GET | — | Trang chủ (index.html) |
| `/dashboard` | GET | Admin | Dashboard admin |

### Authentication

| Endpoint | Method | Auth | Body / Params |
|----------|--------|------|---------------|
| `/api/auth/register` | POST | — | `{username, email, password}` |
| `/api/auth/login` | POST | — | `{username, password}` |
| `/api/auth/logout` | POST | Logged | — |
| `/api/auth/me` | GET | — | Trả thông tin user hiện tại |
| `/api/auth/change_password` | POST | Logged | `{old_password, new_password}` |

### Download

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/download_async` | POST | — | Tạo task tải async, trả `task_id` |
| `/api/stream/{task_id}` | GET | — | SSE: progress/done/error |
| `/api/get_result/{task_id}` | GET | — | Tải file kết quả (Range support) |
| `/api/task_status/{task_id}` | GET | — | Trạng thái task (polling fallback) |
| `/api/cancel_task/{task_id}` | POST | — | Hủy task |
| `/api/cancel_all` | POST | — | Hủy tất cả task + batch |
| `/api/check_urls` | POST | — | Kiểm tra & lấy info nhiều URL |
| `/api/download_video` | POST | — | Download đồng bộ (legacy) |
| `/api/get_video_info` | POST | — | Chỉ lấy metadata (không tải) |

### Batch

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/batch_start` | POST | — | Khởi tạo batch job |
| `/api/batch_stream/{id}` | GET | — | SSE stream kết quả batch |
| `/api/batch_status/{id}` | GET | — | Polling fallback cho iOS/Safari |
| `/api/batch_cancel/{id}` | POST | — | Hủy batch |
| `/api/batch_item_msgs/{id}/{index}` | GET | — | Progress messages của 1 item |

**Body `batch_start`:**
```json
{
  "urls": ["https://tiktok.com/..."],
  "audio": true,
  "logo_enabled": false,
  "logo_base64": "data:image/png;base64,...",
  "logo_x": 10, "logo_y": 10,
  "logo_width": 100, "logo_height": 100,
  "logo_original_aspect": 1.0,
  "download_direct": true,
  "save_to_storage": false,
  "group_name": "Batch 16/05",
  "folder_id": "folder_xyz"
}
```

### Kho Lưu Trữ

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/storage/info` | GET | Logged | Quota + used bytes |
| `/api/storage/list` | GET | Logged | Danh sách files |
| `/api/storage/download/{filename}` | GET | Logged | Tải file từ kho |
| `/api/storage/delete` | POST | Logged | Xóa files: `{filenames: [...]}` |
| `/api/storage/download_zip` | POST | Logged | Tải ZIP nhiều files |
| `/api/storage/clear_all` | POST | Logged | Xóa toàn bộ kho |
| `/api/storage/download_group` | POST | Logged | Tải ZIP theo group_id |

### Queue & Persist

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/queue/save` | POST | Logged | Lưu queue |
| `/api/queue/load` | GET | Logged | Load queue đã lưu |
| `/api/queue/clear` | POST | Logged | Xóa queue |
| `/api/queue/run_all` | POST | Logged | Server xử lý queue độc lập |
| `/api/persist/submit` | POST | Logged | Checkpoint URLs |
| `/api/persist/mark_done` | POST | Logged | Đánh dấu done |
| `/api/persist/resume` | POST | Logged | Resume pending jobs |
| `/api/persist/status` | GET | Logged | Danh sách pending |

### Admin

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/admin/dashboard_stats` | GET | Admin | Tất cả stats |
| `/api/admin/dashboard_stream` | GET | Admin | SSE real-time stats |
| `/api/admin/users` | GET | Admin | Danh sách users |
| `/api/admin/lock_user` | POST | Admin | Khoá/mở tài khoản |
| `/api/admin/set_restrictions` | POST | Admin | Đặt hạn chế user |
| `/api/admin/change_user_password` | POST | Admin | Đổi mật khẩu user |
| `/api/admin/delete_user` | POST | Admin | Xóa tài khoản |
| `/api/admin/promote_user` | POST | Admin | Nâng/hạ role |
| `/api/admin/set_quota` | POST | Admin | Đặt quota storage |
| `/api/admin/storage_overview` | GET | Admin | Tổng quan storage |

### Hệ Thống

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/health` | GET | — | Health check |
| `/api/traffic_stats` | GET | — | Tổng lưu lượng Down/Up |
| `/api/visitors` | GET | — | Danh sách visitor |
| `/api/link_stats` | GET | — | Thống kê link đã tìm |
| `/api/client_info` | GET | — | Info thiết bị client |
| `/api/session_exit` | POST | — | Ghi log session end |
| `/api/server_reload` | POST | — | Tín hiệu reload trang |
| `/api/reload_stream` | GET | — | SSE reload notification |
| `/api/logs` | GET | Admin | Đọc log file |
| `/api/cleanup` | POST | — | Dọn tmp files cũ |
| `/api/cleanup_ramdisk` | POST | — | Dọn RAM disk |
| `/api/reload_cookies` | POST | — | Load lại cookies |
| `/api/set_cookies` | POST | — | Set cookies qua API |
| `/api/speedtest_payload` | GET | — | Payload test tốc độ (512KB/1MB) |
| `/api/security/status` | GET | Admin | Danh sách IPs bị block |
| `/api/security/unblock` | POST | Admin | Bỏ block IP |
| `/api/update` | POST | — | Trigger update thư viện |

### THUNDERWAVE™

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/thunderwave/manifest/{task_id}` | GET | — | Manifest parallel download |
| `/api/thunderwave/manifest/storage/{filename}` | GET | Logged | Manifest storage file |

### KeepLink™

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/keeplink/ping` | GET/POST | — | Liveness check |
| `/api/keeplink/stream` | GET | — | SSE keep-alive stream |

### Realtime & WebRTC

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/realtime/subscribe` | GET | — | SSE realtime events |
| `/api/webrtc/offer` | POST | — | WebRTC SDP offer |
| `/api/webrtc/ice` | POST | — | ICE candidate exchange |
| `/api/webrtc/status/{session_id}` | GET | — | WebRTC session status |

### Audio

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/audio/merge_video` | POST | — | Ghép audio mới vào video (multipart) |

### AI

| Endpoint | Method | Auth | Mô tả |
|----------|--------|------|-------|
| `/api/chat` | POST | — | AI chatbot (Claude Haiku / FAQ fallback) |

---

## 18. Giao Diện Frontend

### Tabs Chính

| Tab | ID | Mô tả |
|-----|-----|-------|
| Nhập Link | `input` | Textarea nhập URL, thống kê, tìm kiếm |
| Tiến Trình | `progress` | Real-time progress bar, danh sách video |
| Logo | `logo` | Upload logo, canvas preview 270×480, tọa độ |
| Kho Lưu Trữ | `storage` | Quản lý file, thư mục, tải ZIP |
| Lịch Sử | `history` | Lịch sử URL theo ngày |
| Hàng Chờ | `queue` | Queue manager, drag-drop sắp xếp |

### Chế Độ Lưu

```
[Tải Thẳng] [Lưu Kho] [Cả Hai]
            └── Bắt buộc chọn thư mục khi "Lưu Kho" hoặc "Cả Hai"
```

### AI Eye-Protection Mode

- Tự động bật dark mode sau 18:00 (dựa trên giờ máy client)
- Nút toggle thủ công góc trên phải
- Giảm độ sáng + đổi palette màu nền

### Speed Test Widget

- Đo ping và download speed thực (512KB payload trên mobile, 1MB trên desktop)
- Cập nhật mỗi 20 giây + sau mỗi lần tải video
- Callback `window._reportDownloadSpeed(bytes, sec)` từ triggerDownload

### Service Worker

- Cache assets, offline support cơ bản
- Monitor batch job khi tab ẩn → push notification khi xong
- Cleanup blobs URL khi trang đóng

### ServiceWorker Endpoints

- `GET /sw.js` — Service Worker script (Flask serve)

---

## 19. Dashboard Admin

### Sections

| Section | Nội dung |
|---------|---------|
| Tổng Quan | Visitor độc nhất, tài khoản, storage dùng, uptime, CPU |
| Hardware | CPU per-core, RAM, Swap, Disk partitions |
| Mạng & Lưu Lượng | **Traffic tích lũy all-time**, interfaces, packets |
| Tải Xuống | Guest today, active tasks/batches |
| Thiết Bị | Bar chart: device / browser / OS / quốc gia |
| Storage | Bảng: user, used, quota, files |
| Tài Khoản | Bảng users, lock/unlock inline |
| Visitor | 20 lượt gần nhất: IP, device, quốc gia, thời gian |

### Real-time Stream

`GET /api/admin/dashboard_stream` — SSE, cập nhật stats mỗi 5 giây không cần reload.

### Traffic Panel (v10.5)

```
📊 LƯU LƯỢNG TÍCH LŨY (bền vững qua restart)
┌─────────────────┬─────────────────┐
│ ↓ 50.2 GB       │ ↑ 10.0 GB       │
│ Tổng tải về     │ Tổng gửi đi     │
│   (all-time)    │   (all-time)    │
├─────────────────┼─────────────────┤
│ ↓ 5.0 GB        │ ↑ 1.0 GB        │
│ Nhận phiên này  │ Gửi phiên này   │
└─────────────────┴─────────────────┘
```

---

## 20. Lưu Ý Tương Thích iOS & Safari

### Vấn Đề Và Giải Pháp

| Vấn đề | Nguyên nhân | Fix |
|--------|-------------|-----|
| `Can't find variable: _resolvePoller` | `const` trong Promise executor không visible ra ngoài scope trong JSCore (iOS) | Khai báo `let _resolvePoller = null` TRƯỚC `await new Promise()` |
| Video mở trong browser thay vì tải | `window.open/_blank` → Safari play inline | `fetch → blob → URL.createObjectURL → <a download>` |
| SSE không ổn định (background tab) | iOS suspend JS khi tab ẩn | Auto-switch sang polling; restart poll khi tab visible lại |
| Content-Disposition bị ignore | Safari cần MIME cụ thể | `Content-Type: video/mp4; codecs="avc1.42E01E, mp4a.40.2"` cho iOS |
| Range request probe | Safari gửi `bytes=0-1` trước khi download | Fast-path: trả ngay ≤2 bytes, không mmap |

### Yêu Cầu Phiên Bản

- **iOS 13+** — hỗ trợ `download` attribute trên blob URLs
- **iOS 15+** — hỗ trợ đầy đủ Web Share API (tùy chọn)
- **Safari 14+** (macOS) — fetch → blob download hoạt động chuẩn

---

## Phụ Lục: SEO Meta Tags (v10.5)

```html
<!-- Primary -->
<title>TikDown Turbo — Tải Video TikTok Không Watermark Miễn Phí | HD + Logo</title>
<meta name="description" content="...">
<meta name="keywords" content="...">
<meta name="robots" content="index, follow, max-snippet:-1, ...">
<link rel="canonical" href="https://tikdown.eyecore.cloud/">

<!-- Open Graph -->
<meta property="og:type" content="website">
<meta property="og:title" content="...">
<meta property="og:description" content="...">
<meta property="og:image" content="...">

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">

<!-- JSON-LD Schema -->
<script type="application/ld+json">
{
  "@type": "WebApplication",
  "applicationCategory": "MultimediaApplication",
  "offers": { "@type": "Offer", "price": "0" },
  "featureList": [...]
}
</script>
```

> ⚠️ Cập nhật `canonical` và `og:url` nếu deploy trên domain khác `tikdown.eyecore.cloud`.

---

*Tài liệu này được tạo tự động từ codebase TikDown Turbo v10.5.0 — Cập nhật: 2025-05-16*
