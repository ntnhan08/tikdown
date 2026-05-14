# EYECORE TikTok Downloader — Tài liệu Kỹ thuật Siêu Chi tiết

> **Phiên bản**: v10.5.0-TURBO-FULL  
> **Stack**: Python 3.10+ / Flask / FFmpeg / Vanilla JS  
> **Cổng mặc định**: `2110`  
> **Tổng dòng code**: ~9.700 (app.py) + ~9.400 (index.html)

---

## Mục lục

1. [Tổng quan hệ thống](#1)
2. [Kiến trúc tổng thể](#2)
3. [Cài đặt & Khởi chạy](#3)
4. [Cấu hình & Hằng số](#4)
5. [Pipeline tải video](#5)
6. [FFmpeg Pipeline & Video Processing](#6)
7. [THUNDERWAVE™ Protocol v2.0](#7)
8. [EYECORE KeepLink™ v3](#8)
9. [EYECORE Realtime Push Channel™](#9)
10. [WebRTC Bridge v1.0](#10)
11. [Background Persist & Checkpoint System](#11)
12. [Batch Completion Logic — tryResolve](#12)
13. [Hệ thống xác thực & phân quyền](#13)
14. [Kho lưu trữ (Storage)](#14)
15. [Hàng chờ (Queue)](#15)
16. [Tải đồng loạt (Batch)](#16)
17. [iOS Delivery](#17)
18. [AI Chatbot](#18)
19. [Admin Dashboard](#19)
20. [Bảo mật hệ thống](#20)
21. [API Reference đầy đủ](#21)
22. [Cấu trúc thư mục](#22)
23. [Troubleshooting](#23)
24. [Changelog đầy đủ](#24)

---

## 1. Tổng quan hệ thống {#1}

**EYECORE TikTok Downloader** là ứng dụng web tải video TikTok không watermark,
chạy hoàn toàn trên máy chủ nội bộ (localhost/LAN).

### Mục tiêu thiết kế

| Mục tiêu | Giải pháp |
|----------|-----------|
| Tốc độ | Race 4–9 APIs song song; THUNDERWAVE™ v2 |
| Độ tin cậy | S0–S5 truncation recovery; 100% target |
| Thực thời | RTPC™ + KeepLink™ v3 + WebRTC Bridge |
| Không mất dữ liệu | Checkpoint system + auto-resume |
| Đa thiết bị | iOS tappable, Android 4w, Desktop 6–8w |
| Ít tài nguyên mạng | KeepLink < 1KB/min; THUNDERWAVE queue 1-at-a-time |

### Tính năng chính

| Tính năng | Chi tiết |
|-----------|----------|
| Tải đơn | 1 URL → race → FFmpeg → validate → THUNDERWAVE™ |
| Tải đồng loạt | ≤100 URLs/batch, song song theo hardware tier |
| Hàng chờ | Nhiều batch chạy tuần tự |
| Kho lưu trữ | TTL 15 ngày, quota per-user, tự dọn |
| Thư mục kho | LocalStorage + server metadata 2-way sync |
| Logo overlay | Custom watermark vị trí/kích thước tùy chỉnh |
| Scale 720p | Upscale lanczos nếu < 720p, mọi pipeline path |
| AI Chatbot | Claude API hoặc rule-based, tiếng Việt |
| Dark Mode | WCAG AA+ contrast, tự bật sau 18h |
| Checkpoint | Lưu links → resume sau browser đóng |

---

## 2. Kiến trúc tổng thể {#2}

```
┌──────────────────────────────────────────────────────────────────┐
│                        BROWSER (Client)                           │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                    JavaScript Modules                        │  │
│  │                                                              │  │
│  │  Batch Engine        THUNDERWAVE™ v2   KeepLink™ v3          │  │
│  │  _fetchAndSave()     Adaptive N-stream  Single SSE           │  │
│  │  tryResolve()        Queue 1-at-a-time  Watchdog 20s         │  │
│  │                                                              │  │
│  │  RTPC™ Client        WebRTC Bridge     Persist Client        │  │
│  │  storage_update      RTCPeerConn       checkpoint submit     │  │
│  │  auth_change         DataChannel       mark_done/resume      │  │
│  └─────────────────────────────────────────────────────────────┘  │
└───────────────────────────┬──────────────────────────────────────┘
                            │ HTTP / SSE / Range Requests
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Flask Server (app.py)                          │
│                       72 routes                                   │
│                                                                    │
│  Download Engine           FFmpeg Pipeline                        │
│  _race_download()          PATH A: stream copy  (0–1s)           │
│  4–9 APIs song song        PATH B: encode+scale (1–30s)          │
│  Retry rotation            S0–S5 truncation recovery             │
│                            720p upscale tại ensure layer         │
│                                                                    │
│  User Storage              Task/Batch System                     │
│  user_storage/             TASK_STORE / BATCH_STORE              │
│  _meta.json+folder_id      ThreadPoolExecutor N workers          │
│  TTL 15 ngày               SSE Queue per BatchJob                │
│  RTPC broadcast            Background persist (checkpoint)       │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
         External APIs: TikWM / yt-dlp / ssstik / TikTokApi /
                        Cobalt / LocoDownloader / TTDownloader
```

### Luồng dữ liệu chính

```
URL Input
  → check_urls (validate + dedup)
  → persist/submit (checkpoint ONLY — không chạy batch)
  → batch_start → BatchJob.start()
       → Phase 1: _race_download_to_file() × N (4-9 APIs song song)
       → _process_video_file() (FFmpeg: PATH A hoặc PATH B)
       → _ensure_valid_mp4() (3 lớp + 720p upscale)
       → save_to_user_storage() → _push_to_user() RTPC
       → Push SSE result → Client
  → Client THUNDERWAVE™ v2:
       → measureSpeed() (512KB probe)
       → adaptWorkers() (1–8 dựa trên tốc độ + device)
       → Queue 1-at-a-time
       → Parallel range-fetch → reassemble → Blob → download
  → tryResolve(): 4 điều kiện strict
       → finalizedCount >= total
       → pendingFetch <= 0
       → _pendingFileSaves <= 0
       → allStarted (mọi fetch đã bắt đầu)
       → "XONG" notification
```

---

## 3. Cài đặt & Khởi chạy {#3}

### Yêu cầu hệ thống

| Thành phần | Tối thiểu | Khuyến nghị |
|-----------|-----------|-------------|
| OS | Windows 10 / Ubuntu 20+ / macOS 12+ | Ubuntu 22 LTS |
| Python | 3.10+ | 3.11+ |
| RAM | 4 GB | 16 GB+ (RAM disk /dev/shm) |
| Disk | 20 GB | 100 GB+ |
| CPU | 4 nhân | 8–16 nhân (Ryzen/i7) |
| FFmpeg | 4.4+ | 6.0+ |
| Network LAN | 100 Mbps | 1 Gbps (THUNDERWAVE™ 50MB/s) |

### Cài đặt nhanh

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y ffmpeg python3-pip
pip install flask flask-cors flask-compress requests httpx yt-dlp psutil TikTokApi

# Windows
pip install flask flask-cors flask-compress requests httpx yt-dlp psutil
# Cài FFmpeg từ ffmpeg.org, thêm vào PATH

# Khởi chạy
python app.py
# → http://localhost:2110
```

### Startup log

```
════════════════════════════════════════════════════════
⚡ TIKTOK DOWNLOADER TURBO - v10.5.0 — FULL FEATURED
════════════════════════════════════════════════════════
  FFmpeg  : ✅
  Encoder : 🚀 h264_vaapi / 🔵 libx264 (fallback)
  CPU     : 8 slots (100% of 8 cores)
  HW Tier : 🟢 STRONG — timeout×1.0 — workers=10
  KeepLink: 🟢 v3 Single-SSE 15s heartbeat
  Chunk   : 🟢 Max 64MB → ~50MB/s LAN
  Persist : 🟢 ./pending_persist/
```

---

## 4. Cấu hình & Hằng số {#4}

```python
# Network
PORT                  = 2110

# Storage
_STORAGE_TTL_DAYS     = 15           # Xóa sau 15 ngày
_DEFAULT_QUOTA_BYTES  = 3 * 1024**3  # 3 GB/user
_ADMIN_QUOTA_BYTES    = 100 * 1024**3

# Batch
BATCH_HARD_CAP        = 100          # Max URLs/batch

# Guest
_GUEST_DAILY_LIMIT    = 10           # 10 video/ngày

# FFmpeg
_COMPRESS_THRESHOLD_MB = 50          # File > 50MB → nén
_CPU_COUNT            = min(int(cpu_count * 1.0), 32)  # 100%

# THUNDERWAVE™ chunks
CHUNK_64MB = file > 200MB   # Desktop large
CHUNK_32MB = file > 50MB    # Desktop medium
CHUNK_16MB = default        # Desktop normal
CHUNK_2MB  = Android        
CHUNK_1MB  = iOS / Safari   

# KeepLink™ v3
KL_HEARTBEAT_INTERVAL = 15s  # Server
KL_CLIENT_WATCHDOG    = 20s  # Client reconnect nếu im > 20s

# ffprobe cache
_FFPROBE_CACHE_TTL    = 30s
_FFPROBE_MAX_CACHE    = 200 entries
```

### Hardware Tier Detection

| Tier | Phần cứng | Timeout | Workers |
|------|-----------|---------|---------|
| 0 WEAK | Celeron, Atom, ≤2 nhân | ×2.5 | 3 |
| 1 MEDIUM | i3, i5 cũ, ≤4 nhân | ×1.5 | 6 |
| 2 STRONG | i5-8th+, i7, Ryzen | ×1.0 | 10 |

---

## 5. Pipeline tải video {#5}

### 5.1 Race Download

```
URL
 ├─ Mobile API    ─┐
 ├─ TikWM API      │  Song song, lấy kết quả
 ├─ yt-dlp         ├─ NHANH NHẤT
 ├─ ssstik.io      │
 └─ Cobalt/...    ─┘
         │
         ▼ Nếu tất cả fail:
 _download_with_rotation_retry()
   → Thử từng API 1 lần, vòng xoay, tối đa 5 rounds
```

### 5.2 Retry Logic

```
Attempt 1: race download
Attempt 2: race + notify retry
Attempt 3: race + delay 1.5s
Attempt 4: rotation retry × 5
  → Vẫn fail → errCount++ (nhưng batch tiếp tục)
```

### 5.3 Parallel Chunk Download (file lớn)

```python
# _download_via_chunks()
workers = {STRONG: 10, MEDIUM: 6, WEAK: 3}[hardware_tier]
# N concurrent range-requests → merge → lưu disk
```

---

## 6. FFmpeg Pipeline & Video Processing {#6}

### 6.1 PATH A vs PATH B

```
Probe: _probe_once() → {codec, w, h, fps, duration, size}
    │
    ├─ PATH A — Stream Copy (0–1s)
    │   Điều kiện: codec=H264 AND short_side≥720
    │              AND không logo AND không nén
    │   └─ Trả thẳng raw_path
    │
    └─ PATH B — Full Encode (1–30s)
        ├─ Scale: scale=-2:720:flags=lanczos (nếu <720p)
        ├─ Logo: filter_complex overlay
        ├─ Compress: CRF=23 preset=ultrafast
        ├─ Transcode: H264 (vaapi/nvenc/qsv/libx264)
        └─ Validate: _validate_ffmpeg_output()
```

### 6.2 Input Flags Robust (v2)

```bash
ffmpeg -y \
  -probesize 100M \            # Đọc đủ container
  -analyzeduration 10M \       # Phân tích 10s đầu
  -fflags +genpts+igndts+discardcorrupt+fastseek \
  -err_detect ignore_err \
  -max_error_rate 1.0 \
  -ignore_unknown \            # Bỏ qua streams lạ
  -avoid_negative_ts make_zero \
  -i input.mp4 ...
```

### 6.3 Truncation Recovery — 6 Strategies (S0→S5)

Kích hoạt khi: `output_duration / input_duration < 25%`

| Strategy | Kỹ thuật | Mục đích |
|----------|----------|----------|
| **S0** | Pre-repair: `-c copy -ignore_unknown` → overwrites raw | Fix container trước encode |
| S1 | `genpts + copyts + vsync vfr` | Fix PTS/DTS |
| S2 | Re-remux → MKV → encode lại | Fix broken container |
| S3 | Force `-t [duration]` từ stream probe | Fix PTS gap |
| S4 | Brute force `probesize=500M`, accept > 50KB | Tất cả fail |
| **S5** | Trả raw file nếu ffprobe validates | Last resort: không bao giờ fail hoàn toàn |

### 6.4 `_ensure_valid_mp4` — 3 Lớp

```
Layer 1: ffprobe
  ├─ codec = H264 + w/h valid?
  ├─ short_side < 720 → upscale lanczos (720p fix)
  └─ Không phải H264 → Layer 2

Layer 2: re-encode ultrafast
  └─ probesize=200M -ignore_unknown CRF=23 ultrafast
     tune=zerolatency

Layer 3: remux
  └─ -c copy -movflags +faststart
```

### 6.5 ffprobe Cache

```python
_ffprobe_cache: dict  # filepath → (result: bool, timestamp)
_FFPROBE_CACHE_TTL = 30s
# Tránh gọi ffprobe lặp cho cùng file trong 30s
# Auto-evict khi > 200 entries
```

### 6.6 Hardware Encoder

```
Thứ tự: h264_vaapi → h264_nvenc → h264_qsv → libx264 (luôn hoạt động)
```

---

## 7. THUNDERWAVE™ Protocol v2.0 {#7}

> **Tên đầy đủ**: Total High-speed Unified Network Data Extraction R-architecture with Windowed Adaptive Velocity Engine™  
> **Version**: 2.0 | **Target**: 50MB/s LAN, ít tài nguyên, 1 video tại 1 thời điểm

### 7.1 So sánh v1.0 vs v2.0

| | v1.0 | v2.0 |
|--|------|------|
| Workers | Cố định 6–8 | **Adaptive: đo speed → 1–6** |
| Concurrency | N videos song song | **1 video tại 1 thời điểm** |
| Speed probe | Không | **512KB probe → MB/s thực** |
| Network usage | Cao | **Thấp (queue 1-at-a-time)** |
| iOS | `window.open()` (bị block) | **Direct `<a href>` tappable** |
| Queue | Không | **FIFO, `_processQueue()`** |

### 7.2 Adaptive Worker Algorithm

```javascript
// 1. Đo tốc độ thực (512KB probe)
async function _measureSpeed(url) {
    const t0  = Date.now();
    const res = await fetch(url, {
        headers: { 'Range': 'bytes=0-524287' },
        signal: AbortSignal.timeout(3000),
    });
    await res.arrayBuffer();
    const elapsed = (Date.now() - t0) / 1000;
    return Math.round((524288 / elapsed) / (1024 * 1024)); // MB/s
}

// 2. Quyết định workers dựa trên speed + device
function _adaptWorkers(speedMBs, fileSize) {
    if (iOS)              return 1;  // Safari single stream
    if (speedMBs >= 50)   return 6;  // Fast LAN → 6 streams
    if (speedMBs >= 20)   return 4;  // Medium → 4 streams
    if (speedMBs >= 10)   return 2;  // Slow → 2 streams
    return 1;                        // Very slow → single
}
```

### 7.3 Queue: Không Flood Network

```javascript
// Batch 5 videos: tải tuần tự, không song song
const _queue = [];
let _running = false;

async function _processQueue() {
    if (_running || _queue.length === 0) return;
    _running = true;
    while (_queue.length > 0) {
        const job = _queue.shift();
        await job();  // Video N xong → Video N+1 bắt đầu
    }
    _running = false;
}
```

### 7.4 Parallel Range Fetch (trong 1 video)

```
Client                           Server
  │                                │
  │─── GET manifest/<task_id> ────▶│
  │◀── {workers:4, ranges:[...]} ──│
  │                                │
  │─── [W0] Range: 0–13MB ────────▶│
  │─── [W1] Range: 13–26MB ───────▶│ ← Song song TRONG 1 video
  │─── [W2] Range: 26–39MB ───────▶│
  │─── [W3] Range: 39–52MB ───────▶│
  │                                │
  │◀── Chunk 0 ────────────────────│
  │◀── Chunk 1 ────────────────────│ ← ~50MB/s tổng
  │◀── Chunk 2 ────────────────────│
  │◀── Chunk 3 ────────────────────│
  │                                │
  │─── Reassemble → Blob → Save ───│
```

### 7.5 API Endpoints

```
GET /api/thunderwave/manifest/<task_id>
GET /api/thunderwave/manifest/storage/<filename>

Response: {
  "ok": true,
  "protocol": "THUNDERWAVE/1.0",
  "filename": "video.mp4",
  "size": 52428800,
  "workers": 4,
  "chunk_size": 13107200,
  "ranges": [
    {"i":0, "start":0,        "end":13107199, "size":13107200},
    {"i":1, "start":13107200, "end":26214399, "size":13107200},
    ...
  ]
}
```

---

## 8. EYECORE KeepLink™ v3 {#8}

> Single SSE, watchdog 20s, < 1KB/min bandwidth

### 8.1 So sánh v2 vs v3

| | v2 | v3 |
|--|----|----|
| HTTP ping | Mỗi 4–12s | **Không có** |
| SSE connections | 2 (ping + keeplink) | **1 duy nhất** |
| Bandwidth | ~5KB/min | **< 1KB/min** |
| Server heartbeat | 2s | **15s** |
| Client watchdog | Không | **✅ 20s** |
| Backoff | 1→2→4→8s | **2→4→8→16s** |
| Code phức tạp | HTTP ping + SSE stream | **Chỉ SSE** |

### 8.2 Client Logic

```javascript
(function _initKeepLink() {
    let _klES    = null;
    let _klFails = 0;
    let _klLastHB = 0;

    function _klConnect() {
        _klES = new EventSource('/api/keeplink/stream?sid=' + KL_SID);

        _klES.onopen = () => { _klLastHB = Date.now(); };
        _klES.addEventListener('kl_heartbeat', () => {
            _klFails  = 0;
            _klLastHB = Date.now();
            // → status dot green
        });
        _klES.onerror = () => {
            _klFails++;
            // Backoff: 2→4→8→16s + jitter 300ms
            const delay = Math.min(16000, 2000 * 2 ** (_klFails - 1));
            setTimeout(_klConnect, delay + Math.random() * 300);
        };
    }

    // Watchdog: nếu im > 20s → reconnect
    setInterval(() => {
        if (_klLastHB && Date.now() - _klLastHB > 20000) {
            _klES.close();
            _klConnect();
        }
    }, 5000);

    // Tab visible lại → reconnect ngay
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && _klES.readyState === CLOSED)
            setTimeout(_klConnect, 200);
    });
})();
```

### 8.3 Server

```python
@app.route('/api/keeplink/stream')
def keeplink_stream():
    def _gen():
        while True:
            yield _sse('kl_heartbeat', {'ts': int(time.time()*1000)})
            time.sleep(15)   # 15s = < 1KB/min
    return Response(stream_with_context(_gen()), ...)
```

---

## 9. EYECORE Realtime Push Channel™ {#9}

> Push mọi state change đến TẤT CẢ tabs của user — không cần F5

### 9.1 Events

| Event | Trigger server | Client action |
|-------|---------------|--------------|
| `storage_update` | save/delete file | Refresh tab + badge + folder |
| `auth_change` | login/logout | Re-auth + resume pending |
| `system_notice` | Admin message | Toast notification |
| `rt_heartbeat` | Mỗi 12s | Keep-alive |
| `rt_connected` | Subscribe | Log |

### 9.2 Auto-patched Functions

```python
# save_to_user_storage() được monkey-patch:
def save_to_user_storage(...):
    result = _orig_save_to_user_storage(...)
    if result.get('ok'):
        _push_to_user(username, 'storage_update', {
            'action': 'add',
            'filename': filename,
            'folder_id': folder_id,
            'used': result.get('used', 0),
        })
    return result

# delete_from_user_storage() tương tự
```

### 9.3 Resume on Login

```javascript
// RTPC handler khi nhận auth_change:
_rtES.addEventListener('auth_change', () => {
    fetch('/api/auth/me').then(r => r.json()).then(d => {
        if (d.logged_in) {
            // Check pending checkpoints
            fetch('/api/persist/status').then(r => r.json()).then(ps => {
                const pending = ps.tasks.filter(t => t.status === 'pending');
                if (pending.length > 0) {
                    _toast(`🔄 ${pending.length} lô chưa tải. Đang tiếp tục...`);
                    fetch('/api/persist/resume', { method: 'POST' });
                }
            });
        }
    });
});
```

---

## 10. WebRTC Bridge v1.0 {#10}

```
Browser                         Server
  │                                │
  ├─ RTCPeerConnection              │
  ├─ createDataChannel('thunderwave')
  ├─ createOffer()                  │
  │                                │
  ├── POST /api/webrtc/offer ──────▶│
  │◀── {answer, transport: THUNDERWAVE/1.0}
  │                                │
  └─ Transport: THUNDERWAVE™        │
     (parallel HTTP range requests) │
```

**Note**: Server-side WebRTC peer đầy đủ yêu cầu `aiortc`. Hiện tại bridge trả answer chỉ định THUNDERWAVE™ transport — cùng tốc độ, không cần STUN/TURN.

### 10.1 API

```
POST /api/webrtc/offer    {sdp, type, task_id, filename}
                          → {ok, session_id, answer, transport}

POST /api/webrtc/ice      {session_id, candidate}

GET  /api/webrtc/status/<session_id>
                          → {ok, has_answer, answer, transport}
```

---

## 11. Background Persist & Checkpoint System {#11}

> Không mất links dù browser đóng giữa chừng

### 11.1 Flow đầy đủ

```
[User click Tải]
        │
        ├─ 1. persist/submit
        │      └─ Lưu checkpoint: pending_persist/{pid}.json
        │         status = "pending" (KHÔNG chạy batch)
        │
        ├─ 2. batch_start (chạy bình thường)
        │      └─ Hoàn thành → persist/mark_done
        │         status = "done" → file được xóa/đánh dấu
        │
        └─ 3. Nếu browser đóng TRƯỚC khi batch_start xong:
                Checkpoint vẫn còn status = "pending"
                        │
                        └─ Lần sau đăng nhập:
                           RTPC auth_change → persist/status
                           → persist/resume (server tạo BatchJob mới)
                           → download_direct=false (chỉ lưu kho)
                           → Không cần browser download
```

### 11.2 Checkpoint Format

```json
{
  "pid": "abc123def456",
  "username": "alice",
  "name": "Batch sáng 15/01",
  "urls": ["https://tiktok.com/...", "..."],
  "audio": true,
  "logo_params": { "enabled": false },
  "folder_id": "folder_xyz",
  "download_direct": true,
  "save_to_storage": true,
  "created_at": 1705309800000,
  "status": "pending | running | done | error",
  "batch_id": null
}
```

### 11.3 API

```
POST /api/persist/submit      Ghi checkpoint files (không start batch)
POST /api/persist/mark_done   {pids:[...]} → đánh dấu done
GET  /api/persist/status      Liệt kê checkpoints của user hiện tại
POST /api/persist/resume      Resume tất cả pending (server-side BatchJob)
```

---

## 12. Batch Completion Logic — tryResolve {#12}

> Đây là phần quan trọng nhất — "XONG" chỉ báo khi thực sự xong

### 12.1 Counters

```javascript
let total           = capturedUrls.length;  // Tổng video
let finalizedCount  = 0;   // Số video đã kết thúc (ok + fail)
let pendingFetch    = 0;   // Số fetch đang chạy
let _fetchStarted   = 0;   // Tổng _fetchAndSave đã khởi động
// window._pendingFileSaves   // Số blob đang ghi disk
const processedIndices = new Set();  // Tránh double-process SSE events
```

### 12.2 tryResolve — 4 Điều kiện STRICT

```javascript
function tryResolve() {
    if (_resolved) return;

    const fileSaveDone = (window._pendingFileSaves || 0) <= 0;
    const allStarted   = _fetchStarted >= total
                      || processedIndices.size >= total;

    if (  finalizedCount >= total  // [1] Mọi video đã kết thúc
       && pendingFetch   <= 0      // [2] Không còn fetch active
       && fileSaveDone             // [3] Không còn ghi disk
       && allStarted) {            // [4] Mọi fetch đã được khởi động
        _resolved = true;
        resolve();   // → "XONG"
    }
}
```

### 12.3 Khi nào `finalizedCount` tăng

| Trường hợp | Tăng khi nào |
|-----------|-------------|
| `storage-only` (`download_direct=false`) | Ngay khi SSE result nhận |
| iOS (tappable link) | Ngay khi link được thêm panel |
| Desktop `_fetchAndSave` | **SAU KHI** `fetch().blob()` hoàn thành |
| Error/fail | Ngay khi SSE result nhận |
| `result_retry` | **KHÔNG tăng thêm** — đã tăng lúc fail lần đầu |

### 12.4 _resolvePoller — Periodic Safety Check

```javascript
const _resolvePoller = setInterval(() => {
    if (_resolved) { clearInterval(_resolvePoller); return; }
    const allEventsIn = processedIndices.size >= total;
    const allStarted  = _fetchStarted >= total;
    // Chỉ gọi tryResolve khi CẢ HAI điều kiện này đúng:
    if (finalizedCount >= total && allEventsIn && allStarted)
        tryResolve();
}, 800);
```

### 12.5 Bugs Đã Fix (v10.5.0)

| Bug | Nguyên nhân | Fix |
|-----|------------|-----|
| "Báo xong sớm" #1 | `persist_submit` chạy duplicate batch → RTPC fires sớm | `persist_submit` chỉ lưu checkpoint |
| "Báo xong sớm" #2 | `result_retry` tăng `finalizedCount` ngay lập tức | Không tăng ở retry (đã tăng lúc fail) |
| "Báo xong sớm" #3 | `_resolvePoller` không check `allStarted` | Thêm `allEventsIn && allStarted` guards |
| Storage không hiện | IIFE `storageRefresh` không gọi `storageRenderFiles()` | IIFE version gọi đủ cả 4 functions |

---

## 13. Hệ thống xác thực & phân quyền {#13}

### 13.1 Vai trò

| Role | Giới hạn | Quyền đặc biệt |
|------|---------|---------------|
| `guest` | 10 video/ngày | Không |
| `user` | Không giới hạn + kho 3GB | Batch, queue, storage |
| `admin` | 100GB storage | Dashboard, quản lý user |

### 13.2 Password Policy

```
Độ dài ≥ 8 ký tự
≥ 1 chữ hoa  (A–Z)
≥ 1 chữ thường (a–z)
≥ 1 số (0–9)
≥ 1 ký tự đặc biệt (!@#$%^&*...)
```

### 13.3 Brute-force Protection

```
5 lần fail → Block IP (thời gian tự động)
Admin: POST /api/security/unblock để unblock thủ công
```

### 13.4 API

```
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
POST /api/auth/change_password
```

---

## 14. Kho lưu trữ (Storage) {#14}

### 14.1 Cấu trúc thư mục

```
user_storage/
└── {username}/
    ├── _meta.json      ← metadata + folder_id
    └── *.mp4
```

### 14.2 Metadata (_meta.json)

```json
{
  "tiktok_abc123.mp4": {
    "title": "Video title",
    "url": "https://tiktok.com/@user/video/...",
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

### 14.3 Folder System — 2-way Sync

```
Server metadata (persistent across sessions):
  _meta.json[filename].folder_id = "folder_abc"

Client localStorage (fast UI, offline):
  tikdown_sf_folders: [{id, name, created}]
  tikdown_sf_filemap: {filename: folder_id}

Sync flow (mỗi storageRefresh):
  _sfSyncFromServer(files)
  → Với mỗi file: nếu server folder_id ≠ localStorage → update localStorage
  → Đảm bảo F5 / tab mới vẫn đúng thư mục
```

### 14.4 storageRefresh — Đã Fix v10.5.0

```javascript
// IIFE version (ghi đè global) giờ gọi đầy đủ:
window.storageRefresh = async function() {
    const [infoRes, listRes] = await Promise.all([
        fetch('/api/storage/info'),
        fetch('/api/storage/list'),
    ]);
    const info = await infoRes.json();
    const d    = await listRes.json();
    _allFiles  = d.files || [];

    storageUpdateQuota(info);       // ← [1] Cập nhật quota bar
    storageRenderFiles(_allFiles);  // ← [2] Render main tab list (BUG FIX!)
    storageSyncBadge(_allFiles.length); // ← [3] Update badge
    _sfSyncFromServer(_allFiles);   // ← [4] Sync folder_id
    _sfRenderSidebar();             // ← [5] Update folder sidebar
    _sfRenderFiles();               // ← [6] Update folder file list
};
```

### 14.5 API

```
GET  /api/storage/info              Quota, dung lượng đã dùng
GET  /api/storage/list              Files + folder_id
GET  /api/storage/download/<file>   Range supported, 64MB chunks
POST /api/storage/delete            {filenames:[...]}
POST /api/storage/download_zip      {filenames:[...]}
POST /api/storage/clear_all
POST /api/storage/download_group    {group_id}
```

### 14.6 Auto Cleanup

```python
# Background thread mỗi giờ:
_cleanup_expired_storage_files()
# Xóa file có expires_ts < now
# Cập nhật _meta.json
```

---

## 15. Hàng chờ (Queue) {#15}

### 15.1 Queue Item Format

```json
{
  "id": "q_abc123",
  "name": "Video meme buổi sáng",
  "urls": ["url1", "url2", "url3"],
  "status": "pending | running | done",
  "created_at": 1705309800
}
```

### 15.2 Persist + Queue Integration

Khi run_all():
1. Với mỗi queue item: tạo persist checkpoint riêng
2. Chạy từng batch tuần tự
3. Nếu browser đóng → resume phần còn lại khi login lại

### 15.3 API

```
POST /api/queue/save
GET  /api/queue/load
POST /api/queue/clear
POST /api/queue/run_all   {items:[{name, urls}], audio, folder_id}
```

---

## 16. Tải đồng loạt (Batch) {#16}

### 16.1 BatchJob Structure

```python
class BatchJob:
    batch_id:         str   # MD5 hex ID
    urls:             list  # Danh sách URLs
    total:            int   # Số video
    owner:            str   # Username
    save_to_storage:  bool
    download_direct:  bool
    folder_id:        str   # Giữ nguyên cho TOÀN batch (không clear sớm)
    group_name:       str   # Hiển thị UI
    sse_q:            Queue # SSE event queue (per-batch)
    _ok, _err, _done_count: int
    _failed_items:    list  # Items cần Phase 2 retry
```

### 16.2 Download Modes

| Mode | `download_direct` | `save_to_storage` | Hành vi |
|------|-----------------|-------------------|---------|
| Direct | true | false | Tải về máy ngay |
| Storage | false | true | Chỉ lưu kho |
| Both | true | true | Lưu kho + tải về |

### 16.3 SSE Events từ Server

```javascript
// event: result
{
  index, status, task_id, filename, title,
  size, url, download_direct, save_to_storage,
  storage_saved, folder_id, expires_days
}

// event: result_retry  (video fail được retry thành công)
// event: progress      (per-item progress messages)
// event: batch_done    (toàn batch xong)
// event: heartbeat     (1s keep-alive)
```

### 16.4 Phase 2 Retry

```
Phase 1: N workers song song (theo hardware tier)
         ├─ Video 0: race → FFmpeg → done ✓
         ├─ Video 1: race → fail (4 attempts) ✗
         └─ Video 2: race → FFmpeg → done ✓

Phase 2: Failed items → rotation retry
         ├─ Video 1: API[0] → fail
         ├─ Video 1: API[1] → success ✓
         └─ Emit 'result_retry' SSE event
```

---

## 17. iOS Delivery {#17}

### 17.1 Vấn đề

Safari iOS block `window.open()` từ async SSE handler (mất user gesture context).

### 17.2 Fix: Tappable Panel

```javascript
// Sau khi batch xong trên iOS:
const panel = document.createElement('div');
panel.style = 'background:#0a2e1e; border:3px solid #0bf5b0; ...';
panel.innerHTML = `📱 iOS: Nhấn từng nút để lưu video vào Files`;

_iosLinks.forEach((lnk, i) => {
    const btn = document.createElement('a');
    btn.href   = lnk.dlUrl;
    btn.target = '_blank';
    btn.style  = 'display:block; background:#0bf5b0; color:#000; ...';
    btn.textContent = `⬇ Video ${i+1}: ${lnk.filename.substring(0,30)}...`;
    panel.appendChild(btn);
});
progressCard.appendChild(panel);
```

### 17.3 iOS User Flow

```
1. Batch hoàn thành
2. Panel xanh xuất hiện với N nút tappable
3. User nhấn từng nút → Safari mở tab mới
4. Long-press video → "Save to Photos" hoặc "Download"
```

---

## 18. AI Chatbot {#18}

```
POST /api/chat
Body: { message: "...", history: [...] }
Response: { reply: "..." }
```

Sử dụng Claude API (nếu có API key) hoặc rule-based responses. Floating widget góc phải màn hình. Hỗ trợ tiếng Việt và tiếng Anh.

---

## 19. Admin Dashboard {#19}

```
GET /dashboard   (require role=admin)
```

### 19.1 Tính năng

```
Stats overview:
  Visitors | Requests | Active batches/tasks | Storage usage

User management:
  Lock/unlock | Change password | Delete | Promote/demote | Set quota

Storage overview:
  Per-user breakdown | File count

Security:
  Blocked IPs list | Unblock IP

Live stream:
  GET /api/admin/dashboard_stream   SSE, update mỗi 3s
```

### 19.2 API Admin

```
GET  /api/admin/dashboard_stats
GET  /api/admin/dashboard_stream
GET  /api/admin/users
POST /api/admin/lock_user
POST /api/admin/set_quota          {username, quota_gb}  (0 = unlimited)
POST /api/admin/delete_user
POST /api/admin/promote_user
GET  /api/admin/storage_overview
GET  /api/security/status
POST /api/security/unblock
```

---

## 20. Bảo mật hệ thống {#20}

### 20.1 Các lớp bảo vệ

```
Layer 1: URL Validation
  Allowed: tiktok.com, vm.tiktok.com, vt.tiktok.com, m.tiktok.com

Layer 2: Guest Rate Limiting
  10 downloads/ngày/IP

Layer 3: Behavioral Guard
  N lần fail liên tiếp → Block IP (adaptive backoff)

Layer 4: Session Security
  Secret: auto-generated khi khởi động
  Cookies: HTTPOnly, SameSite

Layer 5: Input Sanitization
  Filename: sanitize chars, max 200 chars, unicode normalization
  Path traversal: os.path.basename() + chroot to storage dir
```

---

## 21. API Reference đầy đủ {#21}

### Core Download

```
POST /api/download_async
  {url, audio, logo_enabled, logo_base64, logo_x, logo_y,
   logo_width, logo_height, save_to_storage, download_direct,
   group_id, group_name, folder_id}
  → {task_id, status, owner, save_to_storage}

GET  /api/stream/<task_id>         SSE: status|heartbeat|storage_saved
GET  /api/get_result/<task_id>     Video binary (Range: bytes=X-Y supported)
GET  /api/task_status/<task_id>    {status, filename, size, title, error}
POST /api/cancel_task/<task_id>
POST /api/cancel_all
POST /api/check_urls               {urls[]} → {valid, invalid, duplicates}
GET  /api/get_video_info           {url} → {title, duration, author, thumbnail}
```

### Batch

```
POST /api/batch_start
  {urls[], audio, logo_*, download_direct, save_to_storage,
   group_name, folder_id}
  → {batch_id, total}

GET  /api/batch_stream/<batch_id>
  SSE: result | result_retry | progress | batch_done | heartbeat

POST /api/batch_cancel/<batch_id>
GET  /api/batch_status/<batch_id>
GET  /api/batch_item_msgs/<batch_id>/<index>
```

### Storage

```
GET  /api/storage/info
GET  /api/storage/list              → files[{filename, size, folder_id, ...}]
GET  /api/storage/download/<file>   Range supported
POST /api/storage/delete            {filenames:[...]}
POST /api/storage/download_zip
POST /api/storage/clear_all
POST /api/storage/download_group    {group_id}
```

### THUNDERWAVE™

```
GET /api/thunderwave/manifest/<task_id>
GET /api/thunderwave/manifest/storage/<filename>
→ {ok, protocol, filename, size, workers, chunk_size, ranges[]}
```

### KeepLink™

```
GET /api/keeplink/stream?sid=<id>   SSE: kl_heartbeat mỗi 15s
```

### Realtime Push

```
GET /api/realtime/subscribe
SSE: rt_connected | rt_heartbeat | storage_update | auth_change | system_notice
```

### WebRTC

```
POST /api/webrtc/offer    → {ok, session_id, answer, transport}
POST /api/webrtc/ice
GET  /api/webrtc/status/<session_id>
```

### Persist/Checkpoint

```
POST /api/persist/submit      Lưu checkpoint (không start batch)
POST /api/persist/mark_done   {pids:[...]}
GET  /api/persist/status      [{pid, name, status, total, batch_id}]
POST /api/persist/resume      Resume pending → BatchJob (download_direct=false)
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
GET  /api/admin/dashboard_stream   SSE, 3s update
GET  /api/admin/users
POST /api/admin/lock_user
POST /api/admin/set_quota          {username, quota_gb}
POST /api/admin/delete_user
POST /api/admin/promote_user
GET  /api/admin/storage_overview
GET  /api/security/status
POST /api/security/unblock
```

### System

```
GET  /api/health
GET  /api/client_info
GET  /api/speedtest_payload
POST /api/cleanup
POST /api/cleanup_ramdisk
POST /api/reload_cookies
POST /api/chat
GET  /api/visitors
GET  /api/link_stats
POST /api/server_reload
GET  /api/reload_stream
```

---

## 22. Cấu trúc thư mục {#22}

```
eyecore_downloader/
├── app.py                    (~9.700 dòng) — Server
├── index.html                (~9.400 dòng) — Frontend
│
├── user_storage/             — Kho video
│   └── {username}/
│       ├── _meta.json        ← metadata + folder_id
│       └── *.mp4
│
├── pending_persist/          — Checkpoint files
│   └── {pid}.json            ← {status: pending|done}
│
├── logs/                     — Server logs
│   ├── app.log
│   ├── error.log
│   └── process.log
│
├── cookies.txt               — TikTok cookies (optional)
├── users.json                — User database
├── visitors.json             — Visitor tracking
│
└── /dev/shm/ (Linux RAM disk)
    ├── raw_*.mp4             ← File thô từ API
    ├── proc_*.mp4            ← File sau FFmpeg
    ├── ensured_*.mp4         ← File sau ensure
    └── s0_repair_*.mp4       ← Pre-repair temp
```

---

## 23. Troubleshooting {#23}

### "Video báo hoàn thành nhưng chưa tải được"

```
Đã fix trong v10.5.0 (3 bugs):
  Bug 1: persist_submit tạo duplicate batch → RTPC fires sớm
  Bug 2: result_retry tăng finalizedCount trước download
  Bug 3: _resolvePoller không check allStarted

Nếu vẫn xảy ra:
  F12 → Console → tìm dòng "XONG" hoặc "_resolved = true"
  Kiểm tra finalizedCount vs total tại thời điểm đó
  Xóa cache trình duyệt → thử lại
```

### "Video không hiện trong Storage tab"

```
Đã fix trong v10.5.0:
  IIFE storageRefresh bây giờ gọi storageRenderFiles() đúng cách

Kiểm tra thủ công:
  Network tab → /api/storage/list → có file không?
  Console → window.storageRefresh() → tab có cập nhật không?
```

### "Video không vào đúng thư mục"

```
Đã fix trong v10.4.0:
  - Duplicate intercept bị xóa
  - folder_id gửi từ client → server → metadata → SSE → client
  - _sfSyncFromServer() sync lại khi storageRefresh

Kiểm tra:
  Server: cat user_storage/{user}/_meta.json | python3 -m json.tool
    → "folder_id": "..." phải có giá trị
  Client: localStorage.getItem('tikdown_sf_filemap')
    → {filename: folder_id} phải khớp
```

### "Truncation: FFmpeg output ngắn hơn input"

```
✗ [validate_output] REAL TRUNCATION: ratio=31% out=7.1s ref=23.1s

Xử lý tự động:
  S0: Pre-repair container (probesize=200M -c copy)
  S1: genpts + copyts + vsync vfr
  S2: Re-remux → MKV → encode
  S3: Force -t [duration]
  S4: Brute force probesize=500M
  S5: Trả raw file nếu playable (last resort)

→ 100% target: user luôn nhận được video
```

### "iOS không tải được video"

```
Không dùng window.open() nữa (bị Safari block từ async).
Giải pháp: Panel tappable sau khi batch xong.

Hướng dẫn:
  1. Đợi batch hoàn thành (panel xanh xuất hiện)
  2. Nhấn nút "⬇ Video N: ..."
  3. Safari mở tab mới hiển thị video
  4. Long-press → "Add to Photos" hoặc "Download"
```

### "SSE bị ngắt giữa chừng"

```
KeepLink™ v3 tự phục hồi:
  - Watchdog phát hiện trong 20s (server heartbeat 15s)
  - Backoff: 2→4→8→16s + jitter 300ms
  - Tab visible lại → reconnect ngay (200ms)
  - Batch có fallback polling qua /api/batch_status
```

### "Quota đầy"

```
User: Liên hệ admin
Admin: POST /api/admin/set_quota { "username": "alice", "quota_gb": 10 }
       quota_gb = 0 → unlimited
```

---

## 24. Changelog đầy đủ {#24}

### v10.5.0 (Tháng 5/2025) — CRITICAL FIXES

**Bug Fixes**:

| Bug | Nguyên nhân | Fix |
|-----|------------|-----|
| "Báo xong sớm" #1 | `persist_submit` chạy duplicate batch → RTPC fires sớm → client tưởng xong | Checkpoint-only: không start batch |
| "Báo xong sớm" #2 | `result_retry` tăng `finalizedCount` ngay khi retry thành công, không đợi download | Không tăng ở retry; đã tăng lúc fail |
| "Báo xong sớm" #3 | `_resolvePoller` không check `allStarted` → fire khi fetch chưa bắt đầu | Thêm `allEventsIn && allStarted` |
| Storage không hiện | IIFE `storageRefresh` không gọi `storageRenderFiles()` | Gọi đủ 4 functions |

**New Features**:
- Checkpoint system v2: `persist/submit` → `persist/mark_done` → `persist/resume`
- Auto-resume on login: RTPC `auth_change` → check pending → toast + resume
- `_fetchStarted` counter: track fetch khởi động để `tryResolve` chính xác
- `doPoll` retry path: thêm `pendingFetch` tracking + `.finally()` handler

---

### v10.4.0 — TURBO + EYECORE PROTOCOLS

**Bug Fixes**:
- Fix folder bug: Xóa duplicate `startDownload` intercept trong `_initStorageFolder`
- `storageOnDownloadDone` dùng `evtData.folder_id` từ server (không dùng `_pendingFolderId`)
- `_sfAssignFileExplicit`: không clear `_pendingFolderId` sớm
- `_sfBatchDone()`: clear sau khi toàn batch xong (không phải sau video đầu)
- `_sfSyncFromServer()`: sync server folder_id vào localStorage
- iOS: tappable link panel thay vì `window.open()` bị block

**New Protocols**:
- THUNDERWAVE™ v2.0: adaptive workers + 512KB speed probe + queue 1-at-a-time
- KeepLink™ v3: single SSE, no HTTP ping, watchdog 20s, < 1KB/min
- RTPC™: SSE push all state changes, auto-refresh, resume on login
- WebRTC Bridge v1.0: SDP signaling + THUNDERWAVE transport
- Background persist v1: checkpoint files + resume endpoint

**Performance**:
- Chunk: 8MB → max 64MB
- CPU: 90% → 100% cores (max 32)
- KeepLink heartbeat: 2s → 15s (-87% bandwidth)
- SSE batch heartbeat: 3s → 1s

---

### v10.3.0 — ROBUST PROCESSING

**Bug Fixes**:
- Truncation threshold: 35% → 25% (TikTok container sai metadata tới 70%)
- S0 pre-repair strategy (trước S1–S4)
- S5 raw file fallback (đảm bảo 100%)
- 720p upscale tại `_ensure_valid_mp4` Layer 1
- `-ignore_unknown` flag added

**Performance**:
- Chunk: 8MB → 64MB (8× throughput)
- CPU: 90% → 100% cores
- SSE heartbeat: 3s → 1s
- ffprobe cache 30s TTL
- Thread pool: 4 → min(10, CPU)
- probesize: default → 100M

---

## Phụ lục A — Glossary

| Thuật ngữ | Định nghĩa |
|-----------|-----------|
| **THUNDERWAVE™ v2** | Adaptive N-stream parallel delivery; queue 1-at-a-time; < bandwidth v1 |
| **KeepLink™ v3** | Single SSE; no HTTP ping; watchdog 20s; < 1KB/min |
| **RTPC™** | Realtime Push Channel; SSE broadcast mọi state change |
| **Checkpoint** | JSON file lưu URLs → resume sau browser đóng |
| **finalizedCount** | Video đã kết thúc (ok+fail). Desktop: tăng SAU khi blob download xong |
| **pendingFetch** | Số `fetch()` đang active |
| **_fetchStarted** | Tổng `_fetchAndSave` đã gọi — guard cho tryResolve |
| **allStarted** | `_fetchStarted >= total` |
| **tryResolve** | Check 4 điều kiện → "XONG" |
| **PATH A** | Stream copy (0–1s): H264 + ≥720p + no logo + no compress |
| **PATH B** | Full encode (1–30s): scale + logo + CRF23 |
| **S0–S5** | 6 strategies truncation recovery (S5 = last resort raw file) |
| **elst** | Edit List atom MP4 — gây TikTok metadata sai duration |
| **VFR** | Variable Frame Rate — nhiều TikTok video FPS không đều |
| **IIFE** | Immediately Invoked Function Expression |
| **Race download** | N APIs chạy song song → lấy kết quả nhanh nhất |
| **Rotation retry** | Thử từng API 1 lần theo vòng xoay sau khi race fail |

---

## Phụ lục B — Performance Benchmarks

| Scenario | Thời gian |
|----------|-----------|
| 1 video H264 ≥720p stream copy | 0.5–2s |
| 1 video encode 720p (i7-8th) | 3–10s |
| 1 video encode 720p (Celeron) | 10–30s |
| Batch 10 video (STRONG) | 15–60s |
| Batch 50 video | 5–15 phút |
| THUNDERWAVE™ 50MB (LAN 1Gbps, 6 streams) | ~1s |
| THUNDERWAVE™ 200MB (LAN 1Gbps, 8 streams) | ~4s |
| Storage list refresh | < 200ms |
| RTPC event lag | < 50ms LAN |
| KeepLink reconnect | < 300ms |
| Checkpoint submit (100 URLs) | < 500ms |
| Resume on login | < 1s detect, ~2s start |

---

*Cập nhật: v10.5.0 — Tháng 5 năm 2025*
