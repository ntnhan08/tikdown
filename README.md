# TikDown Pro — Tài liệu kỹ thuật v3.0 ⚡

> **Phiên bản**: 3.0 | **Tốc độ mục tiêu**: ↑20MB/s | **iOS**: 100%

---

## Mục lục
1. [Kiến trúc tổng thể](#1-kiến-trúc-tổng-thể)
2. [THUNDERWAVE™ v3.0](#2-thunderwave-v30-protocol)
3. [EYECORE KeepLink™ v4](#3-eyecore-keeplink-v4)
4. [Logo Verification Engine v2.0](#4-logo-verification-engine-v20)
5. [Hệ thống xử lý video x10](#5-hệ-thống-xử-lý-video-x10)
6. [Quản lý âm thanh](#6-quản-lý-âm-thanh)
7. [iOS Support 100%](#7-ios-support-100)
8. [Cài đặt & Khởi chạy](#8-cài-đặt--khởi-chạy)
9. [API Reference](#9-api-reference)

---

## 1. Kiến trúc tổng thể

<!--ARCH_SVG_START-->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 480" font-family="monospace,sans-serif">
  <rect width="900" height="480" fill="#0d1117" rx="12"/>
  <text x="450" y="36" text-anchor="middle" fill="#58a6ff" font-size="17" font-weight="bold">TikDown Pro — System Architecture v3.0</text>
  <!-- CLIENT -->
  <rect x="28" y="58" width="196" height="370" fill="#161b22" stroke="#30363d" rx="8"/>
  <text x="126" y="82" text-anchor="middle" fill="#79c0ff" font-size="13" font-weight="bold">CLIENT</text>
  <rect x="44" y="95" width="164" height="30" fill="#21262d" rx="5"/><text x="126" y="115" text-anchor="middle" fill="#e6edf3" font-size="11">🖥️ Desktop Browser (32 workers)</text>
  <rect x="44" y="133" width="164" height="30" fill="#21262d" rx="5"/><text x="126" y="153" text-anchor="middle" fill="#e6edf3" font-size="11">📱 Android Chrome (12 workers)</text>
  <rect x="44" y="171" width="164" height="30" fill="#21262d" rx="5"/><text x="126" y="191" text-anchor="middle" fill="#e6edf3" font-size="11">🍎 iOS Safari (4 workers) ✅</text>
  <rect x="44" y="215" width="164" height="42" fill="#1f3a5f" stroke="#388bfd" rx="5"/>
  <text x="126" y="233" text-anchor="middle" fill="#79c0ff" font-size="10" font-weight="bold">⚡ THUNDERWAVE™ v3.0</text>
  <text x="126" y="249" text-anchor="middle" fill="#56d364" font-size="10">32 streams | ↑20MB/s</text>
  <rect x="44" y="265" width="164" height="42" fill="#2d1f3a" stroke="#a371f7" rx="5"/>
  <text x="126" y="283" text-anchor="middle" fill="#d2a8ff" font-size="10" font-weight="bold">📡 KeepLink™ v4</text>
  <text x="126" y="299" text-anchor="middle" fill="#56d364" font-size="10">SSE + HTTP Ping | 1s watchdog</text>
  <rect x="44" y="315" width="164" height="42" fill="#1a2f1a" stroke="#56d364" rx="5"/>
  <text x="126" y="333" text-anchor="middle" fill="#56d364" font-size="10" font-weight="bold">💾 IndexedDB Audio Store</text>
  <text x="126" y="349" text-anchor="middle" fill="#8b949e" font-size="10">Auto-save 7 ngày | Inline SVG icons</text>
  <rect x="44" y="365" width="164" height="42" fill="#21262d" stroke="#ffa657" rx="5"/>
  <text x="126" y="383" text-anchor="middle" fill="#ffa657" font-size="10" font-weight="bold">🔬 Logo 3-layer verify (client)</text>
  <text x="126" y="399" text-anchor="middle" fill="#8b949e" font-size="10">10 retry max | strict → relax</text>
  <!-- Arrows -->
  <defs>
    <marker id="aB" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#388bfd"/></marker>
    <marker id="aG" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#56d364"/></marker>
  </defs>
  <line x1="226" y1="170" x2="342" y2="170" stroke="#388bfd" stroke-width="2" marker-end="url(#aB)"/>
  <text x="284" y="163" text-anchor="middle" fill="#388bfd" font-size="9">HTTPS</text>
  <line x1="342" y1="195" x2="226" y2="195" stroke="#56d364" stroke-width="2" marker-end="url(#aG)"/>
  <text x="284" y="210" text-anchor="middle" fill="#56d364" font-size="9">↑20MB/s video</text>
  <!-- SERVER -->
  <rect x="344" y="58" width="252" height="370" fill="#161b22" stroke="#30363d" rx="8"/>
  <text x="470" y="82" text-anchor="middle" fill="#79c0ff" font-size="13" font-weight="bold">FLASK SERVER (Python)</text>
  <rect x="360" y="96" width="220" height="34" fill="#21262d" rx="5"/>
  <text x="470" y="113" text-anchor="middle" fill="#ffa657" font-size="11" font-weight="bold">🔥 Video Processing Engine x10</text>
  <text x="470" y="126" text-anchor="middle" fill="#8b949e" font-size="9">FFmpeg threads=0 | Semaphore CPU×3</text>
  <rect x="360" y="138" width="220" height="34" fill="#21262d" rx="5"/>
  <text x="470" y="155" text-anchor="middle" fill="#ffa657" font-size="11" font-weight="bold">🛡️ Logo Verify Engine v2.0</text>
  <text x="470" y="168" text-anchor="middle" fill="#8b949e" font-size="9">3 lớp: stderr→pixel→variance | 10 retry</text>
  <rect x="360" y="180" width="220" height="34" fill="#21262d" rx="5"/>
  <text x="470" y="197" text-anchor="middle" fill="#ffa657" font-size="11" font-weight="bold">⚡ THUNDERWAVE™ Manifest v3</text>
  <text x="470" y="210" text-anchor="middle" fill="#8b949e" font-size="9">32 ranges | 128MB chunks | ↑20MB/s</text>
  <rect x="360" y="222" width="220" height="34" fill="#21262d" rx="5"/>
  <text x="470" y="239" text-anchor="middle" fill="#ffa657" font-size="11" font-weight="bold">📡 KeepLink SSE Stream</text>
  <text x="470" y="252" text-anchor="middle" fill="#8b949e" font-size="9">2s heartbeat | /api/keeplink/ping 3s</text>
  <rect x="360" y="264" width="220" height="34" fill="#21262d" rx="5"/>
  <text x="470" y="281" text-anchor="middle" fill="#ffa657" font-size="11" font-weight="bold">🎵 Audio Replace Engine</text>
  <text x="470" y="294" text-anchor="middle" fill="#8b949e" font-size="9">-map 0:v:0 -map 1:a:0 | IndexedDB</text>
  <rect x="360" y="306" width="220" height="34" fill="#21262d" rx="5"/>
  <text x="470" y="323" text-anchor="middle" fill="#ffa657" font-size="11" font-weight="bold">🔬 Speedtest Payload x10</text>
  <text x="470" y="336" text-anchor="middle" fill="#8b949e" font-size="9">10MB mobile / 20MB desktop</text>
  <rect x="360" y="348" width="220" height="42" fill="#1f3a5f" stroke="#388bfd" rx="5"/>
  <text x="470" y="365" text-anchor="middle" fill="#79c0ff" font-size="11" font-weight="bold">🗄️ Task + Batch Engine</text>
  <text x="470" y="379" text-anchor="middle" fill="#56d364" font-size="9">Parallel | CPU×3 semaphore | mmap</text>
  <text x="470" y="393" text-anchor="middle" fill="#56d364" font-size="9">X-Max-Speed: 20MB/s header</text>
  <!-- Arrow SERVER → TIKTOK -->
  <line x1="598" y1="170" x2="692" y2="170" stroke="#388bfd" stroke-width="2" marker-end="url(#aB)"/>
  <text x="645" y="163" text-anchor="middle" fill="#388bfd" font-size="9">API Fetch</text>
  <line x1="692" y1="195" x2="598" y2="195" stroke="#56d364" stroke-width="2" marker-end="url(#aG)"/>
  <text x="645" y="210" text-anchor="middle" fill="#56d364" font-size="9">Raw Video</text>
  <!-- TIKTOK -->
  <rect x="694" y="58" width="178" height="160" fill="#161b22" stroke="#30363d" rx="8"/>
  <text x="783" y="82" text-anchor="middle" fill="#79c0ff" font-size="13" font-weight="bold">TIKTOK API</text>
  <rect x="710" y="96" width="146" height="28" fill="#21262d" rx="5"/><text x="783" y="115" text-anchor="middle" fill="#e6edf3" font-size="10">📱 Video CDN</text>
  <rect x="710" y="132" width="146" height="28" fill="#21262d" rx="5"/><text x="783" y="151" text-anchor="middle" fill="#e6edf3" font-size="10">🔄 API v1/v2/v3 Race</text>
  <rect x="710" y="168" width="146" height="28" fill="#21262d" rx="5"/><text x="783" y="187" text-anchor="middle" fill="#e6edf3" font-size="10">🏎️ retry 5 lần</text>
  <!-- STORAGE -->
  <rect x="694" y="235" width="178" height="193" fill="#161b22" stroke="#30363d" rx="8"/>
  <text x="783" y="258" text-anchor="middle" fill="#79c0ff" font-size="13" font-weight="bold">STORAGE</text>
  <rect x="710" y="268" width="146" height="28" fill="#21262d" rx="5"/><text x="783" y="287" text-anchor="middle" fill="#e6edf3" font-size="10">📁 /tmp/fast (RAM disk)</text>
  <rect x="710" y="304" width="146" height="28" fill="#21262d" rx="5"/><text x="783" y="323" text-anchor="middle" fill="#e6edf3" font-size="10">🧹 Auto-cleanup 1h</text>
  <rect x="710" y="340" width="146" height="28" fill="#21262d" rx="5"/><text x="783" y="359" text-anchor="middle" fill="#e6edf3" font-size="10">💨 mmap zero-copy</text>
  <rect x="710" y="376" width="146" height="28" fill="#1f3a5f" stroke="#388bfd" rx="5"/><text x="783" y="395" text-anchor="middle" fill="#79c0ff" font-size="10">↑20MB/s | 128MB chunk</text>
  <!-- Footer -->
  <rect x="28" y="440" width="844" height="26" fill="#161b22" rx="5"/>
  <text x="450" y="457" text-anchor="middle" fill="#56d364" font-size="10">⚡ THUNDERWAVE™ v3.0 | 🔬 Logo Verify v2.0 | 📡 KeepLink™ v4 | 💾 IndexedDB | 🍎 iOS 100% | ↑20.0MB/s</text>
</svg>
<!--ARCH_SVG_END-->

---

## 2. THUNDERWAVE™ v3.0 Protocol

<!--TW_SVG_START-->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 300" font-family="monospace,sans-serif">
  <rect width="820" height="300" fill="#0d1117" rx="10"/>
  <text x="410" y="28" text-anchor="middle" fill="#58a6ff" font-size="14" font-weight="bold">⚡ THUNDERWAVE™ v3.0 — Parallel Download Flow</text>
  <defs>
    <marker id="tw1" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#388bfd"/></marker>
    <marker id="tw2" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#56d364"/></marker>
    <marker id="tw3" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#a371f7"/></marker>
    <marker id="tw4" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#ffa657"/></marker>
  </defs>
  <!-- File -->
  <rect x="20" y="50" width="110" height="200" fill="#1f3a5f" stroke="#388bfd" rx="6"/>
  <text x="75" y="72" text-anchor="middle" fill="#79c0ff" font-size="10" font-weight="bold">VIDEO FILE</text>
  <rect x="28" y="82"  width="94" height="22" fill="#388bfd" rx="3"/><text x="75" y="97"  text-anchor="middle" fill="#fff" font-size="8">Chunk 0 (0–4MB)</text>
  <rect x="28" y="110" width="94" height="22" fill="#2ea043" rx="3"/><text x="75" y="125" text-anchor="middle" fill="#fff" font-size="8">Chunk 1 (4–8MB)</text>
  <rect x="28" y="138" width="94" height="22" fill="#a371f7" rx="3"/><text x="75" y="153" text-anchor="middle" fill="#fff" font-size="8">Chunk 2 (8–12MB)</text>
  <rect x="28" y="166" width="94" height="22" fill="#ffa657" rx="3"/><text x="75" y="181" text-anchor="middle" fill="#fff" font-size="8">Chunk 3–N</text>
  <text x="75" y="208" text-anchor="middle" fill="#56d364" font-size="8">Desktop: 32</text>
  <text x="75" y="222" text-anchor="middle" fill="#79c0ff" font-size="8">Android: 12</text>
  <text x="75" y="236" text-anchor="middle" fill="#ffa657" font-size="8">iOS: 4</text>
  <!-- Arrows chunk → worker -->
  <line x1="132" y1="93"  x2="195" y2="115" stroke="#388bfd" stroke-width="1.8" marker-end="url(#tw1)"/>
  <line x1="132" y1="121" x2="195" y2="155" stroke="#2ea043" stroke-width="1.8" marker-end="url(#tw2)"/>
  <line x1="132" y1="149" x2="195" y2="195" stroke="#a371f7" stroke-width="1.8" marker-end="url(#tw3)"/>
  <line x1="132" y1="177" x2="195" y2="235" stroke="#ffa657" stroke-width="1.8" marker-end="url(#tw4)"/>
  <!-- Workers -->
  <rect x="197" y="100" width="135" height="28" fill="#388bfd22" stroke="#388bfd" rx="5"/><text x="264" y="118" text-anchor="middle" fill="#79c0ff" font-size="9">Worker 0 — fetch + retry×3</text>
  <rect x="197" y="140" width="135" height="28" fill="#2ea04322" stroke="#2ea043" rx="5"/><text x="264" y="158" text-anchor="middle" fill="#56d364" font-size="9">Worker 1 — fetch + retry×3</text>
  <rect x="197" y="180" width="135" height="28" fill="#a371f722" stroke="#a371f7" rx="5"/><text x="264" y="198" text-anchor="middle" fill="#d2a8ff" font-size="9">Worker 2 — fetch + retry×3</text>
  <rect x="197" y="220" width="135" height="28" fill="#ffa65722" stroke="#ffa657" rx="5"/><text x="264" y="238" text-anchor="middle" fill="#ffa657" font-size="9">Worker N — fetch + retry×3</text>
  <!-- Speed probe -->
  <rect x="197" y="262" width="135" height="26" fill="#21262d" stroke="#56d364" rx="5"/>
  <text x="264" y="276" text-anchor="middle" fill="#56d364" font-size="9">🏎️ Speed Probe 20MB</text>
  <text x="264" y="286" text-anchor="middle" fill="#8b949e" font-size="8">→ chọn workers tối ưu</text>
  <!-- Arrows workers → assembler -->
  <line x1="334" y1="114" x2="410" y2="155" stroke="#388bfd" stroke-width="1.5" marker-end="url(#tw1)"/>
  <line x1="334" y1="154" x2="410" y2="168" stroke="#2ea043" stroke-width="1.5" marker-end="url(#tw2)"/>
  <line x1="334" y1="194" x2="410" y2="182" stroke="#a371f7" stroke-width="1.5" marker-end="url(#tw3)"/>
  <line x1="334" y1="234" x2="410" y2="196" stroke="#ffa657" stroke-width="1.5" marker-end="url(#tw4)"/>
  <!-- Assembler -->
  <rect x="412" y="105" width="130" height="120" fill="#161b22" stroke="#56d364" stroke-width="1.5" rx="6"/>
  <text x="477" y="126" text-anchor="middle" fill="#56d364" font-size="11" font-weight="bold">ASSEMBLER</text>
  <text x="477" y="144" text-anchor="middle" fill="#8b949e" font-size="8">Uint8Array(fileSize)</text>
  <text x="477" y="159" text-anchor="middle" fill="#8b949e" font-size="8">set(chunk, offset)</text>
  <rect x="424" y="168" width="106" height="18" fill="#1f3a5f" rx="3"/><text x="477" y="181" text-anchor="middle" fill="#79c0ff" font-size="8">Promise.all(workers)</text>
  <rect x="424" y="192" width="106" height="20" fill="#2ea04322" stroke="#56d364" rx="3"/><text x="477" y="206" text-anchor="middle" fill="#56d364" font-size="8">Blob → createObjectURL</text>
  <!-- Arrow assembler → browser -->
  <line x1="544" y1="165" x2="620" y2="165" stroke="#56d364" stroke-width="2" marker-end="url(#tw2)"/>
  <!-- Browser -->
  <rect x="622" y="100" width="170" height="150" fill="#1a2f1a" stroke="#56d364" rx="6"/>
  <text x="707" y="124" text-anchor="middle" fill="#56d364" font-size="12" font-weight="bold">BROWSER SAVE</text>
  <text x="707" y="144" text-anchor="middle" fill="#8b949e" font-size="9">📥 a.download click</text>
  <text x="707" y="160" text-anchor="middle" fill="#ffa657" font-size="9">🍎 iOS: blob URL path</text>
  <text x="707" y="176" text-anchor="middle" fill="#8b949e" font-size="9">window.open fallback</text>
  <rect x="634" y="190" width="146" height="22" fill="#1f3a5f" rx="3"/>
  <text x="707" y="205" text-anchor="middle" fill="#79c0ff" font-size="9" font-weight="bold">↑20MB/s achieved ✅</text>
  <text x="707" y="222" text-anchor="middle" fill="#8b949e" font-size="8">X-Max-Speed header</text>
  <text x="707" y="237" text-anchor="middle" fill="#8b949e" font-size="8">128MB server chunks</text>
</svg>
<!--TW_SVG_END-->

### So sánh phiên bản

| Thông số | v1.0 | v2.0 | **v3.0 ⚡** |
|---|---|---|---|
| iOS workers | 1 | 1 | **4** |
| Android workers | 4 | 2 | **12** |
| Desktop workers | 6–8 | 2–8 | **12–32** |
| Speedtest payload | 512KB | 512KB | **10–20MB** |
| Retry per chunk | ✗ | ✗ | **3x backoff** |
| iOS dedicated path | ✗ | ✗ | **✅** |
| Server chunk | 16MB | 16MB | **32–128MB** |
| Target speed | ~2MB/s | ~5MB/s | **↑20MB/s** |

---

## 3. EYECORE KeepLink™ v4

<!--KL_SVG_START-->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 260" font-family="monospace,sans-serif">
  <rect width="780" height="260" fill="#0d1117" rx="10"/>
  <text x="390" y="26" text-anchor="middle" fill="#d2a8ff" font-size="13" font-weight="bold">📡 EYECORE KeepLink™ v4 — Connection State Machine</text>
  <defs>
    <marker id="kG" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#56d364"/></marker>
    <marker id="kR" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#f85149"/></marker>
    <marker id="kP" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#a371f7"/></marker>
    <marker id="kO" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#ffa657"/></marker>
  </defs>
  <!-- States -->
  <ellipse cx="120" cy="110" rx="78" ry="32" fill="#1f3a5f" stroke="#388bfd" stroke-width="1.5"/>
  <text x="120" y="106" text-anchor="middle" fill="#79c0ff" font-size="10" font-weight="bold">CONNECTING</text>
  <text x="120" y="120" text-anchor="middle" fill="#8b949e" font-size="8">EventSource open</text>

  <ellipse cx="360" cy="80" rx="88" ry="36" fill="#1a2f1a" stroke="#56d364" stroke-width="2"/>
  <text x="360" y="73" text-anchor="middle" fill="#56d364" font-size="11" font-weight="bold">✅ CONNECTED</text>
  <text x="360" y="88" text-anchor="middle" fill="#8b949e" font-size="8">SSE open + HTTP Ping</text>
  <text x="360" y="101" text-anchor="middle" fill="#56d364" font-size="9">Heartbeat: 2s ⚡</text>
  <text x="360" y="113" text-anchor="middle" fill="#56d364" font-size="8">Ping backup: 3s</text>

  <ellipse cx="360" cy="195" rx="78" ry="30" fill="#2d1f1a" stroke="#ffa657" stroke-width="1.5"/>
  <text x="360" y="191" text-anchor="middle" fill="#ffa657" font-size="10" font-weight="bold">⚠️ STALE</text>
  <text x="360" y="206" text-anchor="middle" fill="#8b949e" font-size="8">Không HB trong 3s ⚡</text>

  <ellipse cx="620" cy="110" rx="92" ry="32" fill="#2d1f1f" stroke="#f85149" stroke-width="1.5"/>
  <text x="620" y="106" text-anchor="middle" fill="#f85149" font-size="10" font-weight="bold">🔁 RECONNECTING</text>
  <text x="620" y="120" text-anchor="middle" fill="#8b949e" font-size="8">Backoff: 100ms×2^n max 3s</text>

  <!-- Transitions -->
  <line x1="198" y1="100" x2="270" y2="88" stroke="#56d364" stroke-width="1.5" marker-end="url(#kG)"/>
  <text x="234" y="88" text-anchor="middle" fill="#56d364" font-size="8">onopen</text>

  <line x1="360" y1="116" x2="360" y2="165" stroke="#ffa657" stroke-width="1.5" marker-end="url(#kO)"/>
  <text x="390" y="145" fill="#ffa657" font-size="8">HB timeout 3s</text>

  <line x1="437" y1="195" x2="540" y2="140" stroke="#f85149" stroke-width="1.5" marker-end="url(#kR)"/>
  <text x="495" y="178" fill="#f85149" font-size="8">close+retry</text>

  <line x1="528" y1="110" x2="198" y2="110" stroke="#a371f7" stroke-width="1.5" stroke-dasharray="5,3" marker-end="url(#kP)"/>
  <text x="360" y="130" text-anchor="middle" fill="#a371f7" font-size="8">reconnect (50ms delay)</text>

  <line x1="448" y1="80" x2="528" y2="98" stroke="#f85149" stroke-width="1.5" marker-end="url(#kR)"/>
  <text x="490" y="74" fill="#f85149" font-size="8">onerror</text>

  <!-- HTTP Ping panel -->
  <rect x="28" y="228" width="724" height="24" fill="#161b22" stroke="#56d364" rx="5"/>
  <text x="390" y="244" text-anchor="middle" fill="#56d364" font-size="9">
    ⚡ HTTP Ping backup: /api/keeplink/ping mỗi 3s | AbortSignal.timeout(2s) | fails-- khi thành công
  </text>
</svg>
<!--KL_SVG_END-->

### So sánh v3 → v4

| Thông số | v3 | **v4 ⚡** |
|---|---|---|
| Heartbeat server | 15s | **2s** |
| Watchdog interval | 5s | **1s** |
| Stale timeout | 20s | **3s** |
| Reconnect tối đa | 16s | **3s** |
| HTTP Ping backup | ✗ | **✅ mỗi 3s** |
| Delay sau tab focus | 200ms | **50ms** |
| Server ping interval | 4–8s | **1–3s** |

---

## 4. Logo Verification Engine v2.0

<!--LV_SVG_START-->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 320" font-family="monospace,sans-serif">
  <rect width="820" height="320" fill="#0d1117" rx="10"/>
  <text x="410" y="26" text-anchor="middle" fill="#ffa657" font-size="13" font-weight="bold">🔬 Logo Verification Engine v2.0 — 3-Layer Pipeline (10 retries)</text>
  <defs>
    <marker id="lvO" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#ffa657"/></marker>
    <marker id="lvG" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#56d364"/></marker>
    <marker id="lvR" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#f85149"/></marker>
  </defs>
  <!-- Encode box -->
  <rect x="20" y="55" width="138" height="68" fill="#1f3a5f" stroke="#388bfd" rx="6"/>
  <text x="89" y="76" text-anchor="middle" fill="#79c0ff" font-size="11" font-weight="bold">FFmpeg Encode</text>
  <text x="89" y="92" text-anchor="middle" fill="#8b949e" font-size="8">overlay + logo filter</text>
  <text x="89" y="106" text-anchor="middle" fill="#8b949e" font-size="8">threads=0 | ultrafast</text>
  <text x="89" y="116" text-anchor="middle" fill="#56d364" font-size="8">libx264 fallback</text>
  <!-- Arrow encode → L1 -->
  <line x1="160" y1="89" x2="205" y2="89" stroke="#ffa657" stroke-width="2" marker-end="url(#lvO)"/>
  <!-- L1 -->
  <rect x="207" y="50" width="148" height="78" fill="#2d1f1a" stroke="#ffa657" stroke-width="1.5" rx="6"/>
  <text x="281" y="70" text-anchor="middle" fill="#ffa657" font-size="11" font-weight="bold">L1: stderr scan</text>
  <text x="281" y="86" text-anchor="middle" fill="#8b949e" font-size="8">~0ms | instantaneous</text>
  <text x="281" y="100" text-anchor="middle" fill="#8b949e" font-size="8">"overlay" / "filtergraph"</text>
  <text x="281" y="114" text-anchor="middle" fill="#8b949e" font-size="8">"codec=none" / "image2"</text>
  <text x="281" y="124" text-anchor="middle" fill="#8b949e" font-size="8">10 signal patterns</text>
  <!-- L1 PASS → L2 -->
  <line x1="357" y1="89" x2="400" y2="89" stroke="#56d364" stroke-width="1.5" marker-end="url(#lvG)"/>
  <text x="378" y="82" text-anchor="middle" fill="#56d364" font-size="7">PASS</text>
  <!-- L1 FAIL -->
  <line x1="281" y1="128" x2="281" y2="268" stroke="#f85149" stroke-width="1.5" stroke-dasharray="4,3" marker-end="url(#lvR)"/>
  <!-- L2 -->
  <rect x="402" y="50" width="152" height="88" fill="#2d1f3a" stroke="#a371f7" stroke-width="1.5" rx="6"/>
  <text x="478" y="70" text-anchor="middle" fill="#d2a8ff" font-size="11" font-weight="bold">L2: Frame Extract</text>
  <text x="478" y="86" text-anchor="middle" fill="#8b949e" font-size="8">~200ms | ffmpeg -vframes 1</text>
  <text x="478" y="100" text-anchor="middle" fill="#8b949e" font-size="8">sample tại giữa video</text>
  <text x="478" y="114" text-anchor="middle" fill="#8b949e" font-size="8">crop vùng logo (sx/sy)</text>
  <text x="478" y="128" text-anchor="middle" fill="#8b949e" font-size="8">Pillow RGBA pixel</text>
  <!-- L2 PASS → L3 -->
  <line x1="556" y1="89" x2="598" y2="89" stroke="#56d364" stroke-width="1.5" marker-end="url(#lvG)"/>
  <text x="576" y="82" text-anchor="middle" fill="#56d364" font-size="7">PASS</text>
  <!-- L2 FAIL -->
  <line x1="478" y1="138" x2="478" y2="268" stroke="#f85149" stroke-width="1.5" stroke-dasharray="4,3" marker-end="url(#lvR)"/>
  <!-- L3 -->
  <rect x="600" y="50" width="196" height="88" fill="#1a2f1a" stroke="#56d364" stroke-width="1.5" rx="6"/>
  <text x="698" y="70" text-anchor="middle" fill="#56d364" font-size="11" font-weight="bold">L3: Area Variance</text>
  <text x="698" y="86" text-anchor="middle" fill="#8b949e" font-size="8">statistics.variance(pixels_L)</text>
  <text x="698" y="100" text-anchor="middle" fill="#8b949e" font-size="8">threshold: var &lt; 15 = FAIL</text>
  <text x="698" y="114" text-anchor="middle" fill="#8b949e" font-size="8">solid region = logo missing</text>
  <text x="698" y="128" text-anchor="middle" fill="#56d364" font-size="8">strict=False sau 7 retries</text>
  <!-- L3 PASS -->
  <line x1="698" y1="138" x2="698" y2="166" stroke="#56d364" stroke-width="2" marker-end="url(#lvG)"/>
  <rect x="614" y="168" width="168" height="30" fill="#1a2f1a" stroke="#56d364" rx="5"/>
  <text x="698" y="183" text-anchor="middle" fill="#56d364" font-size="11" font-weight="bold">✅ LOGO VERIFIED</text>
  <text x="698" y="194" text-anchor="middle" fill="#8b949e" font-size="7">→ giao file cho client</text>
  <!-- L3 FAIL -->
  <line x1="698" y1="198" x2="698" y2="268" stroke="#f85149" stroke-width="1.5" stroke-dasharray="4,3" marker-end="url(#lvR)"/>
  <!-- Retry pool -->
  <rect x="110" y="270" width="590" height="40" fill="#2d1f1f" stroke="#f85149" stroke-width="1.5" rx="6"/>
  <text x="405" y="287" text-anchor="middle" fill="#f85149" font-size="11" font-weight="bold">🔁 RETRY ENGINE — tối đa 10 lần (từ 5) | Fallback: libx264 bypass HW bug</text>
  <text x="405" y="302" text-anchor="middle" fill="#8b949e" font-size="8">Attempt 1-7: strict | 8-10: relax | Backoff 300ms×n | size_verify + pixel_verify kết hợp</text>
</svg>
<!--LV_SVG_END-->

**Công thức phát hiện logo bị mất:**
```python
pixels = list(logo_region.convert('L').getdata())
variance = statistics.variance(pixels)
if variance < 15:
    # Logo region là solid color → logo không hiển thị
    return False, f'logo_region_solid(var={variance:.1f})'
```

---

## 5. Hệ thống xử lý video x10

<!--VP_SVG_START-->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 180" font-family="monospace,sans-serif">
  <rect width="780" height="180" fill="#0d1117" rx="10"/>
  <text x="390" y="24" text-anchor="middle" fill="#ffa657" font-size="13" font-weight="bold">🔥 Video Processing Pipeline x10 Upgrade</text>
  <defs>
    <marker id="vp" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0L0,6L7,3z" fill="#ffa657"/></marker>
  </defs>
  <rect x="12" y="42" width="125" height="100" fill="#1f3a5f" stroke="#388bfd" rx="5"/>
  <text x="74" y="60" text-anchor="middle" fill="#79c0ff" font-size="9" font-weight="bold">① DOWNLOAD</text>
  <text x="74" y="75" text-anchor="middle" fill="#8b949e" font-size="7">Race v1/v2/v3</text>
  <text x="74" y="88" text-anchor="middle" fill="#8b949e" font-size="7">retry 5 lần</text>
  <text x="74" y="101" text-anchor="middle" fill="#56d364" font-size="7">parallel prefetch</text>
  <text x="74" y="114" text-anchor="middle" fill="#56d364" font-size="7">FAST_TMPDIR</text>
  <text x="74" y="130" text-anchor="middle" fill="#ffa657" font-size="7">Semaphore: CPU×3</text>

  <line x1="139" y1="92" x2="154" y2="92" stroke="#ffa657" stroke-width="2" marker-end="url(#vp)"/>

  <rect x="156" y="42" width="125" height="100" fill="#1f3a5f" stroke="#388bfd" rx="5"/>
  <text x="218" y="60" text-anchor="middle" fill="#79c0ff" font-size="9" font-weight="bold">② PROBE</text>
  <text x="218" y="75" text-anchor="middle" fill="#8b949e" font-size="7">ffprobe JSON</text>
  <text x="218" y="88" text-anchor="middle" fill="#8b949e" font-size="7">codec/res/fps</text>
  <text x="218" y="101" text-anchor="middle" fill="#8b949e" font-size="7">VFR detect</text>
  <text x="218" y="114" text-anchor="middle" fill="#56d364" font-size="7">HW tier detect</text>
  <text x="218" y="127" text-anchor="middle" fill="#56d364" font-size="7">HW encoder probe</text>

  <line x1="283" y1="92" x2="298" y2="92" stroke="#ffa657" stroke-width="2" marker-end="url(#vp)"/>

  <rect x="300" y="42" width="140" height="100" fill="#2d1f3a" stroke="#a371f7" rx="5"/>
  <text x="370" y="60" text-anchor="middle" fill="#d2a8ff" font-size="9" font-weight="bold">③ ENCODE x10</text>
  <text x="370" y="75" text-anchor="middle" fill="#8b949e" font-size="7">threads=0 (auto-max)</text>
  <text x="370" y="88" text-anchor="middle" fill="#8b949e" font-size="7">NVENC/VAAPI/VTB/CPU</text>
  <text x="370" y="101" text-anchor="middle" fill="#8b949e" font-size="7">ultrafast + zerolatency</text>
  <text x="370" y="114" text-anchor="middle" fill="#56d364" font-size="7">Logo 3-layer verify</text>
  <text x="370" y="127" text-anchor="middle" fill="#56d364" font-size="7">10 retries guaranteed</text>

  <line x1="442" y1="92" x2="458" y2="92" stroke="#ffa657" stroke-width="2" marker-end="url(#vp)"/>

  <rect x="460" y="42" width="130" height="100" fill="#2d1a1a" stroke="#f85149" rx="5"/>
  <text x="525" y="60" text-anchor="middle" fill="#f85149" font-size="9" font-weight="bold">④ VALIDATE</text>
  <text x="525" y="75" text-anchor="middle" fill="#8b949e" font-size="7">size &gt; 0.5MB</text>
  <text x="525" y="88" text-anchor="middle" fill="#8b949e" font-size="7">ffprobe video stream</text>
  <text x="525" y="101" text-anchor="middle" fill="#8b949e" font-size="7">duration ratio 25%</text>
  <text x="525" y="114" text-anchor="middle" fill="#56d364" font-size="7">stderr error scan</text>
  <text x="525" y="127" text-anchor="middle" fill="#56d364" font-size="7">MULTI-STRATEGY retry</text>

  <line x1="592" y1="92" x2="608" y2="92" stroke="#ffa657" stroke-width="2" marker-end="url(#vp)"/>

  <rect x="610" y="42" width="155" height="100" fill="#1a2f1a" stroke="#56d364" rx="5"/>
  <text x="687" y="60" text-anchor="middle" fill="#56d364" font-size="9" font-weight="bold">⑤ DELIVER ↑20MB/s</text>
  <text x="687" y="75" text-anchor="middle" fill="#8b949e" font-size="7">mmap zero-copy</text>
  <text x="687" y="88" text-anchor="middle" fill="#8b949e" font-size="7">128MB chunks server</text>
  <text x="687" y="101" text-anchor="middle" fill="#8b949e" font-size="7">+faststart moov</text>
  <text x="687" y="114" text-anchor="middle" fill="#56d364" font-size="7">X-Max-Speed: 20MB/s</text>
  <text x="687" y="127" text-anchor="middle" fill="#56d364" font-size="7">iOS MIME codecs hint</text>

  <rect x="12" y="152" width="753" height="18" fill="#161b22" rx="3"/>
  <text x="390" y="165" text-anchor="middle" fill="#56d364" font-size="8">
    CPU: max(8, cpu_count×2, 128) | FFmpeg: threads=0 | SEMAPHORE: max(16, CPU×3) | LOGO_RETRIES: 10 | CHUNK_MAX: 128MB
  </text>
</svg>
<!--VP_SVG_END-->

---

## 6. Quản lý âm thanh

### Audio Replace — xóa âm thanh gốc và thêm âm thanh mới

```bash
# Lệnh FFmpeg đảm bảo 100% xóa audio gốc:
ffmpeg -y \
  -i  video.mp4           # Input 0: video (audio gốc BỊ BỎ)
  -i  custom_audio.mp3    # Input 1: audio người dùng chọn
  -map 0:v:0              # Chỉ lấy VIDEO từ input 0
  -map 1:a:0              # Chỉ lấy AUDIO từ input 1 (audio mới)
  -c:v copy               # Copy video không re-encode
  -c:a aac -b:a 192k      # AAC 192kbps
  -ar 44100               # Sample rate chuẩn
  -shortest               # Cắt theo độ dài ngắn hơn
  output.mp4
```

> ⚠️ **Quan trọng**: Không dùng `-map 0` vì sẽ mang cả audio gốc theo. Phải dùng `-map 0:v:0` để chỉ lấy stream video.

### Audio Auto-Save (IndexedDB)

```
Chọn file → _saveAudioToIDB(file) → IndexedDB.put(ArrayBuffer)
                                                 ↓
Tải trang lần sau → _autoLoadSavedAudio() → IndexedDB.get()
                                                 ↓
window._addAudioFile = File(name, ArrayBuffer)  (sẵn sàng dùng)
                                                 ↓
Xóa file → clearAddAudio() → IndexedDB.delete() → null
```

**Giới hạn**: Lưu tối đa 7 ngày. Hỗ trợ: MP3, WAV, OGG, FLAC, M4A, AAC, OPUS.

---

## 7. iOS Support 100%

| Vấn đề | Nguyên nhân | Giải pháp |
|---|---|---|
| Không tải được | Safari hạn chế parallel fetch | 4 dedicated workers |
| File không save | `<a download>` bị chặn | `_iosDownload()` → blob URL |
| MIME mơ hồ | Safari strict MIME | `video/mp4; codecs="avc1..."` |
| Tốc độ chậm | Chunk quá nhỏ | 4MB chunk (từ 1MB) |
| SSE ngắt thường | Mạng iOS không ổn định | HTTP Ping backup 3s |
| Audio không lưu | File object không persist | IndexedDB ArrayBuffer |
| Blank download | window.open bị block | User gesture chain |

---

## 8. Cài đặt & Khởi chạy

```bash
# Dependencies
pip install flask flask-cors pillow yt-dlp

# FFmpeg
sudo apt install ffmpeg        # Ubuntu/Debian
brew install ffmpeg            # macOS

# Chạy
python app.py
# → http://localhost:5000
```

**Yêu cầu**: Python 3.10+ | FFmpeg 4.4+ | RAM 512MB+ | CPU 2+ cores

---

## 9. API Reference

| Endpoint | Method | Mô tả | Tốc độ |
|---|---|---|---|
| `/api/download` | POST | Tải 1 video | — |
| `/api/batch_download` | POST | Batch tải nhiều video | — |
| `/api/task_status/<id>` | GET | Trạng thái task | — |
| `/api/get_result/<id>` | GET | Tải file kết quả | **↑20MB/s** |
| `/api/thunderwave/manifest/<id>` | GET | THUNDERWAVE™ v3.0 manifest | — |
| `/api/keeplink/stream` | GET (SSE) | Heartbeat 2s | — |
| `/api/keeplink/ping` | GET/POST | HTTP Ping backup | — |
| `/api/audio/merge_video` | POST | Replace audio | — |
| `/api/speedtest_payload` | GET | Probe 10/20MB | **↑20MB/s** |

---

*© TikDown Pro v3.0 — THUNDERWAVE™ v3.0 / EYECORE KeepLink™ v4 / Logo Verify Engine v2.0*
