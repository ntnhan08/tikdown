# EYECORE TikTok Downloader — Tài liệu Kỹ thuật Siêu Chi tiết

> **Phiên bản**: v10.4.0-TURBO-FULL  
> **Stack**: Python 3.10+ / Flask / FFmpeg / Vanilla JS  
> **Cổng mặc định**: `2110`  
> **Giấy phép**: Nội bộ — EYECORE Team

---

## Mục lục

1. [Tổng quan hệ thống](#1-tổng-quan-hệ-thống)
2. [Kiến trúc tổng thể](#2-kiến-trúc-tổng-thể)
3. [Cài đặt & Khởi chạy](#3-cài-đặt--khởi-chạy)
4. [Cấu hình hệ thống](#4-cấu-hình-hệ-thống)
5. [Pipeline tải video](#5-pipeline-tải-video)
6. [Xử lý FFmpeg & Video](#6-xử-lý-ffmpeg--video)
7. [Giao thức truyền tải THUNDERWAVE™](#7-giao-thức-truyền-tải-thunderwave)
8. [EYECORE KeepLink™ — Duy trì kết nối](#8-eyecore-keeplink--duy-trì-kết-nối)
9. [EYECORE Realtime Push Channel™](#9-eyecore-realtime-push-channel)
10. [WebRTC Bridge v1.0](#10-webrtc-bridge-v10)
11. [Hệ thống xác thực & phân quyền](#11-hệ-thống-xác-thực--phân-quyền)
12. [Kho lưu trữ (Storage)](#12-kho-lưu-trữ-storage)
13. [Hàng chờ tải (Queue)](#13-hàng-chờ-tải-queue)
14. [Tải đồng loạt (Batch)](#14-tải-đồng-loạt-batch)
15. [AI Chatbot (EYECORE AI)](#15-ai-chatbot-eyecore-ai)
16. [Admin Dashboard](#16-admin-dashboard)
17. [Bảo mật hệ thống](#17-bảo-mật-hệ-thống)
18. [API Reference đầy đủ](#18-api-reference-đầy-đủ)
19. [Cấu trúc thư mục](#19-cấu-trúc-thư-mục)
20. [Troubleshooting](#20-troubleshooting)
21. [Changelog](#21-changelog)

---

## 1. Tổng quan hệ thống

**EYECORE TikTok Downloader** là ứng dụng web tải video TikTok không watermark, chạy hoàn toàn trên máy chủ nội bộ (localhost/LAN). Được xây dựng với mục tiêu:

- **Tốc độ**: Tải song song 4–8 chiến lược đồng thời, truyền file qua THUNDERWAVE™ Protocol
- **Độ tin cậy**: Retry tự động 4 lần, 4 chiến lược xử lý FFmpeg khác nhau, validation đa lớp
- **Thực thời**: SSE (Server-Sent Events) + EYECORE RTPC™ + WebRTC Bridge — không cần F5
- **Đa thiết bị**: Tối ưu cho iOS, Android, Desktop (Chrome/Firefox/Safari)
- **Bảo mật**: Session-based auth, rate limiting, behavioral guard, brute-force protection

### Tính năng chính

| Tính năng | Mô tả |
|-----------|-------|
| Tải đơn | 1 URL → xử lý → tải về ngay |
| Tải đồng loạt | Tối đa 100 URL/batch, song song |
| Hàng chờ | Lưu batch, chạy tuần tự theo lịch |
| Kho lưu trữ | Lưu video server 15 ngày, quota per-user |
| Thư mục kho | Phân loại video theo thư mục (client-side + server-side) |
| Logo overlay | Chèn logo/watermark tùy chỉnh lên video |
| Tắt tiếng | Tải video không có âm thanh |
| Scale 720p | Tự động upscale video < 720p lên 720p |
| AI Chatbot | Hỏi đáp về cách dùng, hỗ trợ tiếng Việt |
| Dark Mode | AI Eye-Protection, tự bật sau 18h |
| THUNDERWAVE™ | Tải file song song N luồng, ~50MB/s LAN |
| KeepLink™ | Kết nối không bao giờ bị ngắt |
| RTPC™ | Cập nhật UI thực thời, không cần F5 |

---

## 2. Kiến trúc tổng thể

```
┌─────────────────────────────────────────────────────────────┐
│                     BROWSER (Client)                         │
│                                                              │
│  ┌─────────────┐  ┌────────────┐  ┌──────────────────────┐  │
│  │  index.html │  │ THUNDERWAVE│  │  EYECORE KeepLink™   │  │
│  │  (UI/UX)    │  │ Client JS  │  │  + RTPC™ + WebRTC    │  │
│  └──────┬──────┘  └─────┬──────┘  └──────────┬───────────┘  │
│         │               │                     │              │
└─────────┼───────────────┼─────────────────────┼─────────────┘
          │ HTTP/SSE      │ Parallel Range       │ SSE Streams
          ▼               ▼ Requests             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask Server (app.py)                     │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   Route Layer (68 routes)             │   │
│  │  /api/download_async  /api/batch_start               │   │
│  │  /api/get_result      /api/batch_stream              │   │
│  │  /api/stream          /api/thunderwave/manifest      │   │
│  │  /api/realtime/subscribe  /api/keeplink/*             │   │
│  │  /api/webrtc/*        /api/storage/*                 │   │
│  │  /api/auth/*          /api/admin/*                   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────┐  ┌────────────────────────────────┐   │
│  │  Download Engine  │  │      FFmpeg Pipeline           │   │
│  │  _race_download   │  │  PATH A: stream copy           │   │
│  │  (4 strategies   │  │  PATH B: encode + scale        │   │
│  │   in parallel)   │  │  Truncation Recovery (4 strat) │   │
│  └──────────────────┘  └────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────┐  ┌────────────────────────────────┐   │
│  │   User Storage   │  │   BatchJob / Task System       │   │
│  │  user_storage/   │  │   TASK_STORE / BATCH_STORE     │   │
│  │  per-user quota  │  │   ThreadPoolExecutor           │   │
│  │  TTL 15 ngày     │  │   SSE Queue per job            │   │
│  └──────────────────┘  └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│              External APIs (Download Sources)                │
│  TikWM  │  ssstik.io  │  yt-dlp  │  TikTokApi              │
│  Cobalt  │  LocoDownloader  │  TTDownloader │  SnapTik      │
└─────────────────────────────────────────────────────────────┘
```

### Luồng dữ liệu chính

```
URL Input → check_urls → batch_start → BatchJob.start()
                                           │
                              _race_download_to_file()
                                   (4 APIs song song)
                                           │
                              _process_video_file()
                                   (FFmpeg pipeline)
                                           │
                              _ensure_valid_mp4()
                               (validate 3 lớp)
                                           │
                    ┌──────────────────────┤
                    │                      │
               download_direct        save_to_storage
               TASK_STORE[id]         user_storage/
                    │                      │
               SSE result event       _push_to_user()
                    │                   (RTPC™)
                    ▼
              THUNDERWAVE™ Client
              (N parallel streams)
                    │
                    ▼
              Browser: Blob → Save
```

---

## 3. Cài đặt & Khởi chạy

### Yêu cầu hệ thống

| Thành phần | Yêu cầu tối thiểu | Khuyến nghị |
|-----------|-------------------|-------------|
| OS | Windows 10 / Ubuntu 20+ / macOS 12+ | Ubuntu 22 LTS |
| Python | 3.10+ | 3.11+ |
| RAM | 4 GB | 8 GB+ |
| Disk | 10 GB (cho storage) | 50 GB+ |
| CPU | 2 nhân | 8 nhân+ (Ryzen/i7) |
| FFmpeg | 4.4+ | 6.0+ (với VAAPI/NVENC) |
| Network | 100 Mbps LAN | 1 Gbps |

### Cài đặt

```bash
# 1. Clone hoặc copy file vào thư mục
mkdir eyecore_downloader && cd eyecore_downloader

# 2. Cài Python dependencies
pip install flask flask-cors flask-compress requests httpx yt-dlp \
            psutil TikTokApi playwright

# 3. Cài FFmpeg
# Ubuntu:
sudo apt install ffmpeg
# Windows: Download từ https://ffmpeg.org/download.html, thêm vào PATH

# 4. Khởi chạy
python app.py
```

### Các biến môi trường

```bash
# Không cần .env — config hardcode trong app.py:
PORT = 2110                    # Cổng mặc định
FAST_TMPDIR = /dev/shm        # RAM disk (Linux) hoặc %TEMP%
USER_STORAGE_DIR = ./user_storage
SESSION_SECRET = <auto-generated>
```

### Startup log

```
════════════════════════════════════════════════════
⚡ TIKTOK DOWNLOADER TURBO - v10.4.0 — FULL FEATURED + KEEPLINK™
════════════════════════════════════════════════════
  FFmpeg  : ✅
  Encoder : 🚀 h264_vaapi (hoặc 🔵 libx264)
  CPU     : 8 slots (100% of 8 cores) | FFmpeg threads=8
  HW Tier : 🟢 STRONG (i5-8th+/i7/Ryzen)
  KeepLink: 🟢 EYECORE KeepLink™
  Chunk   : 🟢 Max 64MB chunks → ~50MB/s LAN
```

---

## 4. Cấu hình hệ thống

### Hằng số quan trọng (app.py)

```python
# ── Storage ──────────────────────────────────────────
_STORAGE_TTL_DAYS      = 15          # Xóa file sau 15 ngày
_DEFAULT_QUOTA_BYTES   = 3 GB        # Quota mặc định user thường
_ADMIN_QUOTA_BYTES     = 100 GB      # Admin = không giới hạn thực tế

# ── Guest limits ─────────────────────────────────────
_GUEST_DAILY_LIMIT     = 10          # 10 video/ngày cho khách

# ── Batch ────────────────────────────────────────────
BATCH_HARD_CAP         = 100         # Tối đa 100 URL/batch

# ── FFmpeg ───────────────────────────────────────────
_SIZE_LIMIT_MB         = 50          # File > 50MB → compress
_CPU_COUNT             = 100% cores  # Tất cả CPU cores
HW_ENCODER             = auto        # vaapi/nvenc/libx264

# ── Chunk sizes (THUNDERWAVE™) ────────────────────────
CHUNK_64MB  = file > 200MB           # Desktop large
CHUNK_32MB  = file > 50MB            # Desktop normal
CHUNK_16MB  = default desktop
CHUNK_2MB   = mobile Android
CHUNK_1MB   = Safari / iOS
```

### Hardware Tier Detection

App tự phát hiện tier phần cứng và điều chỉnh timeout/workers:

| Tier | Phần cứng | FFmpeg timeout | Workers |
|------|-----------|---------------|---------|
| 0 — WEAK | Celeron, Atom, < 4 nhân | × 2.5 | 3 |
| 1 — MEDIUM | i3, i5 cũ, < 8 nhân | × 1.5 | 6 |
| 2 — STRONG | i5-8th+, i7, Ryzen | × 1.0 | 10 |

---

## 5. Pipeline tải video

### 5.1 Chiến lược tải (Race Download)

Khi tải 1 video, hệ thống chạy **4 API song song** và lấy kết quả nhanh nhất:

```
URL ──┬── Strategy 1: TikWM API          ─┐
      ├── Strategy 2: ssstik.io           ├── _race_download_to_file()
      ├── Strategy 3: yt-dlp              ├── → Lấy kết quả NHANH NHẤT
      └── Strategy 4: TikTokApi / Cobalt ─┘
```

Các nguồn tải được thử theo thứ tự ưu tiên:

```python
_DOWNLOAD_PRIORITY_LIST = [
    get_tiktok_info_mobile_api,        # Mobile API (nhanh nhất)
    get_tiktok_info_tikwm,             # TikWM (tin cậy)
    get_tiktok_info_ytdlp,             # yt-dlp (fallback)
    get_tiktok_info_ssstik,            # ssstik.io
    get_tiktok_info_cobalt,            # Cobalt
    get_tiktok_info_tiktokapi,         # TikTokApi (Python)
    get_tiktok_info_locodownloader,    # LocoDownloader
    get_tiktok_info_ttdownloader,      # TTDownloader
    get_tiktok_info_snaptik,           # SnapTik
]
```

### 5.2 Retry Logic

```
Attempt 1 → Race download → nếu fail
Attempt 2 → Race + thông báo retry
Attempt 3 → Race + delay 1.5s
Attempt 4 → Race + delay 3s

Sau 4 lần fail → _download_with_rotation_retry()
  → Thử từng API một theo danh sách xoay vòng
  → Tối đa 5 lần rotation
```

### 5.3 Parallel Chunk Download (cho file lớn)

```python
# Trong _download_via_chunks():
CHUNK_WORKERS = {
    HW_TIER_STRONG: 10,   # 10 luồng song song
    HW_TIER_MEDIUM: 6,
    HW_TIER_WEAK:   3,
}
```

---

## 6. Xử lý FFmpeg & Video

### 6.1 Pipeline xử lý (_process_video_file)

```
raw_path (file thô từ API)
    │
    ├── PRE-STEP: Sanitize (nếu codec=none / container broken)
    │     └── _sanitize_video_for_ffmpeg()
    │
    ├── Probe info: _probe_once()
    │     ├── width, height, fps, has_audio, duration, size
    │     └── vcodec (h264/hevc/none/av1...)
    │
    ├── PATH A: Stream Copy (không cần encode)
    │     Điều kiện: H264 + ≥720p + không cần logo + không cần compress
    │     └── Trả thẳng raw_path (0–1s)
    │
    └── PATH B: Encode (1–30s tùy video)
          ├── Scale 720p: scale=-2:720:flags=lanczos (upscale)
          ├── Logo overlay: filter_complex
          ├── Compress: CRF=23, preset=ultrafast
          ├── Transcode: → H264 libx264 / vaapi / nvenc
          ├── VFR fix: -fflags +genpts+igndts+discardcorrupt
          └── Validate output: _validate_ffmpeg_output()
```

### 6.2 Input Flags Tối ưu (v2)

```bash
ffmpeg -y \
  -probesize 100M \           # Đọc đủ dữ liệu container
  -analyzeduration 10M \      # Phân tích 10s đầu
  -fflags +genpts+igndts+discardcorrupt+fastseek \
  -err_detect ignore_err \    # Bỏ qua packet corrupt
  -max_error_rate 1.0 \       # Không dừng dù nhiều error
  -avoid_negative_ts make_zero \
  -i input.mp4 \
  ...
```

### 6.3 Truncation Recovery — 4 Chiến lược

Khi FFmpeg tạo ra output bị cắt ngắn (`ratio < 25%`):

```
S1: genpts + copyts + vsync vfr
    └── Bảo toàn timestamps gốc, xử lý PTS jump

S2: Re-remux → MKV (loại bỏ container broken) → encode
    └── ffmpeg -c copy → .mkv → encode lại

S3: Force -t [duration] (ép đúng thời lượng)
    └── Lấy duration từ stream probe, không từ container

S4: Brute force (probesize=500M, chấp nhận output > 50KB)
    └── Tốt hơn fail hoàn toàn — user nhận video ngắn hơn
```

### 6.4 _ensure_valid_mp4 (3 lớp kiểm tra)

```
Layer 1: ffprobe check
    ├── Kiểm tra codec H264
    ├── Kiểm tra width/height hợp lệ
    ├── Nếu < 720p → upscale lên 720p (lanczos)
    └── Nếu không phải H264 → sang Layer 2

Layer 2: re-encode ultrafast H264
    └── libx264 CRF=23 ultrafast → file playable

Layer 3: remux (copy container)
    └── ffmpeg -c copy → MP4 mới với faststart
```

### 6.5 ffprobe Cache

```python
_ffprobe_cache: dict = {}  # filepath → (result: bool, timestamp)
_FFPROBE_CACHE_TTL = 30    # giây

# Tránh gọi ffprobe lặp lại cho cùng file trong 30s
# Cache tự dọn khi > 200 entries
```

### 6.6 Detect Hardware Encoder

```python
# Thử theo thứ tự:
1. h264_vaapi  (Intel iGPU / AMD GPU trên Linux)
2. h264_nvenc  (NVIDIA GPU)
3. h264_qsv    (Intel Quick Sync)
4. libx264     (Software fallback — luôn hoạt động)
```

---

## 7. Giao thức truyền tải THUNDERWAVE™

> **Tên đầy đủ**: Total High-speed Unified Network Data Extraction R-architecture with Windowed Adaptive Velocity Engine™  
> **Phiên bản**: 1.0  
> **Mục tiêu**: 50MB/s trên LAN cho mọi thiết bị

### 7.1 Cách hoạt động

```
Client                              Server
  │                                    │
  │── GET /api/thunderwave/manifest ──▶│
  │◀─ {workers, ranges[], size, ...} ──│
  │                                    │
  │── [Worker 0] Range: bytes=0-16M ──▶│
  │── [Worker 1] Range: bytes=16M-32M ▶│  ← Song song
  │── [Worker 2] Range: bytes=32M-48M ▶│  ← Song song
  │── [Worker N] Range: bytes=48M-end ▶│  ← Song song
  │                                    │
  │◀─ [Chunk 0] 16MB binary ───────────│
  │◀─ [Chunk 1] 16MB binary ───────────│  ← Nhận đồng thời
  │◀─ [Chunk 2] 16MB binary ───────────│
  │◀─ [Chunk N] ...binary ─────────────│
  │                                    │
  │── Reassemble in memory ────────────│
  │── Blob → Download ─────────────────│
```

### 7.2 Adaptive Workers

| Device | Workers | Lý do |
|--------|---------|-------|
| iOS Safari | 1 | Safari iOS giới hạn concurrent connections |
| Android Chrome | 4 | Mobile network stability |
| Desktop (file > 100MB) | 8 | Maximum throughput |
| Desktop (file ≤ 100MB) | 6 | Balanced |

### 7.3 API Endpoints

```
GET /api/thunderwave/manifest/<task_id>
GET /api/thunderwave/manifest/storage/<filename>

Response:
{
  "ok": true,
  "mode": "task" | "storage",
  "task_id": "abc123",
  "filename": "video.mp4",
  "size": 52428800,
  "workers": 6,
  "chunk_size": 8738133,
  "ranges": [
    {"i": 0, "start": 0, "end": 8738132, "size": 8738133},
    {"i": 1, "start": 8738133, "end": 17476265, "size": 8738133},
    ...
  ],
  "mime": "video/mp4",
  "protocol": "THUNDERWAVE/1.0"
}
```

### 7.4 Client Implementation (JavaScript)

```javascript
// Sử dụng THUNDERWAVE™
const data = await window.THUNDERWAVE.download(taskId, filename, fileSize, {
    onProgress: (received, total) => {
        updateProgressBar(received / total * 100);
    }
});
const blob = new Blob([data], { type: 'video/mp4' });
// → Trigger browser save
```

---

## 8. EYECORE KeepLink™ — Duy trì kết nối

> **Mục tiêu**: Không bao giờ bị ngắt kết nối, phục hồi < 300ms sau gián đoạn

### 8.1 Cơ chế hoạt động

```
Client                           Server
  │                                 │
  │── Ping mỗi 4–12s (adaptive) ──▶│
  │◀─ {pong, server_load, hint} ────│
  │                                 │
  │══ SSE /api/keeplink/stream ════▶│
  │◀═ kl_heartbeat mỗi 2s ══════════│
  │                                 │
  │  [Tab ẩn] → ping ngay khi hiện lại
  │  [Server tải cao] → giảm interval
  │  [Miss 3 ping] → reconnect với jitter backoff
```

### 8.2 Progressive Reconnect

```javascript
// Backoff: 1s → 2s → 4s → 8s (cộng jitter 0–500ms)
const delay = Math.min(8000, 1000 * Math.pow(2, missedCount));
const jitter = Math.random() * 500;
setTimeout(reconnect, delay + jitter);
```

### 8.3 Server Load Awareness

```python
# Server tính load từ batch + task đang chạy
server_load = min(100, active_batches * 15 + active_tasks * 5)

# Gợi ý interval:
interval_hint = 4s if load > 50% else 8s
```

### 8.4 API Endpoints

```
GET/POST /api/keeplink/ping?sid=<session_id>
  Response: {pong, ts, server_load, interval_hint, sessions}

GET /api/keeplink/stream?sid=<session_id>
  SSE stream: kl_heartbeat mỗi 2s
```

### 8.5 Status Indicator

Dot nhỏ màu trong header:
- 🟢 Xanh: kết nối ổn định
- 🟡 Vàng: đang kết nối
- 🔴 Đỏ: mất kết nối, đang reconnect

---

## 9. EYECORE Realtime Push Channel™

> **RTPC™** — Cập nhật UI không cần F5, push từ server tới TẤT CẢ tab của user

### 9.1 Events được push

| Event | Khi nào | Hành động client |
|-------|---------|-----------------|
| `storage_update` | File được lưu/xóa | Refresh storage tab |
| `auth_change` | Đăng nhập/đăng xuất | Re-check auth |
| `system_notice` | Thông báo admin | Toast notification |
| `rt_heartbeat` | Mỗi 12s | Keep-alive |
| `rt_connected` | Khi kết nối | Log |

### 9.2 Subscribe endpoint

```
GET /api/realtime/subscribe  (yêu cầu đăng nhập)
SSE stream: mỗi user có hàng đợi riêng
```

### 9.3 Server broadcast

```python
# Push đến tất cả tab của user
_push_to_user(username, 'storage_update', {
    'action': 'add',
    'filename': 'video.mp4',
    'folder_id': 'folder123',
    'used': 1024000,
})
```

### 9.4 Tích hợp với Storage

Khi lưu file vào kho:
1. `save_to_user_storage()` lưu metadata + `folder_id`
2. Auto-broadcast `storage_update` qua RTPC™
3. Client nhận → gán folder_id trong localStorage → refresh list
4. Không cần F5, không cần polling

---

## 10. WebRTC Bridge v1.0

> Cơ sở hạ tầng WebRTC signaling — sẵn sàng cho peer-to-peer trong tương lai

### 10.1 Architecture

```
Browser ←──── THUNDERWAVE™ ────── Server
   │                                  │
   └── WebRTC RTCPeerConnection        │
       DataChannel (sẵn sàng)         │
   │                                  │
   └── /api/webrtc/offer ────────────▶│
       /api/webrtc/ice                 │
       /api/webrtc/status ◀────────────│
```

### 10.2 Signaling Flow

```javascript
// 1. Client tạo offer
const pc = new RTCPeerConnection({ iceServers: [...] });
const dc = pc.createDataChannel('thunderwave');
const offer = await pc.createOffer();

// 2. Gửi lên server
POST /api/webrtc/offer
{ sdp: offer.sdp, type: 'offer', task_id: 'abc' }

// 3. Server trả answer (THUNDERWAVE transport)
{ answer: { sdp: '...', type: 'answer' }, transport: 'THUNDERWAVE/1.0' }
```

### 10.3 API Endpoints

```
POST /api/webrtc/offer
  Body: {sdp, type, task_id, filename}
  Response: {ok, session_id, answer, transport}

POST /api/webrtc/ice
  Body: {session_id, candidate}

GET /api/webrtc/status/<session_id>
  Response: {ok, has_answer, answer, transport, task_id}
```

---

## 11. Hệ thống xác thực & phân quyền

### 11.1 Các vai trò

| Role | Mô tả | Quyền |
|------|-------|-------|
| `guest` | Chưa đăng nhập | Tải ≤10 video/ngày, không lưu kho |
| `user` | Đã đăng nhập | Tải không giới hạn, lưu kho 3GB, batch |
| `admin` | Quản trị viên | Tất cả + quản lý user + dashboard |

### 11.2 Password Policy

```python
# Yêu cầu mật khẩu:
- Độ dài: ≥ 8 ký tự
- Ít nhất 1 chữ hoa
- Ít nhất 1 chữ thường
- Ít nhất 1 số
- Ít nhất 1 ký tự đặc biệt (!@#$%^&*...)
```

### 11.3 Brute-force Protection

```python
# Sau 5 lần login sai:
_BEHAVIORAL_GUARD.block(ip)
# Block theo IP, tự unblock sau N phút
# Admin có thể unblock thủ công qua dashboard
```

### 11.4 Session

```python
SESSION_SECRET = auto-generated khi khởi động
SESSION_LIFETIME = 7 ngày
```

### 11.5 API Endpoints Auth

```
POST /api/auth/register     Đăng ký (admin approve)
POST /api/auth/login        Đăng nhập
POST /api/auth/logout       Đăng xuất
GET  /api/auth/me           Thông tin user hiện tại
POST /api/auth/change_password  Đổi mật khẩu
```

---

## 12. Kho lưu trữ (Storage)

### 12.1 Cấu trúc thư mục

```
user_storage/
├── admin/
│   ├── _meta.json          # Metadata tất cả file
│   ├── video1.mp4
│   └── video2.mp4
├── alice/
│   ├── _meta.json
│   └── ...
└── bob/
    └── ...
```

### 12.2 Metadata format (_meta.json)

```json
{
  "video_abc123.mp4": {
    "title": "TikTok Video Title",
    "url": "https://www.tiktok.com/@user/video/...",
    "size": 15728640,
    "saved_at": "2024-01-15T10:30:00",
    "saved_at_ts": 1705309800.0,
    "expires_at": "2024-01-30T10:30:00",
    "expires_ts": 1706518200.0,
    "group_id": "batch_abc12345",
    "group_name": "Batch 15/01 10:30",
    "folder_id": "folder_xyz789",
    "status": "ready"
  }
}
```

### 12.3 Hệ thống thư mục

Thư mục là abstraction **client-side** + **server-side đồng bộ**:

```
Client localStorage:
  tikdown_sf_folders: [{id, name, created}]
  tikdown_sf_filemap: {filename: folder_id}

Server metadata:
  _meta.json[filename].folder_id = "folder_xyz"

Sync flow:
  1. Server lưu folder_id trong metadata
  2. Server RTPC broadcast storage_update{folder_id}
  3. Client _sfAssignFileExplicit(filename, folder_id)
  4. storageRefresh() → _sfSyncFromServer() → localStorage update
```

### 12.4 API Storage

```
GET  /api/storage/info              Quota & dung lượng đã dùng
GET  /api/storage/list              Danh sách file (có folder_id)
GET  /api/storage/download/<file>   Tải file (THUNDERWAVE™ compatible)
POST /api/storage/delete            Xóa file
POST /api/storage/download_zip      Tải ZIP nhiều file
POST /api/storage/clear_all         Xóa tất cả file
POST /api/storage/download_group    Tải theo group_id (1 batch)
```

### 12.5 Quota Management

```
User thường:  3 GB mặc định (admin có thể thay đổi)
Admin:        100 GB (effectively unlimited)

Admin set quota:
POST /api/admin/set_quota
  { username, quota_gb }   (0 = unlimited)
```

### 12.6 Auto Cleanup

```python
# Chạy background mỗi giờ
def _cleanup_expired_storage_files():
    # Xóa file quá 15 ngày (TTL)
    # Cập nhật _meta.json
    # Log số file đã xóa
```

---

## 13. Hàng chờ tải (Queue)

### 13.1 Cấu trúc Queue Item

```json
{
  "id": "q_abc123",
  "name": "Video meme buổi sáng",
  "urls": ["url1", "url2", "url3"],
  "audio": true,
  "logo_enabled": false,
  "created_at": 1705309800,
  "status": "pending"
}
```

### 13.2 API Queue

```
POST /api/queue/save        Lưu queue hiện tại
GET  /api/queue/load        Tải queue đã lưu
POST /api/queue/clear       Xóa queue
POST /api/queue/run_all     Chạy tất cả items tuần tự
```

### 13.3 Queue Run Flow

```
run_all() →
  for each item:
    1. _requireFolderIfNeeded() (nếu save_to_storage)
    2. batch_start(item.urls)
    3. Chờ batch hoàn thành
    4. Báo cáo kết quả
    5. Chuyển sang item tiếp theo
```

---

## 14. Tải đồng loạt (Batch)

### 14.1 BatchJob Architecture

```python
class BatchJob:
    batch_id: str           # MD5 unique ID
    urls: list              # Danh sách URL
    total: int              # Số video
    owner: str              # Username
    save_to_storage: bool   # Lưu kho hay không
    download_direct: bool   # Gửi về máy hay không
    folder_id: str          # Thư mục lưu
    group_name: str         # Tên nhóm hiển thị

    # Trạng thái
    _ok: int                # Số thành công
    _err: int               # Số lỗi
    _done_count: int        # Đã xử lý

    # Concurrency
    sse_q: Queue            # SSE event queue
    _failed_items: list     # Items cần retry Phase 2
```

### 14.2 Batch Pipeline

```
Phase 1: Tải song song (ThreadPoolExecutor)
  ├── Worker 0: download video[0]
  ├── Worker 1: download video[1]  ← Song song
  ├── Worker 2: download video[2]
  └── ...

  Mỗi worker:
    1. _race_download_to_file()    (4 APIs song song)
    2. _process_video_file()       (FFmpeg)
    3. _ensure_valid_mp4()         (Validate)
    4. save_to_user_storage()      (nếu cần)
    5. Đăng ký TASK_STORE          (nếu download_direct)
    6. Push SSE event → Client

Phase 2: Retry failed items
  ├── _download_with_rotation_retry()
  └── MAX 5 lần với method rotation
```

### 14.3 SSE Events

```javascript
// Client nhận từ /api/batch_stream/<batch_id>
{
  event: 'result',
  data: {
    index: 3,
    status: 'done',
    task_id: 'abc123',    // Để tải file
    filename: 'video.mp4',
    title: 'TikTok...',
    size: 15728640,
    url: 'https://...',
    download_direct: true,
    save_to_storage: true,
    storage_saved: true,
    folder_id: 'folder_xyz',
    expires_days: 15
  }
}
```

### 14.4 Download Modes

| Mode | `download_direct` | `save_to_storage` | Hành vi |
|------|------------------|-------------------|---------|
| Direct | true | false | Gửi về máy ngay |
| Storage | false | true | Chỉ lưu kho |
| Both | true | true | Lưu kho + gửi về máy |

---

## 15. AI Chatbot (EYECORE AI)

### 15.1 Tính năng

- Hỏi đáp về cách sử dụng web
- Hỗ trợ tiếng Việt và tiếng Anh
- Gợi ý tính năng phù hợp
- Giải thích lỗi và hướng dẫn xử lý
- Floating button góc phải màn hình

### 15.2 Backend

```
POST /api/chat
Body: { message, history }
Response: { reply }
```

Sử dụng Anthropic Claude API (nếu có API key) hoặc rule-based responses.

### 15.3 UI

Chatbot hiển thị dưới dạng floating widget, có thể thu nhỏ/mở rộng, lịch sử chat được giữ trong session.

---

## 16. Admin Dashboard

### 16.1 Truy cập

```
GET /dashboard  (yêu cầu role=admin)
```

### 16.2 Tính năng

```
Stats overview:
  - Total visitors (unique IP)
  - Total requests
  - Active batches / tasks
  - Storage usage toàn hệ thống
  - CPU / RAM realtime

User management:
  - Xem danh sách user
  - Lock/unlock user
  - Đổi mật khẩu
  - Xóa user
  - Set quota GB
  - Promote/demote admin

Storage overview:
  - Tổng dung lượng đang dùng
  - Per-user breakdown
  - File count per user

Security:
  - Blocked IPs list
  - Unblock IP
  - Request logs

Live stream:
  - GET /api/admin/dashboard_stream  (SSE)
  - Update mỗi 3s với stats realtime
```

### 16.3 API Admin Endpoints

```
GET  /api/admin/dashboard_stats     Stats tổng hợp
GET  /api/admin/dashboard_stream    Live stats SSE
GET  /api/admin/users               Danh sách user
POST /api/admin/lock_user           Lock/unlock
POST /api/admin/set_restrictions    Set giới hạn
POST /api/admin/change_user_password
POST /api/admin/delete_user
POST /api/admin/promote_user        Lên/xuống admin
POST /api/admin/set_quota           Set quota GB
GET  /api/admin/storage_overview    Storage per user
GET  /api/security/status           Security stats
POST /api/security/unblock          Unblock IP
```

---

## 17. Bảo mật hệ thống

### 17.1 Các lớp bảo vệ

```
Layer 1: Rate Limiting
  - Guest: 10 downloads/ngày
  - Per-IP: Tự động monitor

Layer 2: Behavioral Guard
  - Phát hiện pattern bất thường
  - Block IP sau N lần thất bại
  - Thời gian block tự động

Layer 3: Session Security
  - Session secret tự generate
  - HTTPOnly cookies
  - CSRF protection via same-origin

Layer 4: Input Validation
  - URL validation (TikTok domain only)
  - Path traversal prevention
  - Filename sanitization

Layer 5: Admin Protection
  - Role-based access control
  - All admin routes @require_admin
  - Audit logging
```

### 17.2 Validated TikTok URLs

```python
# Chỉ chấp nhận URLs từ:
- tiktok.com
- www.tiktok.com
- vm.tiktok.com
- vt.tiktok.com
- m.tiktok.com
```

### 17.3 Filename Sanitization

```python
def safe_filename(title, video_id, features=[]):
    # Loại bỏ ký tự nguy hiểm
    # Max length 200 ký tự
    # Unicode normalization
    # Format: {sanitized_title}_{video_id}_{features}.mp4
```

---

## 18. API Reference đầy đủ

### Core Download

```
POST /api/download_async
  Body: {url, audio, logo_enabled, logo_base64, logo_x, logo_y,
         logo_width, logo_height, save_to_storage, download_direct,
         group_id, group_name, folder_id}
  Response: {task_id, status, owner, save_to_storage, download_direct}

GET  /api/stream/<task_id>
  SSE events: status | storage_saved | heartbeat | error

GET  /api/get_result/<task_id>
  Response: video/mp4 binary (Range request supported)
  Headers: Content-Disposition, Accept-Ranges, Content-Length

GET  /api/task_status/<task_id>
  Response: {task_id, status, filename, size, title, method, error, url}

POST /api/cancel_task/<task_id>
POST /api/cancel_all
```

### Batch

```
POST /api/batch_start
  Body: {urls[], audio, logo_*, download_direct, save_to_storage,
         group_name, folder_id}
  Response: {batch_id, total}

GET  /api/batch_stream/<batch_id>
  SSE: result | result_retry | progress | batch_done | heartbeat

POST /api/batch_cancel/<batch_id>
GET  /api/batch_status/<batch_id>
GET  /api/batch_item_msgs/<batch_id>/<index>
```

### URL Check

```
POST /api/check_urls
  Body: {urls[]}
  Response: {valid[], invalid[], duplicates[], counts}

GET  /api/get_video_info
  Body: {url}
  Response: {title, duration, author, thumbnail, ...}
```

### Storage

```
GET  /api/storage/info
GET  /api/storage/list
GET  /api/storage/download/<filename>   (Range request supported)
POST /api/storage/delete                {filenames[]}
POST /api/storage/download_zip          {filenames[]}
POST /api/storage/clear_all
POST /api/storage/download_group        {group_id} or {day}
```

### THUNDERWAVE™

```
GET /api/thunderwave/manifest/<task_id>
GET /api/thunderwave/manifest/storage/<filename>
Response: {ok, mode, filename, size, workers, chunk_size, ranges[], protocol}
```

### KeepLink™

```
GET/POST /api/keeplink/ping?sid=<session_id>
GET      /api/keeplink/stream?sid=<session_id>
```

### Realtime Push

```
GET /api/realtime/subscribe   (SSE, requires auth)
Events: rt_connected | rt_heartbeat | storage_update | auth_change | system_notice
```

### WebRTC

```
POST /api/webrtc/offer    {sdp, type, task_id, filename}
POST /api/webrtc/ice      {session_id, candidate}
GET  /api/webrtc/status/<session_id>
```

### Queue

```
POST /api/queue/save
GET  /api/queue/load
POST /api/queue/clear
POST /api/queue/run_all
```

### Auth

```
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
POST /api/auth/change_password
```

### Admin

```
GET  /api/admin/dashboard_stats
GET  /api/admin/dashboard_stream
GET  /api/admin/users
POST /api/admin/lock_user
POST /api/admin/set_restrictions
POST /api/admin/change_user_password
POST /api/admin/delete_user
POST /api/admin/promote_user
POST /api/admin/set_quota
GET  /api/admin/storage_overview
GET  /api/security/status
POST /api/security/unblock
```

### System

```
GET  /api/health            Server health check
GET  /api/client_info       Client info (UA, IP, mobile/desktop)
GET  /api/speedtest_payload Payload để đo tốc độ
POST /api/cleanup           Dọn file tạm
POST /api/cleanup_ramdisk   Dọn RAM disk
POST /api/reload_cookies    Reload TikTok cookies
POST /api/set_cookies       Set cookies mới
GET  /api/logs              Server logs (admin)
POST /api/server_reload     Reload server (admin)
GET  /api/reload_stream     SSE stream khi reload
POST /api/chat              AI Chatbot
GET  /api/visitors          Visitor stats
GET  /api/link_stats        Download link stats
```

---

## 19. Cấu trúc thư mục

```
eyecore_downloader/
├── app.py                  # Server chính (~9500 dòng)
├── index.html              # Frontend (~9200 dòng)
├── requirements.txt        # Python dependencies
├── visitors.json           # Visitor tracking
│
├── user_storage/           # Kho lưu trữ video
│   ├── admin/
│   │   ├── _meta.json
│   │   └── *.mp4
│   ├── alice/
│   └── bob/
│
├── logs/                   # Server logs
│   ├── app.log
│   ├── error.log
│   └── process.log
│
└── /tmp hoặc /dev/shm/     # RAM disk (file tạm)
    ├── raw_*.mp4           # File thô từ API
    ├── proc_*.mp4          # File sau FFmpeg
    └── ensured_*.mp4       # File sau ensure layer
```

---

## 20. Troubleshooting

### Lỗi thường gặp

#### `invalid data found when processing input`
```
Nguyên nhân: TikTok MP4 có corrupt B-frames
Fix tự động:
  1. S1: genpts + copyts + vsync vfr
  2. S2: Re-remux → MKV → encode
  3. S3: Force -t [duration]
  4. S4: Brute force, chấp nhận output > 50KB
```

#### `real_truncation (ratio < 25%)`
```
Nguyên nhân: FFmpeg dừng encode sớm do container broken
Fix:
  - Threshold mới: 25% (từ 35%)
  - 4 chiến lược recovery (xem mục 6.3)
```

#### Video không thêm vào thư mục
```
Nguyên nhân: folder_id không được gửi hoặc nhận
Kiểm tra:
  1. folder_id trong batch payload: console.log(_bFolderId)
  2. Server metadata: cat user_storage/{user}/_meta.json
  3. Client localStorage: localStorage.getItem('tikdown_sf_filemap')
Fix:
  - Chọn thư mục trước khi tải (modal folder picker)
  - storageRefresh() sẽ sync từ server qua _sfSyncFromServer()
```

#### iOS không nhận video
```
Nguyên nhân: window.open() bị Safari iOS block từ async context
Fix:
  - Sau batch xong → panel màu xanh với nút <a> tappable
  - User nhấn từng nút để mở/lưu video
```

#### SSE bị ngắt giữa chừng
```
Fix tự động:
  - KeepLink™ phát hiện trong < 4s (từ 6s)
  - Reconnect với jitter backoff: 1s → 2s → 4s → 8s
  - Fallback sang polling /api/task_status
```

#### FFmpeg không tìm thấy
```bash
# Ubuntu
sudo apt install ffmpeg

# Kiểm tra
ffmpeg -version
ffprobe -version
```

#### Kho đầy (quota exceeded)
```
User: liên hệ admin
Admin: POST /api/admin/set_quota {username, quota_gb}
       0 = unlimited
```

---

## 21. Changelog

### v10.4.0 — TURBO FULL (hiện tại)

**Fixes**:
- ✅ Fix folder bug: Bỏ duplicate intercept trong `_initStorageFolder` — folder picker chỉ hiện 1 lần
- ✅ Fix iOS delivery: window.open() → tappable link panel sau batch
- ✅ Fix truncation: threshold 35% → 25%, thêm S2/S3/S4 strategies
- ✅ Fix 720p: upscale ngay tại `_ensure_valid_mp4` Layer 1

**New Features**:
- ⚡ THUNDERWAVE™ Protocol v1.0 — parallel N-stream delivery ~50MB/s
- 📡 EYECORE RTPC™ — real-time push, không cần F5
- 🌐 WebRTC Bridge v1.0 — signaling infrastructure
- 🔗 EYECORE KeepLink™ v2 — 1s heartbeat, 4s timeout, jitter backoff

**Performance**:
- 🚀 Chunk: 8MB → max 64MB (8× throughput)
- 🚀 CPU: 90% → 100% cores (max 32)
- 🚀 SSE heartbeat: 3s → 1s (phát hiện disconnect nhanh hơn)
- 🚀 ffprobe cache: tránh gọi lặp trong 30s
- 🚀 probesize: default → 100M (đọc container đúng hơn)
- 🚀 Thread pool URL check: 4 → min(10, CPU_COUNT)

---

## Phụ lục A — Glossary

| Thuật ngữ | Định nghĩa |
|-----------|-----------|
| **THUNDERWAVE™** | EYECORE parallel download protocol, N streams |
| **KeepLink™** | EYECORE connection persistence system |
| **RTPC™** | Realtime Push Channel — server push events |
| **SSE** | Server-Sent Events — one-way server→client stream |
| **mmap** | Memory-mapped file I/O — zero-copy file serving |
| **VFR** | Variable Frame Rate — nhiều TikTok video có FPS không đều |
| **elst** | Edit List atom trong MP4 — gây metadata sai trên TikTok |
| **PATH A** | Stream copy (không encode, 0–1s) |
| **PATH B** | Full encode với FFmpeg (1–30s) |
| **Truncation** | Video output ngắn hơn input do FFmpeg dừng sớm |
| **Race download** | Chạy N APIs song song, lấy kết quả nhanh nhất |
| **TASK_STORE** | Dict in-memory lưu trạng thái download task |
| **BATCH_STORE** | Dict in-memory lưu trạng thái batch job |

---

## Phụ lục B — Performance Benchmarks

| Scenario | Thời gian |
|----------|-----------|
| Tải 1 video (H264, stream copy) | 0.5–2s |
| Tải 1 video (encode 720p) | 3–15s |
| Batch 10 video (song song) | 15–60s |
| Truyền file 50MB (LAN) | ~1s (THUNDERWAVE™ 6 streams) |
| Truyền file 200MB (LAN) | ~4s (THUNDERWAVE™ 8 streams) |
| FFmpeg encode 1080p→720p | 5–20s (phụ thuộc CPU) |
| Storage list refresh | < 200ms |
| RTPC event lag | < 50ms |

---

*Tài liệu này được tạo tự động từ source code. Cập nhật lần cuối: v10.4.0-TURBO-FULL*
