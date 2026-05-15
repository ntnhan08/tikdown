import os
import re
import json
import time
import shutil
import tempfile
import urllib.parse
import asyncio
import hashlib
import mmap
import subprocess
import sys
import threading
import queue as _queue_module
from datetime import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import uuid
from io import BytesIO
from pathlib import Path
import base64

import requests
import logging
import logging.handlers
from flask import Flask, render_template, request, jsonify, Response, send_file, after_this_request, stream_with_context, session, redirect, url_for
import hmac
import re as _re_auth
from functools import wraps

# Optional: flask-compress để gzip tự động (tăng tốc mạng)
try:
    from flask_compress import Compress as _FlaskCompress
    FLASK_COMPRESS_AVAILABLE = True
except ImportError:
    _FlaskCompress = None
    FLASK_COMPRESS_AVAILABLE = False

# Manual gzip fallback
import gzip as _gzip_mod

# Optional imports — không crash nếu thiếu
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    yt_dlp = None
    YT_DLP_AVAILABLE = False

try:
    from flask_cors import CORS as _CORS
    def CORS(app, **kw):
        _CORS(app, supports_credentials=True,
              origins=['*'],
              allow_headers=['Content-Type', 'Authorization', 'X-Requested-With'],
              methods=['GET', 'POST', 'OPTIONS', 'DELETE', 'PUT'],
              **kw)
except ImportError:
    def CORS(app, **kw):
        @app.after_request
        def _cors(response):
            origin = request.headers.get('Origin', '*')
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,X-Requested-With'
            response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS,DELETE,PUT'
            return response

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None
    HTTPX_AVAILABLE = False

# ---------- TỰ ĐỘNG KIỂM TRA & CẬP NHẬT THƯ VIỆN ----------
_BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR         = os.path.join(_BASE_DIR, 'logs')
_SERVER_START_TIME = time.time()   # ← dùng cho dashboard uptime
_REQ_FILE   = os.path.join(_BASE_DIR, 'requirements.txt')
_VISITORS_FILE = os.path.join(_BASE_DIR, 'visitors.json')
_visitors_lock = threading.Lock()
os.makedirs(_LOG_DIR, exist_ok=True)   # Đảm bảo thư mục log tồn tại

# Packages to auto-update when outdated
_PACKAGES_TO_UPDATE = [
    'yt-dlp', 'flask', 'flask-compress', 'flask-cors',
    'requests', 'httpx', 'psutil', 'TikTokApi',
]

def _update_print(msg: str, color: str = '\033[93m'):
    print(f"{color}📦 [UPDATE] {msg}\033[0m", flush=True)

def _export_requirements():
    """Xuất pip freeze → requirements.txt ngay sau khi update."""
    try:
        r = subprocess.run([sys.executable, '-m', 'pip', 'freeze'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            with open(_REQ_FILE, 'w', encoding='utf-8') as f:
                f.write(f"# TikDown auto-generated — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(r.stdout)
            _update_print(f"✅ requirements.txt xuất xong → {_REQ_FILE}", '\033[92m')
        else:
            _update_print("⚠️  pip freeze thất bại", '\033[91m')
    except Exception as e:
        _update_print(f"⚠️  export requirements lỗi: {e}", '\033[91m')

def check_and_update_dependencies():
    """
    🟡 Tự động kiểm tra + cập nhật toàn bộ thư viện khi server khởi động.
    Sau khi xong xuất requirements.txt với phiên bản chính xác.
    Chạy trong background thread — không block Flask.
    """
    try:
        _update_print("Đang kiểm tra phiên bản thư viện...")
        r_list = subprocess.run(
            [sys.executable, '-m', 'pip', 'list', '--outdated', '--format=json'],
            capture_output=True, text=True, timeout=60
        )
        outdated_map = {}
        if r_list.returncode == 0:
            try:
                for pkg in json.loads(r_list.stdout or '[]'):
                    outdated_map[pkg['name'].lower()] = pkg
            except Exception:
                pass

        updated, skipped = [], []
        for pkg in _PACKAGES_TO_UPDATE:
            if pkg.lower() in outdated_map:
                info = outdated_map[pkg.lower()]
                old_v, new_v = info.get('version','?'), info.get('latest_version','?')
                _update_print(f"  Cập nhật {pkg}: {old_v} → {new_v}...")
                r_up = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '--upgrade', pkg,
                     '--quiet', '--no-warn-script-location'],
                    capture_output=True, text=True, timeout=120
                )
                if r_up.returncode == 0:
                    updated.append(f"{pkg}=={new_v}")
                    _update_print(f"  ✅ {pkg} → {new_v}", '\033[92m')
                else:
                    _update_print(f"  ⚠️  {pkg} thất bại: {r_up.stderr[-80:]}", '\033[91m')
            else:
                skipped.append(pkg)

        if updated:
            _update_print(f"✅ Đã cập nhật {len(updated)}: {', '.join(updated)}", '\033[92m')
        else:
            _update_print("✅ Tất cả thư viện đã mới nhất.", '\033[92m')

        # Luôn xuất requirements.txt sau khi kiểm tra xong
        _export_requirements()

    except Exception as e:
        _update_print(f"⚠️  Lỗi kiểm tra: {e}", '\033[91m')
        # Vẫn xuất requirements.txt dù có lỗi
        _export_requirements()

# ── Chạy ngay khi server khởi động (background) ───────────────────────────────
threading.Thread(target=check_and_update_dependencies, daemon=True, name='auto-update').start()

# Try to import TikTokApi (optional dependency)
try:
    from TikTokApi import TikTokApi
    TIKTOK_API_AVAILABLE = True
except ImportError:
    TIKTOK_API_AVAILABLE = False



# ══════════════════════════════════════════════════════════════════════════════
# 🔐 HỆ THỐNG TÀI KHOẢN NGƯỜI DÙNG — Dr. An + Dr. Bình
# Lưu trữ: users.json | Auth: Flask session | Password: SHA-256 + salt
# ══════════════════════════════════════════════════════════════════════════════
_USERS_FILE = os.path.join(_BASE_DIR, 'users.json')
_users_rw_lock = threading.Lock()

# ── Schema mặc định ──────────────────────────────────────────────────────────
_DEFAULT_USERS_DB = {
    "users": {},          # username → user_record
    "guest_downloads": {} # ip → {count, date}
}

def _load_users_db() -> dict:
    """Đọc users.json an toàn."""
    try:
        if os.path.exists(_USERS_FILE):
            with open(_USERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'users' not in data:
                    data['users'] = {}
                if 'guest_downloads' not in data:
                    data['guest_downloads'] = {}
                return data
    except Exception:
        pass
    return {"users": {}, "guest_downloads": {}}

def _save_users_db(data: dict):
    """Ghi users.json atomic (tránh corrupt)."""
    tmp = _USERS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _USERS_FILE)

# ── Password hashing (Dr. Bình — anti timing-attack) ─────────────────────────
def _hash_password(password: str, salt: str = None) -> tuple:
    """Trả về (hashed, salt)."""
    if salt is None:
        salt = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
    h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                             salt.encode('utf-8'), 100_000)
    return h.hex(), salt

def _verify_password(password: str, hashed: str, salt: str) -> bool:
    computed, _ = _hash_password(password, salt)
    return hmac.compare_digest(computed, hashed)

# ── Validation ────────────────────────────────────────────────────────────────
def _validate_username(u: str) -> str | None:
    """Trả về None nếu hợp lệ, ngược lại trả về thông báo lỗi."""
    if not u or len(u) < 3:
        return "Tên đăng nhập phải có ít nhất 3 ký tự"
    if len(u) > 30:
        return "Tên đăng nhập tối đa 30 ký tự"
    if not re.match(r'^[a-zA-Z0-9_.-]+$', u):
        return "Tên đăng nhập chỉ gồm chữ cái, số, _, . và -"
    if u.lower() in ('admin', 'administrator', 'root', 'superuser') and u != 'admin':
        return "Tên đăng nhập này không được phép"
    return None

def _validate_email(e: str) -> str | None:
    if not e or len(e) > 100:
        return "Email không hợp lệ"
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', e):
        return "Định dạng email không hợp lệ"
    return None

def _validate_password(p: str) -> str | None:
    if not p or len(p) < 6:
        return "Mật khẩu phải có ít nhất 6 ký tự"
    if len(p) > 128:
        return "Mật khẩu tối đa 128 ký tự"
    return None

# ── Khởi tạo tài khoản admin mặc định ───────────────────────────────────────
def _init_default_admin():
    with _users_rw_lock:
        data = _load_users_db()
        if 'admin' not in data['users']:
            pwd_hash, salt = _hash_password('admin123')
            data['users']['admin'] = {
                'username': 'admin',
                'email': 'admin@tikdown.local',
                'password': pwd_hash,
                'salt': salt,
                'role': 'admin',           # admin | user
                'created_at': datetime.now().isoformat(),
                'locked': False,
                'restrictions': {          # chỉ áp dụng với role=user
                    'no_audio_remove': False,
                    'no_logo': False,
                    'no_batch': False,
                },
                'lock_reason': '',
            }
            _save_users_db(data)
            print("✅ [AUTH] Tài khoản admin mặc định đã tạo: admin / admin123")

_init_default_admin()

# ── Session helpers ───────────────────────────────────────────────────────────
def get_current_user() -> dict | None:
    """Lấy thông tin user đang đăng nhập từ session. None = chưa đăng nhập (guest)."""
    username = session.get('username')
    if not username:
        return None
    with _users_rw_lock:
        data = _load_users_db()
    user = data['users'].get(username)
    if not user:
        session.clear()
        return None
    # Nếu tài khoản bị khóa → tự động đăng xuất
    if user.get('locked'):
        session.clear()
        return None
    return user

def get_current_role() -> str:
    """guest | user | admin"""
    user = get_current_user()
    if user is None:
        return 'guest'
    return user.get('role', 'user')

def is_admin() -> bool:
    return get_current_role() == 'admin'

def is_logged_in() -> bool:
    return get_current_user() is not None

def check_user_restriction(restriction: str) -> bool:
    """True = bị hạn chế chức năng này."""
    user = get_current_user()
    if user is None:
        return True  # guest bị hạn chế tất cả
    if user.get('role') == 'admin':
        return False  # admin không bị hạn chế
    return user.get('restrictions', {}).get(restriction, False)

# ── Guest daily download limit ────────────────────────────────────────────────
_GUEST_DAILY_LIMIT = 10

def guest_can_download(ip: str) -> tuple:
    """Trả về (can_download: bool, remaining: int, reset_at: str)."""
    today = datetime.now().strftime('%Y-%m-%d')
    with _users_rw_lock:
        data = _load_users_db()
        gd = data.get('guest_downloads', {})
        rec = gd.get(ip, {})
        if rec.get('date') != today:
            rec = {'date': today, 'count': 0}
        count = rec.get('count', 0)
        remaining = max(0, _GUEST_DAILY_LIMIT - count)
        can = remaining > 0
    # Safe next-midnight calc using timedelta (avoids day+1 overflow at end of month)
    from datetime import timedelta
    _now       = datetime.now()
    _tomorrow  = (_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    reset_at   = _tomorrow.strftime('%H:%M ngày %d/%m')
    return can, remaining, reset_at

def guest_record_download(ip: str):
    """Ghi nhận 1 lần tải của guest."""
    today = datetime.now().strftime('%Y-%m-%d')
    with _users_rw_lock:
        data = _load_users_db()
        gd = data.setdefault('guest_downloads', {})
        rec = gd.get(ip, {'date': today, 'count': 0})
        if rec.get('date') != today:
            rec = {'date': today, 'count': 0}
        rec['count'] = rec.get('count', 0) + 1
        gd[ip] = rec
        _save_users_db(data)

# ── Permission decorators ─────────────────────────────────────────────────────
def require_logged_in(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_logged_in():
            return jsonify({'error': 'Cần đăng nhập', 'code': 'LOGIN_REQUIRED'}), 401
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            return jsonify({'error': 'Không có quyền admin', 'code': 'FORBIDDEN'}), 403
        return f(*args, **kwargs)
    return decorated

# ══════════════════════════════════════════════════════════════════════════════
# 📦 HỆ THỐNG LƯU TRỮ NGƯỜI DÙNG — Dr. An Nguyễn + Dr. Dũng Phạm
# Mỗi user có thư mục riêng: user_storage/{username}/
# Quota mặc định: 3GB | Admin: không giới hạn
# ══════════════════════════════════════════════════════════════════════════════
_USER_STORAGE_DIR      = os.path.join(_BASE_DIR, 'user_storage')
_DEFAULT_QUOTA_BYTES   = 3 * 1024 * 1024 * 1024    # 3 GB
_ADMIN_QUOTA_BYTES     = 100 * 1024 * 1024 * 1024   # 100 GB (effectively unlimited)
_STORAGE_META_FILE     = '_meta.json'               # per-user metadata sidecar
_STORAGE_TTL_DAYS      = 15                         # Tự động xóa sau 15 ngày
_storage_op_lock       = threading.Lock()
os.makedirs(_USER_STORAGE_DIR, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_user_storage_dir(username: str) -> str:
    """Trả về đường dẫn thư mục lưu trữ của user, tạo nếu chưa có."""
    safe = re.sub(r'[^\w\-.]', '_', username)[:60]
    path = os.path.join(_USER_STORAGE_DIR, safe)
    os.makedirs(path, exist_ok=True)
    return path

def get_user_quota_bytes(username: str) -> int:
    """Quota của user tính bằng bytes. Admin = _ADMIN_QUOTA_BYTES."""
    with _users_rw_lock:
        db   = _load_users_db()
        user = db['users'].get(username)
    if not user:
        return 0
    if user.get('role') == 'admin':
        return _ADMIN_QUOTA_BYTES
    return int(user.get('storage_quota_bytes', _DEFAULT_QUOTA_BYTES))

def set_user_quota_bytes(username: str, quota_bytes: int):
    """Admin đặt quota cho user (bytes)."""
    with _users_rw_lock:
        db   = _load_users_db()
        user = db['users'].get(username)
        if user:
            user['storage_quota_bytes'] = max(0, int(quota_bytes))
            _save_users_db(db)

def get_user_storage_used(username: str) -> int:
    """Tính tổng bytes đang dùng trong thư mục lưu trữ của user."""
    d = get_user_storage_dir(username)
    total = 0
    try:
        for fn in os.listdir(d):
            if fn == _STORAGE_META_FILE:
                continue
            fp = os.path.join(d, fn)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    except Exception:
        pass
    return total

def _load_user_storage_meta(username: str) -> dict:
    """Đọc metadata file trong thư mục user (title, url, download_time, ...)."""
    meta_path = os.path.join(get_user_storage_dir(username), _STORAGE_META_FILE)
    try:
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_user_storage_meta(username: str, meta: dict):
    """Ghi metadata của user ra file."""
    meta_path = os.path.join(get_user_storage_dir(username), _STORAGE_META_FILE)
    tmp = meta_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, meta_path)

def save_to_user_storage(username: str, src_path: str, filename: str,
                          title: str = '', url: str = '',
                          group_id: str = '', group_name: str = '',
                          folder_id: str = '') -> dict:
    """
    Sao chép video từ src_path vào thư mục lưu trữ của user.
    Hỗ trợ group_id/group_name để gom file cùng batch/queue.
    Hỗ trợ folder_id để gán file vào thư mục kho client-side.
    TTL: _STORAGE_TTL_DAYS ngày kể từ khi lưu.
    Trả về {'ok': bool, 'reason': str, 'stored_path': str|None, 'used': int, 'quota': int}
    """
    if not username or not src_path or not os.path.exists(src_path):
        return {'ok': False, 'reason': 'file_not_found', 'stored_path': None}

    quota  = get_user_quota_bytes(username)
    used   = get_user_storage_used(username)
    fsize  = os.path.getsize(src_path)

    if quota > 0 and used + fsize > quota:
        remaining = max(0, quota - used)
        return {
            'ok': False, 'reason': 'quota_exceeded',
            'stored_path': None, 'used': used, 'quota': quota,
            'remaining': remaining, 'file_size': fsize,
        }

    storage_dir  = get_user_storage_dir(username)
    dest_path    = os.path.join(storage_dir, filename)

    # Tránh trùng tên
    if os.path.exists(dest_path):
        base, ext = os.path.splitext(filename)
        dest_path = os.path.join(storage_dir, f"{base}_{int(time.time())}{ext}")
        filename  = os.path.basename(dest_path)

    try:
        with _storage_op_lock:
            shutil.copy2(src_path, dest_path)
            # Cập nhật metadata
            meta = _load_user_storage_meta(username)
            _now = datetime.now()
            _expires = _now + __import__('datetime').timedelta(days=_STORAGE_TTL_DAYS)
            meta[filename] = {
                'title':         title or filename,
                'url':           url,
                'size':          fsize,
                'saved_at':      _now.isoformat(),
                'saved_at_ts':   time.time(),
                'expires_at':    _expires.isoformat(),
                'expires_ts':    _expires.timestamp(),
                'group_id':      group_id or '',
                'group_name':    group_name or '',
                'folder_id':     folder_id or '',   # ⚡ FIX: persist folder assignment
                'status':        'ready',
            }
            _save_user_storage_meta(username, meta)

        new_used = get_user_storage_used(username)
        log_process(f'[storage] {username}: saved {filename} ({fsize//1024}KB) used={new_used//1024//1024}MB')
        return {'ok': True, 'reason': 'saved', 'stored_path': dest_path,
                'filename': filename, 'used': new_used, 'quota': quota}
    except Exception as e:
        log_error(f'[storage] save failed for {username}: {e}')
        return {'ok': False, 'reason': str(e), 'stored_path': None, 'used': used, 'quota': quota}

def list_user_storage_files(username: str) -> list:
    """Trả về danh sách files trong storage của user, mới nhất trước."""
    storage_dir = get_user_storage_dir(username)
    meta        = _load_user_storage_meta(username)
    files       = []
    try:
        for fn in os.listdir(storage_dir):
            if fn == _STORAGE_META_FILE:
                continue
            fp = os.path.join(storage_dir, fn)
            if not os.path.isfile(fp):
                continue
            stat = os.stat(fp)
            m    = meta.get(fn, {})
            _now_ts = time.time()
            _exp_ts = m.get('expires_ts', 0)
            _days_left = max(0, round((_exp_ts - _now_ts) / 86400, 1)) if _exp_ts else _STORAGE_TTL_DAYS
            files.append({
                'filename':   fn,
                'title':      m.get('title', fn),
                'url':        m.get('url', ''),
                'size':       stat.st_size,
                'saved_at':   m.get('saved_at', ''),
                'saved_at_ts':m.get('saved_at_ts', stat.st_mtime),
                'expires_at': m.get('expires_at', ''),
                'expires_ts': _exp_ts,
                'days_left':  _days_left,
                'group_id':   m.get('group_id', ''),
                'group_name': m.get('group_name', ''),
                'folder_id':  m.get('folder_id', ''),   # ⚡ FIX: expose folder assignment
                'status':     m.get('status', 'ready'),
            })
    except Exception:
        pass
    files.sort(key=lambda x: x.get('saved_at_ts', 0), reverse=True)
    return files

def delete_from_user_storage(username: str, filename: str) -> dict:
    """Xóa file khỏi storage của user."""
    safe_fn    = os.path.basename(filename)   # chống path traversal
    storage_dir = get_user_storage_dir(username)
    fp         = os.path.join(storage_dir, safe_fn)
    if not os.path.exists(fp):
        return {'ok': False, 'reason': 'file_not_found'}
    try:
        with _storage_op_lock:
            os.unlink(fp)
            meta = _load_user_storage_meta(username)
            meta.pop(safe_fn, None)
            _save_user_storage_meta(username, meta)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'reason': str(e)}

def mark_storage_file_status(username: str, filename: str, status: str):
    """Cập nhật trạng thái file (downloading / ready / error) trong metadata."""
    try:
        with _storage_op_lock:
            meta = _load_user_storage_meta(username)
            if filename in meta:
                meta[filename]['status'] = status
            else:
                meta[filename] = {'title': filename, 'status': status,
                                   'saved_at': datetime.now().isoformat(),
                                   'saved_at_ts': time.time()}
            _save_user_storage_meta(username, meta)
    except Exception:
        pass

# ── Pre-create admin storage ──────────────────────────────────────────────────
get_user_storage_dir('admin')
# ══════════════════════════════════════════════════════════════════════════════
# 🗑️ AUTO CLEANUP — Xóa file hết hạn sau _STORAGE_TTL_DAYS ngày (Dr. Dũng)
# Chạy mỗi giờ trong background, không block server
# ══════════════════════════════════════════════════════════════════════════════

def _cleanup_expired_storage_files():
    """Xóa file đã quá _STORAGE_TTL_DAYS ngày trong tất cả user storage."""
    now_ts = time.time()
    total_deleted = 0
    try:
        if not os.path.isdir(_USER_STORAGE_DIR):
            return
        for user_dir_name in os.listdir(_USER_STORAGE_DIR):
            user_dir = os.path.join(_USER_STORAGE_DIR, user_dir_name)
            if not os.path.isdir(user_dir):
                continue
            meta_path = os.path.join(user_dir, _STORAGE_META_FILE)
            # Derive username from directory name
            username = user_dir_name
            try:
                meta = _load_user_storage_meta(username)
                to_delete = []
                for fn, m in list(meta.items()):
                    exp_ts = m.get('expires_ts', 0)
                    saved_ts = m.get('saved_at_ts', 0)
                    # If no expires_ts, compute from saved_at_ts
                    if not exp_ts and saved_ts:
                        exp_ts = saved_ts + _STORAGE_TTL_DAYS * 86400
                    # Fallback: check file mtime
                    if not exp_ts:
                        fp = os.path.join(user_dir, fn)
                        if os.path.exists(fp):
                            exp_ts = os.path.getmtime(fp) + _STORAGE_TTL_DAYS * 86400
                    if exp_ts and now_ts > exp_ts:
                        to_delete.append(fn)

                for fn in to_delete:
                    fp = os.path.join(user_dir, os.path.basename(fn))
                    try:
                        if os.path.exists(fp):
                            os.unlink(fp)
                            total_deleted += 1
                        meta.pop(fn, None)
                    except Exception as e_del:
                        log_error(f'[cleanup_storage] delete {fp}: {e_del}')

                if to_delete:
                    with _storage_op_lock:
                        _save_user_storage_meta(username, meta)
                    log_process(f'[cleanup_storage] {username}: xóa {len(to_delete)} file hết hạn')

            except Exception as e_user:
                log_error(f'[cleanup_storage] lỗi user {user_dir_name}: {e_user}')

    except Exception as e:
        log_error(f'[cleanup_storage] lỗi chính: {e}')

    if total_deleted > 0:
        log_process(f'[cleanup_storage] ✅ Tổng đã xóa: {total_deleted} file hết hạn')


def _cleanup_expired_storage_daemon():
    """Daemon thread: chạy cleanup mỗi giờ."""
    # Chạy lần đầu sau 5 phút (server vừa khởi động)
    time.sleep(300)
    while True:
        try:
            _cleanup_expired_storage_files()
        except Exception as e:
            log_error(f'[cleanup_daemon] {e}')
        time.sleep(3600)  # Mỗi giờ


threading.Thread(
    target=_cleanup_expired_storage_daemon,
    daemon=True, name='storage-ttl-cleanup'
).start()


# -------------------- CẤU HÌNH ỨNG DỤNG --------------------
app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['SECRET_KEY'] = 'tiktok-ultra-downloader-2026-v8.7.0-race'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False   # False for HTTP localhost
app.config['SESSION_COOKIE_NAME'] = 'tikdown_session'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 30  # 30 ngày

# ── GZIP COMPRESSION (tăng tốc mạng ~60-80%) ─────────────────────────────────
if FLASK_COMPRESS_AVAILABLE:
    app.config['COMPRESS_MIMETYPES'] = [
        'application/json', 'text/html', 'text/css', 'application/javascript',
        'text/plain', 'text/xml', 'application/xml'
    ]
    app.config['COMPRESS_LEVEL'] = 4       # 6→4: nhanh hơn ~40% CPU ít hơn
    app.config['COMPRESS_MIN_SIZE'] = 1000  # bỏ qua response < 1KB
    _FlaskCompress(app)

# ── KEEP-ALIVE + RESPONSE HEADERS CHUNG ──────────────────────────────────────
@app.after_request
def _add_perf_headers(resp):
    ct = resp.content_type or ''
    # video/ và octet-stream là binary; text/event-stream là SSE
    is_video    = 'video/' in ct or 'octet-stream' in ct
    is_sse      = 'text/event-stream' in ct
    is_binary   = is_video or is_sse

    # Manual gzip khi flask-compress không có
    if (not FLASK_COMPRESS_AVAILABLE and not is_binary
            and 'gzip' in request.headers.get('Accept-Encoding', '')
            and 'Content-Encoding' not in resp.headers):
        compressible = any(t in ct for t in ('application/json','text/html','text/css','javascript','text/plain'))
        if compressible:
            data = resp.get_data()
            if len(data) >= 1000:
                resp.set_data(_gzip_mod.compress(data, compresslevel=3))
                resp.headers['Content-Encoding'] = 'gzip'
                resp.headers['Content-Length'] = len(resp.get_data())

    if is_video:
        # ── Video download: KHÔNG đặt Keep-Alive timeout ──────────────────
        # Keep-Alive: timeout=N sẽ kill streaming connection sau N giây "idle".
        # Trên Safari iPhone, OS buffer có thể làm connection tưởng "idle" dù đang download.
        # Giải pháp: để Connection=keep-alive nhưng KHÔNG đặt timeout.
        resp.headers.setdefault('Connection', 'keep-alive')
        # Xóa mọi Keep-Alive timeout header nếu đã được set ở nơi khác
        try: resp.headers.remove('Keep-Alive')
        except Exception: pass
        resp.headers.pop('Content-Encoding', None)   # không bao giờ compress video
    elif is_sse:
        # SSE: keep-alive, không timeout, không cache
        resp.headers.setdefault('Connection', 'keep-alive')
        try: resp.headers.remove('Keep-Alive')
        except Exception: pass
    else:
        # JSON / HTML / CSS — OK đặt Keep-Alive ngắn
        resp.headers.setdefault('Connection', 'keep-alive')
        resp.headers.setdefault('Keep-Alive', 'timeout=30, max=50')

    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# AI BEHAVIORAL SECURITY — Team Gamma
# ══════════════════════════════════════════════════════════════════════════════
import re as _re_sec
from collections import deque as _deque

class BehavioralGuard:
    """
    AI Bảo mật hành vi — chỉ nhắm vào bot/scraper, KHÔNG ảnh hưởng user thường.

    Nguyên tắc:
    - User đã đăng nhập (has_sess=True): HOÀN TOÀN bỏ qua scoring → không bao giờ bị block
    - Chỉ tính điểm cho request KHÔNG có session (khách lạ, bot)
    - Ngưỡng cao: cần pattern rõ ràng của bot mới bị chặn
    """
    SOFT_BLOCK_SEC  = 1800        # 30 phút (bot bị phát hiện sớm)
    HARD_BLOCK_SEC  = 3600        # 1 giờ
    WINDOW_SEC      = 60          # sliding window 60 giây
    MAX_REQ_MIN     = 120         # >120 req/60s mới nghi ngờ (user bình thường < 30)
    MAX_DL_ANON_MIN = 5           # guest tải quá 5 lần/60s → nghi ngờ
    BOT_UA = _re_sec.compile(
        r'python-requests|python-urllib|curl/|wget/|scrapy|httpx|aiohttp|'
        r'go-http-client|java/[0-9]|bot\b|crawl|spider|scrape', _re_sec.IGNORECASE)

    def __init__(self):
        self._lock = threading.Lock()
        self._records = {}
        self._blocked = {}
        threading.Thread(target=self._cleanup_loop, daemon=True).start()

    def _rec(self, ip):
        if ip not in self._records:
            self._records[ip] = {'ts':_deque(),'dl_ts':_deque(),'score':0.0}
        return self._records[ip]

    def _prune(self, dq, now):
        cut = now - self.WINDOW_SEC
        while dq and dq[0] < cut: dq.popleft()

    def check(self, ip, path, ua, has_sess):
        now = time.time()
        with self._lock:
            # ── Kiểm tra block hiện tại ───────────────────────────────────
            blk = self._blocked.get(ip)
            if blk:
                if blk.get('permanent') or now < blk['until']:
                    return False, blk.get('reason','blocked')
                del self._blocked[ip]

            # ── User đã đăng nhập → KHÔNG bao giờ block ──────────────────
            if has_sess:
                return True, 'ok'

            # ── Chỉ tính điểm cho anonymous request ──────────────────────
            r = self._rec(ip)
            self._prune(r['ts'],now); self._prune(r['dl_ts'],now)
            r['ts'].append(now)
            delta = 0.0

            # Signal 1: UA rõ ràng là bot (điểm cao nhất)
            if not ua or self.BOT_UA.search(ua):
                delta += 40

            # Signal 2: Request rate cực cao (>120/60s) — chỉ bot mới đạt
            req_n = len(r['ts'])
            if req_n > self.MAX_REQ_MIN:
                delta += 20 * (req_n / self.MAX_REQ_MIN - 1)

            # Signal 3: Anonymous download quá nhiều lần
            if '/api/storage/download' in path or '/api/result' in path:
                r['dl_ts'].append(now)
                dl_n = len(r['dl_ts'])
                if dl_n > self.MAX_DL_ANON_MIN:
                    delta += 15 * (dl_n / self.MAX_DL_ANON_MIN - 1)

            r['score'] += delta
            score = r['score']

            def _blk(until, perm, reason):
                self._blocked[ip] = {'until':until,'permanent':perm,'reason':reason}
                print(f'[SECURITY] {reason} ip={ip} score={score:.0f}')
                return False, reason

            # Ngưỡng cao: cần score tích lũy rõ ràng mới block
            if score >= 800: return _blk(0,    True,  f'permanent score={score:.0f}')
            if score >= 400: return _blk(now+self.HARD_BLOCK_SEC, False, f'hard_block_1h')
            if score >= 150: return _blk(now+self.SOFT_BLOCK_SEC, False, f'soft_block_30m')

            # Decay nhanh hơn để không tích điểm oan
            r['score'] = max(0.0, score - 2.0)
            return True, 'ok'

    def unblock(self, ip):
        with self._lock:
            if ip in self._blocked:
                del self._blocked[ip]
                if ip in self._records: self._records[ip]['score'] = 0
                return True
            return False

    def status(self):
        now = time.time()
        with self._lock:
            return {'blocked':[{'ip':ip,'permanent':b.get('permanent'),'reason':b.get('reason'),
                              'remaining':max(0,b['until']-now) if not b.get('permanent') else -1}
                             for ip,b in self._blocked.items()],
                    'total_tracked':len(self._records)}

    def _cleanup_loop(self):
        while True:
            time.sleep(600)
            now = time.time()
            with self._lock:
                for ip in [ip for ip,r in list(self._records.items())
                           if not r['ts'] and ip not in self._blocked]:
                    del self._records[ip]

_behavioral_guard = BehavioralGuard()

def _get_real_ip():
    xff = request.headers.get('X-Forwarded-For','')
    return (xff.split(',')[0].strip() if xff else request.remote_addr) or '0.0.0.0'

@app.before_request
def _security_gate():
    if request.method == 'OPTIONS': return None
    p = request.path
    # Bỏ qua static, assets, và các trang/API thông dụng cho user
    SAFE_PREFIXES = ('/static/', '/image/', '/favicon', '/robots')
    if any(p.startswith(pfx) for pfx in SAFE_PREFIXES): return None
    # Bỏ qua trang chủ và login/register (không có session là bình thường)
    SAFE_PATHS = ('/', '/login', '/register', '/logout',
                  '/api/auth/login', '/api/auth/register', '/api/auth/logout',
                  '/api/auth/status', '/api/config')
    if p in SAFE_PATHS: return None
    ok, reason = _behavioral_guard.check(
        _get_real_ip(), p,
        request.headers.get('User-Agent', ''),
        bool(session.get('username'))
    )
    if not ok:
        return jsonify({'error': 'Quá nhiều yêu cầu, thử lại sau.',
                        'code': 'RATE_LIMITED'}), 429

# ══════════════════════════════════════════════════════════════════════════════
# -------------------- FFMPEG CONFIGURATION --------------------
def check_ffmpeg():
    """Kiểm tra ffmpeg có sẵn không"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              timeout=5)
        return result.returncode == 0
    except:
        return False

FFMPEG_AVAILABLE = check_ffmpeg()

# ══════════════════════════════════════════════════════════════════════
# LOGGING — rotate mỗi giờ, giữ 48 giờ gần nhất
# ══════════════════════════════════════════════════════════════════════

def _setup_logger(name, filename, level=logging.DEBUG):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    # Rotate mỗi giờ (interval=1, when='h'), giữ 48 file gần nhất
    handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(_LOG_DIR, filename),
        when='h', interval=1, backupCount=48, encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)
    return logger

error_log   = _setup_logger('tikdown.error',   'error.log',   logging.ERROR)
process_log = _setup_logger('tikdown.process', 'process.log', logging.DEBUG)
access_log  = _setup_logger('tikdown.access',  'access.log',  logging.INFO)

def log_error(msg, exc=None):
    """Ghi lỗi kèm traceback nếu có."""
    if exc:
        error_log.error(f"{msg} | {type(exc).__name__}: {exc}", exc_info=exc)
        # In màu đỏ ra terminal
        print(f"{_RED}✗ [ERROR] {msg} | {type(exc).__name__}: {exc}{_RESET}", flush=True)
    else:
        error_log.error(msg)
        print(f"{_RED}✗ [ERROR] {msg}{_RESET}", flush=True)

def log_process(msg):
    process_log.info(msg)
    print(f"{_CYAN}· [PROC] {msg}{_RESET}", flush=True)

# ── ACCESS LOG & SESSION TRACKER ──────────────────────────────────────────────
_session_store  = {}   # ip → {start: float, last: float, page_views: int, links: int}
_session_lock   = threading.Lock()
_global_link_counter = [0]   # [0] = tổng link đã tìm kiếm kể từ khi server khởi động
_link_lock      = threading.Lock()

def _get_client_ip():
    """Lấy IP thật qua X-Forwarded-For (Nginx) hoặc remote_addr."""
    return (
        (request.headers.get('X-Forwarded-For', '').split(',')[0].strip())
        or request.headers.get('X-Real-IP', '')
        or request.remote_addr
        or 'unknown'
    )

def _log_access(ip: str, path: str, ua: str, extra: str = ''):
    """Ghi 1 dòng vào access.log và in terminal."""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'ip={ip} path={path} ua="{ua[:80]}" {extra}'
    access_log.info(line)
    # Terminal highlight
    print(f"{_CYAN}· [ACCESS] {now_str} {line}{_RESET}", flush=True)

def _session_enter(ip: str, path: str = '/'):
    """Ghi nhận session bắt đầu hoặc activity."""
    with _session_lock:
        if ip not in _session_store:
            _session_store[ip] = {
                'start': time.time(), 'last': time.time(),
                'page_views': 0, 'links_searched': 0
            }
        s = _session_store[ip]
        s['last'] = time.time()
        s['page_views'] += 1

def _session_add_links(ip: str, n: int):
    """Ghi nhận n link tìm kiếm từ ip này."""
    with _session_lock:
        if ip in _session_store:
            _session_store[ip]['links_searched'] = (
                _session_store[ip].get('links_searched', 0) + n
            )
    with _link_lock:
        _global_link_counter[0] += n

def _session_exit(ip: str):
    """Ghi thời gian truy cập khi session kết thúc."""
    with _session_lock:
        s = _session_store.pop(ip, None)
    if not s:
        return
    duration = round(time.time() - s['start'])
    mins, secs = divmod(duration, 60)
    dur_str = f'{mins}m{secs}s' if mins else f'{secs}s'
    msg = (f'ip={ip} duration={dur_str} '
           f'page_views={s["page_views"]} links_searched={s.get("links_searched",0)}')
    access_log.info(f'SESSION_END {msg}')
    print(f"{_GREEN}✓ [SESSION] {msg}{_RESET}", flush=True)

# Auto-expire sessions older than 30 min of inactivity
def _cleanup_sessions():
    while True:
        time.sleep(300)
        now = time.time()
        with _session_lock:
            expired = [ip for ip, s in _session_store.items()
                       if now - s['last'] > 1800]
        for ip in expired:
            _session_exit(ip)

threading.Thread(target=_cleanup_sessions, daemon=True, name='session-cleanup').start()


# ══════════════════════════════════════════════════════════════════════════════
# 🟡 VISITOR JSON LOGGER — lưu IP, thiết bị, thời gian, địa điểm
# File: visitors.json — cập nhật ngay lập tức mỗi lần truy cập
# ══════════════════════════════════════════════════════════════════════════════
def _detect_device_info(ua: str) -> dict:
    ua_l = ua.lower()
    device  = 'Mobile' if ('mobile' in ua_l or 'android' in ua_l) else 'Tablet' if ('ipad' in ua_l or 'tablet' in ua_l) else 'Desktop'
    os_name = ('Android' if 'android' in ua_l else 'iOS' if any(x in ua_l for x in ('iphone','ipad','ipod')) else
               'Windows' if 'windows' in ua_l else 'macOS' if 'mac' in ua_l else 'Linux' if 'linux' in ua_l else 'Unknown')
    browser = ('Edge' if 'edg/' in ua_l else 'Opera' if 'opr/' in ua_l else 'Firefox' if 'firefox' in ua_l else
               'Chrome' if 'chrome' in ua_l else 'Safari' if 'safari' in ua_l else 'Unknown')
    return {'device': device, 'os': os_name, 'browser': browser}

def _geo_lookup_async(ip: str, on_result):
    """Tra cứu địa lý IP qua ip-api.com trong background thread."""
    def _do():
        try:
            import urllib.request as _ur
            url = f'http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp,timezone'
            with _ur.urlopen(url, timeout=5) as r:
                data = json.loads(r.read().decode())
            if data.get('status') == 'success':
                on_result({
                    'country': data.get('country',''), 'region': data.get('regionName',''),
                    'city': data.get('city',''),       'isp': data.get('isp',''),
                    'timezone': data.get('timezone',''),
                })
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

def _load_visitors() -> dict:
    try:
        if os.path.exists(_VISITORS_FILE):
            with open(_VISITORS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_visitors_safe(data: dict):
    """Atomic write để tránh corrupt khi ghi đồng thời."""
    try:
        tmp = _VISITORS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _VISITORS_FILE)
    except Exception as e:
        pass  # log_error chưa defined ở đây, bỏ qua

def record_visitor(ip: str, ua: str, path: str = '/'):
    """Ghi/cập nhật visitor ngay lập tức vào visitors.json."""
    if not ip or ip in ('unknown', '127.0.0.1', '::1', 'localhost'):
        return
    dev      = _detect_device_info(ua)
    dev_key  = f"{dev['device']}|{dev['os']}|{dev['browser']}"
    rec_key  = f"{ip}::{dev_key}"
    now_str  = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    now_ts   = time.time()

    with _visitors_lock:
        data = _load_visitors()
        if rec_key in data:
            rec = data[rec_key]
            rec['visit_count'] = rec.get('visit_count', 1) + 1
            rec['last_seen']   = now_str
            rec['last_seen_ts']= now_ts
            hist = rec.setdefault('visit_history', [])
            hist.append(now_str)
            if len(hist) > 50: rec['visit_history'] = hist[-50:]
        else:
            data[rec_key] = {
                'ip': ip, 'device': dev['device'], 'os': dev['os'], 'browser': dev['browser'],
                'user_agent': ua[:200], 'first_seen': now_str, 'first_seen_ts': now_ts,
                'last_seen': now_str, 'last_seen_ts': now_ts,
                'visit_count': 1, 'visit_history': [now_str], 'location': {},
            }
            # Geo lookup async — điền sau khi có kết quả
            def _on_geo(geo, _k=rec_key):
                with _visitors_lock:
                    vd = _load_visitors()
                    if _k in vd:
                        vd[_k]['location'] = geo
                        _save_visitors_safe(vd)
            _geo_lookup_async(ip, _on_geo)
        _save_visitors_safe(data)


# ── TERMINAL LOGGING (màu ANSI) ──────────────────────────────────────────────
_RESET = '\033[0m'; _BOLD = '\033[1m'; _DIM = '\033[2m'
_RED   = '\033[91m'; _GREEN = '\033[92m'; _YELLOW = '\033[93m'
_CYAN  = '\033[96m'; _WHITE = '\033[97m'

# ══════════════════════════════════════════════════════════════════════════════
# 🔵 TERMINAL STATUS — In định kỳ, KHÔNG xóa màn hình, KHÔNG ẩn log nào
# ══════════════════════════════════════════════════════════════════════════════
# Nguyên tắc: không dùng cursor escape (\033[s/u/H/r) để tránh ẩn output.
# Stats được in như 1 dòng log bình thường mỗi STATUS_INTERVAL giây.
# Tất cả thông tin: HTTP access log, Flask, FFmpeg, download, batch... đều hiện đủ.
# ══════════════════════════════════════════════════════════════════════════════

STATUS_INTERVAL = 10   # giây giữa các lần in stats

_prev_net = {'sent': 0, 'recv': 0, 'ts': time.time()}

def _try_get_psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None

def _collect_hw_stats() -> dict:
    ps = _try_get_psutil()
    if not ps:
        return {}
    cpu  = ps.cpu_percent(interval=None)
    mem  = ps.virtual_memory()
    net  = ps.net_io_counters()
    gpu  = None
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            p = [x.strip() for x in r.stdout.strip().split(',')]
            if len(p) >= 3:
                gpu = {'util': p[0], 'mem_used': p[1],
                       'mem_total': p[2], 'temp': p[3] if len(p) > 3 else '?'}
    except Exception:
        pass
    # AMD GPU fallback (ROCm)
    if not gpu:
        try:
            r2 = subprocess.run(['rocm-smi', '--showuse', '--csv'],
                                capture_output=True, text=True, timeout=2)
            if r2.returncode == 0:
                gpu = {'util': 'AMD', 'mem_used': '?', 'mem_total': '?', 'temp': '?'}
        except Exception:
            pass
    return {
        'cpu':       cpu,
        'ram_used':  mem.used  / 1024**3,
        'ram_total': mem.total / 1024**3,
        'ram_pct':   mem.percent,
        'net_sent':  net.bytes_sent,
        'net_recv':  net.bytes_recv,
        'gpu':       gpu,
    }

def _color_pct(pct, warn=60, crit=85) -> str:
    if pct >= crit: return '\033[91m'   # đỏ
    if pct >= warn: return '\033[93m'   # vàng
    return '\033[92m'                   # xanh lá

def _fmt_rate(kbps: float) -> str:
    if kbps >= 1024 * 1024: return f'{kbps/1024/1024:.2f}GB/s'
    if kbps >= 1024:        return f'{kbps/1024:.1f}MB/s'
    return f'{kbps:.0f}KB/s'

def _print_status_line():
    """
    In 1 dòng stats ra terminal — KHÔNG xóa, KHÔNG overwrite, KHÔNG ẩn gì.
    Hiện tại cùng dòng với các log khác, cuộn bình thường.
    """
    global _prev_net
    try:
        stats = _collect_hw_stats()
        if not stats:
            return

        # ── Thời gian ─────────────────────────────────────────────────────────
        ts = datetime.now().strftime('%H:%M:%S')

        # ── CPU ───────────────────────────────────────────────────────────────
        cpu_pct = stats.get('cpu', 0)
        cpu_c   = _color_pct(cpu_pct)
        cpu_s   = f"{cpu_c}CPU:{cpu_pct:>5.1f}%{_RESET}"

        # ── RAM ───────────────────────────────────────────────────────────────
        ram_u   = stats.get('ram_used', 0)
        ram_t   = stats.get('ram_total', 1)
        ram_pct = stats.get('ram_pct', 0)
        ram_c   = _color_pct(ram_pct)
        ram_s   = f"{ram_c}RAM:{ram_u:.1f}/{ram_t:.1f}GB({ram_pct:.0f}%){_RESET}"

        # ── GPU ───────────────────────────────────────────────────────────────
        gpu_s = ''
        g = stats.get('gpu')
        if g:
            try:
                g_util = float(g['util']) if str(g['util']).replace('.','').isdigit() else 0
                gc = _color_pct(g_util)
                gpu_s = f"  {gc}GPU:{g['util']}% {g['mem_used']}/{g['mem_total']}MB {g['temp']}°C{_RESET}"
            except Exception:
                gpu_s = f"  \033[96mGPU:{g.get('util','?')}{_RESET}"

        # ── Network I/O (tốc độ kể từ lần trước) ─────────────────────────────
        now_ts = time.time()
        dt     = max(0.1, now_ts - _prev_net['ts'])
        tx_kb  = (stats.get('net_sent', 0) - _prev_net['sent']) / dt / 1024
        rx_kb  = (stats.get('net_recv', 0) - _prev_net['recv']) / dt / 1024
        _prev_net = {'sent': stats.get('net_sent', 0),
                     'recv': stats.get('net_recv', 0), 'ts': now_ts}
        net_s = f"\033[96m↑{_fmt_rate(tx_kb)} ↓{_fmt_rate(rx_kb)}{_RESET}"

        # ── Active tasks/batches ───────────────────────────────────────────────
        try:
            with _task_lock:
                active_t = sum(1 for t in TASK_STORE.values()
                               if t.get('status') in ('pending', 'running'))
            with _batch_lock:
                active_b = sum(1 for j in BATCH_STORE.values()
                               if not j.is_done and not j.cancelled)
            task_s = f"\033[96mTasks:{active_t} Batch:{active_b}{_RESET}"
        except Exception:
            task_s = ''

        # ── In 1 dòng tổng hợp (không xóa, không ẩn gì) ─────────────────────
        sep   = f"\033[90m│{_RESET}"
        line  = (f"\033[90m[{ts}]{_RESET} \033[7m⚡STATS{_RESET}  "
                 f"{cpu_s} {sep} {ram_s}{gpu_s} {sep} 🌐{net_s} {sep} {task_s}")
        print(line, flush=True)

    except Exception as e:
        pass   # không để stats crash ảnh hưởng server

def _status_bar_worker():
    """
    Background thread: in stats mỗi STATUS_INTERVAL giây.
    Không dùng cursor escape — tất cả output hiển thị đầy đủ.
    """
    ps = _try_get_psutil()
    if ps:
        ps.cpu_percent(interval=0.5)   # calibrate lần đầu

    # In lần đầu ngay khi start
    time.sleep(3)
    _print_status_line()

    while True:
        time.sleep(STATUS_INTERVAL)
        _print_status_line()

def _log(level: str, msg: str, task_id: str = None):
    color = {'info': _CYAN, 'ok': _GREEN, 'err': _RED, 'warn': _YELLOW}.get(level, _WHITE)
    icon  = {'info': '·', 'ok': '✓', 'err': '✗', 'warn': '!'}.get(level, '·')
    tid   = f'[{task_id[:8]}] ' if task_id else ''
    ts    = datetime.now().strftime('%H:%M:%S')
    print(f"{_DIM}[{ts}]{_RESET} {color}{_BOLD}{icon}{_RESET} {color}{tid}{msg}{_RESET}", flush=True)

# ── HARDWARE ENCODER DETECTION ───────────────────────────────────────────────
def _detect_hw_encoder():
    """
    Phát hiện hardware encoder theo thứ tự ưu tiên tốc độ:
    NVENC (NVIDIA) → VideoToolbox (macOS) → AMF (AMD Win) → QSV (Intel) → VAAPI (Linux) → libx264
    Hardware encoder = 10-50x nhanh hơn libx264 ultrafast.
    """
    candidates = [
        # NVIDIA NVENC: preset p1 = fastest, ll = low latency
        ('h264_nvenc',        ['-preset', 'p1', '-tune', 'll', '-rc', 'vbr', '-cq', '23']),
        # Apple VideoToolbox: realtime=1 không block pipeline
        ('h264_videotoolbox', ['-q:v', '50', '-realtime', '1', '-allow_sw', '1']),
        # AMD AMF (Windows): quality speed = fastest
        ('h264_amf',          ['-quality', 'speed', '-rc', 'cqp', '-qp_i', '23', '-qp_p', '25']),
        # Intel QSV: look_ahead 0 giảm latency
        ('h264_qsv',          ['-preset', 'veryfast', '-look_ahead', '0', '-global_quality', '23']),
        # VAAPI (Linux AMD/Intel)
        ('h264_vaapi',        ['-vaapi_device', '/dev/dri/renderD128', '-vf', 'format=nv12,hwupload', '-qp', '23']),
    ]
    for enc, extra in candidates:
        try:
            r = subprocess.run(
                ['ffmpeg', '-hide_banner', '-loglevel', 'error',
                 '-f', 'lavfi', '-i', 'color=black:s=128x72:d=0.1',
                 '-c:v', enc] + extra + ['-f', 'null', '-'],
                capture_output=True, timeout=6
            )
            if r.returncode == 0:
                print(f'[HW_ENCODER] Selected: {enc}')
                return enc, extra
        except Exception:
            pass
    print('[HW_ENCODER] Fallback: libx264 ultrafast')
    return 'libx264', ['-preset', 'ultrafast', '-crf', '23', '-tune', 'zerolatency']

HW_ENCODER, HW_ENCODER_EXTRA = _detect_hw_encoder()

# ── HARDWARE-AWARE CPU CONFIG ───────────────────────────────────────────────
# Dùng 100% CPU capacity (tăng từ 90%) — không cần dự phòng cho web server (async)
_CPU_COUNT = max(4, min(int((os.cpu_count() or 4) * 1.0), 32))
# FFmpeg threads: dùng toàn bộ core có sẵn (tốt hơn giới hạn cứng)
_FFMPEG_THREADS = str(_CPU_COUNT)

# ── HARDWARE TIER (yếu/trung/mạnh) — để chỉnh adaptive workers ──────────────
def _detect_hardware_tier() -> int:
    """
    0 = yếu   (≤2 cores, e.g. Celeron, Atom, low-end VPS)
    1 = trung  (3-4 cores, e.g. i3, i5-2xxx, Ryzen 3)
    2 = mạnh   (≥5 cores, e.g. i5-8xxx+, i7, Ryzen 5+)
    """
    cores = os.cpu_count() or 2
    try:
        # Thử đo tốc độ thực tế: hash 10MB trong 0.5s
        import hashlib as _hl
        _data = b'x' * (10 * 1024 * 1024)
        _t0 = time.time()
        _hl.md5(_data).hexdigest()
        _dt = time.time() - _t0
        # < 0.05s = fast CPU; < 0.15s = medium; else slow
        if _dt < 0.05 and cores >= 4: return 2
        if _dt < 0.15 and cores >= 2: return 1
        return 0
    except Exception:
        if cores <= 2: return 0
        if cores <= 4: return 1
        return 2

_HARDWARE_TIER = _detect_hardware_tier()
# Điều chỉnh timeout FFmpeg theo tier
_FFMPEG_TIMEOUT_FACTOR = {0: 2.5, 1: 1.5, 2: 1.0}[_HARDWARE_TIER]
_log_prefix = ['[HW:WEAK]', '[HW:MED]', '[HW:STRONG]'][_HARDWARE_TIER]


FFMPEG_SEMAPHORE  = threading.Semaphore(max(3, _CPU_COUNT))
OVERLAY_SEMAPHORE = threading.Semaphore(max(3, _CPU_COUNT))

# ── FFPROBE CACHE: tránh gọi ffprobe nhiều lần cho cùng 1 file ───────────────
# Key: filepath (str) | Value: (result: bool, timestamp: float)
_ffprobe_cache: dict = {}
_ffprobe_cache_lock  = threading.Lock()
_FFPROBE_CACHE_TTL   = 30  # giây — file temp tồn tại ngắn, không cần cache lâu

def _ffprobe_cache_get(filepath: str):
    with _ffprobe_cache_lock:
        entry = _ffprobe_cache.get(filepath)
        if entry and (time.time() - entry[1]) < _FFPROBE_CACHE_TTL:
            return entry[0]   # True/False cached
    return None   # cache miss

def _ffprobe_cache_set(filepath: str, result: bool):
    with _ffprobe_cache_lock:
        _ffprobe_cache[filepath] = (result, time.time())
        # Dọn cache cũ nếu > 200 entries
        if len(_ffprobe_cache) > 200:
            cutoff = time.time() - _FFPROBE_CACHE_TTL
            stale = [k for k, v in _ffprobe_cache.items() if v[1] < cutoff]
            for k in stale:
                del _ffprobe_cache[k]

# Số lần retry toàn bộ race khi tất cả strategies đều thất bại
RACE_MAX_RETRIES = 3

# Lock bảo vệ yt-dlp khỏi race condition khi nhiều thread dùng đồng thời
_ytdlp_lock = threading.Lock()

def merge_video_audio_ffmpeg(video_path, audio_path, output_path):
    """Merge video and audio using FFmpeg with browser-compatible output."""
    if not FFMPEG_AVAILABLE:
        raise Exception("FFmpeg not available")
    
    try:
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]
        
        result = subprocess.run(cmd, 
                              capture_output=True, 
                              timeout=180,
                              text=True)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg failed: {result.stderr[-500:]}")
        
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
            raise Exception("FFmpeg output file invalid")
        
        return True
    except subprocess.TimeoutExpired:
        raise Exception("FFmpeg timeout")
    except Exception as e:
        raise Exception(f"FFmpeg error: {str(e)}")

# -------------------- RAM DISK DETECTION --------------------
# ╔══════════════════════════════════════════════════════════════╗
# ║  ĐỔI ĐƯỜNG DẪN RAM DISK → SỬA DÒNG DƯỚI ĐÂY               ║
# ║  Để trống ("") = tự động chọn                               ║
# ║  Ví dụ Windows: CUSTOM_TMPDIR = r"R:\ramdisk"              ║
# ║  Ví dụ Linux  : CUSTOM_TMPDIR = "/mnt/myramdisk"            ║
# ╚══════════════════════════════════════════════════════════════╝
# 🟡 Claude D: Auto-detect tmpdir cross-platform (Windows/Linux)
# Để trống ("") = tự động chọn tốt nhất cho hệ điều hành hiện tại
CUSTOM_TMPDIR = r"C:\Users\nhanv\Desktop\temp"   # "" = auto | Windows: r"D:\ramdisk" | Linux: "/mnt/ramdisk"

def _get_fast_tmpdir():
    """🟡 Claude D: Cross-platform tmpdir selection (Windows/Linux/macOS)."""
    IS_WINDOWS = sys.platform == 'win32'

    # 1. Custom tmpdir nếu được set
    if CUSTOM_TMPDIR and CUSTOM_TMPDIR.strip():
        p = CUSTOM_TMPDIR.strip()
        try:
            os.makedirs(p, exist_ok=True)
        except Exception:
            pass
        if os.path.isdir(p) and os.access(p, os.W_OK):
            return p
        print(f"[WARN] CUSTOM_TMPDIR '{p}' không hợp lệ → dùng fallback")

    # 2. Linux/macOS: /dev/shm (RAM disk, nhanh nhất)
    if not IS_WINDOWS and os.path.exists('/dev/shm') and os.access('/dev/shm', os.W_OK):
        # Kiểm tra free space >= 512MB
        try:
            st = os.statvfs('/dev/shm')
            free_mb = st.f_bavail * st.f_frsize // (1024*1024)
            if free_mb >= 512:
                return '/dev/shm'
        except Exception:
            return '/dev/shm'

    # 3. Windows: %TEMP% (SSD thường nhanh hơn HDD)
    if IS_WINDOWS:
        win_temp = os.environ.get('TEMP') or os.environ.get('TMP') or tempfile.gettempdir()
        try:
            os.makedirs(win_temp, exist_ok=True)
        except Exception:
            pass
        if os.path.isdir(win_temp) and os.access(win_temp, os.W_OK):
            return win_temp

    # 4. Fallback hệ thống
    return tempfile.gettempdir()

FAST_TMPDIR = _get_fast_tmpdir()

def validate_video_with_ffprobe(filepath):
    """
    Kiểm tra file có video stream hợp lệ không.
    Thử nhiều phương pháp để đảm bảo tương thích mọi build FFmpeg (Windows/Linux).
    Kết quả được cache trong _FFPROBE_CACHE_TTL giây để tránh gọi ffprobe lặp.
    """
    if not filepath or not os.path.exists(filepath):
        return False
    # ── Kiểm tra cache trước ────────────────────────────────────────────────
    cached = _ffprobe_cache_get(filepath)
    if cached is not None:
        return cached
    try:
        # ── Phương pháp 1: select_streams v:0, lấy width ─────────────────────
        r1 = subprocess.run([
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,codec_name',
            '-of', 'json', filepath
        ], capture_output=True, timeout=10, text=True)
        if r1.returncode == 0:
            try:
                d = json.loads(r1.stdout)
                for s in d.get('streams', []):
                    w = s.get('width') or s.get('Width') or 0
                    if w and int(w) > 0:
                        return True
                    cn = (s.get('codec_name') or '').lower()
                    VIDEO_CODECS = ('h264','hevc','h265','vp9','vp8','av1','mpeg4',
                                    'avc','hvc1','hev1','libx264','libx265','prores','dnxhd')
                    if cn in VIDEO_CODECS:
                        return True
            except Exception:
                pass

        # ── Phương pháp 2: không select_streams, check codec_type ────────────
        r2 = subprocess.run([
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=codec_type,width,height,codec_name',
            '-of', 'json', filepath
        ], capture_output=True, timeout=10, text=True)
        if r2.returncode == 0:
            try:
                d2 = json.loads(r2.stdout)
                for s in d2.get('streams', []):
                    ct = (s.get('codec_type') or '').lower()
                    w  = int(s.get('width') or 0)
                    cn = (s.get('codec_name') or '').lower()
                    if ct == 'video' and w > 0:
                        return True
                    if cn in ('h264','hevc','h265','vp9','vp8','av1','mpeg4',
                              'avc','hvc1','hev1','libx264','libx265'):
                        return True
            except Exception:
                pass

        # ── Phương pháp 3: đếm số video streams qua CSV ──────────────────────
        r3 = subprocess.run([
            'ffprobe', '-v', 'error',
            '-select_streams', 'v',
            '-show_entries', 'stream=index',
            '-of', 'csv=p=0', filepath
        ], capture_output=True, timeout=10, text=True)
        if r3.returncode == 0 and r3.stdout.strip():
            _ffprobe_cache_set(filepath, True)
            return True  # có ít nhất 1 video stream index

        _ffprobe_cache_set(filepath, False)
        return False
    except Exception:
        return False


def probe_video_info(filepath):
    """Trả về (width, height, fps, has_audio) hoặc None nếu lỗi."""
    try:
        r = subprocess.run([
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate',
            '-show_entries', 'format=duration',
            '-of', 'json', filepath
        ], capture_output=True, text=True, timeout=4)   # 5s→4s
        if r.returncode != 0:
            return None
        d = json.loads(r.stdout)
        s = d.get('streams', [{}])[0]
        w = int(s.get('width', 0))
        h = int(s.get('height', 0))
        # r_frame_rate là fraction, e.g. "30/1" hay "60000/1001"
        fr = s.get('r_frame_rate', '30/1')
        num, den = (int(x) for x in (fr + '/1').split('/')[:2])
        fps = num / den if den else 30.0
        # Check audio stream
        ra = subprocess.run([
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_type', '-of', 'json', filepath
        ], capture_output=True, text=True, timeout=5)
        has_audio = bool(json.loads(ra.stdout).get('streams'))
        return w, h, fps, has_audio
    except Exception:
        return None

def remove_audio_ffmpeg(input_bytes):
    """
    Xóa audio track cực nhanh:
    - Thử pipe (không cần file tạm, zero disk I/O) cho file < 80MB
    - Thử copy stream với RAM disk
    - Fallback re-encode H.264 ultrafast với RAM disk
    - Nếu tất cả fail → trả về input gốc
    - FFMPEG_SEMAPHORE: tối đa 6 process song song cho batch audio removal
    """
    if not FFMPEG_AVAILABLE:
        raise Exception("FFmpeg not available")

    with FFMPEG_SEMAPHORE:
        return _remove_audio_ffmpeg_impl(input_bytes)


def _remove_audio_ffmpeg_impl(input_bytes):
    """Thực thi xóa audio (được gọi bên trong FFMPEG_SEMAPHORE)."""
    size_mb = len(input_bytes) / 1024 / 1024

    # ── CHIẾN LƯỢC 1: PIPE (zero disk I/O, nhanh nhất) ──────────────────────
    # Dùng cho file < 80MB để tránh pipe buffer overflow
    if size_mb < 80:
        try:
            cmd_pipe = [
                'ffmpeg', '-y',
                '-i', 'pipe:0',
                '-an',
                '-c:v', 'copy',
                '-movflags', '+faststart',
                '-avoid_negative_ts', 'make_zero',
                '-f', 'mp4',
                'pipe:1'
            ]
            proc = subprocess.run(
                cmd_pipe,
                input=input_bytes,
                capture_output=True,
                timeout=90
            )
            if proc.returncode == 0 and proc.stdout and len(proc.stdout) > max(50 * 1024, len(input_bytes) * 0.25):

                return proc.stdout
            # pipe copy fail (có thể do fragmented MP4) → thử pipe re-encode
            cmd_pipe_enc = [
                'ffmpeg', '-y',
                '-i', 'pipe:0',
                '-an',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '23',
                '-threads', _FFMPEG_THREADS,
                '-movflags', '+faststart',
                '-f', 'mp4',
                'pipe:1'
            ]
            proc2 = subprocess.run(
                cmd_pipe_enc,
                input=input_bytes,
                capture_output=True,
                timeout=120
            )
            if proc2.returncode == 0 and proc2.stdout and len(proc2.stdout) > 50 * 1024:

                return proc2.stdout
        except subprocess.TimeoutExpired:
            pass

        except Exception as ep:
            pass

    # ── CHIẾN LƯỢC 2: FILE-BASED với RAM disk ────────────────────────────────
    uid = hashlib.md5(input_bytes[:4096]).hexdigest()[:8]
    in_path   = os.path.join(FAST_TMPDIR, f'tka_in_{uid}.mp4')
    out_copy  = os.path.join(FAST_TMPDIR, f'tka_cp_{uid}.mp4')
    out_enc   = os.path.join(FAST_TMPDIR, f'tka_enc_{uid}.mp4')

    def _rm(*paths):
        for p in paths:
            try:
                if os.path.exists(p): os.unlink(p)
            except Exception: pass

    try:
        with open(in_path, 'wb') as f:
            f.write(input_bytes)

        # 2a: copy stream
        r = subprocess.run([
            'ffmpeg', '-y', '-i', in_path, '-an', '-c:v', 'copy',
            '-movflags', '+faststart', '-avoid_negative_ts', 'make_zero',
            out_copy
        ], capture_output=True, timeout=90)

        if r.returncode == 0 and os.path.exists(out_copy):
            sz = os.path.getsize(out_copy)
            if sz > max(50 * 1024, len(input_bytes) * 0.25) and validate_video_with_ffprobe(out_copy):
                with open(out_copy, 'rb') as f:
                    result = f.read()
                _rm(in_path, out_copy, out_enc)

                return result

        # 2b: re-encode ultrafast
        r2 = subprocess.run([
            'ffmpeg', '-y', '-i', in_path, '-an',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-threads', _FFMPEG_THREADS,
            '-movflags', '+faststart', out_enc
        ], capture_output=True, timeout=180)

        if r2.returncode == 0 and os.path.exists(out_enc):
            sz2 = os.path.getsize(out_enc)
            if sz2 > 50 * 1024 and validate_video_with_ffprobe(out_enc):
                with open(out_enc, 'rb') as f:
                    result = f.read()
                _rm(in_path, out_copy, out_enc)

                return result

        _rm(in_path, out_copy, out_enc)

        return input_bytes

    except Exception as e:
        _rm(in_path, out_copy, out_enc)

        return input_bytes

def convert_to_mp4_ffmpeg(input_path, output_path):
    """Convert any video format to MP4 using FFmpeg"""
    if not FFMPEG_AVAILABLE:
        raise Exception("FFmpeg not available")
    
    try:
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'ultrafast',
            '-crf', '23',
            '-y',
            output_path
        ]
        
        result = subprocess.run(cmd,
                              capture_output=True,
                              timeout=120,
                              text=True)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg conversion failed: {result.stderr}")
        
        return True
    except Exception as e:
        raise Exception(f"Conversion error: {str(e)}")

# ════════════════════════════════════════════════════════════════════════
# LOGO PLACEMENT — Shared helper (Claude A)
# ════════════════════════════════════════════════════════════════════════
# Canvas preview luôn là 270×480 (9:16). TikTok video có thể 576×1024,
# 720×1280, 1080×1920, hoặc landscape 1280×720 ...
#
# Công thức ĐÚNG: scale dựa trên SHORT SIDE của video / SHORT SIDE của canvas.
#   scale = min(video_w, video_h) / min(CANVAS_W, CANVAS_H)
#         = video_short / 270
#
# Điều này đảm bảo:
#   • Logo chiếm cùng % SHORT SIDE dù video có resolution nào.
#   • Tỷ lệ logo gốc được bảo toàn (cả w và h nhân cùng 1 scale).
#   • Không bị distort khi video landscape hoặc portrait.
#   • Force even pixels → H.264 không bị lỗi encoding.
#
# Tất cả 4 hàm overlay đều dùng hàm này — single source of truth.
# ════════════════════════════════════════════════════════════════════════

LOGO_CANVAS_W = 270.0   # Canvas preview width
LOGO_CANVAS_H = 480.0   # Canvas preview height


def _calc_logo_placement(params: dict, vw: int, vh: int) -> tuple:
    """
    Tính toán vị trí và kích thước logo trong video thực.

    Args:
        params: dict với keys 'x', 'y', 'width', 'height' — tọa độ trên canvas 270×480
        vw, vh : kích thước video thực (pixels)

    Returns:
        (lx, ly, lw, lh) — tọa độ/kích thước logo trên video thực, even pixels

    ═══ CÔNG THỨC UNIFORM DUY NHẤT (🔵 Claude B fix) ═══════════════════════
    Dùng MỘT scale duy nhất cho TẤT CẢ: x, y, width, height.
        scale = min(vw, vh) / LOGO_CANVAS_W   (= min(vw,vh) / 270)

    Điều này đảm bảo:
      • Logo chiếm cùng % SHORT SIDE trên mọi video (portrait, landscape, bất kỳ AR)
      • Vị trí logo (% short side) ĐỒNG NHẤT giữa mọi video
      • Kích thước logo (% short side) ĐỒNG NHẤT giữa mọi video
      • Không distort aspect ratio logo

    VD: logo đặt tại x=20,y=20,w=80,h=80 trên canvas 270×480
        → 720p portrait  (720×1280): scale=2.667 → lx=54,ly=54,lw=214,lh=214
        → 1080p portrait(1080×1920): scale=4.000 → lx=80,ly=80,lw=320,lh=320
        → Landscape 720p(1280×720) : scale=2.667 → lx=54,ly=54,lw=214,lh=214
        Tất cả đều là 7.5% / 29.7% của short-side → ĐỒNG NHẤT ✅

    LỖI CŨ (đã xóa):
        lx = cx * vw / CANVAS_W  ← dùng vw/270, khác scale khi landscape
        ly = cy * vh / CANVAS_H  ← dùng vh/480, khác scale khi non-9:16
    ════════════════════════════════════════════════════════════════════════
    """
    cx = float(params.get('x', 0))
    cy = float(params.get('y', 0))
    cw = float(params.get('width', 100))
    ch = float(params.get('height', 100))

    # MỘT scale duy nhất cho tất cả (short-side based)
    scale = min(vw, vh) / LOGO_CANVAS_W   # LOGO_CANVAS_W = 270

    # Vị trí VÀ kích thước đều nhân cùng scale → uniform 100%
    lx = round(cx * scale)
    ly = round(cy * scale)
    lw = max(2, round(cw * scale))
    lh = max(2, round(ch * scale))

    # Force even pixels — H.264 yêu cầu
    lx = lx if lx % 2 == 0 else lx + 1
    ly = ly if ly % 2 == 0 else ly + 1
    lw = lw if lw % 2 == 0 else lw + 1
    lh = lh if lh % 2 == 0 else lh + 1

    # Clamp: đảm bảo logo nằm trong frame
    lx = max(0, min(lx, vw - lw))
    ly = max(0, min(ly, vh - lh))
    lw = max(2, min(lw, vw - lx))
    lh = max(2, min(lh, vh - ly))

    return int(lx), int(ly), int(lw), int(lh)


# -------------------- LOGO OVERLAY FUNCTION --------------------
def overlay_logo_on_video(video_bytes, logo_base64, x, y, width, height):
    """
    Thêm logo lên video.
    video_bytes: nội dung video gốc (bytes)
    logo_base64: ảnh logo dạng base64 (chuỗi, có thể bao gồm 'data:image/...')
    x, y: tọa độ góc trên bên trái của logo (pixel)
    width, height: kích thước logo (pixel)
    Trả về bytes video đã overlay.
    """
    if not FFMPEG_AVAILABLE:
        raise Exception("FFmpeg not available for overlay")

    with OVERLAY_SEMAPHORE:
        return _overlay_logo_impl(video_bytes, logo_base64, x, y, width, height)

def _overlay_logo_impl(video_bytes, logo_base64, x, y, width, height):
    # Tạo ID duy nhất
    uid = hashlib.md5(video_bytes[:4096] + str(time.time()).encode()).hexdigest()[:8]
    video_path = os.path.join(FAST_TMPDIR, f'overlay_vid_{uid}.mp4')
    logo_path = os.path.join(FAST_TMPDIR, f'overlay_logo_{uid}.png')
    out_path = os.path.join(FAST_TMPDIR, f'overlay_out_{uid}.mp4')

    try:
        # Ghi video tạm
        with open(video_path, 'wb') as f:
            f.write(video_bytes)

        # Giải mã logo base64
        if logo_base64.startswith('data:image'):
            logo_base64 = logo_base64.split(',', 1)[-1]
        logo_data = base64.b64decode(logo_base64)
        with open(logo_path, 'wb') as f:
            f.write(logo_data)

        # Probe video dimensions
        probe_cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json',
            video_path
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        if probe_res.returncode != 0:
            raise Exception("Cannot probe video dimensions")
        probe_data = json.loads(probe_res.stdout)
        streams = probe_data.get('streams', [])
        if not streams:
            raise Exception("No video stream found")
        vw = int(streams[0].get('width', 0))
        vh = int(streams[0].get('height', 0))
        if vw == 0 or vh == 0:
            raise Exception("Invalid video dimensions")

        # ── Claude B: dùng _calc_logo_placement() — short-side uniform, even pixels ──
        params = {'x': x, 'y': y, 'width': width, 'height': height}
        lx, ly, lw, lh = _calc_logo_placement(params, vw, vh)

        # FFmpeg overlay — dùng HW encoder nếu có, fallback libx264 ultrafast
        # HW encoder nhanh hơn libx264 ultrafast 5-20x (NVENC/VideoToolbox/AMF/QSV)
        if HW_ENCODER != 'libx264':
            _enc_args = ['-c:v', HW_ENCODER] + HW_ENCODER_EXTRA
        else:
            _enc_args = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                         '-threads', _FFMPEG_THREADS, '-tune', 'zerolatency']

        cmd = [
            'ffmpeg', '-y',
            '-probesize', '5000000',          # 🔧 SPEED: giới hạn probe → khởi động nhanh hơn
            '-analyzeduration', '1000000',    # 🔧 SPEED: giảm analyze → ít delay hơn
            '-i', video_path,
            '-i', logo_path,
            '-filter_complex',
            f'[1:v]format=rgba,scale={lw}:{lh}[logo];[0:v][logo]overlay={lx}:{ly}[outv]',
            '-map', '[outv]',
            '-map', '0:a?',
        ] + _enc_args + [
            '-pix_fmt', 'yuv420p',
            '-c:a', 'copy',                   # 🔧 SPEED: copy audio thay vì re-encode AAC
            '-movflags', '+faststart',
            out_path
        ]

        res = subprocess.run(cmd, capture_output=True, timeout=300)
        if res.returncode != 0:
            raise Exception(f"FFmpeg overlay error: {res.stderr.decode(errors='ignore')[-500:]}")

        if not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
            raise Exception("Output file invalid")

        if not validate_video_with_ffprobe(out_path):
            raise Exception("Output file has no valid video stream")

        with open(out_path, 'rb') as f:
            result = f.read()

        return result

    except Exception as e:
        raise Exception(f"Overlay failed: {str(e)}")
    finally:
        # Dọn dẹp
        for p in [video_path, logo_path, out_path]:
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except:
                pass

def _overlay_logo_on_file(input_path, output_path, logo_base64, x, y, width, height):
    """
    Overlay logo trực tiếp từ file → file (không load video vào RAM).
    Dùng OVERLAY_SEMAPHORE, tối đa 10 tiến trình song song.
    """
    if not FFMPEG_AVAILABLE:
        raise Exception("FFmpeg not available for overlay")
    with OVERLAY_SEMAPHORE:
        _overlay_logo_on_file_impl(input_path, output_path, logo_base64, x, y, width, height)

def _overlay_logo_on_file_impl(input_path, output_path, logo_base64, x, y, width, height):
    """Thực thi overlay logo từ file → file (gọi bên trong OVERLAY_SEMAPHORE).
    Claude B: Dùng _calc_logo_placement() — short-side uniform scale, even pixels."""
    uid = hashlib.md5((input_path + str(time.time())).encode()).hexdigest()[:8]
    logo_path = os.path.join(FAST_TMPDIR, f'overlay_logo_{uid}.png')

    try:
        # Giải mã và lưu logo
        raw_b64 = logo_base64.split(',', 1)[-1] if logo_base64.startswith('data:image') else logo_base64
        with open(logo_path, 'wb') as f:
            f.write(base64.b64decode(raw_b64))

        # Probe kích thước video
        probe_res = subprocess.run([
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json', input_path
        ], capture_output=True, text=True, timeout=5)
        if probe_res.returncode != 0:
            raise Exception("Cannot probe video dimensions")
        probe_data = json.loads(probe_res.stdout)
        streams = probe_data.get('streams', [])
        if not streams:
            raise Exception("No video stream found")
        vw = int(streams[0].get('width', 0))
        vh = int(streams[0].get('height', 0))
        if vw == 0 or vh == 0:
            raise Exception("Invalid video dimensions")

        # ── Claude B: dùng shared helper thay vì 2 scale riêng biệt ─────────
        # Old code: width *= sx, height *= sy → distort logo trên non-9:16 video
        # New code: _calc_logo_placement() → short-side uniform, even pixels, no distort
        params = {'x': x, 'y': y, 'width': width, 'height': height}
        lx, ly, lw, lh = _calc_logo_placement(params, vw, vh)

        # FFmpeg overlay — ưu tiên HW encoder (NVENC/VideoToolbox/AMF/QSV)
        if HW_ENCODER != 'libx264':
            _enc_v = ['-c:v', HW_ENCODER] + HW_ENCODER_EXTRA
        else:
            _enc_v = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                      '-threads', _FFMPEG_THREADS, '-tune', 'zerolatency']

        flt = (f'[1:v]format=rgba,scale={lw}:{lh}[logo];'
               f'[0:v][logo]overlay={lx}:{ly}[outv]')
        _common_front = ['ffmpeg','-y',
                         '-probesize','5000000','-analyzeduration','1000000']
        strategies = [
            # S1: HW encoder + copy audio (nhanh nhất nếu HW khả dụng)
            (240, _common_front + ['-i',input_path,'-i',logo_path,
                   '-filter_complex', flt, '-map','[outv]','-map','0:a?',
                   '-pix_fmt','yuv420p','-c:a','copy',
                   '-movflags','+faststart'] + _enc_v + [output_path]),
            # S2: libx264 ultrafast + copy audio (fallback)
            (300, _common_front + ['-i',input_path,'-i',logo_path,
                   '-filter_complex', flt, '-map','[outv]','-map','0:a?',
                   '-c:v','libx264','-preset','ultrafast','-crf','23',
                   '-threads',_FFMPEG_THREADS,'-pix_fmt','yuv420p',
                   '-c:a','copy','-movflags','+faststart',output_path]),
            # S3: re-encode audio AAC (nếu audio stream không compatible)
            (360, _common_front + ['-i',input_path,'-i',logo_path,
                   '-filter_complex', flt, '-map','[outv]','-map','0:a?',
                   '-c:v','libx264','-preset','ultrafast','-crf','23',
                   '-threads',_FFMPEG_THREADS,'-pix_fmt','yuv420p',
                   '-c:a','aac','-b:a','128k','-movflags','+faststart',output_path]),
        ]
        last_err = ''
        for tmo, cmd in strategies:
            if os.path.exists(output_path):
                try: os.unlink(output_path)
                except: pass
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=tmo)
                if res.returncode == 0 and os.path.exists(output_path):
                    if os.path.getsize(output_path) > 1024 and validate_video_with_ffprobe(output_path):
                        return
                last_err = res.stderr.decode(errors='ignore')[-300:]
            except (subprocess.TimeoutExpired, Exception) as e:
                last_err = str(e)
        raise Exception(f"Overlay failed — {last_err}")



    except Exception as e:
        raise Exception(f"Overlay (file) failed: {str(e)}")
    finally:
        try:
            if os.path.exists(logo_path):
                os.unlink(logo_path)
        except:
            pass

# -------------------- COOKIE MANAGEMENT --------------------
COOKIES_FILE = os.path.join(os.path.dirname(__file__), 'tiktok_cookies.txt')
COOKIES_DICT = {}

def load_cookies_from_file(filepath):
    """Load cookies from Netscape format file, filter only tiktok.com"""
    cookies = {}
    try:
        if not os.path.exists(filepath):
            return cookies
        
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split('\t')
                if len(parts) >= 7:
                    domain = parts[0]
                    # Chỉ lấy cookie cho tiktok.com
                    if 'tiktok.com' in domain:
                        name, value = parts[5], parts[6]
                        cookies[name] = value
        

        return cookies
    except Exception as e:

        return cookies

def load_cookies_from_json(filepath):
    """Load cookies from JSON file, filter tiktok.com"""
    try:
        if not os.path.exists(filepath):
            return {}
        
        with open(filepath, 'r') as f:
            all_cookies = json.load(f)
        
        # Lọc chỉ lấy cookie có domain chứa tiktok.com
        tiktok_cookies = {}
        for name, value in all_cookies.items():
            # Nếu là dict có thể có domain
            if isinstance(value, dict) and 'domain' in value and 'tiktok.com' in value['domain']:
                tiktok_cookies[name] = value.get('value', '')
            else:
                # Nếu là key-value đơn giản, giả sử là cookie tiktok
                tiktok_cookies[name] = value
        

        return tiktok_cookies
    except Exception as e:

        return {}

def get_cookies_dict():
    """Get cookies dictionary for requests, chỉ lấy cookie TikTok"""
    global COOKIES_DICT
    
    # Try loading cookies from files
    if os.path.exists(COOKIES_FILE):
        COOKIES_DICT = load_cookies_from_file(COOKIES_FILE)
    elif os.path.exists('cookies.json'):
        COOKIES_DICT = load_cookies_from_json('cookies.json')
    
    # Add environment variable cookies if available (dạng JSON)
    env_cookies = os.environ.get('TIKTOK_COOKIES')
    if env_cookies:
        try:
            env_cookies_dict = json.loads(env_cookies)
            # Lọc nếu cần
            COOKIES_DICT.update(env_cookies_dict)

        except:
            pass
    
    return COOKIES_DICT

# Load cookies on startup
COOKIES_DICT = get_cookies_dict()

# -------------------- VIDEO VALIDATION (CẢI TIẾN) --------------------
def has_video_track(content):
    """
    Kiểm tra file có chứa video track hợp lệ.
    Ưu tiên dùng ffprobe (chính xác); fallback sang byte-scan.
    """
    if not content or len(content) < 4096:
        return False

    # --- Thử ffprobe trước (chính xác nhất) ---
    if FFMPEG_AVAILABLE:
        try:
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                tmp.write(content[:min(len(content), 4 * 1024 * 1024)])  # chỉ cần 4MB để probe
                tmp_path = tmp.name
            try:
                cmd = [
                    'ffprobe', '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_type,width,height',
                    '-of', 'json',
                    tmp_path
                ]
                r = subprocess.run(cmd, capture_output=True, timeout=10, text=True)
                if r.returncode == 0:
                    data = json.loads(r.stdout)
                    for s in data.get('streams', []):
                        # select_streams v:0 đã lọc video — chỉ cần width > 0
                        w = s.get('width', 0)
                        if w and int(w) > 0:
                            return True
                        # fallback: kiểm tra codec_type nếu có
                        if s.get('codec_type') == 'video' and s.get('width', 0) > 0:
                            return True
                    # ffprobe chạy được nhưng không thấy video stream
                    return False
            finally:
                try: os.unlink(tmp_path)
                except: pass
        except Exception:
            pass  # ffprobe không dùng được, fallback sang byte-scan

    # --- Fallback: byte-scan (scan tối đa 2MB) ---
    scan_size = min(len(content), 2 * 1024 * 1024)
    header = content[:scan_size]
    video_boxes = [b'vide', b'vmhd', b'avc1', b'hvc1', b'hev1', b'vp09', b'av01',
                   b'dvhe', b'dvh1', b'avc3', b'avc4', b'mp4v', b'xvid', b'H264']
    if any(box in header for box in video_boxes):
        return True
    audio_boxes = [b'soun', b'smhd', b'mp4a']
    if any(box in header for box in audio_boxes):
        return False
    return len(content) > 500 * 1024

def is_audio_only(content):
    """
    Xác định file chỉ chứa audio (không video).
    """
    if not content or len(content) < 1024:
        return False
    scan_size = min(len(content), 1 * 1024 * 1024)
    header = content[:scan_size]
    # Dấu hiệu audio-only rõ ràng
    if header.startswith(b'ID3') or header.startswith(b'\xff\xfb'):
        return True
    # Box ftyp M4A (chỉ kiểm tra ở đầu file)
    if b'ftyp' in content[:32] and b'M4A ' in content[:100]:
        return True
    # Có box audio nhưng không có video box (trong toàn bộ vùng scan)
    has_audio_box = b'soun' in header or b'smhd' in header or b'mp4a' in header
    video_boxes = [b'vide', b'vmhd', b'avc1', b'hvc1', b'hev1', b'vp09', b'av01',
                   b'dvhe', b'dvh1', b'avc3', b'mp4v']
    has_video_box = any(b in header for b in video_boxes)
    if has_audio_box and not has_video_box:
        return True
    return False

def validate_video_content(content, min_size=50*1024, strict=True):
    """
    Validate video content với video track bắt buộc.
    """
    if not content:
        return False, "Empty content"
    if len(content) < min_size:
        return False, f"File too small ({len(content)} bytes)"
    if is_audio_only(content):
        return False, "❌ AUDIO-ONLY file detected"
    if not has_video_track(content):
        return False, "❌ No video track detected"
    return True, "✅ Valid video with video track"


def deep_validate_video_file(filepath: str, decode_test: bool = True) -> tuple:
    """
    🔵 Claude B: Kiểm tra video CỰC KỲ nghiêm ngặt — đảm bảo không 1 video lỗi nào.

    Các bước kiểm tra:
      1. File tồn tại và đủ kích thước (≥80KB)
      2. ffprobe đọc được (container hợp lệ)
      3. Có video stream với width > 0
      4. Không phải audio-only
      5. Duration hợp lý (> 0, < 24h)
      6. Decode test: giải mã 1 frame thực tế (phát hiện corrupt frame)

    Trả về (ok: bool, reason: str)
    """
    MIN_SIZE = 80 * 1024
    if not filepath or not os.path.exists(filepath):
        return False, 'file_not_found'

    size = os.path.getsize(filepath)
    if size < MIN_SIZE:
        return False, f'too_small({size}B)'

    if not FFMPEG_AVAILABLE:
        return True, 'ffprobe_unavailable_passthrough'

    # ── Bước 2+3+4+5: ffprobe đầy đủ ─────────────────────────────────────────
    try:
        r = subprocess.run([
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=codec_type,width,height,codec_name'
                            ':format=duration,size',
            '-of', 'json', filepath
        ], capture_output=True, text=True, timeout=12)

        if r.returncode != 0:
            return False, f'ffprobe_failed({r.stderr[-100:]})'

        d = json.loads(r.stdout)
        streams = d.get('streams', [])
        fmt = d.get('format', {})

        # Kiểm tra video stream
        video_streams = [s for s in streams if s.get('codec_type') == 'video']
        if not video_streams:
            VIDEO_CODECS = {'h264','hevc','vp9','vp8','av1','mpeg4','avc','hvc1','hev1','prores'}
            if not any(s.get('codec_name','').lower() in VIDEO_CODECS for s in streams):
                return False, 'no_video_stream'

        # Kiểm tra width > 0
        for vs in video_streams:
            w = int(vs.get('width', 0) or 0)
            if w <= 0:
                return False, f'invalid_width({w})'

        # 🟢 Kiểm tra codec=none — video stream tồn tại nhưng không decode được
        _BROKEN_CODECS = {'none', '', 'unknown', 'rawvideo', 'bin_data', 'data'}
        for vs in video_streams:
            vc = (vs.get('codec_name') or '').lower().strip()
            if vc in _BROKEN_CODECS or 'unknown' in vc:
                return False, f'codec_not_decodable({vc!r})'

        # Kiểm tra audio-only
        audio_only_streams = [s for s in streams if s.get('codec_type') == 'audio']
        if audio_only_streams and not video_streams:
            return False, 'audio_only'

        # Kiểm tra duration
        dur = float(fmt.get('duration', 0) or 0)
        if dur < 0 or dur > 86400:
            return False, f'bad_duration({dur:.1f}s)'

        # ── Bước 6: Decode test — giải mã 1 frame thực tế ────────────────────
        # Phát hiện: corrupt container, truncated bitstream, broken B-frame ref
        # Timeout nhân với tier factor: CPU yếu cho thêm thời gian
        if decode_test and FFMPEG_AVAILABLE:
            decode_timeout = int(15 * _FFMPEG_TIMEOUT_FACTOR)
            try:
                r_dec = subprocess.run([
                    'ffmpeg', '-v', 'error',
                    '-i', filepath,
                    '-vframes', '1',
                    '-f', 'null', '-'
                ], capture_output=True, timeout=decode_timeout)

                if r_dec.returncode != 0:
                    stderr_txt = r_dec.stderr.decode(errors='ignore').lower()
                    # Phân biệt lỗi THỰC SỰ vs warnings bình thường của TikTok
                    FATAL = ['no such file', 'invalid data found when processing input',
                             'moov atom not found', 'decoder not found',
                             'could not find codec parameters', 'no video stream found']
                    # Warnings bình thường của TikTok fragmented MP4 — KHÔNG fail
                    TIKTOK_NORMAL = ['missing picture', 'concealing', 'mmco', 'poc']

                    is_fatal = any(p in stderr_txt for p in FATAL)
                    is_normal = any(p in stderr_txt for p in TIKTOK_NORMAL)

                    if is_fatal and not is_normal:
                        return False, f'decode_failed({r_dec.returncode})'
                    # rc != 0 nhưng chỉ có warnings bình thường → OK
            except subprocess.TimeoutExpired:
                # Decode timeout trên CPU yếu → passthrough (đừng reject video hợp lệ)
                log_process(f'[deep_validate] decode test timeout ({decode_timeout}s) — passthrough')
            except Exception as e_dec:
                log_process(f'[deep_validate] decode test exception: {e_dec}')

        return True, f'ok(size={size//1024}KB dur={dur:.1f}s)'

    except json.JSONDecodeError:
        return False, 'ffprobe_json_error'
    except Exception as e:
        return True, f'exception_passthrough({e})'   # không block khi lỗi không rõ

# -------------------- HYPERSPEED CONFIGURATION --------------------
PROXY = os.environ.get('TIKTOK_PROXY')
proxies_dict = {'http': PROXY, 'https': PROXY} if PROXY else None

OPTIMAL_CHUNKS = 8  # base, will be adjusted

TIKTOK_CDN_ENDPOINTS = [
    'https://v16-webapp-prime.tiktok.com',
    'https://v19-webapp.tiktok.com',
    'https://v16-webapp.tiktok.com',
    'https://v77-webapp.tiktok.com',
    'https://v19-webapp-prime.tiktok.com',
    'https://v16m-webapp.tiktok.com',
]

MOBILE_API_ENDPOINTS = [
    'https://api16-normal-c-useast1a.tiktokv.com',
    'https://api19-normal-c-useast2a.tiktokv.com',
    'https://api22-normal-c-useast1a.tiktokv.com',
    'https://api16-core-c-useast1a.tiktokv.com',
    'https://api16-normal-c-useast2a.tiktokv.com',
    'https://api2-normal-c-useast1a.tiktokv.com',
    'https://api16-normal-useast5.tiktokv.com',
]

# -------------------- HTTPX ASYNC CLIENT --------------------
if HTTPX_AVAILABLE:
    try:
        async_client = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),  # 20/50→8/16
            timeout=httpx.Timeout(25.0),
        )
    except Exception:
        async_client = None
else:
    async_client = None

# ── SESSION POOL — tối ưu cho tốc độ download x100 ──────────────────────────
SESSION_POOL = []
from urllib3.util.retry import Retry as _Retry
for _ in range(12):   # 12 sessions cho parallel requests
    sess = requests.Session()
    sess.proxies = proxies_dict if proxies_dict else {}
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=16,
        pool_maxsize=32,
        max_retries=_Retry(total=2, backoff_factor=0.1,
                           status_forcelist=[429, 500, 502, 503, 504],
                           allowed_methods=['GET', 'POST']),
        pool_block=False
    )
    sess.mount('http://', adapter)
    sess.mount('https://', adapter)
    sess.headers.update({'Connection': 'keep-alive'})
    SESSION_POOL.append(sess)

def get_session():
    return random.choice(SESSION_POOL)

# -------------------- USER AGENTS --------------------
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
]

MOBILE_USER_AGENTS = [
    'TikTok 29.1.0 rv:291024 (iPhone; iOS 16.6; en_US) Cronet',
    'TikTok 29.2.0 rv:292048 (iPhone; iOS 17.0; en_US) Cronet',
]

def get_random_ua():
    return random.choice(USER_AGENTS)

def get_random_mobile_ua():
    return random.choice(MOBILE_USER_AGENTS)

# -------------------- HEADERS --------------------
def get_browser_headers(referer='https://www.tiktok.com/', ua=None, include_cookies=True):
    if ua is None:
        ua = get_random_ua()
    
    headers = {
        'User-Agent': ua,
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Referer': referer,
        'Origin': 'https://www.tiktok.com',
        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="132"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'video',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Connection': 'keep-alive',
    }
    
    # Add cookies to headers if available
    if include_cookies and COOKIES_DICT:
        cookie_str = '; '.join([f"{k}={v}" for k, v in COOKIES_DICT.items()])
        headers['Cookie'] = cookie_str
    
    return headers

def get_video_download_headers(video_url, referer='https://www.tiktok.com/'):
    headers = get_browser_headers(referer, include_cookies=True)
    headers.update({
        'Accept': 'video/webm,video/ogg,video/*;q=0.9',
        'Range': 'bytes=0-',
    })
    return headers

# -------------------- UTILITIES --------------------
def extract_video_id(url):
    patterns = [
        r'/video/(\d+)',
        r'@[\w\.-]+/video/(\d+)',
        r'vt\.tiktok\.com/(\w+)',
        r'vm\.tiktok\.com/(\w+)',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    for part in url.split('/'):
        if part.isdigit() and len(part) > 15:
            return part
    return None

def is_valid_tiktok_url(url):
    return bool(re.match(r'^https?://(www\.|vm\.|vt\.)?tiktok\.com/', url))

# ── USED-NAMES REGISTRY (tránh trùng tên file) ───────────────────────────────
_USED_NAMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'used_names.txt')
_used_names_lock = threading.Lock()
_used_names_set: set = set()

def _load_used_names():
    """Đọc danh sách tên đã dùng từ file .txt khi khởi động."""
    global _used_names_set
    try:
        if os.path.exists(_USED_NAMES_FILE):
            with open(_USED_NAMES_FILE, 'r', encoding='utf-8') as f:
                _used_names_set = {line.strip() for line in f if line.strip()}
    except Exception:
        _used_names_set = set()

def _save_used_name(name: str):
    """Ghi tên mới vào file .txt (append)."""
    try:
        with open(_USED_NAMES_FILE, 'a', encoding='utf-8') as f:
            f.write(name + '\n')
    except Exception:
        pass

_load_used_names()   # Gọi ngay khi module load

def _gen_random_suffix(length: int = 10) -> str:
    """Sinh chuỗi gồm chữ hoa, chữ thường và số, không trùng với tên đã dùng."""
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    with _used_names_lock:
        for _ in range(10000):   # tối đa 10 000 lần thử
            suffix = ''.join(random.choices(chars, k=length))
            stem   = f'tikdown_{suffix}'
            if stem not in _used_names_set:
                _used_names_set.add(stem)
                _save_used_name(stem)
                return suffix
    # fallback cực kỳ hiếm: thêm timestamp để đảm bảo unique
    suffix = ''.join(random.choices(chars, k=length)) + str(int(time.time()))[-4:]
    stem   = f'tikdown_{suffix}'
    _used_names_set.add(stem)
    _save_used_name(stem)
    return suffix

def safe_filename(title=None, video_id=None, max_len=80, features=None):
    """
    Tên file: tikdown_<RANDOM_10_CHARS>.mp4
    RANDOM_10_CHARS: chữ hoa + chữ thường + số, không trùng với các tên đã dùng.
    Danh sách tên đã dùng được lưu vào used_names.txt.
    """
    suffix = _gen_random_suffix(10)
    return f'tikdown_{suffix}.mp4'

# -------------------- IMPROVED FORMAT SELECTION --------------------
def select_best_video_format(formats, prefer_audio=True):
    """
    Chọn format tốt nhất có video.
    Nếu prefer_audio=True: ưu tiên format có cả video+audio.
    Nếu prefer_audio=False: ưu tiên format video-only (hoặc có thể strip sau).
    """
    if not formats:
        return None
    
    video_formats = []
    
    for fmt in formats:
        # CRITICAL: Must have video codec
        if fmt.get('vcodec') == 'none' or not fmt.get('vcodec'):
            continue
        
        ext = fmt.get('ext', '')
        has_audio = fmt.get('acodec') not in ['none', None]
        is_mp4 = ext in ['mp4', 'm4v']
        
        video_formats.append({
            'format': fmt,
            'has_audio': has_audio,
            'is_mp4': is_mp4,
            'height': fmt.get('height', 0) or 0,
            'width': fmt.get('width', 0) or 0,
            'filesize': fmt.get('filesize', 0) or 0,
            'url': fmt.get('url', ''),
            'ext': ext,
        })
    
    if not video_formats:
        return None
    
    # Sort theo tiêu chí
    if prefer_audio:
        # Ưu tiên: MP4 > has_audio > resolution > size
        video_formats.sort(
            key=lambda x: (
                x['is_mp4'],      # Prefer MP4
                x['has_audio'],   # Prefer with audio
                x['height'],      # Higher resolution
                x['filesize'],    # Larger file
            ),
            reverse=True
        )
    else:
        # Ưu tiên video-only, sau đó mới đến MP4, resolution
        video_formats.sort(
            key=lambda x: (
                not x['has_audio'],   # Prefer video-only
                x['is_mp4'],
                x['height'],
                x['filesize'],
            ),
            reverse=True
        )
    
    best = video_formats[0]

    
    return best['url']

# -------------------- INFO EXTRACTION (CONCURRENT) --------------------
def get_tiktok_info_mobile_api(url, endpoint=None):
    try:
        video_id = extract_video_id(url)
        if not video_id or not video_id.isdigit():
            return None

        if endpoint is None:
            endpoint = random.choice(MOBILE_API_ENDPOINTS)
        
        api_url = f"{endpoint}/aweme/v1/feed/?aweme_id={video_id}"
        headers = {'User-Agent': get_random_mobile_ua(), 'Accept-Encoding': 'gzip, deflate'}
        if COOKIES_DICT:
            headers['Cookie'] = '; '.join([f"{k}={v}" for k, v in COOKIES_DICT.items()])

        sess = get_session()
        resp = sess.get(api_url, headers=headers, timeout=3)   # 3s thay vì 5s
        if resp.status_code != 200:
            return None

        data = resp.json()
        if 'aweme_list' not in data or not data['aweme_list']:
            return None

        item = data['aweme_list'][0]
        video = item.get('video', {})
        author = item.get('author', {})

        play_addr     = video.get('play_addr', {})
        download_addr = video.get('download_addr', {})
        
        video_urls = (
            download_addr.get('url_list', []) +
            play_addr.get('url_list', [])
        )
        
        video_url = None
        for vurl in video_urls:
            if 'audio' in vurl.lower() or 'music' in vurl.lower():
                continue
            video_url = vurl
            break
        
        if not video_url and video_urls:
            video_url = video_urls[0]

        return {
            'id': item.get('aweme_id', video_id),
            'title': item.get('desc', 'TikTok Video'),
            'uploader': author.get('unique_id', 'unknown'),
            'duration': video.get('duration', 0) / 1000,
            'thumbnail': video.get('cover', {}).get('url_list', [''])[0],
            'play_url': video_url,
            'download_url': video_url,
            'webpage_url': url,
            'valid': True,
            'method': 'mobile-api'
        }
    except Exception:
        return None

def get_tiktok_info_ytdlp(url, audio=True):
    """yt-dlp with flexible format selection based on audio flag."""
    if not YT_DLP_AVAILABLE:
        return None
    if audio:
        format_strategies = [
            'bestvideo[ext=mp4][vcodec!=none]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio',
            'bestvideo[vcodec!=none]+bestaudio/best',
            'best[vcodec!=none][acodec!=none]',
            'bestvideo+bestaudio',
            'best[vcodec!=none]',
            'best',   # fallback không điều kiện: yt-dlp tự chọn format tốt nhất
            None,     # fallback tuyệt đối: không filter, dùng default yt-dlp
        ]
    else:
        # QUAN TRỌNG: KHÔNG dùng video-only stream vì có thể là H.265/VP9 không tương thích browser.
        # Tải combined video+audio rồi strip audio sau bằng FFmpeg.
        format_strategies = [
            'best[ext=mp4][vcodec!=none][acodec!=none]',
            'bestvideo[ext=mp4][vcodec!=none]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio',
            'best[vcodec!=none][acodec!=none]',
            'best[vcodec!=none]',
            'best',   # fallback không điều kiện
            None,     # fallback tuyệt đối
        ]
    
    for strategy_idx, format_str in enumerate(format_strategies):
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
            'no_check_formats': True,          # bỏ qua kiểm tra format khả dụng
            'allow_unplayable_formats': True,  # cho phép mọi format
            'http_headers': get_browser_headers(include_cookies=False),
            'nocheckcertificate': True,
            'extractor_args': {
                'tiktok': {
                    'api_hostname': random.choice(MOBILE_API_ENDPOINTS).replace('https://', ''),
                    'app_version': '36.1.3',   # newer version bypass status 10240
                    'app_name':    'musical_ly',
                    'webpage_download': ['0'],  # dùng API thay web
                }
            },
        }
        if format_str is not None:
            ydl_opts['format'] = format_str
        
        # Add cookies via file if available
        cookie_file = None
        if COOKIES_DICT:
            cookie_file = os.path.join(FAST_TMPDIR, f'yt_cookies_{uuid.uuid4().hex[:8]}.txt')
            try:
                with open(cookie_file, 'w', newline='\n', encoding='utf-8') as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    f.write("# This file was generated by TikDown. Edit at your own risk.\n\n")
                    for name, value in COOKIES_DICT.items():
                        safe_name  = str(name).replace('\t','').replace('\n','').replace('\r','')
                        safe_value = str(value).replace('\t','').replace('\n','').replace('\r','')
                        if safe_name:
                            f.write(f".tiktok.com\tTRUE\t/\tFALSE\t0\t{safe_name}\t{safe_value}\n")
                ydl_opts['cookiefile'] = cookie_file
            except Exception:
                cookie_file = None
        
        if PROXY:
            ydl_opts['proxy'] = PROXY

        try:
            with _ytdlp_lock, yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    info = info['entries'][0]

                video_id = info.get('id', extract_video_id(url) or 'unknown')
                
                # Get URL
                direct_url = None
                if info.get('url'):
                    direct_url = info['url']
                elif info.get('requested_downloads'):
                    direct_url = info['requested_downloads'][0].get('url')
                elif info.get('formats'):
                    direct_url = select_best_video_format(info['formats'], prefer_audio=audio)
                
                if direct_url:

                    if cookie_file and os.path.exists(cookie_file):
                        try: os.remove(cookie_file)
                        except: pass
                    return {
                        'id': video_id,
                        'title': info.get('title') or f'TikTok Video {video_id}',
                        'uploader': info.get('uploader') or 'unknown',
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail', ''),
                        'play_url': direct_url,
                        'download_url': direct_url,
                        'webpage_url': url,
                        'valid': True,
                        'method': f'yt-dlp-strategy-{strategy_idx + 1}'
                    }
                else:
                    continue
                    
        except Exception as e:
            if cookie_file and os.path.exists(cookie_file):
                try: os.remove(cookie_file)
                except: pass

            continue
    
    return None

def get_tiktok_info_parallel(url, audio=True):
    """
    Race tất cả nguồn song song — lấy kết quả nhanh nhất cho tìm kiếm tức thì.
    """
    cancel = threading.Event()
    result_box  = [None]
    result_lock = threading.Lock()
    found_ev    = threading.Event()

    def _try(fn):
        if cancel.is_set(): return
        try:
            r = fn(url) if fn != get_tiktok_info_ytdlp else fn(url, audio=audio)
            if r and r.get('download_url'):
                with result_lock:
                    if result_box[0] is None:
                        result_box[0] = r
                        found_ev.set()
                        cancel.set()
        except Exception:
            pass

    # 5 nguồn nhanh chạy đồng thời — yt-dlp khởi động sau 4s nếu chưa xong
    fast_fns = [
        get_tiktok_info_mobile_api_all_endpoints,
        get_tiktok_info_tikwm,
        get_tiktok_info_ssstik,
        get_tiktok_info_ttdownloader,
        get_tiktok_info_snaptik,
    ]

    def _ytdlp_delayed():
        found_ev.wait(timeout=4.0)
        if not cancel.is_set():
            _try(get_tiktok_info_ytdlp)

    with ThreadPoolExecutor(max_workers=len(fast_fns) + 1) as ex:
        for fn in fast_fns:
            ex.submit(_try, fn)
        ex.submit(_ytdlp_delayed)
        found_ev.wait(timeout=18.0)
        cancel.set()

    info = result_box[0]
    if info:
        info['url'] = url
        return info

    return {
        'id': extract_video_id(url) or 'unknown',
        'title': 'TikTok Video',
        'url': url,
        'valid': False,
        'error': 'All extraction methods failed'
    }

def get_tiktok_info_mobile_api_all_endpoints(url):
    """
    Race tất cả 5 mobile API endpoints SONG SONG.
    Endpoint nào trả kết quả hợp lệ trước → thắng, huỷ còn lại.
    """
    cancel = threading.Event()

    def _try(ep):
        if cancel.is_set(): return None
        info = get_tiktok_info_mobile_api(url, ep)
        if info and info.get('download_url') and not cancel.is_set():
            cancel.set()
            return info
        return None

    with ThreadPoolExecutor(max_workers=len(MOBILE_API_ENDPOINTS)) as ex:
        futures = {ex.submit(_try, ep): ep for ep in MOBILE_API_ENDPOINTS}
        for f in as_completed(futures):
            try:
                res = f.result()
                if res and res.get('download_url'):
                    return res
            except Exception:
                continue
    return None

def get_tiktok_info_tikwm(url):
    """Dùng tikwm.com API - hoạt động không cần auth, ổn định."""
    try:
        api_url = "https://www.tikwm.com/api/"
        payload = {"url": url, "hd": 1}
        headers = {
            'User-Agent': get_random_ua(),
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'https://www.tikwm.com/',
        }
        sess = get_session()
        resp = sess.post(api_url, data=payload, headers=headers, timeout=5)
        if resp.status_code != 200:
            return None

        result = resp.json()
        if result.get('code') != 0:
            return None

        data = result.get('data', {})
        video_url = data.get('hdplay') or data.get('play') or data.get('wmplay')
        if not video_url:
            return None

        author = data.get('author', {})
        return {
            'id': str(data.get('id', extract_video_id(url) or 'unknown')),
            'title': data.get('title', 'TikTok Video'),
            'uploader': author.get('unique_id', 'unknown'),
            'duration': data.get('duration', 0),
            'thumbnail': data.get('cover', ''),
            'play_url': video_url,
            'download_url': video_url,
            'webpage_url': url,
            'valid': True,
            'method': 'tikwm',
            'file_size': data.get('size', 0),
        }
    except Exception:
        return None


def get_tiktok_info_ssstik(url):
    """ssstik.io API — hỗ trợ tốt video mới, không watermark."""
    try:
        api_url = 'https://ssstik.io/abc?url=dl'
        headers = {
            'User-Agent': get_random_ua(),
            'Referer':    'https://ssstik.io/',
            'Origin':     'https://ssstik.io',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        sess = get_session()
        # Bước 1: lấy token
        r0 = sess.get('https://ssstik.io/', headers={'User-Agent': get_random_ua()}, timeout=5)
        token = ''
        if r0.ok:
            m = re.search(r'id="token"\s+value="([^"]+)"', r0.text)
            if m:
                token = m.group(1)

        payload = {'id': url, 'locale': 'en', 'tt': token}
        resp = sess.post(api_url, data=payload, headers=headers, timeout=6)
        if not resp.ok:
            return None

        # Parse HTML response
        import html as _html
        text = resp.text
        # Tìm link download không watermark
        m = re.search(r'href="(https://[^"]+)"[^>]*>\s*Without watermark', text, re.I)
        if not m:
            m = re.search(r'href="(https://tikcdn[^"]+\.mp4[^"]*)"', text)
        if not m:
            m = re.search(r'href="(https://[^"]+\.mp4[^"]*)"', text)
        if not m:
            return None

        video_url = _html.unescape(m.group(1))
        # Lấy title
        tm = re.search(r'<p[^>]*class="[^"]*maintext[^"]*"[^>]*>([^<]+)<', text)
        title = tm.group(1).strip() if tm else 'TikTok Video'
        return {
            'id': extract_video_id(url) or 'unknown',
            'title': title,
            'uploader': 'unknown',
            'duration': 0,
            'thumbnail': '',
            'play_url': video_url,
            'download_url': video_url,
            'webpage_url': url,
            'valid': True,
            'method': 'ssstik',
        }
    except Exception:
        return None



def get_tiktok_info_cobalt(url: str):
    """
    cobalt.tools API — không cần auth, bypass nhiều geo-block, timeout 6s.
    API docs: https://github.com/imputnet/cobalt
    """
    try:
        resp = get_session().post(
            'https://api.cobalt.tools/api/json',
            json={
                'url': url,
                'vCodec': 'h264',
                'vQuality': '720',
                'aFormat': 'mp3',
                'isAudioOnly': False,
                'disableMetadata': False,
            },
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'User-Agent': get_random_ua(),
            },
            timeout=6
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        status = data.get('status', '')
        if status not in ('stream', 'redirect', 'tunnel', 'success'):
            return None
        video_url = data.get('url') or data.get('stream')
        if not video_url:
            return None
        video_id = extract_video_id(url) or 'unknown'
        return {
            'id':           video_id,
            'title':        data.get('filename', 'TikTok Video').replace('.mp4', ''),
            'download_url': video_url,
            'play_url':     video_url,
            'valid':        True,
            'method':       'cobalt',
        }
    except Exception:
        return None


def get_tiktok_info_locodownloader(url: str):
    """
    locodownloader / tikmate / similar — backup method, no-watermark support.
    """
    try:
        video_id = extract_video_id(url)
        if not video_id:
            return None
        resp = get_session().get(
            f'https://api.tikmate.app/api/lookup?url={quote(url, safe="")}',
            headers={
                'User-Agent': get_random_ua(),
                'Referer':    'https://tikmate.app/',
                'Origin':     'https://tikmate.app',
            },
            timeout=5
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        token = data.get('token')
        vid   = data.get('id', video_id)
        if not token:
            return None
        video_url = f'https://tikmate.app/download/{token}/{vid}.mp4'
        return {
            'id':           vid,
            'title':        data.get('desc', 'TikTok Video'),
            'download_url': video_url,
            'play_url':     video_url,
            'valid':        True,
            'method':       'tikmate',
        }
    except Exception:
        return None


def get_tiktok_info_ttdownloader(url):
    """ttdownloader.com API — nhanh, không cần auth."""
    try:
        sess = get_session()
        # Lấy token từ trang chủ
        r0 = sess.get('https://ttdownloader.com/', timeout=5,
                      headers={'User-Agent': get_random_ua()})
        token = ''
        if r0.ok:
            m = re.search(r'name="token"\s+value="([^"]+)"', r0.text)
            if m:
                token = m.group(1)

        resp = sess.post(
            'https://ttdownloader.com/search/',
            data={'query': url, 'format': '', 'token': token},
            headers={
                'User-Agent':  get_random_ua(),
                'Referer':     'https://ttdownloader.com/',
                'Content-Type':'application/x-www-form-urlencoded',
            },
            timeout=6
        )
        if not resp.ok:
            return None

        # Tìm link video không watermark
        m = re.search(r'href="(https://[^"]+)"[^>]*>Without Watermark', resp.text, re.I)
        if not m:
            m = re.search(r'href="(https://[^"]+\.mp4[^"]*)"', resp.text)
        if not m:
            return None

        video_url = m.group(1)
        return {
            'id': extract_video_id(url) or 'unknown',
            'title': 'TikTok Video',
            'uploader': 'unknown',
            'duration': 0,
            'thumbnail': '',
            'play_url': video_url,
            'download_url': video_url,
            'webpage_url': url,
            'valid': True,
            'method': 'ttdownloader',
        }
    except Exception:
        return None


def get_tiktok_info_snaptik(url):
    """snaptik.app API — phổ biến, hỗ trợ tốt."""
    try:
        sess = get_session()
        video_id = extract_video_id(url)
        if not video_id:
            return None

        resp = sess.post(
            'https://snaptik.app/abc2.php',
            data={'url': url},
            headers={
                'User-Agent':   get_random_ua(),
                'Referer':      'https://snaptik.app/',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            timeout=6
        )
        if not resp.ok:
            return None

        j = resp.json()
        # token
        token = j.get('token', '')
        if not token:
            return None

        # Render endpoint
        resp2 = sess.get(
            f'https://snaptik.app/render-hd.php?token={token}',
            headers={'User-Agent': get_random_ua(), 'Referer': 'https://snaptik.app/'},
            timeout=6
        )
        if not resp2.ok:
            return None

        m = re.search(r'href="(https://[^"]+)"[^>]*>[^<]*HD[^<]*<', resp2.text, re.I)
        if not m:
            m = re.search(r'href="(https://[^"]+\.mp4[^"]*)"', resp2.text)
        if not m:
            return None

        video_url = m.group(1)
        return {
            'id': video_id,
            'title': 'TikTok Video',
            'uploader': 'unknown',
            'duration': 0,
            'thumbnail': '',
            'play_url': video_url,
            'download_url': video_url,
            'webpage_url': url,
            'valid': True,
            'method': 'snaptik',
        }
    except Exception:
        return None

def get_tiktok_info_tiktokapi(url):
    """Phương pháp 3: TikTokApi library (async wrapper)"""
    if not TIKTOK_API_AVAILABLE:
        return None
    
    try:
        video_id = extract_video_id(url)
        if not video_id:
            return None
        
        return asyncio.run(_get_tiktokapi_info_async(video_id, url))
        
    except Exception as e:

        return None

async def _get_tiktokapi_info_async(video_id, original_url):
    """Async helper lấy thông tin video từ TikTokApi"""
    try:
        async with TikTokApi() as api:
            await api.create_sessions(num_sessions=1, sleep_after=3, headless=True)
            video = api.video(id=video_id, url=original_url)
            
            video_data = await video.info()
            
            if not video_data:
                return None
            
            download_url = None
            video_info = video_data.get('video', {})
            
            if 'downloadAddr' in video_info:
                download_url = video_info['downloadAddr']
            elif 'playAddr' in video_info:
                download_url = video_info['playAddr']
            
            if not download_url:
                return None
            
            author = video_data.get('author', {})
            stats = video_data.get('stats', {})
            
            return {
                'id': video_data.get('id', video_id),
                'title': video_data.get('desc', 'TikTok Video'),
                'uploader': author.get('uniqueId', 'unknown'),
                'duration': video_info.get('duration', 0),
                'thumbnail': video_info.get('cover', ''),
                'play_url': download_url,
                'download_url': download_url,
                'webpage_url': original_url,
                'valid': True,
                'method': 'tiktokapi-library',
                'stats': {
                    'views': stats.get('playCount', 0),
                    'likes': stats.get('diggCount', 0),
                    'comments': stats.get('commentCount', 0),
                    'shares': stats.get('shareCount', 0),
                }
            }
    except Exception as e:

        return None

# -------------------- DOWNLOAD ENGINE --------------------
# Pipeline: URL → ghi thẳng vào RAM disk → FFmpeg xử lý trên file → send_file → xóa
# Không bao giờ load video vào Python RAM (bytes).

def _make_cookie_file():
    """Tạo Netscape cookie file trên RAM disk. Trả về path hoặc None."""
    if not COOKIES_DICT:
        return None
    path = os.path.join(FAST_TMPDIR, f'ck_{uuid.uuid4().hex[:8]}.txt')
    try:
        with open(path, 'w', newline='\n', encoding='utf-8') as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# https://curl.se/docs/http-cookies.html\n\n")
            for name, value in COOKIES_DICT.items():
                n = str(name ).strip().replace('\t','').replace('\n','').replace('\r','')
                v = str(value).strip().replace('\t','').replace('\n','').replace('\r','')
                if n:
                    f.write(f".tiktok.com\tTRUE\t/\tFALSE\t0\t{n}\t{v}\n")
        return path
    except Exception:
        return None


def _cleanup_file(*paths):
    """Xóa an toàn một hoặc nhiều file."""
    for p in paths:
        if p:
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


def _stream_url_to_file(video_url: str, referer: str, out_path: str,
                        cancel: threading.Event = None) -> str:
    """
    Tải URL → file với tốc độ tối đa.

    Thuật toán:
    1. GET byte=0-0 → lấy Content-Length và kiểm tra Range support (0 RTT bổ sung)
    2. Nếu Range không hỗ trợ hoặc file nhỏ → single stream
    3. Nếu Range hỗ trợ → chia 64 chunks, mỗi chunk 1 thread riêng
       - Pre-allocate file 1 lần, mỗi thread seek + write tại offset → KHÔNG cần lock
       - Buffer 1 MB/read để giảm syscalls
       - Chunk tự retry 2 lần nếu lỗi
    4. Kiểm tra integrity bằng file size (không gọi ffprobe để tiết kiệm thời gian)
    """
    headers  = get_video_download_headers(video_url, referer)
    # 🟢 Claude C: Adaptive workers theo hardware tier
    # WEAK(0): 3 workers, MED(1): 6, STRONG(2): 10
    BASE_WORKERS = {0: 3, 1: 6, 2: 10}[_HARDWARE_TIER]
    BUF_SIZE     = {0: 1 << 18, 1: 1 << 19, 2: 1 << 20}[_HARDWARE_TIER]  # 256KB/512KB/1MB

    def _is_cancelled():
        return cancel is not None and cancel.is_set()

    for attempt in range(3):
        try:
            if attempt > 0:
                if _is_cancelled(): raise Exception("cancelled")
                time.sleep(0.4 * attempt)
                if os.path.exists(out_path):
                    try: os.unlink(out_path)
                    except: pass

            sess = get_session()

            # ── Probe kích thước + Range support ─────────────────────────
            file_size    = 0
            range_ok     = False
            probe_hdrs   = headers.copy()
            probe_hdrs['Range'] = 'bytes=0-0'
            try:
                pr = sess.get(video_url, headers=probe_hdrs, stream=True, timeout=8)
                if pr.status_code == 206:
                    cr = pr.headers.get('Content-Range', '')   # bytes 0-0/TOTAL
                    if '/' in cr:
                        file_size = int(cr.split('/')[-1])
                    range_ok  = file_size > 0
                elif pr.status_code == 200:
                    file_size = int(pr.headers.get('Content-Length', 0))
                pr.close()
            except Exception:
                pass

            # Fallback: HEAD
            if not file_size:
                try:
                    h = sess.head(video_url, headers=headers, timeout=6)
                    file_size = int(h.headers.get('Content-Length', 0))
                except Exception:
                    pass

            # ── Single stream (nhỏ hoặc không hỗ trợ Range) ──────────────
            if not range_ok or file_size < 512 * 1024:
                r = sess.get(video_url, headers=headers, stream=True, timeout=60)
                r.raise_for_status()
                with open(out_path, 'wb') as f:
                    for chunk in r.iter_content(BUF_SIZE):
                        if chunk: f.write(chunk)
                        if _is_cancelled(): break
                if os.path.exists(out_path) and os.path.getsize(out_path) > 50*1024:
                    return out_path
                raise Exception("single stream: file quá nhỏ")

            # ── Parallel range download ───────────────────────────────────
            # 🟢 Adaptive workers: tỷ lệ với kích thước + hardware tier
            # WEAK: tối đa 3; MED: 4-6; STRONG: 4-10
            max_w = BASE_WORKERS
            num_workers = min(max_w, max(2, file_size // (700 * 1024)))

            # Pre-allocate
            with open(out_path, 'wb') as f:
                f.seek(file_size - 1); f.write(b'\x00')

            chunk_size   = file_size // num_workers
            failed_parts = []

            def _fetch_part(idx: int):
                if _is_cancelled(): return True   # bị cancel = coi như ok (không retry)
                start = idx * chunk_size
                end   = (start + chunk_size - 1) if idx < num_workers - 1 else (file_size - 1)
                h     = headers.copy()
                h['Range'] = f'bytes={start}-{end}'
                for _r in range(3):   # retry mỗi chunk
                    try:
                        rr = get_session().get(video_url, headers=h,
                                               stream=True, timeout=30)
                        if rr.status_code not in (200, 206):
                            continue
                        buf = bytearray()
                        for chunk in rr.iter_content(BUF_SIZE):
                            if chunk: buf.extend(chunk)
                        if not buf:
                            continue
                        # Ghi trực tiếp tại offset — không cần lock (mỗi thread vùng khác nhau)
                        with open(out_path, 'r+b') as fp:
                            fp.seek(start)
                            fp.write(buf)
                        return True
                    except Exception:
                        time.sleep(0.1 * (_r + 1))
                return False

            with ThreadPoolExecutor(max_workers=num_workers) as ex:
                results = list(ex.map(_fetch_part, range(num_workers)))

            if _is_cancelled():
                raise Exception("cancelled")

            if not all(results):
                # Fallback: re-download single-stream các phần thất bại
                bad = [i for i, ok in enumerate(results) if not ok]
                _log('warn', f'parallel: {len(bad)}/{num_workers} chunks failed, retrying single-stream')
                os.unlink(out_path)
                r = sess.get(video_url, headers=headers, stream=True, timeout=120)
                r.raise_for_status()
                with open(out_path, 'wb') as f:
                    for chunk in r.iter_content(BUF_SIZE):
                        if chunk: f.write(chunk)

            actual = os.path.getsize(out_path) if os.path.exists(out_path) else 0
            if actual < 50 * 1024:
                raise Exception(f"file quá nhỏ sau download: {actual}B")

            return out_path

        except Exception as e:
            if 'cancelled' in str(e): raise
            if attempt == 2: raise Exception(f"_stream_url_to_file thất bại: {e}")

    raise Exception("_stream_url_to_file: hết retry")


def _ytdlp_to_file(url, info, out_path):
    """
    yt-dlp ghi video thẳng vào out_path trên RAM disk.
    Luôn tải combined video+audio (FFmpeg sẽ strip audio sau nếu cần).
    Trả về out_path nếu thành công, raise nếu thất bại.
    """
    if not YT_DLP_AVAILABLE:
        raise Exception("yt-dlp not installed")
    # Template không extension — yt-dlp tự thêm đúng ext
    tmpl_base = os.path.splitext(out_path)[0]

    format_strategies = [
        'bestvideo[vcodec!=none][height>=360]+bestaudio[acodec!=none]/best[vcodec!=none][acodec!=none]',
        'bestvideo[vcodec!=none]+bestaudio/best',
        'best[vcodec!=none][acodec!=none]',
        'bestvideo+bestaudio/best',
        'best[vcodec!=none]',
        'best',
        None,
    ]

    last_found = None

    for strategy in format_strategies:
        # Dọn file yt-dlp cũ
        for ext in ('.mp4', '.webm', '.mkv', '.m4v', '.ts'):
            p = tmpl_base + ext
            if os.path.exists(p):
                try: os.unlink(p)
                except: pass

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'outtmpl': tmpl_base + '.%(ext)s',
            'http_headers': get_browser_headers(include_cookies=False),
            'format_sort': ['vcodec:h264'],
            'nocheckcertificate': True,
            'no_check_formats': True,
            'allow_unplayable_formats': True,
            'merge_output_format': 'mp4',
            'extractor_args': {
                'tiktok': {
                    'api_hostname': random.choice(MOBILE_API_ENDPOINTS).replace('https://', ''),
                    'app_version': '36.1.3',   # newer version bypass status 10240
                    'app_name':    'musical_ly',
                    'webpage_download': ['0'],  # dùng API thay web
                }
            },
        }
        if strategy is not None:
            ydl_opts['format'] = strategy
        if FFMPEG_AVAILABLE:
            ydl_opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]
            ydl_opts['prefer_ffmpeg'] = True

        # Cookie file trên RAM disk
        ck = _make_cookie_file()
        if ck:
            ydl_opts['cookiefile'] = ck
        if PROXY:
            ydl_opts['proxy'] = PROXY

        try:
            with _ytdlp_lock:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
        except Exception:
            pass
        finally:
            _cleanup_file(ck)

        # Tìm file yt-dlp vừa ghi
        found = None
        for ext in ('.mp4', '.webm', '.mkv', '.m4v', '.ts'):
            p = tmpl_base + ext
            if os.path.exists(p) and os.path.getsize(p) > 50 * 1024:
                found = p
                break

        if not found:
            continue

        last_found = found

        if validate_video_with_ffprobe(found):
            if found != out_path:
                shutil.move(found, out_path)
            return out_path

    # Emergency: last_found có dữ liệu dù không pass validate
    if last_found and os.path.exists(last_found) and os.path.getsize(last_found) > 100 * 1024:
        if last_found != out_path:
            shutil.move(last_found, out_path)
        return out_path

    raise Exception("yt-dlp: tất cả strategies thất bại")


# ══════════════════════════════════════════════════════════════════════════════
# 🔵 Claude B: METHOD ROTATION — force tải từ 1 API cụ thể (không race)
# Dùng khi retry sau no_video_stream để đổi nguồn tải
# ══════════════════════════════════════════════════════════════════════════════

# Thứ tự rotation: từ nhanh → chậm, đảm bảo mỗi retry dùng API khác nhau
_ROTATION_METHODS = [
    'tikwm',         # 0 — nhanh, ổn định
    'mobile_api',    # 1 — rất nhanh
    'ssstik',        # 2 — hỗ trợ tốt video mới
    'ttdownloader',  # 3 — backup
    'snaptik',       # 4 — HD support
    'ytdlp',         # 5 — fallback chậm nhất nhưng mạnh nhất
]

def _download_with_forced_method(url: str, out_dir: str, method: str, audio: bool = True) -> tuple:
    """
    🔵 Force tải video dùng 1 API cụ thể (không race với các API khác).
    Trả về (raw_path, info) hoặc raise Exception.
    """
    _log('info', f'[method-rotation] Force method: {method} | url={url[:60]}')

    info = None

    if method == 'tikwm':
        info = get_tiktok_info_tikwm(url)
    elif method == 'mobile_api':
        info = get_tiktok_info_mobile_api_all_endpoints(url)
    elif method == 'ssstik':
        info = get_tiktok_info_ssstik(url)
    elif method == 'ttdownloader':
        info = get_tiktok_info_ttdownloader(url)
    elif method == 'snaptik':
        info = get_tiktok_info_snaptik(url)
    elif method == 'ytdlp':
        info = get_tiktok_info_ytdlp(url, audio=audio)
        if info and info.get('download_url'):
            # yt-dlp: tải full (info + file trong 1 lần)
            uid      = hashlib.md5(f"{url}{time.time()}".encode()).hexdigest()[:10]
            out_path = os.path.join(out_dir, f'rot_ytdlp_{uid}.mp4')
            _ytdlp_to_file(url, info, out_path)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 50 * 1024:
                ok_v, _ = _validate_download_input(out_path)
                if ok_v:
                    return out_path, info
            raise Exception(f'ytdlp rotation: file invalid')
    else:
        raise Exception(f'Unknown method: {method}')

    if not info or not info.get('download_url'):
        raise Exception(f'{method}: không lấy được download URL')

    # Stream download
    uid      = hashlib.md5(f"{url}{time.time()}{method}".encode()).hexdigest()[:10]
    out_path = os.path.join(out_dir, f'rot_{method}_{uid}.mp4')
    _stream_url_to_file(info['download_url'], info.get('webpage_url', url), out_path)

    if not os.path.exists(out_path) or os.path.getsize(out_path) < 50 * 1024:
        raise Exception(f'{method}: file quá nhỏ sau download')

    ok_v, reason = _validate_download_input(out_path)
    if not ok_v:
        _cleanup_file(out_path)
        raise Exception(f'{method}: validate failed — {reason}')

    info.setdefault('method', method)
    return out_path, info


def _download_with_rotation_retry(url: str, out_dir: str, audio: bool,
                                   max_attempts: int = 5,
                                   push_cb=None, index: int = 0, total: int = 1) -> tuple:
    """
    🔵+🟢 Tải video với API rotation — đổi API mỗi lần retry.
    Thứ tự: tikwm → mobile_api → ssstik → ttdownloader → snaptik → ytdlp
    push_cb(msg): callback để emit progress message (optional)
    Trả về (raw_path, info) hoặc raise Exception.
    """
    last_err = None
    methods  = _ROTATION_METHODS[:max_attempts]

    for attempt_idx, method in enumerate(methods):
        label = f'[{index+1}/{total}]'
        msg   = f'🔄 {label} Retry {attempt_idx+1}/{len(methods)}: {method.upper()}...'
        _log('warn', msg)
        if push_cb:
            push_cb(msg)

        if attempt_idx > 0:
            time.sleep(1.0 * attempt_idx)

        try:
            raw_path, info = _download_with_forced_method(url, out_dir, method, audio)
            sz_kb = os.path.getsize(raw_path) // 1024
            ok_msg = f'✅ {label} {method.upper()} OK ({sz_kb}KB)'
            _log('ok', ok_msg)
            if push_cb:
                push_cb(ok_msg)
            return raw_path, info
        except Exception as e:
            last_err = e
            _log('warn', f'[rotation] {method} failed: {str(e)[:80]}')

    raise Exception(f'Tất cả {len(methods)} methods thất bại — cuối: {last_err}')


def _tiktokapi_to_file(url, info, out_path):
    """TikTokApi → ghi bytes về file trên RAM disk."""
    if not TIKTOK_API_AVAILABLE:
        raise Exception("TikTokApi not available")

    video_id = info.get('id') or extract_video_id(url)
    if not video_id:
        raise Exception("Không tìm được video ID")

    video_bytes = asyncio.run(_download_tiktokapi_async(video_id, url))
    if not video_bytes or len(video_bytes) < 50 * 1024:
        raise Exception("TikTokApi trả về dữ liệu rỗng hoặc quá nhỏ")

    with open(out_path, 'wb') as f:
        f.write(video_bytes)
    del video_bytes  # giải phóng RAM ngay sau khi ghi

    if not validate_video_with_ffprobe(out_path):
        raise Exception("TikTokApi: không có video stream hợp lệ")

    return out_path


async def _download_tiktokapi_async(video_id, original_url):
    """Async helper: lấy bytes từ TikTokApi."""
    try:
        async with TikTokApi() as api:
            await api.create_sessions(num_sessions=1, sleep_after=3, headless=True)
            video = api.video(id=video_id, url=original_url)
            try:
                video_bytes = await video.bytes()
            except AttributeError:
                info_data = await video.info()
                if not info_data:
                    raise Exception("No video info")
                vi = info_data.get('video', {}) if isinstance(info_data, dict) else {}
                dl_url = (vi.get('downloadAddr') or vi.get('playAddr') or
                          (info_data.get('downloadAddr') if isinstance(info_data, dict) else None))
                if not dl_url:
                    raise Exception("No download URL")
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:  # type: ignore
                    r = await client.get(dl_url, headers=get_browser_headers())
                    video_bytes = r.content
            if not video_bytes:
                raise Exception("Empty response")
            return video_bytes
    except Exception as e:
        raise Exception(f"TikTokApi error: {e}")


def _fetch_url_api_priority(url: str, cancel: threading.Event) -> tuple:
    """
    Pha 1: Race lấy download URL — 6 nguồn chạy song song, lấy kết quả nhanh nhất.

    Thứ tự ưu tiên (tất cả chạy đồng thời T+0):
      • Mobile API  (5 endpoints song song, timeout 3s) ← nhanh nhất ~0.5-2s
      • tikwm API   (timeout 5s)                        ← ổn định ~1-3s
      • ssstik API  (timeout 6s)                        ← mới, hỗ trợ tốt
      • ttdownloader(timeout 6s)                        ← backup
      • snaptik API (timeout 6s)                        ← HD support
      • yt-dlp      (chỉ khởi động sau 5s nếu trên chưa xong) ← fallback chậm

    Trả về (info_dict, elapsed) hoặc raise Exception.
    """
    t0 = time.time()
    url_found   = threading.Event()
    result_box  = [None]
    result_lock = threading.Lock()

    def _set_result(info):
        with result_lock:
            if result_box[0] is None and info and info.get('download_url'):
                result_box[0] = info
                url_found.set()
                cancel.set()
                return True
        return False

    def _worker_mobile():
        if cancel.is_set(): return
        _set_result(get_tiktok_info_mobile_api_all_endpoints(url))

    def _worker_tikwm():
        if cancel.is_set(): return
        _set_result(get_tiktok_info_tikwm(url))

    def _worker_ssstik():
        if cancel.is_set(): return
        _set_result(get_tiktok_info_ssstik(url))

    def _worker_ttdl():
        if cancel.is_set(): return
        _set_result(get_tiktok_info_ttdownloader(url))

    def _worker_snaptik():
        if cancel.is_set(): return
        _set_result(get_tiktok_info_snaptik(url))

    def _worker_cobalt():
        if cancel.is_set(): return
        _set_result(get_tiktok_info_cobalt(url))

    def _worker_tikmate():
        if cancel.is_set(): return
        _set_result(get_tiktok_info_locodownloader(url))

    # yt-dlp khởi động sau 4s (nặng hơn, dùng làm fallback)
    def _worker_ytdlp():
        url_found.wait(timeout=4.0)
        if cancel.is_set() or url_found.is_set():
            return
        _log('warn', 'Các API chưa xong sau 4s → fallback yt-dlp...')
        try:
            _set_result(get_tiktok_info_ytdlp(url, audio=True))
        except Exception:
            pass

    workers = [_worker_mobile, _worker_tikwm, _worker_cobalt, _worker_tikmate,
               _worker_ssstik, _worker_ttdl, _worker_snaptik, _worker_ytdlp]
    with ThreadPoolExecutor(max_workers=len(workers)) as ex:
        for w in workers:
            ex.submit(w)
        url_found.wait(timeout=12.0)
        cancel.set()

    info = result_box[0]
    if not info or not info.get('download_url'):
        raise Exception("Không lấy được download URL từ bất kỳ nguồn nào")

    elapsed = round(time.time() - t0, 2)
    _log('ok', f'URL ready [{info.get("method","?")}] in {elapsed}s → {info["download_url"][:60]}...')
    return info, elapsed


def _race_download_to_file(url: str, out_dir: str, audio: bool = True) -> tuple:
    """
    2-pha tốc độ tối đa:

    Pha 1 (~0.5-3s): Race lấy download URL
      • Mobile API (5 endpoints song song, timeout 5s) → nhanh nhất
      • tikwm API (timeout 8s)
      • yt-dlp info-only (chỉ khởi động sau 8s nếu API chưa xong)

    Pha 2 (~2-6s): 64-connection parallel download
      • Pre-allocate file
      • Mỗi chunk ghi tại offset riêng — KHÔNG lock
      • Chunk tự retry 3 lần

    Fallback: nếu Pha 1 thất bại → yt-dlp full download (info + download trong 1 lần)
    """
    errors_all = []

    for attempt in range(1, RACE_MAX_RETRIES + 1):
        uid        = hashlib.md5(f"{url}{time.time()}{attempt}".encode()).hexdigest()[:10]
        out_path   = os.path.join(out_dir, f'race_{uid}.mp4')
        cancel_ev  = threading.Event()
        start_time = time.time()

        if attempt > 1:
            _log('warn', f'Retry {attempt}/{RACE_MAX_RETRIES}...')
            time.sleep(min(attempt * 1.5, 5.0))

        try:
            # ── Pha 1: Lấy download URL ───────────────────────────────────────
            _log('info', f'Pha 1: Race URL via API...', )
            info, url_elapsed = _fetch_url_api_priority(url, cancel_ev)
            dl_url = info['download_url']

            # ── Pha 2: Download 64-connection ─────────────────────────────────
            _log('info', f'Pha 2: Download 64-conn → {os.path.basename(out_path)}')
            _stream_url_to_file(dl_url, info.get('webpage_url', url), out_path)

            if not os.path.exists(out_path) or os.path.getsize(out_path) < 50 * 1024:
                raise Exception("File sau download quá nhỏ hoặc không tồn tại")

            # ── MD Phần 1: Validate file vừa tải ────────────────────────────
            ok_in, reason_in = _validate_download_input(out_path)
            if not ok_in:
                raise Exception(f'Validate input failed: {reason_in}')
            _log('ok', f'Input validated: {reason_in}')

            total = round(time.time() - start_time, 1)
            sz    = os.path.getsize(out_path) // 1024
            print(f"{_GREEN}✓ [Race] {info.get('method','?')} | {sz}KB | URL:{url_elapsed}s | total:{total}s{_RESET}", flush=True)
            return out_path, info

        except Exception as e:
            _cleanup_file(out_path)
            err_msg = str(e)
            _log('warn', f'attempt {attempt} failed: {err_msg[:80]}')
            errors_all.append(f"[{attempt}] {err_msg}")

            # Fallback: yt-dlp full download (info + file trong 1 lần)
            if attempt == 1:
                try:
                    _log('warn', 'Fallback: yt-dlp full download...')
                    out_ytdlp = os.path.join(out_dir, f'race_ytdlp_{uid}.mp4')
                    info_ytdlp = get_tiktok_info_ytdlp(url, audio=True) or {
                        'id': extract_video_id(url) or 'unknown',
                        'title': 'TikTok Video', 'webpage_url': url,
                    }
                    _ytdlp_to_file(url, info_ytdlp, out_ytdlp)
                    if os.path.exists(out_ytdlp) and os.path.getsize(out_ytdlp) > 50*1024:
                        total = round(time.time() - start_time, 1)
                        sz    = os.path.getsize(out_ytdlp) // 1024
                        print(f"{_GREEN}✓ [yt-dlp fallback] {sz}KB | {total}s{_RESET}", flush=True)
                        info_ytdlp.setdefault('method', 'yt-dlp-fallback')
                        return out_ytdlp, info_ytdlp
                except Exception as e2:
                    errors_all.append(f"[ytdlp-fallback] {e2}")

    raise Exception(f"Tất cả {RACE_MAX_RETRIES} lần thất bại — {' | '.join(errors_all)}")



# ── TARGET: 720p + 30fps ──────────────────────────────────────────────────────
TARGET_LONG  = 1280
TARGET_SHORT = 720
TARGET_FPS   = 30

# ══════════════════════════════════════════════════════════════════════════════
# MD PIPELINE VALIDATION — theo tài liệu xử-ly-loi-video-pipeline.md
# Validate tại 2 điểm: sau tải (input) và sau FFmpeg (output)
# ══════════════════════════════════════════════════════════════════════════════

_MIN_VALID_SIZE = 80 * 1024   # 80KB — file nhỏ hơn chắc chắn là lỗi

def _validate_download_input(path: str) -> tuple:
    """
    🔵+🟢 Validate file vừa tải về.
    Nếu phát hiện codec=none → tự động sanitize TRƯỚC khi reject.
    Trả về (ok: bool, reason: str). Path có thể bị thay bởi sanitized version.
    """
    if not path or not os.path.exists(path):
        return False, 'file_not_found'

    size = os.path.getsize(path)
    if size < _MIN_VALID_SIZE:
        log_error(f'[validate_input] FAIL file quá nhỏ: {size}B path={path}')
        return False, f'file_too_small({size}B)'

    # 🟢 Kiểm tra needs_sanitize TRƯỚC deep_validate
    # Nếu codec=none → sanitize ngay, không reject vội
    pre_probe = _probe_once(path)
    if pre_probe and pre_probe.get('needs_sanitize'):
        log_process(f'[validate_input] needs_sanitize → attempting sanitize: {path}')
        try:
            sanitized = _sanitize_video_for_ffmpeg(path)
            if sanitized and os.path.exists(sanitized) and sanitized != path:
                log_process(f'[validate_input] sanitize OK → {sanitized}')
                # Validate sanitized file
                ok2, reason2 = deep_validate_video_file(sanitized, decode_test=False)
                if ok2:
                    return True, f'sanitized+ok: {reason2}'
                log_error(f'[validate_input] sanitized file still invalid: {reason2}')
                _cleanup_file(sanitized)
                return False, f'sanitize_failed({reason2})'
        except Exception as e_san:
            log_error(f'[validate_input] sanitize exception: {e_san}')
            # Fall through to deep_validate (might still pass)

    # 🔵 deep_validate với decode_test
    ok, reason = deep_validate_video_file(path, decode_test=True)
    if not ok:
        log_error(f'[validate_input] FAIL deep_validate: {reason} path={path}')
        return False, reason

    log_process(f'[validate_input] OK: {reason}')
    return True, reason


def _validate_ffmpeg_output(in_path: str, out_path: str, in_info: dict) -> tuple:
    """
    Validate file output sau FFmpeg theo MD Phần 2.
    Trả về (ok: bool, reason: str).
    """
    if not out_path or not os.path.exists(out_path):
        return False, 'output_not_found'

    out_size = os.path.getsize(out_path)
    if out_size < 10 * 1024:
        log_error(f'[validate_output] FAIL output quá nhỏ: {out_size}B')
        return False, f'output_too_small({out_size}B)'

    if not FFMPEG_AVAILABLE:
        return True, 'ffprobe_skipped'

    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-show_entries', 'stream=codec_type,width,height'
                             ':format=duration',
             '-of', 'json', out_path],
            capture_output=True, text=True, timeout=12
        )
        if r.returncode != 0:
            log_error(f'[validate_output] FAIL ffprobe: {r.stderr[-200:]}')
            return False, 'output_ffprobe_failed'

        d = json.loads(r.stdout)
        out_streams = d.get('streams', [])
        out_fmt     = d.get('format', {})

        # Kiểm tra 1: có video stream
        has_video = any(s.get('codec_type') == 'video' for s in out_streams)
        if not has_video:
            log_error(f'[validate_output] FAIL mất hình sau FFmpeg! out={out_path}')
            return False, 'output_no_video_stream'

        # ── Duration validation — chỉ fail khi truncate THỰC SỰ ──────────────
        # TikTok MP4 có format.duration sai do elst atom — KHÔNG dùng delta tuyệt đối.
        # Chỉ fail nếu output < 25% input VÀ input đủ dài (> 20s).
        in_dur  = float(in_info.get('duration', 0) or 0)
        out_dur = float(out_fmt.get('duration', 0) or 0)
        if in_dur > 1 and out_dur > 0:
            delta = abs(in_dur - out_dur)
            if delta > 5.0:
                log_error(f'[validate_output] WARN duration delta={delta:.1f}s (in={in_dur:.1f} out={out_dur:.1f}) — TikTok container known issue, checking truncation')
            # Fail chỉ khi video THỰC SỰ bị cắt ngắn nặng (< 25% input, input > 20s)
            if in_dur > 20.0 and out_dur > 0:
                in_stream_dur = float(in_info.get('duration_stream', 0) or 0)
                ref_dur = in_stream_dur if in_stream_dur > 5 else in_dur
                ratio   = out_dur / ref_dur if ref_dur > 0 else 1.0
                # Threshold 25% (từ 35%) — TikTok container có thể báo sai tới 70%
                if ratio < 0.25:
                    log_error(f'[validate_output] REAL TRUNCATION: ratio={ratio:.0%} out={out_dur:.1f}s ref={ref_dur:.1f}s')
                    return False, f'real_truncation({ratio:.0%}_of_input)'
                if ratio < 0.50:
                    log_process(f'[validate_output] WARN possible truncation: ratio={ratio:.0%} — accepting (TikTok elst issue)')

        return True, f'ok(size={out_size//1024}KB dur={out_dur:.1f}s)'

    except Exception as e:
        log_error(f'[validate_output] exception: {e}')
        return True, f'validate_exception_passthrough'   # passthrough


def _scan_ffmpeg_stderr(stderr_bytes: bytes) -> list:
    """
    🔵 Scan FFmpeg stderr — phát hiện lỗi FATAL vs WARNING.
    Trả về list fatal errors (caller dùng để quyết định retry/fallback).

    UPDATED: Thêm codec=none specific patterns từ lỗi thực tế:
      'Decoding requested, but no decoder found for: none'
      'error binding an input stream to complex filtergraph'
    """
    FATAL_PATTERNS = [
        # Core fatal errors
        b'no video stream found',
        b'moov atom not found',
        b'could not find codec parameters',
        b'error while decoding stream',
        b'no such file or directory',
        b'decoder not found',
        b'error binding filtergraph',
        b'error binding an input stream',
        # codec=none specific
        b'no decoder found for: none',
        b'decoding requested, but no decoder found',
        b'unspecified pixel format',
        b'width or height not set',
        b'codec not currently supported',
        # 🔴 ENHANCED: additional fatal patterns
        b'invalid data found when processing input',
        b'end of file',                 # truncated file
        b'broken pipe',
        b'cannot allocate memory',
        b'permission denied',
        b'failed to open segment',
        b'error muxing a packet',
        b'too many packets buffered',
        b'encoder not found',
        b'output file is empty',
        b'file truncated',
        b'av_interleaved_write_frame(): broken pipe',
    ]
    WARN_PATTERNS = [
        b'missing picture',
        b'invalid data found',
        b'application provided invalid',
        b'could not find ref with poc',
        b'mmco: unref short failure',
        b'concealing',
        b'pts has no value',
        b'dts out of order',
    ]
    text = stderr_bytes.lower() if stderr_bytes else b''
    fatal_found = [p.decode() for p in FATAL_PATTERNS if p in text]
    warn_found  = [p.decode() for p in WARN_PATTERNS  if p in text]
    if warn_found:
        log_process(f'[ffmpeg_warn] non-fatal: {warn_found}')
    return fatal_found
_SIZE_LIMIT_MB    = 50
_SIZE_LIMIT_BYTES = _SIZE_LIMIT_MB * 1024 * 1024


def _build_robust_input_flags(is_vfr: bool = False) -> list:
    """
    Build FFmpeg input flags để handle TikTok fragmented/broken MP4.
    v2: Thêm -probesize và -analyzeduration lớn hơn để đọc đúng metadata.
    """
    return [
        '-probesize',         '100M',        # đọc đủ dữ liệu trước khi bắt đầu encode
        '-analyzeduration',   '10M',         # phân tích 10 giây đầu để detect format
        '-fflags',            '+genpts+igndts+discardcorrupt+fastseek',
        '-err_detect',        'ignore_err',
        '-max_error_rate',    '1.0',
        '-avoid_negative_ts', 'make_zero',
    ]

def _get_video_encoder(need_filter: bool = False):
    """
    Trả về (encoder, extra_args) phù hợp với task hiện tại.
    vaapi cần hwupload filter nên không dùng được khi đã có filter_complex.
    """
    if HW_ENCODER == 'h264_vaapi' and need_filter:
        # vaapi không compatible với filter_complex tùy ý → fallback software
        return 'libx264', ['-preset', 'ultrafast', '-crf', '23', '-tune', 'zerolatency']
    return HW_ENCODER, list(HW_ENCODER_EXTRA)


def _run_ffmpeg(cmd: list, timeout: int = 300) -> subprocess.CompletedProcess:
    """Chạy FFmpeg trong FFMPEG_SEMAPHORE với timeout thích ứng."""
    # HW encoder nhanh hơn nhiều → không nhân timeout (tránh chờ lâu vô lý)
    # CPU yếu (tier=0) nhân 2.0x thay vì 2.5x (ultrafast không cần nhiều time)
    _tier_factor = {0: 2.0, 1: 1.3, 2: 1.0}.get(_HARDWARE_TIER, 1.3)
    adj_timeout  = int(timeout * _tier_factor)
    with FFMPEG_SEMAPHORE:
        return subprocess.run(cmd, capture_output=True, timeout=adj_timeout)


def _probe_once(path: str):
    """
    Probe day du 1 lan: width, height, fps, has_audio, duration, size_bytes.
    Tra ve dict hoac None.
    
    🟢 Claude C: Bo sung flag needs_sanitize khi phat hien:
      - vcodec == none / empty → can sanitize truoc khi encode
      - pix_fmt khong hop le → FFmpeg khong decode duoc
      - width/height le → can force even pixels truoc filtergraph
    """
    try:
        r = subprocess.run([
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=codec_type,width,height,r_frame_rate,codec_name,duration,pix_fmt'
                            ':format=duration,size',
            '-of', 'json', path
        ], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return None
        d = json.loads(r.stdout)
        fmt     = d.get('format', {})
        streams = d.get('streams', [])
        video   = next((s for s in streams if s.get('codec_type') == 'video'), {})
        audio   = next((s for s in streams if s.get('codec_type') == 'audio'), None)

        w = int(video.get('width', 0))
        h = int(video.get('height', 0))
        if w == 0 or h == 0:
            return None

        fr_str = video.get('r_frame_rate', '30/1')
        num, den = (int(x) for x in (fr_str + '/1').split('/')[:2])
        fps = num / den if den else 30.0

        fmt_dur    = float(fmt.get('duration', 0) or 0)
        stream_dur = float(video.get('duration', 0) or 0)
        if stream_dur > 0 and fmt_dur > 0:
            real_dur = stream_dur if abs(fmt_dur - stream_dur) > 5.0 else fmt_dur
        elif stream_dur > 0:
            real_dur = stream_dur
        else:
            real_dur = fmt_dur

        vcodec  = (video.get('codec_name') or '').lower().strip()
        pix_fmt = (video.get('pix_fmt')    or '').lower().strip()

        # 🟢 Detect codec=none and other conditions needing sanitize
        _BROKEN_CODECS = {'none', '', 'unknown', 'rawvideo', 'bin_data', 'data'}
        needs_sanitize = (
            vcodec in _BROKEN_CODECS or
            'unknown' in vcodec or
            pix_fmt in {'unknown', ''} or
            w % 2 != 0 or h % 2 != 0
        )
        if needs_sanitize:
            log_process(f'[probe] needs_sanitize=True: vcodec={vcodec!r} pix_fmt={pix_fmt!r} dims={w}x{h}')

        return {
            'w': w, 'h': h, 'fps': fps,
            'has_audio': audio is not None,
            'vcodec': vcodec,
            'pix_fmt': pix_fmt,
            'duration': real_dur,
            'duration_fmt': fmt_dur,
            'duration_stream': stream_dur,
            'size': int(fmt.get('size', os.path.getsize(path)) or os.path.getsize(path)),
            'needs_sanitize': needs_sanitize,
        }
    except Exception:
        return None

def _calc_bitrate_for_50mb(duration: float, keep_audio: bool) -> int:
    """Tính target video bitrate (kbps) để output ≤ 50MB."""
    if duration < 1:
        return 0
    AUDIO_KBPS = 128 if keep_audio else 0
    total_kbps = int((_SIZE_LIMIT_MB * 8 * 1024 * 0.92) / duration)
    return max(200, total_kbps - AUDIO_KBPS)


# ══════════════════════════════════════════════════════════════════════════════
# 🔵 Claude B: VIDEO SANITIZER — chuẩn hoá container trước khi encode
# Giải quyết: codec=none, unknown pix_fmt, broken timestamps, odd dimensions
# ══════════════════════════════════════════════════════════════════════════════

def _sanitize_video_for_ffmpeg(raw_path: str) -> str:
    """
    🔵 Chuẩn hoá video khi phát hiện codec=none hoặc container bị lỗi.
    Mục tiêu: tạo file MP4 hợp lệ mà FFmpeg có thể decode để encode lại.

    Chiến lược (theo thứ tự tốc độ giảm dần):

    S1: Re-mux với -c copy (nhanh nhất, <1s) — sửa container metadata, không re-encode
        Thường đủ để fix elst offset, timestamp, fragment metadata

    S2: Force H.264 decode + copy audio (1-5s)
        Dùng khi S1 thất bại — decode video stream một lần để normalize codec params

    S3: Full re-encode minimal (5-30s)
        Dùng khi S2 thất bại — libx264 ultrafast, scale even dimensions, normalize everything

    S4: Extract video-only + re-encode (last resort)
        Dùng khi tất cả thất bại — bỏ audio, chỉ giữ video

    Trả về path file đã sanitize (có thể là raw_path gốc nếu không cần sửa).
    Raise Exception nếu tất cả strategies thất bại.
    """
    if not FFMPEG_AVAILABLE:
        return raw_path

    info = _probe_once(raw_path)
    if not info:
        log_process(f'[sanitize] probe fail → skip (không có info)')
        return raw_path

    if not info.get('needs_sanitize', False):
        return raw_path  # không cần sanitize

    w, h     = info['w'], info['h']
    vcodec   = info.get('vcodec', '')
    pix_fmt  = info.get('pix_fmt', '')
    size_kb  = info['size'] // 1024
    log_process(f'[sanitize] START: vcodec={vcodec!r} pix_fmt={pix_fmt!r} dims={w}x{h} size={size_kb}KB')

    uid      = hashlib.md5(f'san{raw_path}{time.time()}'.encode()).hexdigest()[:10]
    out_path = os.path.join(FAST_TMPDIR, f'san_{uid}.mp4')
    robust   = _build_robust_input_flags(True)  # genpts+igndts+discardcorrupt+ignore_err

    def _cleanup_out():
        try:
            if os.path.exists(out_path): os.unlink(out_path)
        except: pass

    def _valid_output(p):
        """Kiểm tra output có video stream hợp lệ không."""
        if not os.path.exists(p) or os.path.getsize(p) < 50 * 1024:
            return False, 'too_small'
        probe = _probe_once(p)
        if not probe:
            return False, 'probe_fail'
        if probe.get('needs_sanitize'):
            return False, f'still_broken: codec={probe.get("vcodec")} pix={probe.get("pix_fmt")}'
        return True, f'ok({probe["w"]}x{probe["h"]} codec={probe["vcodec"]})'

    # ── Strategy 1: Re-mux copy ───────────────────────────────────────────────
    try:
        _cleanup_out()
        r1 = subprocess.run(
            ['ffmpeg', '-y'] + robust + ['-i', raw_path,
             '-c', 'copy', '-map', '0', '-avoid_negative_ts', 'make_zero',
             '-movflags', '+faststart', out_path],
            capture_output=True, timeout=int(30 * _FFMPEG_TIMEOUT_FACTOR)
        )
        ok, reason = _valid_output(out_path)
        if ok:
            log_process(f'[sanitize] S1 remux-copy OK → {reason}')
            _cleanup_file(raw_path)
            return out_path
        log_process(f'[sanitize] S1 fail: {reason} rc={r1.returncode}')
    except Exception as e:
        log_process(f'[sanitize] S1 exception: {e}')

    # ── Strategy 2: Force-decode video + copy audio ───────────────────────────
    # Khi codec=none: dùng -vcodec rawvideo hoặc -f rawvideo để force decode
    # Thực tế: thêm -vf format=yuv420p để normalize pixel format
    try:
        _cleanup_out()
        # Force even dimensions
        ew = w  if w  % 2 == 0 else w  + 1
        eh = h  if h  % 2 == 0 else h  + 1
        scale_f = f'scale={ew}:{eh}:flags=fast_bilinear,format=yuv420p'
        r2 = subprocess.run(
            ['ffmpeg', '-y'] + robust + ['-i', raw_path,
             '-vf', scale_f,
             '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
             '-threads', _FFMPEG_THREADS,
             '-c:a', 'copy',
             '-avoid_negative_ts', 'make_zero',
             '-movflags', '+faststart', out_path],
            capture_output=True, timeout=int(120 * _FFMPEG_TIMEOUT_FACTOR)
        )
        ok, reason = _valid_output(out_path)
        if ok:
            log_process(f'[sanitize] S2 force-decode OK → {reason}')
            _cleanup_file(raw_path)
            return out_path
        stderr2 = r2.stderr.decode(errors='ignore')[-300:]
        log_process(f'[sanitize] S2 fail: {reason} rc={r2.returncode} {stderr2[-100:]}')
    except Exception as e:
        log_process(f'[sanitize] S2 exception: {e}')

    # ── Strategy 3: Full re-encode + normalize everything ────────────────────
    try:
        _cleanup_out()
        ew = w  if w  % 2 == 0 else w  + 1
        eh = h  if h  % 2 == 0 else h  + 1
        r3 = subprocess.run(
            ['ffmpeg', '-y'] + robust + ['-i', raw_path,
             '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
             '-pix_fmt', 'yuv420p',
             '-vf', f'scale={ew}:{eh}:flags=fast_bilinear',
             '-threads', _FFMPEG_THREADS,
             '-c:a', 'aac', '-b:a', '128k',
             '-avoid_negative_ts', 'make_zero',
             '-movflags', '+faststart', out_path],
            capture_output=True, timeout=int(180 * _FFMPEG_TIMEOUT_FACTOR)
        )
        ok, reason = _valid_output(out_path)
        if ok:
            log_process(f'[sanitize] S3 full-encode OK → {reason}')
            _cleanup_file(raw_path)
            return out_path
        stderr3 = r3.stderr.decode(errors='ignore')[-300:]
        log_process(f'[sanitize] S3 fail: {reason} rc={r3.returncode} {stderr3[-100:]}')
    except Exception as e:
        log_process(f'[sanitize] S3 exception: {e}')

    # ── Strategy 4: Extract raw video bytes + mux vào MP4 mới ────────────────
    # Khi container hoàn toàn broken — dùng -f rawvideo làm decoder giả
    try:
        _cleanup_out()
        ew = w  if w  % 2 == 0 else w  + 1
        eh = h  if h  % 2 == 0 else h  + 1
        fps_s = f'{min(info.get("fps", 30.0), 60.0):.2f}'
        r4 = subprocess.run(
            ['ffmpeg', '-y'] + robust + [
             '-i', raw_path,
             '-an',  # bỏ audio
             '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
             '-pix_fmt', 'yuv420p',
             '-vf', f'scale={ew}:{eh}:flags=fast_bilinear,fps={fps_s}',
             '-threads', _FFMPEG_THREADS,
             '-movflags', '+faststart', out_path],
            capture_output=True, timeout=int(180 * _FFMPEG_TIMEOUT_FACTOR)
        )
        ok, reason = _valid_output(out_path)
        if ok:
            log_process(f'[sanitize] S4 video-only OK → {reason}')
            _cleanup_file(raw_path)
            return out_path
        log_process(f'[sanitize] S4 fail: {reason} rc={r4.returncode}')
    except Exception as e:
        log_process(f'[sanitize] S4 exception: {e}')

    _cleanup_out()
    raise Exception(
        f'_sanitize_video_for_ffmpeg: tất cả 4 strategies thất bại '
        f'(vcodec={vcodec!r} dims={w}x{h} size={size_kb}KB)'
    )




# ══════════════════════════════════════════════════════════════════════════════
# TEAM DELTA: 720p UPSCALE + ADAPTIVE CRF (Smart Compression)
# ══════════════════════════════════════════════════════════════════════════════

def _analyze_scene_complexity(video_path: str, duration: float) -> float:
    """Phân tích complexity bằng I-frame ratio. Trả 0.0 (tĩnh) đến 1.0 (hành động)."""
    if not FFMPEG_AVAILABLE or duration <= 0:
        return 0.5
    sample_dur = min(30.0, duration * 0.4)
    try:
        r = subprocess.run(
            ['ffprobe','-v','quiet',
             '-read_intervals', f'%+#{int(sample_dur)}',
             '-show_frames','-select_streams','v',
             '-show_entries','frame=pict_type','-of','csv', video_path],
            capture_output=True, text=True,
            timeout=max(15, int(sample_dur * 0.5))
        )
        frames = [l for l in r.stdout.splitlines() if l.startswith('frame,')]
        total  = len(frames)
        if total < 5:
            return 0.5
        i_frames   = sum(1 for l in frames if ',I' in l)
        ratio      = i_frames / total
        complexity = min(1.0, max(0.0, (ratio - 0.03) / 0.15))
        log_process(f'[complexity] {total} frames, I={i_frames}, ratio={ratio:.3f} → {complexity:.2f}')
        return complexity
    except Exception as e:
        log_error(f'[complexity] {e}')
        return 0.5


def _adaptive_crf(complexity: float) -> int:
    """
    CRF thích ứng theo độ phức tạp:
    0.0 (tĩnh, nói chuyện) → CRF 32 (nén mạnh, tiết kiệm 40-50%)
    1.0 (hành động)        → CRF 23 (giữ chất lượng)
    """
    return max(23, min(32, 32 - int(complexity * 9)))


def _upscale_to_720p(raw_path: str, info: dict) -> str:
    """
    PRE-STEP 1: Upscale lên 720p bằng lanczos (sắc nét) nếu video nhỏ hơn 720p.
    Không upscale nếu video đã >= 720p. Trả về path mới hoặc raw_path nếu bỏ qua.
    """
    if not FFMPEG_AVAILABLE or not info:
        return raw_path
    w, h  = info.get('w', 0), info.get('h', 0)
    short = min(w, h)
    if short <= 0 or short >= 720:
        log_process(f'[upscale] Bỏ qua — {w}x{h} đã đủ 720p')
        return raw_path

    scale_f = (f'scale=-2:720:flags=lanczos' if w < h
               else f'scale=720:-2:flags=lanczos')

    uid      = hashlib.md5(f'up{raw_path}{time.time()}'.encode()).hexdigest()[:8]
    out_path = os.path.join(FAST_TMPDIR, f'up720_{uid}.mp4')
    dur      = info.get('duration', 60)
    timeout_s = int(max(60, dur * 1.5) * _FFMPEG_TIMEOUT_FACTOR)

    try:
        log_process(f'[upscale] {w}x{h} → 720p lanczos | timeout={timeout_s}s')
        r = subprocess.run(
            ['ffmpeg','-y','-i',raw_path,
             '-vf',scale_f,
             '-c:v','libx264','-crf','20','-preset','ultrafast','-tune','zerolatency',
             '-c:a','copy','-pix_fmt','yuv420p',
             '-threads',_FFMPEG_THREADS,'-movflags','+faststart',out_path],
            capture_output=True, timeout=timeout_s
        )
        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 50*1024:
            ni = _probe_once(out_path)
            if ni:
                log_process(f'[upscale] OK → {ni["w"]}x{ni["h"]} ({os.path.getsize(out_path)//1024}KB)')
                _cleanup_file(raw_path)
                return out_path
        log_error(f'[upscale] FFmpeg rc={r.returncode}: {r.stderr[-150:]!r}')
        _cleanup_file(out_path)
    except subprocess.TimeoutExpired:
        log_error(f'[upscale] timeout {timeout_s}s')
        _cleanup_file(out_path)
    except Exception as e:
        log_error(f'[upscale] {e}')
        _cleanup_file(out_path)
    return raw_path



def _ensure_valid_mp4(path: str, duration_hint: float = 0) -> str:
    """
    Lớp đảm bảo cuối cùng: KHÔNG BAO GIỜ trả file raw/broken.
    Gọi sau _process_video_file(). Nếu output chưa valid → re-encode ultrafast.
    Trả về path hợp lệ hoặc raise Exception.
    """
    if not path or not os.path.exists(path):
        raise Exception(f"[ensure] File không tồn tại: {path!r}")

    size = os.path.getsize(path)
    if size < 50 * 1024:   # < 50KB chắc chắn sai
        raise Exception(f"[ensure] File quá nhỏ {size}B: {path!r}")

    # Layer 1: ffprobe check
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name,width,height,duration',
             '-of', 'json', path],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            d = json.loads(r.stdout)
            streams = d.get('streams', [])
            if streams:
                vcodec = streams[0].get('codec_name', '').lower()
                w = int(streams[0].get('width', 0) or 0)
                h = int(streams[0].get('height', 0) or 0)
                short_side = min(w, h) if w > 0 and h > 0 else 0
                _needs_720p = short_side > 0 and short_side < 720
                if vcodec in ('h264','avc','avc1') and w > 0 and h > 0 and not _needs_720p:
                    log_process(f'[ensure] OK: {vcodec} {w}x{h} {size//1024}KB')
                    return path   # ✅ file valid, đủ 720p
                elif vcodec in ('h264','avc','avc1') and _needs_720p:
                    # ⚡ FIX: upscale < 720p lên 720p tại ensure layer
                    log_process(f'[ensure] H264 nhưng {w}x{h} < 720p → upscale')
                    uid_up = hashlib.md5(f"up{path}{time.time()}".encode()).hexdigest()[:8]
                    up_p   = os.path.join(FAST_TMPDIR, f'up720_{uid_up}.mp4')
                    _sf    = 'scale=-2:720' if w >= h else 'scale=720:-2'
                    try:
                        r_up = subprocess.run([
                            'ffmpeg', '-y',
                            '-fflags', '+genpts+igndts', '-err_detect', 'ignore_err',
                            '-i', path,
                            '-vf', f'{_sf}:flags=lanczos',
                            '-map', '0:v:0', '-map', '0:a?',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '22',
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
                            '-threads', _FFMPEG_THREADS,
                            '-movflags', '+faststart', up_p,
                        ], capture_output=True, timeout=max(60, int((duration_hint or 60) * 1.2) + 20))
                        if r_up.returncode == 0 and os.path.exists(up_p) and os.path.getsize(up_p) > 50*1024:
                            log_process(f'[ensure] 720p-upscale OK {w}x{h}→720p {os.path.getsize(up_p)//1024}KB')
                            _cleanup_file(path)
                            return up_p
                    except Exception as _e_up:
                        log_error(f'[ensure] 720p upscale exception: {_e_up}')
                    _cleanup_file(up_p)
                    # Upscale failed → dùng file gốc (tốt hơn fail)
                    log_process(f'[ensure] 720p upscale thất bại → dùng file gốc {w}x{h}')
                    return path
                log_error(f'[ensure] Layer1 fail: codec={vcodec!r} {w}x{h} → re-encode')
            else:
                log_error('[ensure] Layer1: no video streams → re-encode')
        else:
            log_error(f'[ensure] ffprobe error: {r.stderr[-100:]!r} → re-encode')
    except Exception as e:
        log_error(f'[ensure] ffprobe exception: {e} → re-encode')

    # Layer 2: re-encode ultrafast H264 (không quan tâm nội dung, chỉ cần playable)
    uid    = hashlib.md5(f"ensure{path}{time.time()}".encode()).hexdigest()[:8]
    fix_p  = os.path.join(FAST_TMPDIR, f'ensured_{uid}.mp4')
    to_s   = max(90, int((duration_hint or 60) * 2.0) + 30)
    try:
        r2 = subprocess.run(
            ['ffmpeg', '-y',
             '-probesize', '200M', '-analyzeduration', '20M',
             '-fflags', '+genpts+igndts+discardcorrupt',
             '-err_detect', 'ignore_err', '-max_error_rate', '1.0',
             '-ignore_unknown',
             '-i', path,
             '-map', '0:v:0', '-map', '0:a?',
             '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
             '-tune', 'zerolatency', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
             '-threads', _FFMPEG_THREADS,
             '-movflags', '+faststart', fix_p],
            capture_output=True, timeout=to_s
        )
        if r2.returncode == 0 and os.path.exists(fix_p) and os.path.getsize(fix_p) > 50*1024:
            log_process(f'[ensure] Layer2 re-encode OK → {os.path.getsize(fix_p)//1024}KB')
            _cleanup_file(path)
            return fix_p
        log_error(f'[ensure] Layer2 fail rc={r2.returncode}: {r2.stderr[-100:]!r}')
        _cleanup_file(fix_p)
    except subprocess.TimeoutExpired:
        log_error(f'[ensure] Layer2 timeout {to_s}s')
        _cleanup_file(fix_p)
    except Exception as e3:
        log_error(f'[ensure] Layer2 exception: {e3}')
        _cleanup_file(fix_p)

    # Layer 3: minimal remux (chỉ copy container, không encode lại)
    remux_p = os.path.join(FAST_TMPDIR, f'remux_{uid}.mp4')
    try:
        r3 = subprocess.run(
            ['ffmpeg', '-y', '-fflags', '+genpts', '-i', path,
             '-c', 'copy', '-movflags', '+faststart', remux_p],
            capture_output=True, timeout=30
        )
        if r3.returncode == 0 and os.path.exists(remux_p) and os.path.getsize(remux_p) > 50*1024:
            log_process(f'[ensure] Layer3 remux OK {os.path.getsize(remux_p)//1024}KB')
            _cleanup_file(path)
            return remux_p
        _cleanup_file(remux_p)
    except Exception:
        _cleanup_file(remux_p)

    # Không thể sửa → raise để caller biết video thực sự lỗi
    raise Exception(f"[ensure] Không thể tạo video hợp lệ từ {path!r}")

def _process_video_file(raw_path: str, audio: bool, logo_params: dict) -> str:
    """
    Single-pass FFmpeg theo MD pipeline:
    ─ PRE-STEP: Sanitize nếu codec=none / container broken
    ─ PATH A: Stream copy (0–1s) nếu đã OK
    ─ PATH B: Encode với explicit -map, VFR fix, validate output
    """
    if not FFMPEG_AVAILABLE or not raw_path or not os.path.exists(raw_path):
        return raw_path

    # ── 🔵 PRE-STEP: Sanitize codec=none / broken container ─────────────────
    # Phải làm TRƯỚC khi probe để lấy info đúng
    try:
        pre_info = _probe_once(raw_path)
        if pre_info and pre_info.get('needs_sanitize'):
            log_process(f'[process] PRE-SANITIZE: vcodec={pre_info.get("vcodec")!r} — fixing...')
            raw_path = _sanitize_video_for_ffmpeg(raw_path)
    except Exception as e_san:
        log_error(f'[process] pre-sanitize error (continuing): {e_san}')
        # Nếu sanitize fail, vẫn thử encode bình thường

    info = _probe_once(raw_path)
    if not info:
        log_error(f"_probe_once failed, blind H.264 re-encode: {raw_path}")
        out_blind = os.path.join(FAST_TMPDIR, f'proc_blind_{uuid.uuid4().hex[:8]}.mp4')
        # MD: explicit -map để không mất video stream
        audio_a = ['-an'] if not audio else ['-map', '0:v:0', '-map', '0:a?', '-c:a', 'aac', '-b:a', '128k']
        try:
            r_bl = subprocess.run(
                ['ffmpeg', '-y', '-fflags', '+genpts',   # MD: fix VFR
                 '-i', raw_path,
                 '-map', '0:v:0']   # MD: explicit video map
                + audio_a
                + ['-c:v', 'libx264', '-crf', str(_acrf), '-preset', 'ultrafast',
                   '-pix_fmt', 'yuv420p', '-threads', _FFMPEG_THREADS,
                   '-movflags', '+faststart', out_blind],
                capture_output=True, timeout=180
            )
            warns = _scan_ffmpeg_stderr(r_bl.stderr)
            if warns:
                log_error(f'[blind_encode] FFmpeg warnings: {warns}')
            ok_out, r_out = _validate_ffmpeg_output(raw_path, out_blind, {})
            if r_bl.returncode == 0 and ok_out:
                log_process(f"proc BLIND-ENCODE ok {os.path.getsize(out_blind)//1024}KB")
                _cleanup_file(raw_path)
                return out_blind
            _cleanup_file(out_blind)
        except Exception as e_bl:
            log_error("blind re-encode", e_bl)
            _cleanup_file(out_blind)
        return raw_path

    w, h         = info['w'], info['h']
    fps          = info['fps']
    has_audio    = info['has_audio']
    duration     = info['duration']
    size_bytes   = info['size']
    remove_audio = not audio

    logo_active = bool(
        logo_params and logo_params.get('enabled')
        and logo_params.get('logo_base64') and FFMPEG_AVAILABLE
    )

    TARGET = 720
    short_side = min(w, h)
    # need_scale: upscale nếu nhỏ hơn 720p; KHÔNG downscale video đã lớn hơn
    need_scale    = short_side < TARGET
    need_compress = size_bytes > _SIZE_LIMIT_BYTES

    vcodec = info.get('vcodec', '').lower()
    BROWSER_H264_CODECS = ('h264', 'avc', 'avc1', 'avc3', 'avc4', 'x264', 'libx264')
    need_transcode = vcodec not in BROWSER_H264_CODECS

    is_vfr = fps > 59 or (fps % 1 != 0)

    need_recode = need_scale or logo_active or need_compress or need_transcode

    # ── SPEED: Adaptive CRF (không chạy analysis trên hot path) ─────────────
    # Dùng CRF cố định ultrafast — bỏ _analyze_scene_complexity() khỏi hot path
    # vì nó tiêu tốn 5-30s mỗi video. CRF 23 ultrafast cho ra chất lượng tốt.
    _acrf = 23   # fixed fast CRF (tốt hơn 28 veryfast về chất lượng/tốc độ)
    log_process(f'[process] CRF={_acrf} dims={w}x{h} dur={duration:.1f}s '
                f'scale={need_scale} transcode={need_transcode} compress={need_compress}')

    # ── SPEED: Scale filter — gộp upscale vào encode chính (1 pass thay 2) ──
    # Không chạy _upscale_to_720p() riêng lẻ nữa, xử lý trong PATH B

    uid      = hashlib.md5(f"{raw_path}{time.time()}{random.random()}".encode()).hexdigest()[:12]
    out_path = os.path.join(FAST_TMPDIR, f'proc_{uid}.mp4')

    # ── PATH A: Stream copy ────────────────────────────────────────────────────
    if not need_recode:
        # ⚡ FIX: Luôn scale lên 720p ngay cả khi H264 — đảm bảo chất lượng tối thiểu
        # Trước đây PATH A bypass scaling → video < 720p được trả thẳng mà không upscale
        if not remove_audio and not need_scale:
            log_process(f"proc DIRECT-RETURN {w}x{h} {size_bytes//1024}KB codec={vcodec}")
            return raw_path

        # Xóa audio — stream copy (nhanh)
        log_process(f"proc STREAM-COPY-NOAUDIO {w}x{h} {size_bytes//1024}KB")
        t0 = time.time()
        MIN_A = max(10*1024, size_bytes // 4)
        _rf = _build_robust_input_flags(is_vfr)
        copy_cmds = [
            # MD: explicit -map 0:v:0 để không mất video; robust flags để handle broken PTS
            ['ffmpeg','-y'] + _rf + ['-i',raw_path,'-map','0:v:0','-an',
             '-c:v','copy','-threads',_FFMPEG_THREADS,'-movflags','+faststart',out_path],
            ['ffmpeg','-y'] + _rf + ['-i',raw_path,'-map','0:v:0','-an',
             '-c:v','copy','-avoid_negative_ts','make_zero',
             '-threads',_FFMPEG_THREADS,'-movflags','+faststart',out_path],
        ]
        for cmd in copy_cmds:
            if os.path.exists(out_path):
                try: os.unlink(out_path)
                except: pass
            r = _run_ffmpeg(cmd, timeout=30)
            warns = _scan_ffmpeg_stderr(r.stderr)
            if warns:
                log_error(f'[stream_copy] warnings: {warns}')
            ok_v, rv = _validate_ffmpeg_output(raw_path, out_path, info)
            if r.returncode == 0 and ok_v and os.path.getsize(out_path) > MIN_A:
                log_process(f"proc COPY-NOAUDIO done {os.path.getsize(out_path)//1024}KB in {round(time.time()-t0,2)}s")
                _cleanup_file(raw_path)
                return out_path
        if os.path.exists(out_path):
            try: os.unlink(out_path)
            except: pass
        # fallthrough to PATH B

    # ── PATH B: Encode ─────────────────────────────────────────────────────────
    # SPEED: upscale 720p gộp vào encode chính (không chạy pass riêng)
    # scale=-2:720 giữ tỉ lệ và force even pixels; lanczos cho upscale, fast_bilinear cho downscale
    if need_scale:
        _up = short_side < TARGET   # True = upscale, False = không xảy ra (need_scale=False nếu >=720)
        _scale_algo = 'lanczos' if _up else 'fast_bilinear'
        vf_scale = (f'scale=-2:{TARGET}:flags={_scale_algo}' if w < h
                    else f'scale={TARGET}:-2:flags={_scale_algo}')
    else:
        vf_scale = None

    target_vbr = _calc_bitrate_for_50mb(duration, keep_audio=audio) if need_compress else 0

    logo_path = None
    lx = ly = lw_l = lh_l = 0
    logo_filter_str = ''
    if logo_active:
        raw_b64 = logo_params['logo_base64']
        if raw_b64.startswith('data:image'):
            raw_b64 = raw_b64.split(',', 1)[-1]
        try:
            logo_uid  = uuid.uuid4().hex[:8]
            logo_path = os.path.join(FAST_TMPDIR, f'proc_logo_{logo_uid}.png')

            # ── Giải mã và normalize logo ─────────────────────────────────
            logo_raw_bytes = base64.b64decode(raw_b64)

            # Thử dùng Pillow để convert sang PNG chuẩn (tránh 'codec=none')
            try:
                from PIL import Image
                import io as _io
                img = Image.open(_io.BytesIO(logo_raw_bytes)).convert('RGBA')
                img.save(logo_path, 'PNG')
                _log('info', f'logo normalized via Pillow: {img.size}')
            except Exception:
                # Fallback: ghi thẳng bytes (WEBP/JPEG/GIF cũng được FFmpeg đọc)
                with open(logo_path, 'wb') as lf:
                    lf.write(logo_raw_bytes)

            # ── Claude A: dùng _calc_logo_placement() — single source of truth ──
            # Thay vì dùng scale=min(sx,sy) (cũ, không nhất quán với các hàm khác),
            # dùng short-side uniform scale + force even pixels.
            lx, ly, lw_l, lh_l = _calc_logo_placement(logo_params, w, h)

            # SPEED: skip ffprobe logo validation — Pillow đã đảm bảo PNG valid
            # FFprobe logo probe tiêu tốn 0.5-2s, không cần thiết vì ta đã dùng Pillow
            logo_filter_str = f'[1:v]format=rgba,scale={lw_l}:{lh_l}[logo];'
            _log('info', f'logo placement: {lw_l}x{lh_l} at ({lx},{ly}) | video={w}x{h}')

        except Exception as e_logo:
            log_error(f'logo prep fail: {e_logo}')
            logo_active = False
            if logo_path and os.path.exists(logo_path):
                try: os.unlink(logo_path)
                except: pass
            logo_path = None

    # 🟡 hw_enc always defined here (fix 'hw_enc in dir()' anti-pattern)
    enc, enc_extra = _get_video_encoder(need_filter=bool(vf_scale or logo_active))
    hw_enc = enc
    hw_extra = list(enc_extra)

    # ── SPEED: Preset ultrafast + tune zerolatency cho mọi cấu hình server ─────
    # ultrafast = 5-10x nhanh hơn veryfast, CRF 23 bù lại chất lượng
    # Hardware encoder (NVENC/VAAPI/VTB) tự động ưu tiên = 10-50x nhanh hơn CPU
    _x264_speed = ['-preset', 'ultrafast', '-tune', 'zerolatency']
    if target_vbr > 0:
        if hw_enc != 'libx264':
            enc_args = (['-c:v', hw_enc] + hw_extra +
                        ['-b:v', f'{target_vbr}k', '-maxrate', f'{int(target_vbr*1.5)}k',
                         '-bufsize', f'{target_vbr*3}k', '-pix_fmt', 'yuv420p',
                         '-threads', _FFMPEG_THREADS])
        else:
            enc_args = (['-c:v', 'libx264',
                         '-b:v', f'{target_vbr}k', '-maxrate', f'{int(target_vbr*1.5)}k',
                         '-bufsize', f'{target_vbr*3}k']
                        + _x264_speed
                        + ['-pix_fmt', 'yuv420p', '-threads', _FFMPEG_THREADS])
    else:
        if hw_enc != 'libx264':
            enc_args = (['-c:v', hw_enc] + hw_extra +
                        ['-pix_fmt', 'yuv420p', '-threads', _FFMPEG_THREADS])
        else:
            enc_args = (['-c:v', 'libx264', '-crf', str(_acrf)]
                        + _x264_speed
                        + ['-pix_fmt', 'yuv420p', '-threads', _FFMPEG_THREADS])

    # MD: explicit -map để không bao giờ mất video stream
    if remove_audio:
        audio_args     = ['-an']
        video_map_args = ['-map', '0:v:0']
    elif has_audio:
        audio_args     = ['-map', '0:a?', '-c:a', 'aac', '-b:a', '128k']
        video_map_args = ['-map', '0:v:0']
    else:
        audio_args     = []
        video_map_args = ['-map', '0:v:0']

    if logo_active and logo_path:
        base_cmd = ['ffmpeg', '-y'] + _build_robust_input_flags(is_vfr)
        # Input 0: video; Input 1: logo với explicit -f image2 hint
        # Tránh lỗi 'no decoder found for: none' khi FFmpeg không nhận dạng format
        base_cmd += ['-i', raw_path, '-f', 'image2', '-i', logo_path]
        if vf_scale:
            chain = f'[0:v]{vf_scale}[sc];[sc][logo]overlay={lx}:{ly}[outv]'
        else:
            chain = f'[0:v][logo]overlay={lx}:{ly}[outv]'
        filter_args    = ['-filter_complex', logo_filter_str + chain, '-map', '[outv]']
        video_map_args = []
    elif vf_scale:
        base_cmd = ['ffmpeg', '-y'] + _build_robust_input_flags(is_vfr)
        base_cmd    += ['-i', raw_path]
        chain_fc     = f'[0:v]{vf_scale}[outv]'
        filter_args  = ['-filter_complex', chain_fc, '-map', '[outv]']
        video_map_args = []
    else:
        base_cmd    = ['ffmpeg', '-y'] + _build_robust_input_flags(is_vfr)
        base_cmd   += ['-i', raw_path]
        filter_args = []

    cmd = (base_cmd + filter_args + video_map_args + enc_args
           + audio_args + ['-movflags', '+faststart', out_path])

    reasons = []
    if need_scale:     reasons.append(f'scale→720p')
    if logo_active:    reasons.append('logo')
    if need_compress:  reasons.append(f'compress→<50MB')
    if need_transcode: reasons.append(f'transcode({vcodec}→H264)')
    if remove_audio:   reasons.append('no-audio')
    if is_vfr:         reasons.append('vfr-fix')
    log_process(f"proc ENCODE [{hw_enc}] {w}x{h} {size_bytes//1024}KB | {' + '.join(reasons)}")

    MIN_B  = max(10*1024, size_bytes // 100)   # SPEED: lower threshold
    # SPEED: adaptive timeout — ngắn cho video ngắn, đủ dài cho video dài
    _enc_timeout = max(60, int(duration * 1.2) + 30)  # 1.2x realtime + 30s buffer
    t0     = time.time()
    r_out  = None
    try:
        r = _run_ffmpeg(cmd, timeout=_enc_timeout)
        elapsed = round(time.time()-t0, 1)

        # MD Phần 2.3 Kiểm tra 4: scan stderr
        warns = _scan_ffmpeg_stderr(r.stderr)
        if warns:
            log_error(f'[proc_encode] FFmpeg stderr warnings: {warns}')

        # 🔵 Phát hiện codec=none / filtergraph errors → sanitize raw + retry NGAY
        _CODEC_NONE_SIGNALS = [
            'no decoder found for: none',
            'decoding requested, but no decoder found',
            'error binding filtergraph',
            'error binding an input stream',
        ]
        _has_codec_none = any(sig in w for w in warns for sig in _CODEC_NONE_SIGNALS)

        if r.returncode != 0 and _has_codec_none and os.path.exists(raw_path):
            log_process('[proc_encode] codec=none detected → sanitize raw + retry...')
            if os.path.exists(out_path):
                try: os.unlink(out_path)
                except: pass
            try:
                san_path = _sanitize_video_for_ffmpeg(raw_path)
                if san_path and os.path.exists(san_path) and san_path != raw_path:
                    # Re-probe sanitized file
                    san_info = _probe_once(san_path)
                    if san_info and not san_info.get('needs_sanitize'):
                        # Rebuild command với file đã sanitize
                        san_cmd = [arg if arg != raw_path else san_path for arg in cmd]
                        san_cmd[san_cmd.index(out_path)] = out_path  # keep same output
                        if os.path.exists(out_path): os.unlink(out_path)
                        r_san = _run_ffmpeg(san_cmd, timeout=int(300 * _FFMPEG_TIMEOUT_FACTOR))
                        if r_san.returncode == 0 and os.path.exists(out_path):
                            ok_san, r_san_out = _validate_ffmpeg_output(san_path, out_path, san_info)
                            san_sz = os.path.getsize(out_path)
                            if ok_san and san_sz > MIN_B:
                                log_process(f'proc SANITIZE-RETRY OK {san_sz//1024}KB')
                                _cleanup_file(san_path)
                                return out_path
                        _cleanup_file(san_path)
                    else:
                        log_error(f'[proc_encode] sanitize output still broken, giving up codec=none path')
                        _cleanup_file(san_path)
            except Exception as e_san_retry:
                log_error(f'[proc_encode] sanitize retry exception: {e_san_retry}')

        if r.returncode == 0 and os.path.exists(out_path):
            # MD Phần 2: validate output
            ok_out, r_out = _validate_ffmpeg_output(raw_path, out_path, info)
            out_sz = os.path.getsize(out_path)
            if ok_out and out_sz > MIN_B:
                log_process(f"proc ENCODE OK {out_sz//1024}KB in {elapsed}s | {r_out}")
                _cleanup_file(raw_path)
                return out_path
            else:
                log_error(f'[proc_encode] output validation FAIL: {r_out} sz={out_sz}B')
                if os.path.exists(out_path):
                    try: os.unlink(out_path)
                    except: pass
        else:
            err = r.stderr.decode(errors='ignore')[-300:]
            log_error(f'[proc_encode] rc={r.returncode}: {err}')

        # ── S0: Pre-repair invalid data với mp4box hoặc ffmpeg remux ─────────
        # Chạy trước 4 strategies khác — cố sửa container trước khi encode
        if r_out == 'real_truncation' or (r_out and 'truncation' in str(r_out)):
            _s0_path = os.path.join(FAST_TMPDIR, f's0_repair_{uuid.uuid4().hex[:6]}.mp4')
            try:
                r_s0 = subprocess.run([
                    'ffmpeg', '-y',
                    '-probesize', '200M', '-analyzeduration', '20M',
                    '-fflags', '+genpts+igndts+discardcorrupt',
                    '-err_detect', 'ignore_err', '-max_error_rate', '1.0',
                    '-i', raw_path,
                    '-c', 'copy',
                    '-map', '0:v?', '-map', '0:a?',
                    '-ignore_unknown',
                    '-movflags', '+faststart',
                    _s0_path,
                ], capture_output=True, timeout=60)
                if r_s0.returncode == 0 and os.path.exists(_s0_path) and os.path.getsize(_s0_path) > MIN_B:
                    # Thay raw_path bằng file đã repair để các strategy sau dùng
                    shutil.copy2(_s0_path, raw_path)
                    log_process(f'proc S0-PRE-REPAIR OK {os.path.getsize(raw_path)//1024}KB')
                _cleanup_file(_s0_path)
            except Exception as e_s0:
                log_error(f'[proc] S0 pre-repair exception: {e_s0}')
                _cleanup_file(_s0_path)

        # ── MULTI-STRATEGY TRUNCATION RECOVERY ───────────────────────────────
        # Khi truncation xảy ra, thử 4 chiến lược khác nhau:
        # S1: genpts+copyts+vsync vfr (tương tự cũ nhưng với probesize lớn)
        # S2: Re-remux input sang MKV → encode lại (loại bỏ container broken)
        # S3: -ss 0 -t [duration] để force đúng thời lượng
        # S4: Chấp nhận output bị truncate nếu > 3s (tốt hơn là fail hoàn toàn)
        if r_out == 'real_truncation' or (r_out and 'truncation' in str(r_out)):
            log_process('proc TRUNCATION-RECOVERY: thử 4 chiến lược...')

            # ── Strategy 1: genpts + copyts + vsync vfr ───────────────────────
            _s1_ok = False
            try:
                if os.path.exists(out_path): os.unlink(out_path)
                s1_base = (['ffmpeg', '-y']
                            + _build_robust_input_flags(True)
                            + ['-i', raw_path])
                s1_cmd = (s1_base + filter_args + video_map_args + enc_args
                          + ['-vsync', 'vfr', '-copyts']
                          + audio_args + ['-movflags', '+faststart', out_path])
                r_s1 = _run_ffmpeg(s1_cmd, timeout=_enc_timeout)
                if r_s1.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > MIN_B:
                    ok_s1, r_s1_out = _validate_ffmpeg_output(raw_path, out_path, info)
                    if ok_s1:
                        log_process(f'proc S1-RECOVERY OK {os.path.getsize(out_path)//1024}KB')
                        _cleanup_file(raw_path)
                        return out_path
                    elif 'truncation' not in str(r_s1_out):
                        # Không truncation nhưng có vấn đề khác → vẫn dùng
                        if os.path.getsize(out_path) > MIN_B:
                            log_process(f'proc S1-RECOVERY partial-ok {os.path.getsize(out_path)//1024}KB ({r_s1_out})')
                            _cleanup_file(raw_path)
                            return out_path
                if os.path.exists(out_path): os.unlink(out_path)
            except Exception as e_s1:
                log_error(f'[proc] S1 exception: {e_s1}')

            # ── Strategy 2: Re-remux input → MKV → encode mới ────────────────
            try:
                remux_path = os.path.join(FAST_TMPDIR, f'remux_{uuid.uuid4().hex[:8]}.mkv')
                if os.path.exists(out_path): os.unlink(out_path)
                r_remux = subprocess.run([
                    'ffmpeg', '-y',
                    '-probesize', '200M', '-analyzeduration', '20M',
                    '-fflags', '+genpts+igndts+discardcorrupt',
                    '-err_detect', 'ignore_err', '-max_error_rate', '1.0',
                    '-i', raw_path,
                    '-c', 'copy',                     # remux không encode
                    '-movflags', '+faststart',
                    remux_path
                ], capture_output=True, timeout=60)
                if r_remux.returncode == 0 and os.path.exists(remux_path) and os.path.getsize(remux_path) > MIN_B:
                    # Encode từ file đã remux
                    s2_cmd_parts = [arg if arg != raw_path else remux_path for arg in s1_cmd]
                    r_s2 = _run_ffmpeg(s2_cmd_parts, timeout=_enc_timeout)
                    _cleanup_file(remux_path)
                    if r_s2.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > MIN_B:
                        ok_s2, _ = _validate_ffmpeg_output(raw_path, out_path, info)
                        if ok_s2:
                            log_process(f'proc S2-REMUX-RECOVERY OK {os.path.getsize(out_path)//1024}KB')
                            _cleanup_file(raw_path)
                            return out_path
                _cleanup_file(remux_path)
                if os.path.exists(out_path): os.unlink(out_path)
            except Exception as e_s2:
                log_error(f'[proc] S2 exception: {e_s2}')

            # ── Strategy 3: Force -t [duration] để output đúng thời lượng ────
            try:
                if os.path.exists(out_path): os.unlink(out_path)
                # Lấy duration thực từ stream (không từ container)
                _force_dur = info.get('duration_stream') or info.get('duration') or duration
                s3_base = (['ffmpeg', '-y']
                            + _build_robust_input_flags(True)
                            + ['-i', raw_path])
                s3_cmd = (s3_base + filter_args + video_map_args + enc_args
                          + ['-t', str(max(1.0, float(_force_dur)))]
                          + audio_args + ['-movflags', '+faststart', out_path])
                r_s3 = _run_ffmpeg(s3_cmd, timeout=_enc_timeout)
                if r_s3.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > MIN_B:
                    ok_s3, _ = _validate_ffmpeg_output(raw_path, out_path, info)
                    if ok_s3:
                        log_process(f'proc S3-FORCE-DUR OK {os.path.getsize(out_path)//1024}KB')
                        _cleanup_file(raw_path)
                        return out_path
                if os.path.exists(out_path): os.unlink(out_path)
            except Exception as e_s3:
                log_error(f'[proc] S3 exception: {e_s3}')

            # ── Strategy 4: Đơn giản nhất, chấp nhận mọi output > 3s ─────────
            # Tốt hơn là fail hoàn toàn — user nhận được video ngắn hơn dự kiến
            try:
                if os.path.exists(out_path): os.unlink(out_path)
                s4_cmd = [
                    'ffmpeg', '-y',
                    '-probesize', '500M', '-analyzeduration', '50M',
                    '-fflags', '+genpts+igndts+discardcorrupt',
                    '-err_detect', 'ignore_err', '-max_error_rate', '1.0',
                    '-i', raw_path,
                    '-map', '0:v:0',
                    '-c:v', 'libx264', '-crf', '23', '-preset', 'ultrafast',
                    '-pix_fmt', 'yuv420p', '-threads', _FFMPEG_THREADS,
                ] + (['-an'] if remove_audio else ['-map', '0:a?', '-c:a', 'aac', '-b:a', '128k']) + [
                    '-movflags', '+faststart', out_path
                ]
                r_s4 = _run_ffmpeg(s4_cmd, timeout=max(120, _enc_timeout))
                if os.path.exists(out_path):
                    sz_s4 = os.path.getsize(out_path)
                    if sz_s4 > 50 * 1024:   # ít nhất 50KB — có nội dung
                        log_process(f'proc S4-BRUTE-FORCE OK {sz_s4//1024}KB (chấp nhận output có thể ngắn hơn)')
                        _cleanup_file(raw_path)
                        return out_path
                if os.path.exists(out_path): os.unlink(out_path)
            except Exception as e_s4:
                log_error(f'[proc] S4 exception: {e_s4}')

            log_error(f'[proc_encode] TẤT CẢ 4 strategies truncation recovery thất bại')

            # ── Strategy 5 (LAST RESORT): Trả thẳng raw_path nếu nó playable ──
            # Tốt hơn fail hoàn toàn — user nhận được video gốc (có thể có watermark)
            if os.path.exists(raw_path) and os.path.getsize(raw_path) > MIN_B:
                cached = _ffprobe_cache_get(raw_path)
                if cached is None:
                    cached = validate_video_with_ffprobe(raw_path)
                if cached:
                    log_process(f'proc S5-RAW-FALLBACK: trả raw file {os.path.getsize(raw_path)//1024}KB')
                    return raw_path   # raw file — playable dù không processed

        # Fallback: scale → scale (nếu zscale-based filter không có)
        if vf_scale and 'zscale' in vf_scale:
            vf_fb = vf_scale.replace('zscale=','scale=').replace(':filter=bilinear',':flags=fast_bilinear')
            chain_fb = f'[0:v]{vf_fb}[outv]'
            base_fb = ['ffmpeg', '-y'] + _build_robust_input_flags(is_vfr)
            base_fb += ['-i', raw_path]
            cmd_fb   = (base_fb
                        + ['-filter_complex',chain_fb,'-map','[outv]']
                        + audio_args
                        + ['-c:v','libx264','-crf','23','-preset','ultrafast','-tune','zerolatency',
                           '-pix_fmt','yuv420p','-threads',_FFMPEG_THREADS]
                        + ['-movflags','+faststart',out_path])
            if os.path.exists(out_path):
                try: os.unlink(out_path)
                except: pass
            r2 = _run_ffmpeg(cmd_fb, timeout=_enc_timeout)
            ok2, ro2 = _validate_ffmpeg_output(raw_path, out_path, info)
            if r2.returncode == 0 and ok2 and os.path.getsize(out_path) > MIN_B:
                log_process(f"proc FALLBACK-SCALE ok {os.path.getsize(out_path)//1024}KB")
                _cleanup_file(raw_path)
                return out_path

    except Exception as e:
        log_error("_process_video_file encode", e)
    finally:
        if logo_path and os.path.exists(logo_path):
            try: os.unlink(logo_path)
            except: pass
        if os.path.exists(out_path):
            try:
                if os.path.getsize(out_path) < MIN_B: os.unlink(out_path)
            except: pass

    # ── FALLBACK CUỐI: re-encode H.264 đơn giản nhất ─────────────────────────
    try:
        out_fb = os.path.join(FAST_TMPDIR, f'proc_fb_{uuid.uuid4().hex[:8]}.mp4')
        fb_base = ['ffmpeg', '-y'] + _build_robust_input_flags(is_vfr)
        fb_base += ['-i', raw_path]
        fb_audio = (['-an'] if remove_audio
                    else (['-map','0:v:0','-map','0:a?','-c:a','aac','-b:a','128k']
                          if has_audio else ['-map','0:v:0']))
        r_fb = subprocess.run(
            fb_base + ['-map','0:v:0']
            + ['-c:v','libx264','-crf','23','-preset','ultrafast','-tune','zerolatency',
               '-pix_fmt','yuv420p','-threads',_FFMPEG_THREADS]
            + fb_audio + ['-movflags','+faststart',out_fb],
            capture_output=True, timeout=max(60, int(duration*1.2)+30)
        )
        ok_fb, rfb = _validate_ffmpeg_output(raw_path, out_fb, info)
        if r_fb.returncode == 0 and ok_fb and os.path.getsize(out_fb) > 10*1024:
            log_process(f"proc FALLBACK-ENCODE ok {os.path.getsize(out_fb)//1024}KB")
            _cleanup_file(raw_path)
            return out_fb
        _cleanup_file(out_fb)
    except Exception as e_fb:
        log_error("_process_video_file fallback encode", e_fb)

    log_error(f'[proc] TẤT CẢ paths thất bại codec={vcodec} — raising để trigger re-download')
    raise Exception(f'proc_all_failed: codec={vcodec}, truncation detected, re-download needed')

def _normalize_video_file(input_path, output_path,
                           remove_audio=False, logo_params=None):
    """
    Legacy wrapper — gọi _process_video_file bên trong.
    Giữ để tương thích với các route cũ (batch download, v.v.).
    """
    result = _process_video_file(input_path, audio=(not remove_audio), logo_params=logo_params)
    if result != input_path and os.path.exists(result):
        try:
            shutil.copy2(result, output_path)
            _cleanup_file(result)
            return output_path
        except Exception:
            return result
    return result

# ══════════════════════════════════════════════════════════════════════════════
# LOGO SIZE GUARD — kiểm tra & retry khi video có logo bị quá nhỏ
# ══════════════════════════════════════════════════════════════════════════════
LOGO_MIN_BYTES   = int(1.1 * 1024 * 1024)   # 1.1 MB
LOGO_MAX_RETRIES = 5

def _logo_size_retry(
    url: str,
    audio: bool,
    logo_params: dict,
    result_path: str,
    extra_files: list,
    label: str = '',
    emit_cb=None,
) -> tuple:
    """
    Kiểm tra dung lượng video **chỉ khi logo đang bật**.
    Nếu file < LOGO_MIN_BYTES (1.1 MB) → xóa, tải lại và xử lý lại tối đa
    LOGO_MAX_RETRIES (5) lần cho đến khi đạt ngưỡng hoặc hết retry.

    Tham số:
        url          – TikTok URL gốc
        audio        – giữ audio hay không
        logo_params  – dict logo (enabled, logo_base64, x, y, w, h)
        result_path  – đường dẫn file đã xử lý xong (input)
        extra_files  – list file tạm liên quan (sẽ được cleanup nếu retry)
        label        – chuỗi log thêm (task_id ngắn hoặc [batch][index])
        emit_cb      – callable(msg: str) để push SSE status, hoặc None

    Trả về:
        (final_result_path, final_extra_files)
        – Luôn trả về đường dẫn hợp lệ (có thể là bản cũ nếu tất cả retry đều nhỏ)
    """
    logo_active = bool(
        logo_params and logo_params.get('enabled')
        and logo_params.get('logo_base64') and FFMPEG_AVAILABLE
    )
    # Không bật logo → bỏ qua hoàn toàn
    if not logo_active:
        return result_path, extra_files

    current_path  = result_path
    current_extra = list(extra_files)

    for attempt in range(1, LOGO_MAX_RETRIES + 1):
        try:
            current_size = os.path.getsize(current_path) if os.path.exists(current_path) else 0
        except OSError:
            current_size = 0

        size_mb = round(current_size / 1024 / 1024, 2)

        if current_size >= LOGO_MIN_BYTES:
            # Đạt ngưỡng — OK
            if attempt > 1:
                _log('ok', f'{label} ✅ logo-size OK sau retry {attempt-1}: {size_mb}MB')
                if emit_cb:
                    emit_cb(f'✅ Logo OK ({size_mb}MB) sau {attempt-1} lần thử lại')
            return current_path, current_extra

        # Nhỏ hơn ngưỡng → thông báo và retry
        _log('warn',
             f'{label} ⚠️ Logo video quá nhỏ ({size_mb}MB < {LOGO_MIN_BYTES/1024/1024:.1f}MB) '
             f'— retry {attempt}/{LOGO_MAX_RETRIES}')
        if emit_cb:
            emit_cb(f'⚠️ File nhỏ ({size_mb}MB), tải lại lần {attempt}/{LOGO_MAX_RETRIES}...')

        # Xóa file hiện tại và file tạm
        _cleanup_file(current_path, *current_extra)
        current_path  = None
        current_extra = []

        try:
            new_raw, new_info = _race_download_to_file(url, FAST_TMPDIR, audio=audio)
            new_result = _process_video_file(new_raw, audio, logo_params)

            if new_result != new_raw:
                current_extra = [new_raw]
            else:
                current_extra = []

            current_path = new_result
            _log('info',
                 f'{label} 🔁 retry {attempt} → {os.path.getsize(new_result)//1024}KB')

        except Exception as ex:
            _log('err', f'{label} retry {attempt} failed: {ex}')
            if emit_cb:
                emit_cb(f'❌ Retry {attempt} thất bại: {str(ex)[:60]}')
            # Không có file mới → thoát sớm, trả về None để caller xử lý
            return current_path, current_extra

    # Hết 5 lần vẫn nhỏ → log cảnh báo nhưng vẫn trả file cuối cùng
    if current_path and os.path.exists(current_path):
        final_mb = round(os.path.getsize(current_path) / 1024 / 1024, 2)
        _log('warn',
             f'{label} ⚠️ Hết {LOGO_MAX_RETRIES} lần retry — file vẫn nhỏ ({final_mb}MB), trả về.')
        if emit_cb:
            emit_cb(f'⚠️ Vẫn nhỏ sau {LOGO_MAX_RETRIES} lần ({final_mb}MB) — trả về bản tốt nhất')
    return current_path, current_extra


# ==================== TASK & SSE INFRASTRUCTURE ====================
# Mỗi download là 1 task chạy background thread.
# Client nhận realtime qua SSE (Server-Sent Events) không polling.
# File kết quả lưu trên đĩa đến khi client GET /api/get_result/<task_id>.

_task_lock  = threading.Lock()
TASK_STORE  = {}   # task_id → {status, result_path, filename, info, error, created_at, tmp_files}
SSE_QUEUES  = {}   # task_id → queue.Queue  (push events từ background → SSE generator)

# ── AUTO-EXPIRE CLEANUP — xóa task > 1h để tránh memory leak ─────────────────
_TASK_TTL = 3600  # 1 giờ

def _auto_cleanup_tasks():
    """Xóa task cũ > 1h và file tạm liên quan mỗi 10 phút."""
    while True:
        try:
            time.sleep(600)   # 10 phút
            now = time.time()
            expired = []
            with _task_lock:
                for tid, t in list(TASK_STORE.items()):
                    if now - t.get('created_at', now) > _TASK_TTL:
                        expired.append(tid)
                for tid in expired:
                    t = TASK_STORE.pop(tid, {})
                    SSE_QUEUES.pop(tid, None)
                    _cleanup_file(t.get('result_path'), *(t.get('extra_files') or []))
            if expired:
                _log('info', f'auto-cleanup: xóa {len(expired)} task hết hạn')
        except Exception:
            pass

threading.Thread(target=_auto_cleanup_tasks, daemon=True, name='task-cleanup').start()

# ══════════════════════════════════════════════════════════════════════════════
# BATCH PARALLEL ENGINE — xử lý song song, trả về đúng thứ tự
# ══════════════════════════════════════════════════════════════════════════════
_batch_lock = threading.Lock()
BATCH_STORE = {}   # batch_id → BatchJob

class BatchJob:
    """
    Pipeline Batch Engine — 2 phases:

    Phase 1 (main): Tải + xử lý tuần tự, prefetch song song
      • _do_download: retry 5 lần với method rotation khi no_video_stream
      • _process_and_deliver: validate + FFmpeg

    Phase 2 (retry failed): Sau khi xong toàn bộ, retry các video lỗi
      • Tối đa 5 lần mỗi video, rotation API khác nhau
      • Emit result_retry event để client cập nhật UI

    Queue item progress: mỗi index có per_item_msgs[] để client detail panel
    """

    MAX_DL_RETRIES      = 3    # lần thử ban đầu (race download)
    MAX_ROTATION_RETRY  = 5    # lần retry với method rotation khi validate fail
    MAX_FAILED_RETRY    = 5    # lần tải lại video đã fail ở phase 2

    def __init__(self, batch_id: str, urls: list, audio: bool, logo_params: dict,
                 owner: str = '', save_to_storage: bool = False,
                 download_direct: bool = True, group_name: str = '',
                 folder_id: str = ''):
        self.batch_id         = batch_id
        self.urls             = list(urls)
        self.total            = len(urls)
        self.audio            = audio
        self.logo_params      = logo_params
        self.owner            = owner
        self.save_to_storage  = save_to_storage
        self.download_direct  = download_direct
        self.group_name       = group_name or f'Batch {datetime.now().strftime("%d/%m %H:%M")}'
        self.folder_id        = folder_id or ''   # ⚡ FIX: giữ folder_id cho toàn batch

        self._ok         = 0
        self._err        = 0
        self._done_count = 0

        self.sse_q      = _queue_module.Queue(maxsize=2000)
        self.cancelled  = False
        self.created_at = time.time()

        self.results_log = []
        self._log_lock   = threading.Lock()
        self.is_done     = False

        # 🟡 Per-item progress messages: index → list[str]
        self.per_item_msgs: dict = {i: [] for i in range(self.total)}
        self._item_lock = threading.Lock()

        # Track failed items for phase 2 retry
        self._failed_items: list = []   # list of (index, url)

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        threading.Thread(target=self._orchestrate, daemon=True).start()

    def cancel(self):
        self.cancelled = True
        _log('info', f'[batch {self.batch_id[:8]}] cancel requested')

    def get_item_msgs(self, index: int) -> list:
        """Trả về danh sách progress messages của item index."""
        with self._item_lock:
            return list(self.per_item_msgs.get(index, []))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _push(self, event: str, data: dict):
        try:
            self.sse_q.put_nowait({'event': event, 'data': data})
        except _queue_module.Full:
            pass
        if event in ('result', 'batch_done', 'result_retry'):
            with self._log_lock:
                self.results_log.append({'event': event, 'data': data})
        if event in ('batch_done', '_end'):
            self.is_done = True

    def _item_msg(self, index: int, msg: str):
        """Thêm 1 message vào per-item log và push SSE item_progress."""
        with self._item_lock:
            lst = self.per_item_msgs.setdefault(index, [])
            lst.append(msg)
            if len(lst) > 30:
                self.per_item_msgs[index] = lst[-30:]
        try:
            self.sse_q.put_nowait({'event': 'item_progress', 'data': {
                'index': index, 'msg': msg
            }})
        except _queue_module.Full:
            pass

    def _orchestrate(self):
        _log('info', f'[batch {self.batch_id[:8]}] pipeline start | {self.total} URLs')
        try:
            dl_executor = ThreadPoolExecutor(max_workers=1)
            dl_futures  = {}
            dl_futures[0] = dl_executor.submit(self._do_download, 0)

            # ── Phase 1: Main pass ─────────────────────────────────────────
            for i in range(self.total):
                if self.cancelled:
                    for j in range(i, self.total):
                        self._push('result', {'index': j, 'status': 'cancelled',
                                              'error': 'Đã dừng bởi người dùng'})
                        self._err += 1; self._done_count += 1
                    break

                try:
                    raw_path, info, err_msg = dl_futures[i].result(timeout=400)
                except Exception as ex:
                    raw_path, info, err_msg = None, {}, str(ex)

                if i + 1 < self.total and (i + 1) not in dl_futures:
                    dl_futures[i + 1] = dl_executor.submit(self._do_download, i + 1)

                self._process_and_deliver(i, raw_path, info, err_msg)
                dl_futures.pop(i, None)

            dl_executor.shutdown(wait=False)

            # ── Phase 2: Retry failed items ────────────────────────────────
            if self._failed_items and not self.cancelled:
                n_failed = len(self._failed_items)
                _log('warn', f'[batch {self.batch_id[:8]}] Phase 2: retry {n_failed} failed items')
                self._push('progress', {
                    'index': -1, 'stage': 'retry_phase',
                    'msg': f'🔄 Bắt đầu tải lại {n_failed} video lỗi...'
                })

                for fi, (orig_idx, url) in enumerate(list(self._failed_items)):
                    if self.cancelled:
                        break
                    self._push('progress', {
                        'index': orig_idx, 'stage': 'retry',
                        'msg': f'🔄 [{fi+1}/{n_failed}] Tải lại video #{orig_idx+1}...'
                    })
                    self._retry_failed_item(orig_idx, url, fi, n_failed)

            _log('ok', f'[batch {self.batch_id[:8]}] DONE ✅{self._ok} ❌{self._err}/{self.total}')
            self._push('batch_done', {'ok': self._ok, 'error': self._err, 'total': self.total})
            self._push('_end', {})

        except Exception as ex:
            import traceback
            _log('err', f'[batch {self.batch_id[:8]}] orchestrate error: {ex}\n{traceback.format_exc()[:400]}')
            self._push('batch_done', {
                'ok': self._ok,
                'error': self._err + (self.total - self._done_count),
                'total': self.total
            })
            self._push('_end', {})

    def _do_download(self, index: int) -> tuple:
        """
        Download với race APIs + rotation retry nếu validate fail.
        Trả về (raw_path, info, err_msg).
        """
        if self.cancelled:
            return None, {}, 'Đã dừng bởi người dùng'

        url = self.urls[index]
        label = f'[{index+1}/{self.total}]'

        def _push_msg(msg):
            self._push('progress', {'index': index, 'stage': 'race', 'msg': msg})
            self._item_msg(index, msg)

        _push_msg(f'⬇️ {label} Đang tải...')

        last_err = None

        # Bước 1: Race download (3 lần)
        for attempt in range(1, self.MAX_DL_RETRIES + 1):
            if self.cancelled:
                return None, {}, 'Đã dừng bởi người dùng'
            try:
                if attempt > 1:
                    time.sleep(1.5 * (attempt - 1))
                    _push_msg(f'⬇️ {label} Race retry {attempt}/{self.MAX_DL_RETRIES}...')

                raw_path, info = _race_download_to_file(url, FAST_TMPDIR, audio=self.audio)
                sz_kb = os.path.getsize(raw_path) // 1024
                _push_msg(f'✅ {label} Đã tải ({sz_kb}KB) — chờ xử lý...')
                _log('ok', f'[batch {self.batch_id[:8]}] [{index}] dl OK {sz_kb}KB')
                return raw_path, info, None

            except Exception as e:
                last_err = e
                _log('warn', f'[batch {self.batch_id[:8]}] [{index}] dl attempt {attempt}: {e}')

        err_msg = str(last_err) if last_err else 'Download failed'
        _push_msg(f'❌ {label} Race download thất bại: {err_msg[:60]}')
        _log('err', f'[batch {self.batch_id[:8]}] [{index}] download FAILED: {err_msg[:80]}')
        return None, {}, err_msg

    def _process_and_deliver(self, index: int, raw_path, info: dict, dl_err,
                              is_retry: bool = False):
        """
        FFmpeg process → validate → đăng ký TASK_STORE → emit result.
        Nếu validate fail → rotation retry tối đa MAX_ROTATION_RETRY lần.
        """
        url   = self.urls[index]
        label = f'[{index+1}/{self.total}]'

        def _push_msg(msg):
            self._push('progress', {'index': index, 'stage': 'processing', 'msg': msg})
            self._item_msg(index, msg)

        if dl_err or not raw_path:
            # Ghi vào failed list để phase 2 retry (trừ khi đây đã là retry rồi)
            if not is_retry:
                self._failed_items.append((index, url))
            self._err += 1
            self._done_count += 1
            self._push('result' if not is_retry else 'result_retry', {
                'index': index, 'status': 'failed',
                'error': dl_err or 'Không tải được file', 'is_retry': is_retry
            })
            return

        _push_msg(f'🔧 {label} Đang xử lý video...')

        try:
            result_path = _process_video_file(raw_path, self.audio, self.logo_params)
            # GUARANTEE: không bao giờ trả raw/broken
            result_path = _ensure_valid_mp4(result_path, getattr(self, '_dur_hint', 60))

            if not os.path.exists(result_path):
                raise Exception(f'File không tồn tại sau xử lý')
            sz = os.path.getsize(result_path)
            if sz < 10 * 1024:
                raise Exception(f'File quá nhỏ: {sz}B')

            # 🔵 Validate
            _bv_ok, _bv_reason = deep_validate_video_file(result_path, decode_test=False)

            if not _bv_ok:
                _cleanup_file(result_path)
                # ── 🔵+🟢 ROTATION RETRY khi validate fail ────────────────
                # Đổi API và tải lại thay vì re-encode cùng file lỗi
                _log('warn', f'[batch][{index}] validate fail: {_bv_reason} — bắt đầu rotation retry')
                _push_msg(f'⚠️ {label} Video lỗi ({_bv_reason}) — đang đổi API...')

                rotation_ok = False
                for rot_attempt in range(self.MAX_ROTATION_RETRY):
                    if self.cancelled:
                        break
                    method = _ROTATION_METHODS[rot_attempt % len(_ROTATION_METHODS)]
                    _push_msg(f'🔄 {label} Rotation {rot_attempt+1}/{self.MAX_ROTATION_RETRY}: {method.upper()}')

                    try:
                        new_raw, new_info = _download_with_forced_method(
                            url, FAST_TMPDIR, method, self.audio
                        )
                        new_result = _process_video_file(new_raw, self.audio, self.logo_params)

                        new_sz = os.path.getsize(new_result) if os.path.exists(new_result) else 0
                        new_ok, new_reason = deep_validate_video_file(new_result, decode_test=False)

                        if new_ok and new_sz > 10 * 1024:
                            _log('ok', f'[batch][{index}] rotation {method} OK → {new_sz//1024}KB')
                            _push_msg(f'✅ {label} {method.upper()} thành công ({new_sz//1024}KB)')
                            # Dùng file mới
                            if new_result != new_raw:
                                _cleanup_file(new_raw)
                            result_path = new_result
                            info        = new_info
                            sz          = new_sz
                            rotation_ok = True
                            break
                        else:
                            _cleanup_file(new_result)
                            if new_result != new_raw:
                                _cleanup_file(new_raw)
                            _log('warn', f'[batch][{index}] rotation {method} validate fail: {new_reason}')

                    except Exception as rot_e:
                        _log('warn', f'[batch][{index}] rotation {method} error: {rot_e}')

                if not rotation_ok:
                    # Thêm vào failed list để phase 2 retry (nếu chưa là retry)
                    if not is_retry:
                        self._failed_items.append((index, url))
                    self._err += 1
                    self._done_count += 1
                    err_msg = f'no_video_stream sau {self.MAX_ROTATION_RETRY} rotation ({sz}B)'
                    _push_msg(f'❌ {label} Thất bại sau rotation: {err_msg}')
                    _log('err', f'[batch {self.batch_id[:8]}] [{index}] rotation FAILED')
                    self._push('result' if not is_retry else 'result_retry', {
                        'index': index, 'status': 'failed',
                        'error': err_msg, 'is_retry': is_retry, 'url': url
                    })
                    return

            # ── Đăng ký TASK_STORE ─────────────────────────────────────────
            task_id = hashlib.md5(
                f'{url}{time.time()}{index}{random.random()}'.encode()
            ).hexdigest()

            features = ['720p']
            if not self.audio:         features.append('noaudio')
            if (self.logo_params and self.logo_params.get('enabled')
                    and self.logo_params.get('logo_base64') and FFMPEG_AVAILABLE):
                features.append('logo')

            filename = safe_filename(info.get('title', ''), info.get('id', 'unknown'),
                                     features=features)
            extra    = [raw_path] if result_path != raw_path else []

            with _task_lock:
                TASK_STORE[task_id] = {
                    'status':      'done',
                    'result_path': result_path,
                    'filename':    filename,
                    'size':        sz,
                    'info':        info,
                    'extra_files': extra,
                    'created_at':  time.time(),
                    'url':         url,
                }

            # ── Lưu kho / download trực tiếp theo flag ───────────────────────
            _st_result = {}
            if self.save_to_storage and self.owner:
                try:
                    _st_result = save_to_user_storage(
                        self.owner, result_path, filename,
                        title=info.get('title', ''), url=url,
                        group_id=self.batch_id[:12],
                        group_name=self.group_name,
                        folder_id=self.folder_id   # ⚡ FIX: truyền folder_id từ batch
                    )
                    if _st_result.get('ok'):
                        _push_msg(f'☁️ {label} Đã lưu vào kho ({_st_result.get("used",0)//1024//1024}MB)')
                    else:
                        _push_msg(f'⚠️ Kho đầy: {_st_result.get("reason","")}')
                except Exception as _bst_e:
                    _push_msg(f'⚠️ Lỗi lưu kho: {str(_bst_e)[:40]}')

            # Nếu không download_direct → không cần giữ task_id để download
            _effective_task_id = task_id if self.download_direct else ''

            self._ok += 1
            self._done_count += 1
            _push_msg(f'✅ {label} Hoàn thành! {sz//1024}KB')
            _log('ok', f'[batch {self.batch_id[:8]}] [{index}] ✅ {sz//1024}KB → "{filename}"')
            evt = 'result' if not is_retry else 'result_retry'
            self._push(evt, {
                'index':           index,
                'status':          'done',
                'task_id':         _effective_task_id,
                'filename':        filename,
                'title':           info.get('title', ''),
                'size':            sz,
                'url':             url,
                'is_retry':        is_retry,
                'download_direct': self.download_direct,
                'save_to_storage': self.save_to_storage,
                'storage_saved':   _st_result.get('ok', False),
                'folder_id':       self.folder_id,   # ⚡ FIX: trả folder_id về client
                'expires_days':    _STORAGE_TTL_DAYS,
            })

        except Exception as e:
            _cleanup_file(raw_path)
            err_msg = str(e)
            if not is_retry:
                self._failed_items.append((index, url))
            self._err += 1
            self._done_count += 1
            _push_msg(f'❌ {label} Lỗi xử lý: {err_msg[:80]}')
            _log('err', f'[batch {self.batch_id[:8]}] [{index}] process FAILED: {err_msg}')
            self._push('result' if not is_retry else 'result_retry', {
                'index': index, 'status': 'failed',
                'error': err_msg, 'is_retry': is_retry, 'url': url
            })

    def _retry_failed_item(self, orig_idx: int, url: str, fi: int, n_failed: int):
        """
        🟢 Phase 2: Retry 1 video đã fail với method rotation (MAX_FAILED_RETRY lần).
        Nếu thành công → update _ok/_err, emit result_retry done.
        """
        label = f'[retry {fi+1}/{n_failed}]'

        def _push_msg(msg):
            self._push('progress', {'index': orig_idx, 'stage': 'retry', 'msg': msg})
            self._item_msg(orig_idx, msg)

        _push_msg(f'🔄 {label} Tải lại video #{orig_idx+1} với API rotation...')

        # Đã fail trước → giảm _err 1 để tính lại đúng khi thành công
        self._err = max(0, self._err - 1)

        try:
            raw_path, info = _download_with_rotation_retry(
                url, FAST_TMPDIR, self.audio,
                max_attempts=self.MAX_FAILED_RETRY,
                push_cb=lambda m: _push_msg(m),
                index=orig_idx, total=self.total,
            )
            # Xử lý file đã tải
            _push_msg(f'🔧 {label} Đang xử lý (FFmpeg)...')
            self._process_and_deliver(orig_idx, raw_path, info, None, is_retry=True)

        except Exception as e:
            self._err += 1
            err_msg = str(e)
            _push_msg(f'❌ {label} Thất bại sau {self.MAX_FAILED_RETRY} lần: {err_msg[:80]}')
            _log('err', f'[batch {self.batch_id[:8]}] retry[{orig_idx}] FAILED: {err_msg}')
            self._push('result_retry', {
                'index': orig_idx, 'status': 'failed',
                'error': err_msg, 'is_retry': True, 'url': url,
            })

# ── SSE EMIT ─────────────────────────────────────────────────────────────────
def _emit(task_id: str, event: str, data: dict):
    """Push 1 SSE event vào queue của task_id."""
    with _task_lock:
        q = SSE_QUEUES.get(task_id)
    if q:
        try:
            q.put_nowait({'event': event, 'data': data})
        except _queue_module.Full:
            pass   # queue đầy → bỏ qua (client chưa kết nối)

# ── BACKGROUND DOWNLOAD TASK ─────────────────────────────────────────────────
def _background_download(task_id: str, url: str, audio: bool, logo_params: dict,
                          owner: str = '', save_to_storage: bool = False,
                          download_direct: bool = True,
                          group_id: str = '', group_name: str = '',
                          folder_id: str = ''):
    """
    Pipeline:
      1. Race 4 strategies → file trên RAM disk
      2. Single-pass FFmpeg
      3. Nếu download_direct=True → đăng ký GET /api/get_result
      4. Nếu save_to_storage=True → lưu vào user_storage (TTL 15 ngày)
         (cả 2 có thể cùng True — tải về máy VÀ lưu kho)
    """
    with _task_lock:
        if task_id not in SSE_QUEUES:
            SSE_QUEUES[task_id] = _queue_module.Queue(maxsize=200)

    raw_path    = None
    result_path = None
    extra_files = []
    MAX_TASK_RETRIES = 4

    _log('info', f'▶ {url[:70]}', task_id)

    last_error = None
    for attempt in range(1, MAX_TASK_RETRIES + 1):
        # ── Kiểm tra cancelled trước mỗi lần thử ─────────────────────────────
        with _task_lock:
            _cur_status = TASK_STORE.get(task_id, {}).get('status', '')
        if _cur_status == 'cancelled':
            _log('info', f'task {task_id[:8]} đã bị cancel, thoát background_download', task_id)
            return
        _cleanup_file(raw_path, *extra_files)
        raw_path = result_path = None
        extra_files = []

        try:
            if attempt > 1:
                _log('warn', f'🔄 Thử lại lần {attempt}/{MAX_TASK_RETRIES}...', task_id)
                _emit(task_id, 'status', {'stage':'race',
                    'msg': f'🔄 Thử lại lần {attempt}/{MAX_TASK_RETRIES}...', 'ts': time.time()})
                time.sleep(1.5 * (attempt - 1))

            # ─ 1. Race download ───────────────────────────────────────────
            _log('info', f'⚡ Race strategies{"  #"+str(attempt) if attempt>1 else ""}...', task_id)
            _emit(task_id, 'status', {'stage':'race',
                'msg': f'⚡ Đang chạy 4 strategies song song{f" (lần {attempt})" if attempt>1 else ""}...',
                'ts': time.time()})

            t0 = time.time()
            raw_path, info = _race_download_to_file(url, FAST_TMPDIR, audio=audio)
            dl_sec  = round(time.time()-t0, 1)
            size_kb = os.path.getsize(raw_path) // 1024
            method  = info.get('method', 'unknown')
            title   = info.get('title', 'TikTok Video')

            _log('ok', f'📥 {size_kb}KB ({dl_sec}s) [{method}] "{title[:40]}"', task_id)
            _emit(task_id, 'status', {'stage':'downloaded',
                'msg': f'📥 Tải xong {size_kb}KB (method: {method})',
                'size': size_kb, 'method': method, 'title': title, 'ts': time.time()})

            # ─ 2. Single-pass FFmpeg ──────────────────────────────────────
            logo_active  = bool(logo_params and logo_params.get('enabled')
                                and logo_params.get('logo_base64') and FFMPEG_AVAILABLE)
            label = []
            if not audio:     label.append('no-audio')
            if logo_active:   label.append('logo')
            label_str = ' + '.join(label) if label else 'stream copy'

            _log('info', f'🔧 Xử lý: {label_str}...', task_id)
            _emit(task_id, 'status', {'stage':'processing',
                'msg': f'🔧 Đang xử lý: {label_str}...', 'ts': time.time()})

            t1 = time.time()
            result_path = _process_video_file(raw_path, audio, logo_params)
            result_path = _ensure_valid_mp4(result_path, info.get('duration', 60) if info else 60)

            proc_sec = round(time.time()-t1, 1)

            if result_path != raw_path:
                extra_files.append(raw_path)

            # ─ 3. Validate ───────────────────────────────────────────────
            if not os.path.exists(result_path):
                raise Exception(f"File kết quả không tồn tại: {result_path}")
            sz_check = os.path.getsize(result_path)
            if sz_check < 10 * 1024:
                raise Exception(f"File kết quả quá nhỏ: {sz_check} bytes")

            # 🔵 Claude B: dùng deep_validate (decode_test=False vì đã encode, nhanh hơn)
            _dv_ok, _dv_reason = deep_validate_video_file(result_path, decode_test=False)
            if not _dv_ok:
                _log('warn', f'deep_validate fail: {_dv_reason} sz={sz_check}', task_id)
                raise Exception(f"File kết quả không hợp lệ: {_dv_reason} (size={sz_check}B)")

            # ─ 4. Đăng ký (logo size guard đã loại bỏ) ───────────────────
            _features = ['720p']
            if not audio:    _features.append('noaudio')
            if logo_active:  _features.append('logo')
            filename    = safe_filename(info.get('title',''), info.get('id','unknown'), features=_features)
            result_size = os.path.getsize(result_path)
            result_mb   = round(result_size/1024/1024, 1)

            _log('ok', f'✅ {result_mb}MB ({proc_sec}s) → "{filename}"', task_id)

            _quality_score = _score_video_quality(result_path)
            with _task_lock:
                TASK_STORE[task_id] = {
                    'status':        'done',
                    'result_path':   result_path,
                    'filename':      filename,
                    'size':          result_size,
                    'info':          info,
                    'extra_files':   extra_files,
                    'created_at':    time.time(),
                    'url':           url,
                    'quality_score': _quality_score,
                }
            # ── Lưu vào user storage theo flag (Dr. An) ───────────────────────
            # save_to_storage=True  → lưu vào kho (TTL 15 ngày)
            # download_direct=True  → giữ TASK_STORE để client GET /api/get_result
            # Cả 2 True → làm cả hai
            _storage_result = {}
            _should_save = save_to_storage and owner
            if _should_save:
                try:
                    _storage_result = save_to_user_storage(
                        owner, result_path, filename,
                        title=title, url=url,
                        group_id=group_id, group_name=group_name,
                        folder_id=folder_id
                    )
                    if _storage_result.get('ok'):
                        _log('ok', f'[storage] {owner}: {filename} lưu kho OK', task_id)
                        _emit(task_id, 'storage_saved', {
                            'filename':     filename,
                            'folder_id':    folder_id or '',
                            'used':         _storage_result.get('used', 0),
                            'quota':        _storage_result.get('quota', 0),
                            'expires_days': _STORAGE_TTL_DAYS,
                        })
                    else:
                        _log('warn', f'[storage] {owner}: {_storage_result.get("reason")}', task_id)
                except Exception as _e_st:
                    log_error(f'[storage] save error for {owner}: {_e_st}')

            # Nếu KHÔNG download_direct → dọn file kết quả luôn sau khi đã lưu kho
            if not download_direct and result_path and os.path.exists(result_path):
                _cleanup_file(result_path, *extra_files)
                result_path = None
                with _task_lock:
                    TASK_STORE[task_id]['result_path'] = None
                    TASK_STORE[task_id]['status'] = 'storage_only'

            _emit(task_id, 'done', {
                'filename': filename, 'size': result_size, 'title': title,
                'method': method, 'task_id': task_id, 'ts': time.time(),
                'download_direct':  download_direct,
                'save_to_storage':  save_to_storage,
                'storage_saved':    _storage_result.get('ok', False),
                'storage_used':     _storage_result.get('used', 0),
                'storage_quota':    _storage_result.get('quota', 0),
                'expires_days':     _STORAGE_TTL_DAYS,
                'quality_score':    _quality_score,
            })
            last_error = None
            break

        except Exception as e:
            last_error = e
            err_str = str(e)
            _log('err', f'attempt {attempt}/{MAX_TASK_RETRIES}: {e}', task_id)
            log_error(f"task {task_id[:8]} attempt {attempt}/{MAX_TASK_RETRIES}: {e}", e)
            _cleanup_file(raw_path, *extra_files)
            raw_path = result_path = None
            extra_files = []
            # 🔴 Claude B: Nếu lỗi do truncation/proc_all_failed → thử rotation API ngay
            if 'proc_all_failed' in err_str and attempt < MAX_TASK_RETRIES:
                _log('warn', f'🔄 Truncation detected → rotation retry {attempt}/{MAX_TASK_RETRIES}...', task_id)
                _emit(task_id, 'status', {'stage': 'race',
                    'msg': f'🔄 Video bị cắt ngắn — đổi API lần {attempt}/{MAX_TASK_RETRIES}...', 'ts': time.time()})
                method = _ROTATION_METHODS[attempt % len(_ROTATION_METHODS)]
                try:
                    raw_path, info = _download_with_forced_method(url, FAST_TMPDIR, method, audio)
                    result_path = _process_video_file(raw_path, audio, logo_params)
                    result_path = _ensure_valid_mp4(result_path, (info or {}).get('duration', 60))

                    if result_path != raw_path:
                        extra_files = [raw_path]
                    sz_check = os.path.getsize(result_path) if result_path and os.path.exists(result_path) else 0
                    if sz_check < 10 * 1024:
                        raise Exception(f"Rotation result too small: {sz_check}B")
                    _dv_ok, _dv_reason = deep_validate_video_file(result_path, decode_test=False)
                    if not _dv_ok:
                        raise Exception(f"Rotation validate fail: {_dv_reason}")
                    # SUCCESS
                    _features = ['720p']
                    if not audio: _features.append('noaudio')
                    filename = safe_filename(info.get('title',''), info.get('id','unknown'), features=_features)
                    result_size = os.path.getsize(result_path)
                    with _task_lock:
                        TASK_STORE[task_id] = {
                            'status': 'done', 'result_path': result_path, 'filename': filename,
                            'size': result_size, 'info': info, 'extra_files': extra_files,
                            'created_at': time.time(), 'url': url,
                        }
                    _emit(task_id, 'done', {
                        'filename': filename, 'size': result_size,
                        'title': info.get('title', 'TikTok Video'),
                        'method': method, 'task_id': task_id, 'ts': time.time(),
                    })
                    _emit(task_id, '_end', {})
                    return
                except Exception as rot_e:
                    _log('warn', f'Rotation {method} also failed: {rot_e}', task_id)
                    _cleanup_file(raw_path, *extra_files)
                    raw_path = result_path = None
                    extra_files = []
                    last_error = rot_e
            if attempt < MAX_TASK_RETRIES:
                continue

    if last_error is not None:
        _log('err', f'❌ Thất bại sau {MAX_TASK_RETRIES} lần: {last_error}', task_id)
        with _task_lock:
            TASK_STORE[task_id] = {'status':'error','error':str(last_error),'created_at':time.time()}
        _emit(task_id, 'error', {'msg': str(last_error), 'ts': time.time()})

    try: _emit(task_id, '_end', {})
    except Exception: pass


# ── CLEANUP CŨ (chạy mỗi 10 phút) ───────────────────────────────────────────
def _cleanup_old_tasks():
    while True:
        time.sleep(600)
        now = time.time()
        # ── Dọn tasks cũ ─────────────────────────────────────────────────────
        with _task_lock:
            old = [tid for tid, t in TASK_STORE.items()
                   if now - t.get('created_at', now) > 3600]  # > 60 phút
        for tid in old:
            with _task_lock:
                t = TASK_STORE.pop(tid, {})
                SSE_QUEUES.pop(tid, None)
            rp = t.get('result_path')
            if rp:
                try:
                    if os.path.exists(rp): os.unlink(rp)
                except: pass
            for p in t.get('tmp_files', []):
                try:
                    if os.path.exists(p): os.unlink(p)
                except: pass
        # ── Dọn batch jobs cũ (> 30 phút) ────────────────────────────────────
        with _batch_lock:
            old_batches = [bid for bid, j in BATCH_STORE.items()
                           if now - j.created_at > 1800]
        for bid in old_batches:
            with _batch_lock:
                BATCH_STORE.pop(bid, None)

threading.Thread(target=_cleanup_old_tasks, daemon=True).start()

# ─── HELPER: single-pass audio removal + logo overlay ────────────────────────
def _remove_audio_and_overlay_logo_file(input_path, output_path, logo_base64, x, y, width, height):
    """
    1 lệnh FFmpeg: xóa audio VÀ overlay logo.
    Dùng OVERLAY_SEMAPHORE (tối đa 3 tiến trình song song).
    Claude A: Dùng _calc_logo_placement() — short-side uniform scale, even pixels.
    """
    if not FFMPEG_AVAILABLE:
        raise Exception("FFmpeg not available for combined operation")
    with OVERLAY_SEMAPHORE:
        uid       = hashlib.md5((input_path + str(time.time())).encode()).hexdigest()[:8]
        logo_path = os.path.join(FAST_TMPDIR, f'combo_logo_{uid}.png')
        try:
            raw_b64 = logo_base64.split(',', 1)[-1] if logo_base64.startswith('data:image') else logo_base64
            with open(logo_path, 'wb') as f:
                f.write(base64.b64decode(raw_b64))
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height', '-of', 'json', input_path],
                capture_output=True, text=True, timeout=10)
            if probe.returncode != 0: raise Exception("ffprobe failed")
            streams = json.loads(probe.stdout).get('streams', [])
            if not streams: raise Exception("No video stream")
            vw = int(streams[0].get('width', 0))
            vh = int(streams[0].get('height', 0))
            if not vw or not vh: raise Exception("Invalid dims")

            # ── Claude A: _calc_logo_placement() thay cho 4 dòng scale riêng biệt ──
            params = {'x': x, 'y': y, 'width': width, 'height': height}
            lx, ly, lw, lh = _calc_logo_placement(params, vw, vh)

            flt = (f'[1:v]format=rgba,scale={lw}:{lh}[logo];'
                   f'[0:v][logo]overlay={lx}:{ly}[outv]')
            base = ['ffmpeg', '-y', '-i', input_path, '-i', logo_path,
                    '-filter_complex', flt, '-map', '[outv]']
            strategies = [
                # S1: encode video + copy audio (nhanh nhất)
                (300, ['-c:v','libx264','-preset','ultrafast','-crf','18','-threads',_FFMPEG_THREADS,'-c:a','copy','-movflags','+faststart']),
                # S2: encode video + encode audio
                (300, ['-c:v','libx264','-preset','ultrafast','-crf','18','-threads',_FFMPEG_THREADS,'-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart']),
                # S3: fix odd dimensions
                (400, ['-c:v','libx264','-preset','ultrafast','-crf','18','-threads',_FFMPEG_THREADS,'-pix_fmt','yuv420p','-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:a','aac','-b:a','128k','-movflags','+faststart']),
            ]
            last_err = ''
            for idx, (tmo, enc) in enumerate(strategies):
                if os.path.exists(output_path):
                    try: os.unlink(output_path)
                    except: pass
                res = subprocess.run(base + enc + [output_path], capture_output=True, timeout=tmo)
                if res.returncode == 0 and os.path.exists(output_path):
                    sz = os.path.getsize(output_path)
                    if sz > 1024 and validate_video_with_ffprobe(output_path):

                        return
                last_err = res.stderr.decode(errors='ignore')[-200:]
            raise Exception(f"All combined strategies failed — {last_err[-200:]}")
        except Exception as e:
            raise Exception(f"_remove_audio_and_overlay_logo_file: {e}")
        finally:
            try:
                if os.path.exists(logo_path): os.unlink(logo_path)
            except: pass


# ─── HELPER: audio removal 5 strategies ──────────────────────────────────────
def _remove_audio_file(input_path, output_path):
    """
    Xóa audio track file→file. Ưu tiên -c:v copy (stream copy, <1s).
    Fallback re-encode chỉ khi copy thất bại.
    FFMPEG_SEMAPHORE tối đa 6 song song.
    """
    if not FFMPEG_AVAILABLE:
        raise Exception("FFmpeg not available")
    MIN_SIZE = max(50 * 1024, int(os.path.getsize(input_path) * 0.1))
    with FFMPEG_SEMAPHORE:
        strategies = [
            # S1: stream copy hoàn toàn — nhanh nhất (<1s)
            (30,  ['ffmpeg','-y','-i',input_path,'-an','-c:v','copy','-movflags','+faststart',output_path]),
            # S2: copy + reset timestamps
            (30,  ['ffmpeg','-y','-i',input_path,'-an','-c:v','copy','-avoid_negative_ts','make_zero','-movflags','+faststart',output_path]),
            # S3: chỉ map video stream
            (30,  ['ffmpeg','-y','-i',input_path,'-map','0:v:0','-c:v','copy','-movflags','+faststart',output_path]),
            # S4: re-encode fallback (chỉ khi copy thất bại)
            (120, ['ffmpeg','-y','-i',input_path,'-an','-c:v','libx264','-preset','ultrafast','-crf','23','-threads',_FFMPEG_THREADS,'-movflags','+faststart',output_path]),
            # S5: re-encode + fix dimensions
            (120, ['ffmpeg','-y','-i',input_path,'-an','-c:v','libx264','-preset','ultrafast','-crf','23','-pix_fmt','yuv420p','-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2','-threads',_FFMPEG_THREADS,'-movflags','+faststart',output_path]),
        ]
        last_err = ''
        for tmo, cmd in strategies:
            if os.path.exists(output_path):
                try: os.unlink(output_path)
                except: pass
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=tmo)
                if r.returncode == 0 and os.path.exists(output_path):
                    if os.path.getsize(output_path) > MIN_SIZE and validate_video_with_ffprobe(output_path):
                        return
                last_err = r.stderr.decode(errors='ignore')[-300:]
            except (subprocess.TimeoutExpired, Exception):
                pass
        raise Exception(f"All audio-removal strategies failed — {last_err}")





# ==================== ROUTES ====================


# ─────────────────────────────────────────────────────────────────────────────
# AI VIDEO QUALITY SCORER
# ─────────────────────────────────────────────────────────────────────────────
def _score_video_quality(path: str) -> float:
    """
    Chấm điểm chất lượng video (0-10).
    Dựa trên: độ phân giải (30%), bitrate (30%), fps (20%), audio bitrate (20%).
    """
    if not path or not os.path.exists(path) or not FFMPEG_AVAILABLE:
        return 0.0
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-show_entries', 'stream=codec_type,width,height,r_frame_rate,bit_rate:format=bit_rate',
             '-of', 'json', path],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode != 0:
            return 0.0
        d    = json.loads(r.stdout)
        strs = d.get('streams', [])
        fmt  = d.get('format', {})

        vst  = next((s for s in strs if s.get('codec_type') == 'video'), {})
        ast  = next((s for s in strs if s.get('codec_type') == 'audio'), {})

        # Resolution score
        w, h = int(vst.get('width',0)), int(vst.get('height',0))
        short = min(w, h)
        res_score = 10 if short >= 1080 else 8 if short >= 720 else 6 if short >= 480 else 4

        # Bitrate score (kbps)
        tot_br = int(fmt.get('bit_rate', 0)) / 1000  # → kbps
        br_score = 10 if tot_br >= 3000 else 8 if tot_br >= 1500 else 6 if tot_br >= 800 else 4

        # FPS score
        fps_str = vst.get('r_frame_rate', '0/1')
        try:
            num, den = map(int, fps_str.split('/'))
            fps = num / den if den else 0
        except:
            fps = 0
        fps_score = 10 if fps >= 59 else 8 if fps >= 29 else 6 if fps >= 23 else 4

        # Audio score
        a_br = int(ast.get('bit_rate', 0)) / 1000  # kbps
        aud_score = 10 if a_br >= 192 else 8 if a_br >= 128 else 6 if a_br >= 96 else (4 if a_br > 0 else 5)

        score = (res_score*0.30 + br_score*0.30 + fps_score*0.20 + aud_score*0.20)
        return round(score, 1)
    except Exception as e:
        log_error(f'[score_quality] {e}')
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# EYECORE AI CHATBOT — Endpoint
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/chat', methods=['POST'])
def api_chat():
    """AI chatbot sử dụng Claude Haiku — hỗ trợ người dùng TikDown Turbo."""
    import urllib.request as _urlreq
    data = request.get_json(force=True)
    messages = data.get('messages', [])
    if not messages:
        return jsonify({'error': 'No messages'}), 400

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        # Fallback: semantic FAQ matching (no API key)
        last = messages[-1].get('content', '').lower() if messages else ''
        # Normalize: remove diacritics approximation + common typos
        import unicodedata, re as _re
        def _norm(s):
            s = unicodedata.normalize('NFKD', s)
            s = ''.join(c for c in s if not unicodedata.combining(c))
            return s.lower()
        q = _norm(last)
        # Intent → keywords → answer
        FAQ = [
            (['tikdown','ung dung','app','san pham','cong cu','la gi','gi vay','gi do'],
             'TikDown Turbo là công cụ tải video TikTok không watermark tốc độ cao của EYECORE AI. Sử dụng đa luồng (Multi-threading) và thuật toán thông minh. Giá trị cốt lõi: Tốc độ - Đơn giản - Hiệu quả.'),
            (['eyecore','doi ngu','team','ai la','cong ty','ai phat trien'],
             'EYECORE AI là đội ngũ phát triển AI trẻ Việt Nam, chuyên về thị giác máy tính (Computer Vision) và công cụ web hiệu suất cao. Sản phẩm nổi bật: TikDown Turbo.'),
            (['cach tai','huong dan','lam sao','thu tuc','dung the nao','bat dau','steps'],
             'Cách tải video: 1) Dán link TikTok vào ô nhập liệu. 2) Nhấn TÌM KIẾM. 3) Chọn chế độ: Tải Thẳng/Lưu Kho/Cả Hai. 4) Nếu lưu kho: chọn thư mục. 5) Nhấn TẢI VIDEO.'),
            (['thu muc','folder','luu kho','storage','kho luu','kho tru'],
             'Kho Lưu Trữ hoạt động theo thư mục: 1) Tạo thư mục trong tab KHO. 2) Khi tải với chế độ "Lưu Kho", PHẢI chọn thư mục (bắt buộc). 3) Video lưu 15 ngày, dung lượng 3GB/tài khoản.'),
            (['logo','watermark','them logo','anh logo','brand','overlay'],
             'Thêm logo: Vào tab LOGO → Upload ảnh PNG/JPG (tối đa 5MB) → Kéo thả vị trí hoặc nhập tọa độ → Bật checkbox "Thêm logo" → Tải video. Logo sẽ được gắn vào video.'),
            (['hang cho','queue','xep hang','nhieu link','batch','dong loat'],
             'Hàng Chờ: Dán nhiều link TikTok → vào tab HÀNG CHỜ → kéo thả sắp xếp thứ tự → hệ thống tự động tải lần lượt. Hỗ trợ tải song song nhiều video.'),
            (['loi','khong tai','sao khong','failed','error','thu lai'],
             'Xử lý lỗi: 1) Copy lại link từ app TikTok. 2) Kiểm tra video không bị private/xóa. 3) Thử lại sau vài giây (server tự retry). 4) Nếu lỗi "chọn thư mục": tạo thư mục trước trong tab KHO.'),
            (['dark mode','toi','bao ve mat','eye','dem','sang','giao dien'],
             'AI Eye-Protection Mode: Tự động bật dark mode sau 18:00 để bảo vệ mắt. Nhấn nút "AI Eye" ở góc trên để bật/tắt thủ công hoặc xem thông tin chi tiết.'),
            (['chat luong','diem','score','do phan giai','resolution','bitrate','fps'],
             'AI Chấm Điểm Video: Sau khi tải, video được chấm điểm 1-10 dựa trên: độ phân giải (30%), bitrate (30%), FPS (20%), chất lượng audio (20%). Hiển thị trong tab KHO LƯU TRỮ.'),
        ]
        best_reply = None
        best_score = 0
        for keywords, reply in FAQ:
            score = sum(1 for kw in keywords if kw in q)
            if score > best_score:
                best_score = score
                best_reply = reply
        if best_reply and best_score > 0:
            return jsonify({'reply': best_reply})
        return jsonify({'reply': 'Xin chào! Tôi là EYECORE Assistant. Tôi có thể giúp bạn về: cách tải video, quản lý thư mục, thêm logo, hàng chờ, chất lượng video, hoặc thông tin về EYECORE AI. Hỏi tôi bất cứ điều gì!'})

    SYSTEM = """Bạn là trợ lý AI của EYECORE AI và TikDown Turbo.

EYECORE AI: đội ngũ phát triển AI trẻ, tập trung thị giác máy tính và công cụ web hiệu suất cao.
TikDown Turbo: tải video TikTok không logo, tốc độ cao, đa luồng.
Giá trị cốt lõi: Tốc độ - Đơn giản - Hiệu quả.

Cách dùng: Dán link → TÌM KIẾM → chọn Tải Thẳng/Lưu Kho → chọn thư mục (nếu lưu kho) → TẢI.
Tính năng: tải đơn/hàng loạt, thêm logo, kho lưu trữ theo thư mục, hàng chờ tự động, AI Eye-Protection.

Trả lời bằng tiếng Việt, ngắn gọn, thân thiện."""

    try:
        payload = json.dumps({
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 400,
            'system': SYSTEM,
            'messages': messages[-12:],  # tối đa 12 tin nhắn gần nhất
        }).encode('utf-8')

        req = _urlreq.Request(
            'https://api.anthropic.com/v1/messages',
            data=payload,
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            }
        )
        with _urlreq.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())

        text = result.get('content', [{}])[0].get('text', 'Xin lỗi, không có phản hồi.')
        return jsonify({'reply': text})
    except Exception as e:
        log_error(f'[chat] API error: {e}')
        return jsonify({'reply': f'Tôi đang gặp sự cố kết nối ({type(e).__name__}). Vui lòng thử lại sau.'})


@app.route('/')
def index():
    # Thử render_template trước (nếu có thư mục templates/)
    # Nếu không có → đọc trực tiếp từ cùng thư mục app.py
    try:
        return render_template('index.html')
    except Exception:
        idx_path = os.path.join(_BASE_DIR, 'index.html')
        if os.path.exists(idx_path):
            with open(idx_path, 'r', encoding='utf-8') as f:
                return Response(f.read(), mimetype='text/html')
        return 'index.html not found', 404


# ── 📊 DASHBOARD HTML — embedded (không cần file riêng) ──────────────────────
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TikDown Admin Dashboard</title>
<link rel="icon" href="/image/2.ico">
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
:root{--bg:#0f1117;--card:#1a1d27;--card2:#22263a;--border:#2e3350;--accent:#ff4d6d;
  --green:#00d68f;--blue:#4361ee;--yellow:#ffd166;--purple:#a855f7;--cyan:#22d3ee;
  --text:#e2e8f0;--muted:#64748b;--red:#ef4444}
body{background:var(--bg);color:var(--text);min-height:100vh}

/* HEADER */
.hdr{background:#0a0a14;border-bottom:2px solid var(--border);padding:12px 20px;
  display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:50}
.hdr-title{font-size:1.1rem;font-weight:800;color:var(--yellow);letter-spacing:.5px}
.hdr-right{display:flex;align-items:center;gap:8px}
.live-dot{width:8px;height:8px;background:var(--green);border-radius:50%;
  animation:pulse 1.5s ease-in-out infinite;display:inline-block;margin-right:4px}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.hdr-time{font-size:.78rem;color:var(--muted)}
.btn{padding:6px 14px;border:1.5px solid var(--border);border-radius:4px;font-size:.78rem;
  font-weight:700;cursor:pointer;transition:.15s;text-decoration:none;display:inline-flex;align-items:center;gap:5px}
.btn:hover{opacity:.85;transform:translateY(-1px)}
.btn-home{background:var(--card2);color:var(--text)}
.btn-refresh{background:var(--green);color:#000;border-color:var(--green)}
.btn-out{background:var(--red);color:#fff;border-color:var(--red)}

/* LAYOUT */
.wrap{max-width:1400px;margin:0 auto;padding:16px;display:grid;gap:14px}

/* SECTION LABEL */
.sec{font-size:.7rem;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;
  color:var(--muted);padding:10px 0 6px;border-bottom:1px solid var(--border);margin-bottom:12px}

/* STAT CARD GRID */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.sc{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;
  position:relative;overflow:hidden;transition:.2s}
.sc:hover{border-color:var(--accent);transform:translateY(-2px)}
.sc::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--sc-color,var(--accent))}
.sc-val{font-size:1.9rem;font-weight:900;line-height:1;margin-bottom:4px}
.sc-lbl{font-size:.7rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.sc-sub{font-size:.7rem;color:var(--muted);margin-top:3px}

/* PANEL */
.panel{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.ph{background:var(--card2);padding:10px 16px;font-size:.8rem;font-weight:800;
  color:var(--text);display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--border)}
.ph-icon{font-size:.9rem}
.pb{padding:14px}

/* GRID LAYOUTS */
.g2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:600px){.g2{grid-template-columns:1fr}.stats-grid{grid-template-columns:repeat(2,1fr)}.hdr{padding:8px 12px}.hdr-title{font-size:.9rem}.wrap{padding:10px}}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
@media(max-width:900px){.g3,.g4{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.g2,.g3,.g4{grid-template-columns:1fr}}

/* PROGRESS BAR */
.pb-wrap{margin-bottom:10px}
.pb-top{display:flex;justify-content:space-between;font-size:.75rem;font-weight:700;margin-bottom:4px}
.pb-track{background:#1e2235;border-radius:4px;height:10px;overflow:hidden}
.pb-fill{height:100%;border-radius:4px;transition:width .8s ease}

/* BAR CHART */
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.bar-lbl{width:80px;font-size:.73rem;font-weight:700;text-align:right;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--muted)}
.bar-track2{flex:1;background:#1e2235;border-radius:3px;height:20px;overflow:hidden}
.bar-fill2{height:100%;border-radius:3px;display:flex;align-items:center;
  padding-right:6px;justify-content:flex-end;transition:width .6s ease;min-width:24px}
.bar-fill2 span{font-size:.68rem;font-weight:900;color:rgba(255,255,255,.9)}

/* TABLE */
.tbl{width:100%;border-collapse:collapse;font-size:.78rem}
.tbl th{background:#0a0a14;padding:8px 10px;text-align:left;font-size:.68rem;
  font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:var(--muted)}
.tbl td{padding:7px 10px;border-bottom:1px solid var(--border)}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover td{background:var(--card2)}
.badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:.65rem;font-weight:800}
.badge-admin{background:rgba(255,209,102,.15);color:var(--yellow);border:1px solid rgba(255,209,102,.3)}
.badge-user{background:rgba(67,97,238,.15);color:var(--blue);border:1px solid rgba(67,97,238,.3)}
.badge-lock{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.badge-ok{background:rgba(0,214,143,.15);color:var(--green);border:1px solid rgba(0,214,143,.3)}
.badge-mobile{background:rgba(168,85,247,.15);color:var(--purple)}
.badge-desk{background:rgba(34,211,238,.15);color:var(--cyan)}

/* CPU CORES GRID */
.core-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(50px,1fr));gap:6px}
.core-item{background:var(--card2);border-radius:4px;padding:5px 4px;text-align:center}
.core-pct{font-size:.82rem;font-weight:900}
.core-lbl{font-size:.6rem;color:var(--muted);margin-top:2px}

/* NET IFACE */
.iface-row{display:flex;justify-content:space-between;align-items:center;
  padding:5px 0;border-bottom:1px solid var(--border);font-size:.76rem}
.iface-row:last-child{border-bottom:none}

/* DISK PART */
.disk-item{background:var(--card2);border-radius:6px;padding:10px 12px;margin-bottom:8px}
.disk-item:last-child{margin-bottom:0}

/* PROCESS TABLE */
.proc-bar{height:6px;background:#1e2235;border-radius:3px;overflow:hidden;margin-top:3px}
.proc-bar-fill{height:100%;border-radius:3px;background:var(--accent)}

/* MINI METRIC */
.mini-row{display:flex;justify-content:space-between;align-items:center;
  padding:5px 0;border-bottom:1px solid rgba(46,51,80,.5);font-size:.76rem}
.mini-row:last-child{border-bottom:none}
.mini-val{font-weight:800;color:var(--text)}

/* VISITOR ROW */
.vis-row{display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding:6px 0;
  border-bottom:1px solid var(--border);font-size:.74rem}
.vis-row:last-child{border-bottom:none}
.vis-ip{font-family:monospace;color:var(--cyan);font-size:.71rem;min-width:120px}
.vis-cnt{background:var(--card2);border-radius:10px;padding:1px 7px;font-size:.65rem;font-weight:800}

/* SPINNER */
#loadOverlay{position:fixed;inset:0;background:rgba(15,17,23,.92);z-index:9999;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
.spin{width:40px;height:40px;border:4px solid var(--border);
  border-top-color:var(--yellow);border-radius:50%;animation:sp .7s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.load-txt{font-size:.88rem;color:var(--muted);font-weight:700}

/* TOAST */
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
  background:var(--card2);color:var(--text);padding:9px 20px;border:1.5px solid var(--border);
  border-radius:6px;font-size:.82rem;font-weight:700;z-index:9999;display:none}

/* ERROR STATE */
.err-box{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);
  border-radius:6px;padding:10px 14px;color:var(--red);font-size:.8rem;margin:8px 0}
.empty-txt{color:var(--muted);font-size:.8rem;padding:14px 0;text-align:center}
</style>
</head>
<body>

<div id="loadOverlay"><div class="spin"></div><div class="load-txt">Đang tải dữ liệu thực tế...</div></div>
<div id="toast"></div>

<!-- HEADER -->
<div class="hdr">
  <div class="hdr-title">⚡ TikDown Admin Dashboard</div>
  <div class="hdr-right" style="flex-wrap:wrap;gap:6px;">
    <span style="font-size:.72rem;color:var(--muted);">
      Task: <span id="liveActiveTasks" style="color:var(--yellow);font-weight:800;">—</span>
      &nbsp;Batch: <span id="liveActiveBatches" style="color:var(--purple);font-weight:800;">—</span>
    </span>
    <span class="live-dot" id="liveDot" title="Đang kết nối..."></span>
    <span class="hdr-time" id="hdrTime">—</span>
    <button class="btn btn-refresh" onclick="loadData()">↺ Làm mới</button>
    <a href="/" class="btn btn-home">⌂ Trang chủ</a>
    <button class="btn btn-out" onclick="doLogout()">⏏ Đăng xuất</button>
  </div>
</div>

<div class="wrap">

<!-- ══ TỔNG QUAN ══ -->
<div class="sec">📊 Tổng quan</div>
<div class="stats-grid" id="overviewCards"></div>

<!-- ══ SERVER HARDWARE ══ -->
<div class="sec">🖥 Tài nguyên server (thời gian thực)</div>
<div class="g2" id="hwPanels"></div>

<!-- ══ MẠNG & I/O ══ -->
<div class="sec">🌐 Mạng & Tiến trình</div>
<div class="g2" id="netPanels"></div>

<!-- ══ TẢI XUỐNG ══ -->
<div class="sec">⬇ Trạng thái tải xuống</div>
<div class="stats-grid" id="dlCards"></div>

<!-- ══ THIẾT BỊ / TRÌNH DUYỆT ══ -->
<div class="sec">📱 Thiết bị & Trình duyệt</div>
<div class="g4" id="chartPanels"></div>

<!-- ══ STORAGE ══ -->
<div class="sec">💾 Storage người dùng</div>
<div class="panel">
  <div class="ph"><span class="ph-icon">💾</span> Chi tiết storage</div>
  <div style="overflow-x:auto">
    <table class="tbl">
      <thead><tr><th>#</th><th>Tên</th><th>Vai trò</th><th>Đã dùng</th><th>Quota</th><th>Files</th><th>%</th></tr></thead>
      <tbody id="tbStorage"></tbody>
    </table>
  </div>
</div>

<!-- ══ TÀI KHOẢN ══ -->
<div class="sec">👥 Người dùng</div>
<div class="panel">
  <div class="ph"><span class="ph-icon">👤</span> Danh sách tài khoản</div>
  <div style="overflow-x:auto">
    <table class="tbl">
      <thead><tr><th>#</th><th>Tên đăng nhập</th><th>Vai trò</th><th>Trạng thái</th><th>Ngày tạo</th><th>Files</th><th>Storage</th></tr></thead>
      <tbody id="tbUsers"></tbody>
    </table>
  </div>
</div>

<!-- ══ VISITOR ══ -->
<div class="sec">👁 Visitor gần đây (20 lượt)</div>
<div class="panel">
  <div class="ph"><span class="ph-icon">🌍</span> Truy cập mới nhất</div>
  <div class="pb" id="visitorList"></div>
</div>

</div><!-- /wrap -->

<script>
'use strict';
let _d = null; // cached data
const C = ['#ff4d6d','#4361ee','#00d68f','#ffd166','#a855f7','#22d3ee','#fb8500','#e11d48'];

function toast(m,d=3000){const e=document.getElementById('toast');e.textContent=m;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',d);}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtN(n){if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return String(n);}
function fmtMB(b){if(b>=1024*1024*1024)return(b/1024**3).toFixed(2)+' GB';return(b/1024**2).toFixed(1)+' MB';}
function pctColor(p){return p>85?'var(--red)':p>60?'var(--yellow)':'var(--green)';}

function progBar(pct, lbl, sub=''){
  const c = pctColor(pct);
  return `<div class="pb-wrap">
    <div class="pb-top"><span>${lbl}</span><span style="color:${c}">${pct}%</span></div>
    ${sub?`<div style="font-size:.68rem;color:var(--muted);margin-bottom:4px">${sub}</div>`:''}
    <div class="pb-track"><div class="pb-fill" style="width:${pct}%;background:${c}"></div></div>
  </div>`;
}

function barChart(obj, maxBars=8){
  const entries = Object.entries(obj||{}).sort((a,b)=>b[1]-a[1]).slice(0,maxBars);
  if(!entries.length) return '<div class="empty-txt">Chưa có dữ liệu</div>';
  const max = entries[0][1]||1;
  return entries.map(([k,v],i)=>{
    const pct = Math.max(5, Math.round(v/max*100));
    return `<div class="bar-row">
      <div class="bar-lbl" title="${esc(k)}">${esc(k)}</div>
      <div class="bar-track2">
        <div class="bar-fill2" style="width:${pct}%;background:${C[i%C.length]}">
          <span>${v}</span>
        </div>
      </div>
    </div>`;
  }).join('');
}

function statCard(val, lbl, sub='', color='var(--accent)'){
  return `<div class="sc" style="--sc-color:${color}">
    <div class="sc-val" style="color:${color}">${val}</div>
    <div class="sc-lbl">${lbl}</div>
    ${sub?`<div class="sc-sub">${sub}</div>`:''}
  </div>`;
}

async function loadData(){
  document.getElementById('loadOverlay').style.display='flex';
  try{
    const r = await fetch('/api/admin/dashboard_stats',{cache:'no-store',credentials:'include',headers:{'Accept':'application/json'}});
    if(r.status===403){window.location.href='/';return;}
    if(!r.ok) throw new Error('HTTP '+r.status);
    _d = await r.json();
    if(!_d.ok) throw new Error(_d.error||'API error');
    renderAll(_d);
    document.getElementById('hdrTime').textContent = 'Cập nhật: '+(_d.generated_at||'?');
  }catch(e){
    toast('❌ Lỗi: '+e.message, 6000);
    console.error(e);
  }finally{
    document.getElementById('loadOverlay').style.display='none';
  }
}

function renderAll(d){
  renderOverview(d);
  renderHardware(d.system||{}, d.platform||{}, d.app||{});
  renderNetwork(d.system||{}, d.proc||{});
  renderDownloads(d.downloads||{});
  renderCharts(d.visitors||{});
  renderStorage(d.storage||{});
  renderUsers(d.users||{});
  renderVisitors(d.visitors||{});
}

function renderOverview(d){
  const v = d.visitors||{}, u = d.users||{}, s = d.storage||{}, a = d.app||{}, sys = d.system||{};
  document.getElementById('overviewCards').innerHTML = [
    statCard(fmtN(v.total_unique||0), 'Visitor độc nhất', `Hôm nay: ${v.today||0}`, 'var(--blue)'),
    statCard(fmtN(v.today||0), 'Truy cập hôm nay', `Tuần này: ${v.this_week||0}`, 'var(--cyan)'),
    statCard(fmtN(u.total||0), 'Tài khoản', `Admin ${u.admin||0} · Khoá ${u.locked||0}`, 'var(--yellow)'),
    statCard((s.total_used_gb||0).toFixed(2)+' GB', 'Storage dùng', `${(s.users||[]).length} user`, 'var(--green)'),
    statCard(a.uptime_str||'—', 'App uptime', `Khởi động: ${a.started_at||'?'}`, 'var(--purple)'),
    statCard(sys.sys_uptime_str||'—', 'Server uptime', `Boot: ${(sys.boot_time||'').substring(11,16)||'?'}`, 'var(--accent)'),
    statCard(a.task_store||0, 'Task store', `Batch: ${a.batch_store||0}`, 'var(--muted)'),
    statCard((sys.cpu_percent||0)+'%', 'CPU hiện tại', `${sys.cpu_cores_log||0} cores · ${(sys.cpu_freq_mhz||0)/1000>0?((sys.cpu_freq_mhz||0)/1000).toFixed(1)+' GHz':'—'}`, (sys.cpu_percent||0)>70?'var(--red)':'var(--green)'),
  ].join('');
}

function renderHardware(sys, plt, app){
  if(!sys.cpu_percent && sys.cpu_percent !== 0){
    document.getElementById('hwPanels').innerHTML = `<div class="panel" style="grid-column:span 2"><div class="pb"><div class="empty-txt">psutil không khả dụng — pip install psutil</div></div></div>`;
    return;
  }

  // CPU Panel
  const cpuHtml = `
    ${progBar(sys.cpu_percent||0,'CPU tổng', `User ${sys.cpu_user||0}s · System ${sys.cpu_system||0}s · Idle ${sys.cpu_idle||0}s`)}
    <div style="font-size:.72rem;color:var(--muted);margin-bottom:8px">
      ${sys.cpu_cores_log||0} logical / ${sys.cpu_cores_phy||0} physical cores · ${sys.cpu_freq_mhz ? (sys.cpu_freq_mhz/1000).toFixed(2)+' GHz' : '—'}
    </div>
    ${(sys.cpu_per_core||[]).length > 0 ? `
    <div class="core-grid">
      ${(sys.cpu_per_core||[]).map((p,i)=>`
        <div class="core-item">
          <div class="core-pct" style="color:${pctColor(p)}">${p}%</div>
          <div class="core-lbl">C${i}</div>
        </div>`).join('')}
    </div>` : ''}
    <div style="margin-top:12px">
      ${progBar(sys.mem_percent||0,'RAM', `${sys.mem_used_gb||0} / ${sys.mem_total_gb||0} GB · Buffer ${sys.mem_buffers_mb||0}MB · Cache ${sys.mem_cached_mb||0}MB`)}
      ${progBar(sys.swap_percent||0,'Swap', `${sys.swap_used_gb||0} / ${sys.swap_total_gb||0} GB`)}
    </div>`;

  // Disk Panel
  let diskHtml = progBar(sys.disk_percent||0, 'Disk /', `${sys.disk_used_gb||0} GB dùng / ${sys.disk_total_gb||0} GB · Còn ${sys.disk_free_gb||0} GB`);
  const parts = (sys.disk_parts||[]).filter(p=>p.mount!=='/');
  if(parts.length){
    diskHtml += `<div style="margin-top:10px;font-size:.7rem;color:var(--muted);font-weight:700;margin-bottom:6px">CÁC PHÂN VÙNG KHÁC</div>`;
    parts.slice(0,5).forEach(p=>{
      diskHtml += `<div class="disk-item">
        <div style="display:flex;justify-content:space-between;font-size:.76rem;font-weight:700;margin-bottom:6px">
          <span style="color:var(--cyan)">${esc(p.mount)}</span>
          <span style="color:var(--muted)">${p.fs}</span>
          <span style="color:${pctColor(p.pct)}">${p.pct}%</span>
        </div>
        <div class="pb-track"><div class="pb-fill" style="width:${p.pct}%;background:${pctColor(p.pct)}"></div></div>
        <div style="font-size:.68rem;color:var(--muted);margin-top:3px">${p.used_gb}/${p.total_gb} GB</div>
      </div>`;
    });
  }

  // Platform info
  diskHtml += `<div style="margin-top:12px">
    ${[
      ['OS', `${plt.os||'?'} ${plt.release||''}`],
      ['Hostname', plt.hostname||'?'],
      ['IP local', plt.ip_local||'?'],
      ['CPU', plt.processor||plt.machine||'?'],
      ['Python', plt.python||'?'],
      ['FFmpeg', app.ffmpeg?'✅ OK':'❌ Không có'],
      ['Encoder', app.encoder||'?'],
      ['yt-dlp', app.yt_dlp?'✅':'❌'],
      ['Cookies', app.cookies||0],
    ].map(([k,v])=>`<div class="mini-row"><span style="color:var(--muted)">${k}</span><span class="mini-val">${esc(String(v))}</span></div>`).join('')}
  </div>`;

  // Temp
  const temps = sys.temps||{};
  if(Object.keys(temps).length){
    diskHtml += `<div style="margin-top:10px;font-size:.7rem;color:var(--muted);font-weight:700;margin-bottom:5px">🌡 NHIỆT ĐỘ</div>`;
    diskHtml += Object.entries(temps).map(([k,v])=>{
      const c = v>80?'var(--red)':v>60?'var(--yellow)':'var(--green)';
      return `<div class="mini-row"><span style="color:var(--muted)">${esc(k)}</span><span style="color:${c};font-weight:800">${v}°C</span></div>`;
    }).join('');
  }

  document.getElementById('hwPanels').innerHTML = `
    <div class="panel"><div class="ph"><span class="ph-icon">⚙️</span> CPU & RAM</div><div class="pb">${cpuHtml}</div></div>
    <div class="panel"><div class="ph"><span class="ph-icon">💽</span> Disk & Hệ thống</div><div class="pb">${diskHtml}</div></div>`;
}

function renderNetwork(sys, proc){
  // Network
  let netHtml = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
      <div class="sc" style="--sc-color:var(--green)">
        <div class="sc-val" style="color:var(--green)">${sys.net_recv_mb||0} <span style="font-size:.9rem">MB</span></div>
        <div class="sc-lbl">↓ Nhận tổng</div>
      </div>
      <div class="sc" style="--sc-color:var(--blue)">
        <div class="sc-val" style="color:var(--blue)">${sys.net_sent_mb||0} <span style="font-size:.9rem">MB</span></div>
        <div class="sc-lbl">↑ Gửi tổng</div>
      </div>
    </div>
    <div style="font-size:.7rem;color:var(--muted);font-weight:700;margin-bottom:6px">CÁC INTERFACE</div>`;
  const ifaces = sys.net_ifaces||{};
  if(Object.keys(ifaces).length){
    netHtml += Object.entries(ifaces).slice(0,6).map(([name,s])=>`
      <div class="iface-row">
        <span style="color:var(--cyan);font-weight:700">${esc(name)}</span>
        <span style="color:var(--green)">↓${s.recv_mb} MB</span>
        <span style="color:var(--blue)">↑${s.sent_mb} MB</span>
      </div>`).join('');
  } else {
    netHtml += '<div class="empty-txt">Không có dữ liệu interface</div>';
  }
  netHtml += `<div class="mini-row" style="margin-top:8px">
    <span style="color:var(--muted)">Packets recv</span><span class="mini-val">${fmtN(sys.net_pkts_recv||0)}</span></div>
  <div class="mini-row">
    <span style="color:var(--muted)">Packets sent</span><span class="mini-val">${fmtN(sys.net_pkts_sent||0)}</span></div>`;

  // Processes
  let procHtml = `<div class="mini-row" style="margin-bottom:8px">
    <span style="color:var(--muted)">Tổng tiến trình</span>
    <span class="mini-val" style="color:var(--yellow)">${proc.count||'—'}</span>
  </div>
  <div style="font-size:.7rem;color:var(--muted);font-weight:700;margin-bottom:6px">TOP CPU (%)</div>`;
  const topCpu = proc.top_cpu||[];
  if(topCpu.length){
    procHtml += `<table class="tbl" style="font-size:.73rem">
      <thead><tr><th>PID</th><th>Tên</th><th>CPU%</th><th>MEM%</th><th>Status</th></tr></thead>
      <tbody>${topCpu.slice(0,8).map(p=>{
        const cpu = p.cpu_percent||0;
        return `<tr>
          <td style="color:var(--muted)">${p.pid||'?'}</td>
          <td style="font-weight:700;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.name||'?')}</td>
          <td style="color:${cpu>50?'var(--red)':cpu>20?'var(--yellow)':'var(--green)'};font-weight:800">${cpu}%</td>
          <td style="color:var(--muted)">${(p.memory_percent||0).toFixed(1)}%</td>
          <td><span class="badge badge-ok">${esc(p.status||'?')}</span></td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
  } else {
    procHtml += '<div class="empty-txt">Không có dữ liệu tiến trình</div>';
  }

  document.getElementById('netPanels').innerHTML = `
    <div class="panel"><div class="ph"><span class="ph-icon">🌐</span> Mạng</div><div class="pb">${netHtml}</div></div>
    <div class="panel"><div class="ph"><span class="ph-icon">⚙️</span> Tiến trình</div><div class="pb">${procHtml}</div></div>`;
}

function renderDownloads(dl){
  document.getElementById('dlCards').innerHTML = [
    statCard(dl.active_tasks||0,'Task đang chạy','','var(--yellow)'),
    statCard(dl.done_tasks||0,'Task hoàn thành','','var(--green)'),
    statCard(dl.error_tasks||0,'Task lỗi','','var(--red)'),
    statCard(dl.active_batches||0,'Batch đang chạy','','var(--purple)'),
    statCard(dl.done_batches||0,'Batch hoàn thành','','var(--blue)'),
    statCard(dl.guest_today||0,'Guest tải hôm nay','','var(--cyan)'),
  ].join('');
}

function renderCharts(v){
  document.getElementById('chartPanels').innerHTML = `
    <div class="panel"><div class="ph">📱 Thiết bị</div><div class="pb">${barChart(v.devices)}</div></div>
    <div class="panel"><div class="ph">🌐 Trình duyệt</div><div class="pb">${barChart(v.browsers)}</div></div>
    <div class="panel"><div class="ph">🖥 Hệ điều hành</div><div class="pb">${barChart(v.os)}</div></div>
    <div class="panel"><div class="ph">🌍 Quốc gia</div><div class="pb">${barChart(v.countries)}</div></div>`;
}

function renderStorage(s){
  const rows = s.users||[];
  document.getElementById('tbStorage').innerHTML = rows.length ? rows.map((r,i)=>{
    const pct = r.unlimited ? 0 : r.quota_gb>0 ? Math.min(100,Math.round(r.used_mb/(r.quota_gb*1024)*100)) : 0;
    const c   = pctColor(pct);
    return `<tr>
      <td style="color:var(--muted)">${i+1}</td>
      <td><b>${esc(r.username)}</b></td>
      <td><span class="badge badge-${r.role==='admin'?'admin':'user'}">${r.role}</span></td>
      <td>${r.used_mb} MB</td>
      <td>${r.unlimited?'∞ Không giới hạn':r.quota_gb+' GB'}</td>
      <td>${r.file_count}</td>
      <td style="min-width:80px">
        <div style="font-size:.68rem;color:${c};font-weight:800;margin-bottom:2px">${r.unlimited?'Admin':''+pct+'%'}</div>
        <div class="pb-track"><div class="pb-fill" style="width:${pct}%;background:${c}"></div></div>
      </td>
    </tr>`;
  }).join('') : `<tr><td colspan="7" class="empty-txt">Chưa có dữ liệu</td></tr>`;
}

function renderUsers(u){
  const list = u.list||[];
  document.getElementById('tbUsers').innerHTML = list.length ? list.map((r,i)=>{
    const lockBadge = r.locked ? `<span class="badge badge-lock">Khoá</span>` : `<span class="badge badge-ok">Hoạt động</span>`;
    const created  = (r.created_at||'').substring(0,10);
    return `<tr>
      <td style="color:var(--muted)">${i+1}</td>
      <td><b>${esc(r.username)}</b></td>
      <td><span class="badge badge-${r.role==='admin'?'admin':'user'}">${r.role}</span></td>
      <td>${lockBadge}</td>
      <td style="color:var(--muted)">${created||'—'}</td>
      <td>${r.file_count}</td>
      <td>${r.used_mb} MB / ${r.unlimited?'∞':r.quota_gb+' GB'}</td>
    </tr>`;
  }).join('') : `<tr><td colspan="7" class="empty-txt">Chưa có dữ liệu</td></tr>`;
}

function renderVisitors(v){
  const list = v.recent||[];
  if(!list.length){document.getElementById('visitorList').innerHTML='<div class="empty-txt">Chưa có visitor nào</div>';return;}
  document.getElementById('visitorList').innerHTML = list.map(r=>{
    const ipMask = (r.ip||'?').replace(/(\\.\\d+)$/, '.***');
    const devBadge = r.device==='Mobile' ? `<span class="badge badge-mobile">📱 ${r.device}</span>` : `<span class="badge badge-desk">🖥 ${r.device}</span>`;
    const loc = [r.city,r.country].filter(x=>x&&x!=='—').join(', ')||'—';
    return `<div class="vis-row">
      <span class="vis-ip">${esc(ipMask)}</span>
      ${devBadge}
      <span style="color:var(--muted)">${esc(r.os)}</span>
      <span style="color:var(--muted)">${esc(r.browser)}</span>
      <span>🌍 ${esc(loc)}</span>
      ${r.isp&&r.isp!=='—'?`<span style="color:var(--muted);font-size:.68rem">${esc(r.isp.substring(0,25))}</span>`:''}
      <span class="vis-cnt">×${r.visit_count||1}</span>
      <span style="color:var(--muted);font-size:.68rem;margin-left:auto">${(r.last_seen||'').substring(0,16)}</span>
    </div>`;
  }).join('');
}

async function doLogout(){
  try{await fetch('/api/auth/logout',{method:'POST',credentials:'include'});}catch(_){}
  window.location.href='/';
}

// ── Realtime clock ────────────────────────────────────────────────────────────
setInterval(() => {
  const e = document.getElementById('hdrTime');
  if (e && !e.dataset.sseUpdating) {
    const n = new Date();
    e.textContent = n.toLocaleTimeString('vi-VN', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
}, 1000);

// ── SSE realtime update (light stats mỗi 5s) ──────────────────────────────────
let _sseEs = null;
let _sseRetries = 0;

function connectSSE() {
  if (_sseEs) { try { _sseEs.close(); } catch(_) {} }
  _sseEs = new EventSource('/api/admin/dashboard_stream', { withCredentials: true });

  _sseEs.onopen = () => {
    _sseRetries = 0;
    document.getElementById('liveDot').style.background = 'var(--green)';
    document.getElementById('liveDot').title = 'SSE kết nối realtime';
  };

  _sseEs.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data);
      if (!d.ok) return;
      // Cập nhật nhẹ các số liệu thay đổi thường xuyên
      patchLiveStats(d);
      // Cập nhật timestamp
      const tEl = document.getElementById('hdrTime');
      if (tEl) { tEl.textContent = 'Live: ' + (d.generated_at || ''); tEl.dataset.sseUpdating = '1'; }
    } catch(_) {}
  };

  _sseEs.onerror = () => {
    document.getElementById('liveDot').style.background = 'var(--red)';
    _sseEs.close(); _sseEs = null;
    _sseRetries++;
    // Exponential backoff: 5s, 10s, 20s, max 60s
    const delay = Math.min(5000 * Math.pow(2, _sseRetries - 1), 60000);
    setTimeout(connectSSE, delay);
  };
}

function patchLiveStats(d) {
  // Helper patch 1 card value
  const patch = (sel, val) => {
    const el = document.querySelector(sel);
    if (el) el.textContent = val;
  };

  // Overview cards — cập nhật các giá trị thay đổi realtime
  if (d.visitors) {
    patch('#overviewCards .sc:nth-child(1) .sc-val', fmtN(d.visitors.total_unique || 0));
    patch('#overviewCards .sc:nth-child(1) .sc-sub', 'Hôm nay: ' + (d.visitors.today || 0));
    patch('#overviewCards .sc:nth-child(2) .sc-val', fmtN(d.visitors.today || 0));
    patch('#overviewCards .sc:nth-child(2) .sc-sub', 'Tuần này: ' + (d.visitors.this_week || 0));
  }
  if (d.users) {
    patch('#overviewCards .sc:nth-child(3) .sc-val', fmtN(d.users.total || 0));
    patch('#overviewCards .sc:nth-child(3) .sc-sub', 'Admin ' + (d.users.admin||0) + ' · Khoá ' + (d.users.locked||0));
  }
  if (d.storage) {
    patch('#overviewCards .sc:nth-child(4) .sc-val', (d.storage.total_used_gb||0).toFixed(2) + ' GB');
  }
  if (d.uptime) {
    patch('#overviewCards .sc:nth-child(5) .sc-val', d.uptime);
  }
  if (d.system && (d.system.cpu_percent !== undefined)) {
    const cpuPct = d.system.cpu_percent || 0;
    const cpuEl  = document.querySelector('#overviewCards .sc:nth-child(8) .sc-val');
    if (cpuEl) { cpuEl.textContent = cpuPct + '%'; cpuEl.style.color = pctColor(cpuPct); }
    // CPU & RAM progress bars (nếu đang hiển thị hwPanels)
    const fills = document.querySelectorAll('.pb-fill');
    if (fills.length >= 2) {
      fills[0].style.width = cpuPct + '%';
      fills[0].style.background = pctColor(cpuPct);
      if (d.system.mem_percent !== undefined) {
        fills[1].style.width = (d.system.mem_percent || 0) + '%';
        fills[1].style.background = pctColor(d.system.mem_percent || 0);
      }
    }
  }
  // Download stats cards
  if (d.downloads) {
    const dl = d.downloads;
    patch('#dlCards .sc:nth-child(1) .sc-val', dl.active_tasks || 0);
    patch('#dlCards .sc:nth-child(2) .sc-val', dl.done_tasks || 0);
    patch('#dlCards .sc:nth-child(3) .sc-val', dl.error_tasks || 0);
    patch('#dlCards .sc:nth-child(4) .sc-val', dl.active_batches || 0);
    patch('#dlCards .sc:nth-child(5) .sc-val', dl.done_batches || 0);
    patch('#dlCards .sc:nth-child(6) .sc-val', dl.guest_today || 0);
    // Live header counters
    const lat = document.getElementById('liveActiveTasks');
    const lab = document.getElementById('liveActiveBatches');
    if (lat) { lat.textContent = dl.active_tasks || 0; lat.style.color = dl.active_tasks > 0 ? 'var(--yellow)' : 'var(--muted)'; }
    if (lab) { lab.textContent = dl.active_batches || 0; lab.style.color = dl.active_batches > 0 ? 'var(--purple)' : 'var(--muted)'; }
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Load đầy đủ 1 lần khi mở
  loadData().then(() => {
    // Sau khi load xong → kết nối SSE để cập nhật realtime
    connectSSE();
  });
  // Refresh đầy đủ mỗi 2 phút (để cập nhật visitor list, storage, etc.)
  setInterval(loadData, 120000);
});
</script>
</body>
</html>
"""


@app.route('/dashboard')
def dashboard_page():
    """Trang dashboard thống kê — chỉ admin."""
    if not is_admin():
        return redirect('/')
    return Response(_DASHBOARD_HTML, mimetype='text/html')



@app.route('/api/admin/dashboard_stats', methods=['GET'])
@require_admin
def admin_dashboard_stats():
    """Trả về toàn bộ số liệu THỰC TẾ cho trang dashboard admin."""
    import platform as _platform

    # ── Users ────────────────────────────────────────────────────────────────
    with _users_rw_lock:
        db = _load_users_db()
    users        = db['users']
    total_users  = len(users)
    admin_count  = sum(1 for u in users.values() if u.get('role') == 'admin')
    locked_count = sum(1 for u in users.values() if u.get('locked'))
    today        = datetime.now().strftime('%Y-%m-%d')
    guest_dl     = db.get('guest_downloads', {})
    guest_today  = sum(r.get('count', 0) for r in guest_dl.values() if r.get('date') == today)

    # ── Visitors ─────────────────────────────────────────────────────────────
    with _visitors_lock:
        visitors_raw = _load_visitors()
    total_unique = len(visitors_raw)
    today_count  = sum(1 for v in visitors_raw.values() if v.get('last_seen', '').startswith(today))
    week_ago     = (datetime.now() - __import__('datetime').timedelta(days=7)).strftime('%Y-%m-%d')
    week_count   = sum(1 for v in visitors_raw.values() if v.get('last_seen', '') >= week_ago)

    devices = {}; browsers = {}; os_stats = {}; countries = {}
    for v in visitors_raw.values():
        for d, key in [(devices,'device'),(browsers,'browser'),(os_stats,'os')]:
            k = v.get(key,'Unknown') or 'Unknown'
            d[k] = d.get(k,0) + 1
        c = v.get('location',{}).get('country','Unknown') or 'Unknown'
        countries[c] = countries.get(c,0) + 1

    recent_visitors = sorted(visitors_raw.values(), key=lambda x: x.get('last_seen_ts',0), reverse=True)[:20]
    safe_recent = [{
        'ip':          _v.get('ip','?'),
        'device':      _v.get('device','?'),
        'os':          _v.get('os','?'),
        'browser':     _v.get('browser','?'),
        'country':     _v.get('location',{}).get('country','—'),
        'city':        _v.get('location',{}).get('city','—'),
        'isp':         _v.get('location',{}).get('isp','—'),
        'last_seen':   _v.get('last_seen',''),
        'first_seen':  _v.get('first_seen',''),
        'visit_count': _v.get('visit_count',1),
    } for _v in recent_visitors]

    # ── Storage ───────────────────────────────────────────────────────────────
    storage_rows = []
    for uname, udata in users.items():
        used  = get_user_storage_used(uname)
        quota = get_user_quota_bytes(uname)
        flist = list_user_storage_files(uname)
        storage_rows.append({
            'username':    uname,
            'role':        udata.get('role','user'),
            'used_bytes':  used,
            'used_mb':     round(used/1024**2, 1),
            'quota_gb':    round(quota/1024**3, 1),
            'file_count':  len(flist),
            'unlimited':   quota >= _ADMIN_QUOTA_BYTES,
            'locked':      bool(udata.get('locked')),
            'created_at':  udata.get('created_at',''),
        })
    storage_rows.sort(key=lambda x: -x['used_bytes'])
    total_storage_bytes = sum(r['used_bytes'] for r in storage_rows)

    # ── Active tasks/batches ──────────────────────────────────────────────────
    active_tasks   = sum(1 for t in TASK_STORE.values() if t.get('status') in ('pending','running'))
    done_tasks     = sum(1 for t in TASK_STORE.values() if t.get('status') == 'done')
    error_tasks    = sum(1 for t in TASK_STORE.values() if t.get('status') == 'error')
    with _batch_lock:
        active_batches = sum(1 for j in BATCH_STORE.values() if not j.is_done and not j.cancelled)
        done_batches   = sum(1 for j in BATCH_STORE.values() if j.is_done)

    # ── Server / System info (THỰC TẾ) ────────────────────────────────────────
    sys_info = {}
    net_info = {}
    proc_info = {}
    try:
        import psutil as _ps

        # CPU
        cpu_pct     = _ps.cpu_percent(interval=0.2)
        cpu_each    = _ps.cpu_percent(percpu=True)
        cpu_count_l = _ps.cpu_count(logical=True)
        cpu_count_p = _ps.cpu_count(logical=False) or cpu_count_l
        cpu_freq    = _ps.cpu_freq()
        cpu_times   = _ps.cpu_times()

        # RAM
        mem  = _ps.virtual_memory()
        swap = _ps.swap_memory()

        # Disk
        disk = _ps.disk_usage('/')
        disk_parts = []
        try:
            for part in _ps.disk_partitions(all=False):
                try:
                    du = _ps.disk_usage(part.mountpoint)
                    disk_parts.append({
                        'mount': part.mountpoint,
                        'fs':    part.fstype,
                        'total_gb': round(du.total/1024**3,1),
                        'used_gb':  round(du.used/1024**3,1),
                        'pct':      round(du.percent,1),
                    })
                except Exception:
                    pass
        except Exception:
            pass

        # Network
        net = _ps.net_io_counters()
        net_if = {}
        try:
            for iface, stats in _ps.net_io_counters(pernic=True).items():
                if stats.bytes_sent + stats.bytes_recv > 0:
                    net_if[iface] = {
                        'sent_mb': round(stats.bytes_sent/1024**2,1),
                        'recv_mb': round(stats.bytes_recv/1024**2,1),
                    }
        except Exception:
            pass

        # Boot time / uptime hệ thống
        boot_ts  = _ps.boot_time()
        sys_up   = int(time.time() - boot_ts)

        # Processes
        proc_count = len(_ps.pids())
        try:
            top_procs = []
            for p in _ps.process_iter(['pid','name','cpu_percent','memory_percent','status']):
                try:
                    if p.info['cpu_percent'] is not None:
                        top_procs.append(p.info)
                except Exception:
                    pass
            top_procs.sort(key=lambda x: (x.get('cpu_percent') or 0), reverse=True)
            proc_info = {
                'count': proc_count,
                'top_cpu': top_procs[:5],
            }
        except Exception:
            proc_info = {'count': proc_count, 'top_cpu': []}

        # Temperature
        temps = {}
        try:
            for name, entries in (_ps.sensors_temperatures() or {}).items():
                for e in entries:
                    if e.current:
                        temps[e.label or name] = round(e.current, 1)
        except Exception:
            pass

        sys_info = {
            # CPU
            'cpu_percent':   round(cpu_pct, 1),
            'cpu_per_core':  [round(c,1) for c in cpu_each],
            'cpu_cores_log': cpu_count_l,
            'cpu_cores_phy': cpu_count_p,
            'cpu_freq_mhz':  round(cpu_freq.current,0) if cpu_freq else 0,
            'cpu_user':      round(cpu_times.user,1),
            'cpu_system':    round(cpu_times.system,1),
            'cpu_idle':      round(cpu_times.idle,1),
            # RAM
            'mem_total_gb':  round(mem.total/1024**3,2),
            'mem_used_gb':   round(mem.used/1024**3,2),
            'mem_free_gb':   round(mem.available/1024**3,2),
            'mem_percent':   round(mem.percent,1),
            'mem_buffers_mb':round(getattr(mem,'buffers',0)/1024**2,1),
            'mem_cached_mb': round(getattr(mem,'cached',0)/1024**2,1),
            # Swap
            'swap_total_gb': round(swap.total/1024**3,2),
            'swap_used_gb':  round(swap.used/1024**3,2),
            'swap_percent':  round(swap.percent,1),
            # Disk root
            'disk_total_gb': round(disk.total/1024**3,1),
            'disk_used_gb':  round(disk.used/1024**3,1),
            'disk_free_gb':  round(disk.free/1024**3,1),
            'disk_percent':  round(disk.percent,1),
            'disk_parts':    disk_parts,
            # Net
            'net_sent_mb':   round(net.bytes_sent/1024**2,1),
            'net_recv_mb':   round(net.bytes_recv/1024**2,1),
            'net_pkts_sent': net.packets_sent,
            'net_pkts_recv': net.packets_recv,
            'net_ifaces':    net_if,
            # Uptime
            'sys_uptime_sec':  sys_up,
            'sys_uptime_str':  f"{sys_up//3600}h {(sys_up%3600)//60}m",
            'boot_time':       datetime.fromtimestamp(boot_ts).strftime('%Y-%m-%d %H:%M:%S'),
            # Temperature
            'temps': temps,
        }
    except Exception as _e_sys:
        sys_info = {'error': str(_e_sys)}

    # ── Platform info ─────────────────────────────────────────────────────────
    platform_info = {
        'os':        _platform.system(),
        'release':   _platform.release(),
        'version':   _platform.version()[:80],
        'machine':   _platform.machine(),
        'processor': _platform.processor()[:60] or _platform.machine(),
        'python':    _platform.python_version(),
        'hostname':  _platform.node(),
    }
    try:
        import socket as _sock
        platform_info['ip_local'] = _get_local_ip()
    except Exception:
        pass

    # ── Flask / App info ──────────────────────────────────────────────────────
    app_uptime_sec = int(time.time() - _SERVER_START_TIME)
    app_info = {
        'uptime_sec': app_uptime_sec,
        'uptime_str': f"{app_uptime_sec//3600}h {(app_uptime_sec%3600)//60}m {app_uptime_sec%60}s",
        'started_at': datetime.fromtimestamp(_SERVER_START_TIME).strftime('%Y-%m-%d %H:%M:%S'),
        'port':       2110,
        'ffmpeg':     FFMPEG_AVAILABLE,
        'encoder':    HW_ENCODER,
        'yt_dlp':     YT_DLP_AVAILABLE,
        'cookies':    len(COOKIES_DICT),
        'task_store': len(TASK_STORE),
        'batch_store':len(BATCH_STORE),
    }

    return jsonify({
        'ok':           True,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'generated_ts': time.time(),
        'users': {
            'total':   total_users,
            'admin':   admin_count,
            'regular': total_users - admin_count,
            'locked':  locked_count,
            'list':    storage_rows,   # reuse for user table
        },
        'visitors': {
            'total_unique': total_unique,
            'today':        today_count,
            'this_week':    week_count,
            'devices':      devices,
            'browsers':     browsers,
            'os':           os_stats,
            'countries':    dict(sorted(countries.items(), key=lambda x: -x[1])[:15]),
            'recent':       safe_recent,
        },
        'downloads': {
            'guest_today':    guest_today,
            'active_tasks':   active_tasks,
            'done_tasks':     done_tasks,
            'error_tasks':    error_tasks,
            'active_batches': active_batches,
            'done_batches':   done_batches,
        },
        'storage': {
            'users':            storage_rows,
            'total_used_bytes': total_storage_bytes,
            'total_used_gb':    round(total_storage_bytes/1024**3, 3),
        },
        'system':   sys_info,
        'platform': platform_info,
        'app':      app_info,
        'proc':     proc_info,
    })


@app.route('/api/admin/dashboard_stream')
@require_admin
def admin_dashboard_stream():
    """SSE endpoint — đẩy stats realtime mỗi 5 giây cho Dashboard admin."""
    import platform as _platform

    def _build_stats():
        """Gọi lại logic tương tự admin_dashboard_stats nhưng nhẹ hơn (bỏ visitor detail)."""
        try:
            with _users_rw_lock:
                db = _load_users_db()
            users       = db['users']
            today       = datetime.now().strftime('%Y-%m-%d')
            guest_dl    = db.get('guest_downloads', {})
            guest_today = sum(r.get('count', 0) for r in guest_dl.values() if r.get('date') == today)
            total_users  = len(users)
            admin_count  = sum(1 for u in users.values() if u.get('role') == 'admin')
            locked_count = sum(1 for u in users.values() if u.get('locked'))

            with _visitors_lock:
                visitors_raw = _load_visitors()
            total_unique = len(visitors_raw)
            today_count  = sum(1 for v in visitors_raw.values() if v.get('last_seen', '').startswith(today))
            week_ago     = (datetime.now() - __import__('datetime').timedelta(days=7)).strftime('%Y-%m-%d')
            week_count   = sum(1 for v in visitors_raw.values() if v.get('last_seen', '') >= week_ago)

            active_tasks   = sum(1 for t in TASK_STORE.values() if t.get('status') in ('pending','running'))
            done_tasks     = sum(1 for t in TASK_STORE.values() if t.get('status') == 'done')
            error_tasks    = sum(1 for t in TASK_STORE.values() if t.get('status') == 'error')
            with _batch_lock:
                active_batches = sum(1 for j in BATCH_STORE.values() if not j.is_done and not j.cancelled)
                done_batches   = sum(1 for j in BATCH_STORE.values() if j.is_done)

            # Lightweight sys stats
            sys_snap = {}
            try:
                import psutil as _ps
                sys_snap = {
                    'cpu_percent': _ps.cpu_percent(interval=0.1),
                    'mem_percent': _ps.virtual_memory().percent,
                    'mem_used_gb': round(_ps.virtual_memory().used / 1024**3, 2),
                    'mem_total_gb': round(_ps.virtual_memory().total / 1024**3, 2),
                    'disk_percent': _ps.disk_usage('/').percent,
                }
            except Exception:
                pass

            uptime_sec = int(time.time() - _SERVER_START_TIME)
            h, rem = divmod(uptime_sec, 3600)
            m, s   = divmod(rem, 60)
            uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

            total_storage_bytes = sum(
                get_user_storage_used(u) for u in users
            )

            return {
                'ok': True,
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'users':     {'total': total_users, 'admin': admin_count, 'locked': locked_count},
                'visitors':  {'total_unique': total_unique, 'today': today_count, 'this_week': week_count},
                'downloads': {
                    'guest_today': guest_today,
                    'active_tasks': active_tasks, 'done_tasks': done_tasks, 'error_tasks': error_tasks,
                    'active_batches': active_batches, 'done_batches': done_batches,
                },
                'storage':   {'total_used_gb': round(total_storage_bytes / 1024**3, 3)},
                'system':    sys_snap,
                'uptime':    uptime_str,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def _generate():
        # Ping đầu tiên ngay lập tức
        try:
            data = _build_stats()
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'ok': False, 'error': str(e)})}\n\n"

        # Sau đó đẩy mỗi 3 giây để realtime hơn
        while True:
            time.sleep(3)
            try:
                data = _build_stats()
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: {json.dumps({'ok': False, 'error': str(e)})}\n\n"

    resp = Response(
        stream_with_context(_generate()),
        mimetype='text/event-stream'
    )
    resp.headers['Cache-Control']     = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    resp.headers['Connection']        = 'keep-alive'
    return resp




# ── SERVER-SIDE QUEUE PERSISTENCE ────────────────────────────────────────────
# Lưu trạng thái queue của user vào server để khi browser đóng vẫn tiếp tục
_SERVER_QUEUE_STORE = {}   # username → [{'urls': [...], 'name': str, 'status': str}]
_sq_lock = threading.Lock()

@app.route('/api/queue/save', methods=['POST'])
@require_logged_in
def queue_save():
    """Lưu toàn bộ hàng chờ lên server (gọi khi thêm item hoặc trước khi đóng)."""
    username = session.get('username')
    data     = request.get_json(force=True) or {}
    items    = data.get('items', [])  # [{name, urls[], status}]
    with _sq_lock:
        _SERVER_QUEUE_STORE[username] = [
            {'name': str(it.get('name','')), 'urls': list(it.get('urls',[])), 
             'status': str(it.get('status','pending'))}
            for it in items if it.get('urls')
        ]
    return jsonify({'ok': True, 'saved': len(items)})

@app.route('/api/queue/load', methods=['GET'])
@require_logged_in
def queue_load():
    """Lấy lại hàng chờ đã lưu khi browser mở lại."""
    username = session.get('username')
    with _sq_lock:
        items = _SERVER_QUEUE_STORE.get(username, [])
    return jsonify({'ok': True, 'items': items})

@app.route('/api/queue/clear', methods=['POST'])
@require_logged_in
def queue_clear():
    """Xóa hàng chờ server sau khi đã xử lý xong."""
    username = session.get('username')
    with _sq_lock:
        _SERVER_QUEUE_STORE.pop(username, None)
    return jsonify({'ok': True})

@app.route('/api/queue/run_all', methods=['POST'])
@require_logged_in
def queue_run_all():
    """
    Nhận toàn bộ pending items trong queue, đăng ký tất cả thành batch_start
    với save_to_storage=True (background persist). Server tự xử lý tuần tự
    ngay cả khi browser đóng.
    """
    username = session.get('username')
    data     = request.get_json(force=True) or {}
    items    = data.get('items', [])   # [{name, urls[]}]
    audio    = data.get('audio', True)
    logo_params = data.get('logo_params', {'enabled': False})
    group_prefix = data.get('group_prefix', '')
    folder_id    = data.get('folder_id', '')

    if not username:
        return jsonify({'error': 'Cần đăng nhập'}), 401
    if not items:
        return jsonify({'error': 'Không có items'}), 400

    batch_ids = []
    for it in items:
        urls = [u for u in it.get('urls', []) if is_valid_tiktok_url(u)]
        if not urls:
            continue
        _bid = hashlib.md5(
            f"persist_{username}{''.join(urls)}{time.time()}{random.random()}".encode()
        ).hexdigest()
        _gname    = it.get('name', group_prefix)
        _fid      = it.get('folder_id', folder_id)
        job = BatchJob(_bid, urls, audio, logo_params,
                       owner=username,
                       save_to_storage=True,
                       download_direct=True,
                       group_name=_gname,
                       folder_id=_fid)
        with _batch_lock:
            BATCH_STORE[_bid] = job
        job.start()
        batch_ids.append({'batch_id': _bid, 'name': _gname, 'total': len(urls)})

    with _sq_lock:
        _SERVER_QUEUE_STORE[username] = []

    _log('info', f'[queue_run_all] {username}: {len(batch_ids)} batches submitted')
    return jsonify({'ok': True, 'batches': batch_ids, 'count': len(batch_ids)})


# ══════════════════════════════════════════════════════════════════════════════
# 🔒 BACKGROUND PERSIST — Lưu toàn bộ link vào file, xử lý dù browser đóng
# Khi user bắt đầu tải → gửi TẤT CẢ links (cả queue) lên server → lưu file
# Server đọc file lần lượt → xử lý → dù client mất kết nối vẫn tiếp tục
# ══════════════════════════════════════════════════════════════════════════════
_PERSIST_DIR = os.path.join(_BASE_DIR, 'pending_persist')
os.makedirs(_PERSIST_DIR, exist_ok=True)
_persist_lock = threading.Lock()


@app.route('/api/persist/submit', methods=['POST'])
@require_logged_in
def persist_submit():
    """
    CHECKPOINT-ONLY: Lưu danh sách URL vào file checkpoint.
    KHÔNG chạy batch (tránh xử lý trùng với batch_start).
    Nếu browser đóng giữa chừng, /api/persist/resume sẽ khởi động lại.
    """
    username = session.get('username')
    data     = request.get_json(force=True) or {}
    groups   = data.get('groups', [])
    if not groups:
        return jsonify({'ok': True, 'submitted': [], 'count': 0})

    submitted = []
    ts_base = int(time.time() * 1000)
    for idx, grp in enumerate(groups):
        urls = [u for u in grp.get('urls', []) if is_valid_tiktok_url(u)]
        if not urls:
            continue
        pid   = hashlib.md5(f"ckpt_{username}_{ts_base}_{idx}".encode()).hexdigest()[:16]
        fpath = os.path.join(_PERSIST_DIR, f'{pid}.json')
        record = {
            'pid':             pid,
            'username':        username,
            'name':            grp.get('name', f'Lô {idx+1}'),
            'urls':            urls,
            'audio':           grp.get('audio', True),
            'logo_params':     grp.get('logo_params', {'enabled': False}),
            'folder_id':       grp.get('folder_id', ''),
            'download_direct': grp.get('download_direct', True),
            'save_to_storage': grp.get('save_to_storage', True),
            'created_at':      ts_base,
            'status':          'pending',   # chờ — batch_start sẽ xử lý
            'batch_id':        None,
        }
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(record, f)
        submitted.append({'pid': pid, 'name': record['name'], 'total': len(urls)})

    return jsonify({'ok': True, 'submitted': submitted, 'count': len(submitted)})


@app.route('/api/persist/mark_done', methods=['POST'])
@require_logged_in
def persist_mark_done():
    """Đánh dấu checkpoint đã hoàn thành (gọi sau khi batch_start xong)."""
    username = session.get('username')
    data  = request.get_json(force=True) or {}
    pids  = data.get('pids', [])
    for pid in pids:
        fpath = os.path.join(_PERSIST_DIR, f'{pid}.json')
        try:
            if os.path.exists(fpath):
                with open(fpath, 'r') as f: rec = json.load(f)
                if rec.get('username') == username:
                    rec['status'] = 'done'
                    with open(fpath, 'w') as f: json.dump(rec, f)
        except: pass
    return jsonify({'ok': True})


@app.route('/api/persist/resume', methods=['POST'])
@require_logged_in
def persist_resume():
    """
    Khi user quay lại web sau khi đóng browser:
    Kiểm tra checkpoint files còn 'pending' → chạy lại các batch chưa hoàn thành.
    """
    username = session.get('username')
    resumed  = []
    try:
        for fn in os.listdir(_PERSIST_DIR):
            if not fn.endswith('.json'): continue
            fp = os.path.join(_PERSIST_DIR, fn)
            try:
                with open(fp, 'r') as f: rec = json.load(f)
                if rec.get('username') != username: continue
                if rec.get('status') != 'pending':  continue
                # Còn pending → resume bằng cách tạo batch mới
                urls = [u for u in rec.get('urls', []) if is_valid_tiktok_url(u)]
                if not urls: continue
                _bid = hashlib.md5(f"resume_{rec['pid']}{time.time()}".encode()).hexdigest()
                job  = BatchJob(_bid, urls, rec.get('audio', True), rec.get('logo_params', {}),
                                owner=username,
                                save_to_storage=rec.get('save_to_storage', True),
                                download_direct=False,   # resume: chỉ lưu kho, không download
                                group_name=f"[Resume] {rec.get('name','')}",
                                folder_id=rec.get('folder_id', ''))
                with _batch_lock:
                    BATCH_STORE[_bid] = job
                rec['status']   = 'running'
                rec['batch_id'] = _bid
                with open(fp, 'w') as f: json.dump(rec, f)

                def _finish_resume(j, fp2, rec2):
                    j.start(); j._thread.join()
                    rec2['status'] = 'done'
                    with open(fp2, 'w') as f2: json.dump(rec2, f2)

                threading.Thread(target=_finish_resume, args=(job, fp, rec), daemon=True).start()
                resumed.append({'pid': rec['pid'], 'batch_id': _bid, 'total': len(urls)})
            except: pass
    except: pass
    return jsonify({'ok': True, 'resumed': resumed, 'count': len(resumed)})


@app.route('/api/persist/status', methods=['GET'])
@require_logged_in
def persist_status():
    """Trả về danh sách pending/running persist tasks của user."""
    username = session.get('username')
    result   = []
    try:
        for fn in os.listdir(_PERSIST_DIR):
            if not fn.endswith('.json'):
                continue
            fp = os.path.join(_PERSIST_DIR, fn)
            try:
                with open(fp, 'r') as f:
                    rec = json.load(f)
                if rec.get('username') == username:
                    result.append({
                        'pid':      rec.get('pid'),
                        'name':     rec.get('name'),
                        'status':   rec.get('status'),
                        'total':    len(rec.get('urls', [])),
                        'batch_id': rec.get('batch_id'),
                    })
            except: pass
    except: pass
    return jsonify({'ok': True, 'tasks': result})

# ── 🟡 Claude D: /sw.js — Service Worker phục vụ trực tiếp từ Flask ──────────
# Thay vì dùng Blob URL (bị chặn vì protocol 'blob-request://' không hợp lệ),
# SW được serve từ /sw.js với Content-Type đúng và scope '/' hợp lệ.
_SW_JS_CODE = r"""
// TikDown Turbo — Service Worker v2.0
// Phục vụ bởi Flask tại /sw.js (không dùng Blob URL)

const POLL_INTERVAL = 3000;
let _monitoredTasks = new Map();
let _pollTimer = null;

self.addEventListener('message', (event) => {
    const { type, taskId, batchId } = event.data || {};
    if (type === 'MONITOR_TASK' && taskId) {
        _monitoredTasks.set(taskId, { type: 'task', ts: Date.now() });
        startPolling();
    }
    if (type === 'MONITOR_BATCH' && batchId) {
        _monitoredTasks.set(batchId, { type: 'batch', ts: Date.now() });
        startPolling();
    }
    if (type === 'UNMONITOR' && taskId) { _monitoredTasks.delete(taskId); }
    if (type === 'UNMONITOR_BATCH' && batchId) { _monitoredTasks.delete(batchId); }
    if (type === 'CLEAR_ALL') { _monitoredTasks.clear(); stopPolling(); }
});

function startPolling() {
    if (_pollTimer) return;
    _pollTimer = setInterval(pollTasks, POLL_INTERVAL);
}
function stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

async function pollTasks() {
    if (_monitoredTasks.size === 0) { stopPolling(); return; }
    const toRemove = [];
    for (const [id, meta] of _monitoredTasks) {
        if (Date.now() - meta.ts > 30 * 60 * 1000) { toRemove.push(id); continue; }
        try {
            if (meta.type === 'task') {
                const r = await fetch('/api/task_status/' + id, { cache: 'no-store' });
                if (r.status === 404) { toRemove.push(id); continue; }
                const data = await r.json();
                if (data.status === 'done' || data.status === 'error') {
                    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
                    for (const c of clients) c.postMessage({ type: 'TASK_RESULT', taskId: id, status: data.status, filename: data.filename || '', title: data.title || '' });
                    if (data.status === 'done') {
                        try { await self.registration.showNotification('TikDown ✅ Tải xong!', { body: data.title ? ('📹 ' + data.title.slice(0, 40)) : '✅ Video đã sẵn sàng', icon: '/image/2.ico', tag: 'tikdown-' + id }); } catch(e) {}
                    }
                    toRemove.push(id);
                }
            } else if (meta.type === 'batch') {
                const r = await fetch('/api/batch_status/' + id + '?since=0', { cache: 'no-store' });
                if (r.status === 404) { toRemove.push(id); continue; }
                const data = await r.json();
                if (data.is_done) {
                    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
                    for (const c of clients) c.postMessage({ type: 'BATCH_RESULT', batchId: id, ok: data.ok || 0, total: data.total || 0 });
                    try { await self.registration.showNotification('TikDown ✅ Batch xong!', { body: '✅ ' + (data.ok || 0) + '/' + (data.total || 0) + ' video đã tải xong', icon: '/image/2.ico', tag: 'tikdown-batch-' + id }); } catch(e) {}
                    toRemove.push(id);
                }
            }
        } catch(e) {}
    }
    for (const id of toRemove) _monitoredTasks.delete(id);
    if (_monitoredTasks.size === 0) stopPolling();
}

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
        if (clients.length > 0) { clients[0].focus(); return; }
        return self.clients.openWindow('/');
    }));
});

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
"""

@app.route('/sw.js')
def serve_sw():
    """Serve Service Worker JS — tránh lỗi blob-request:// protocol not supported."""
    from flask import make_response
    resp = make_response(_SW_JS_CODE.strip())
    resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp


# ── MỚI: Tạo task download async ─────────────────────────────────────────────
@app.route('/api/download_async', methods=['POST'])
def download_async():
    """
    POST body: {url, audio, logo_enabled, logo_base64, logo_x, logo_y, logo_width, logo_height}
    Trả về ngay: {task_id}
    Client sau đó kết nối GET /api/stream/<task_id> để nhận SSE realtime.
    """
    data = request.get_json(force=True) or {}
    url  = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'Missing URL'}), 400
    if not is_valid_tiktok_url(url):
        return jsonify({'error': 'Invalid TikTok URL'}), 400

    audio_param = data.get('audio', True)
    audio = audio_param in [True, 'true', '1', 'yes']

    logo_enabled = bool(data.get('logo_enabled', False))

    # ── KIỂM TRA QUYỀN ────────────────────────────────────────────────────────
    allowed, err_msg, err_code = _check_download_permission(
        audio=audio, logo_enabled=logo_enabled, is_batch=False
    )
    if not allowed:
        return jsonify({'error': err_msg, 'code': err_code}), 403

    # Ghi nhận download của guest
    if get_current_role() == 'guest':
        guest_record_download(_get_client_ip())

    logo_params = {
        'enabled':    data.get('logo_enabled', False),
        'logo_base64': data.get('logo_base64', ''),
        'x':          data.get('logo_x', 0),
        'y':          data.get('logo_y', 0),
        'width':      data.get('logo_width',  100),
        'height':     data.get('logo_height', 100),
        'original_aspect': data.get('logo_original_aspect', None),
    }
    _asp = logo_params.get('original_aspect')
    if _asp and isinstance(_asp, (int, float)) and _asp > 0:
        logo_params['height'] = round(logo_params['width'] * _asp)

    # ── Chế độ lưu trữ (Dr. An) ──────────────────────────────────────────────
    # save_to_storage: True = lưu vào KHO của user sau khi tải
    # download_direct: True = gửi file về máy ngay
    # Mặc định (tương thích cũ): download_direct=True, save_to_storage=False
    save_to_storage  = bool(data.get('save_to_storage', False))
    download_direct  = bool(data.get('download_direct', True))
    group_id         = str(data.get('group_id', ''))
    group_name       = str(data.get('group_name', ''))
    folder_id        = str(data.get('folder_id', ''))   # ⚡ FIX: nhận folder_id từ client

    _owner = session.get('username') or ''

    # ── BACKGROUND PERSISTENCE: chỉ force save khi user chọn storage/both
    # Nếu user chọn direct → KHÔNG lưu kho, gửi thẳng về máy
    # Nếu user chọn storage/both → lưu kho (+ gửi về máy nếu both)
    # _bg_persist: True nếu đây là request từ queue server-side persist
    _bg_persist = bool(data.get('_bg_persist', False))
    if _owner and (save_to_storage or _bg_persist):
        save_to_storage = True   # giữ như cũ
    # download_direct: nếu chỉ lưu kho thì không cần giữ task_id cho client

    task_id = hashlib.md5(
        f"{url}{time.time()}{random.random()}".encode()
    ).hexdigest()

    with _task_lock:
        SSE_QUEUES[task_id]  = _queue_module.Queue(maxsize=200)
        TASK_STORE[task_id]  = {'status': 'pending', 'created_at': time.time(), 'url': url}

    _log('info', f'Task created: {task_id[:8]} | url={url[:60]} | owner={_owner or "guest"} | save={save_to_storage} direct={download_direct}', task_id)

    with _task_lock:
        TASK_STORE[task_id]['owner'] = _owner

    t = threading.Thread(
        target=_background_download,
        args=(task_id, url, audio, logo_params, _owner),
        kwargs={'save_to_storage': save_to_storage, 'download_direct': download_direct,
                'group_id': group_id, 'group_name': group_name, 'folder_id': folder_id},
        daemon=True
    )
    t.start()

    return jsonify({'task_id': task_id, 'status': 'pending', 'owner': _owner or None,
                    'save_to_storage': save_to_storage, 'download_direct': download_direct})


# ── MỚI: SSE stream cho task ─────────────────────────────────────────────────
@app.route('/api/stream/<task_id>', methods=['GET'])
def stream_task(task_id):
    """
    SSE endpoint: mỗi sự kiện là 1 dòng JSON.
    event: status | done | error | heartbeat | _end
    """
    with _task_lock:
        exists = task_id in TASK_STORE
        if exists and task_id not in SSE_QUEUES:
            SSE_QUEUES[task_id] = _queue_module.Queue(maxsize=200)
        q = SSE_QUEUES.get(task_id)

    if not exists:
        return jsonify({'error': 'Task not found'}), 404

    def generate():
        # Kiểm tra ngay nếu task đã done/error trước khi client kết nối
        with _task_lock:
            stored = TASK_STORE.get(task_id, {})
        if stored.get('status') == 'done':
            info = stored.get('info', {})
            yield _sse('done', {
                'filename': stored.get('filename', ''),
                'size':     stored.get('size', 0),
                'title':    info.get('title', ''),
                'method':   info.get('method', ''),
                'task_id':  task_id,
                'url':      stored.get('url', ''),
            })
            return
        if stored.get('status') == 'error':
            yield _sse('error', {'msg': stored.get('error', 'Unknown error')})
            return

        # Stream sự kiện từ queue
        # 🔧 SPEED: giảm heartbeat 12s→3s, store_check 3s→1s → phản hồi nhanh hơn
        heartbeat_interval   = 3    # giây (cũ: 12)
        store_check_interval = 1    # kiểm tra TASK_STORE mỗi 1s (cũ: 3)
        last_hb    = time.time()
        last_check = time.time()
        while True:
            try:
                # 🔧 SPEED: timeout 1.0→0.3s → wake up nhanh hơn khi task xong
                evt = q.get(timeout=0.3)
                if evt['event'] == '_end':
                    break
                yield _sse(evt['event'], evt['data'])
                if evt['event'] in ('done', 'error'):
                    break
            except _queue_module.Empty:
                now = time.time()

                # ── Kiểm tra TASK_STORE định kỳ ─────────────────────────────
                # Đề phòng trường hợp event '_end' / 'done' bị drop (queue đầy)
                # khi client disconnect trước → reconnect lại.
                if now - last_check >= store_check_interval:
                    last_check = now
                    with _task_lock:
                        st = TASK_STORE.get(task_id, {})
                    status = st.get('status')
                    if status == 'done':
                        _info = st.get('info', {})
                        yield _sse('done', {
                            'filename': st.get('filename', ''),
                            'size':     st.get('size', 0),
                            'title':    _info.get('title', ''),
                            'method':   _info.get('method', ''),
                            'task_id':  task_id,
                            'url':      st.get('url', ''),
                        })
                        return
                    elif status == 'error':
                        yield _sse('error', {'msg': st.get('error', 'Unknown error')})
                        return
                    elif status not in ('pending', 'running', None):
                        # Unknown / cancelled — báo lỗi
                        yield _sse('error', {'msg': f'Task status: {status}'})
                        return

                # ── Heartbeat ────────────────────────────────────────────────
                if now - last_hb >= heartbeat_interval:
                    yield _sse('heartbeat', {'ts': now})
                    last_hb = now

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection':        'keep-alive',
            'Access-Control-Allow-Origin': '*',
        }
    )

def _sse(event: str, data: dict) -> str:
    """Format 1 SSE message."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── MỚI: Lấy file kết quả sau khi done ───────────────────────────────────────
@app.route('/api/get_result/<task_id>', methods=['GET'])
def get_result(task_id):
    """
    Phục vụ video tốc độ tối đa — mmap zero-copy streaming.
    Desktop 4MB chunks / Mobile 512KB / Safari probe 1-byte fast-path.
    """
    with _task_lock:
        task = TASK_STORE.get(task_id)

    if not task:
        return jsonify({'error': 'Task not found'}), 404
    if task['status'] == 'pending':
        return jsonify({'error': 'Task still processing', 'task_id': task_id}), 202
    if task['status'] == 'error':
        return jsonify({'error': task.get('error', 'Download failed')}), 500
    if task['status'] != 'done':
        return jsonify({'error': f'Unknown task status: {task["status"]}'}), 500

    result_path = task.get('result_path')
    filename    = task.get('filename', 'tiktok_video.mp4')

    if not result_path or not os.path.exists(result_path):
        return jsonify({'error': 'Result file missing — task may have expired'}), 404

    file_size = os.path.getsize(result_path)
    if file_size == 0:
        return jsonify({'error': 'Result file is empty'}), 500

    encoded_filename = quote(filename, safe='')   # RFC 5987 percent-encode
    # filename= phải ASCII-safe; filename*= mang Unicode qua RFC 5987
    _ascii_fn   = filename.encode('ascii', 'replace').decode('ascii')
    _content_disp = f'attachment; filename="{_ascii_fn}"; filename*=UTF-8\'\'{encoded_filename}'

    ua_str     = request.headers.get('User-Agent', '').lower()
    _is_mobile = any(k in ua_str for k in ('mobile', 'android', 'iphone', 'ipad'))
    _is_safari = 'safari' in ua_str and 'chrome' not in ua_str
    # ⚡ TURBO: chunk lớn hơn để đạt 50MB/s trên LAN/local
    if _is_safari:
        CHUNK = 1    * 1024*1024  # 1 MB — Safari buffer limit nới rộng
    elif _is_mobile:
        CHUNK = 2    * 1024*1024  # 2 MB — mobile
    elif file_size > 200 * 1024*1024:
        CHUNK = 64   * 1024*1024  # 64 MB — file rất lớn (>200MB)
    elif file_size > 50 * 1024*1024:
        CHUNK = 32   * 1024*1024  # 32 MB — file lớn (>50MB)
    else:
        CHUNK = 16   * 1024*1024  # 16 MB — mặc định

    # ── Parse Range header ────────────────────────────────────────────────────
    byte_start = 0
    byte_end   = file_size - 1
    is_partial = False

    range_hdr = request.headers.get('Range', '').strip()
    if range_hdr and range_hdr.startswith('bytes='):
        try:
            spec        = range_hdr[6:]
            first_range = spec.split(',')[0].strip()
            parts       = first_range.split('-', 1)
            s_part      = parts[0].strip()
            e_part      = parts[1].strip() if len(parts) > 1 else ''
            if s_part == '' and e_part:
                byte_start = max(0, file_size - int(e_part))
                byte_end   = file_size - 1
            elif s_part and e_part == '':
                byte_start = int(s_part)
                byte_end   = file_size - 1
            else:
                byte_start = int(s_part) if s_part else 0
                byte_end   = int(e_part) if e_part else file_size - 1
            byte_start = max(0, min(byte_start, file_size - 1))
            byte_end   = max(byte_start, min(byte_end, file_size - 1))
            is_partial = True
        except Exception:
            byte_start = 0; byte_end = file_size - 1; is_partial = False

    content_length = byte_end - byte_start + 1

    # ── Fast-path: Safari probe (1-2 bytes) → trả ngay, không mở mmap ───────
    if is_partial and content_length <= 2:
        try:
            with open(result_path, 'rb') as _pf:
                _pf.seek(byte_start)
                probe_data = _pf.read(content_length)
        except Exception:
            probe_data = b'\x00' * content_length
        resp = Response(probe_data, status=206, mimetype='video/mp4')
        resp.headers.update({
            'Content-Length':       str(len(probe_data)),
            'Content-Range':        f'bytes {byte_start}-{byte_end}/{file_size}',
            'Accept-Ranges':        'bytes',
            'Content-Disposition':  _content_disp,
            'Cache-Control':        'no-store',
            'X-Accel-Buffering':    'no',
            'Access-Control-Allow-Origin':   '*',
            'Access-Control-Expose-Headers': 'Content-Disposition, Content-Length, Accept-Ranges',
        })
        return resp

    # ── mmap zero-copy streaming generator ───────────────────────────────────
    def _generate_fast():
        bytes_sent = 0
        try:
            with open(result_path, 'rb') as f:
                try:
                    # mmap: OS page cache → Python buffer, zero extra copy
                    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                    mm.seek(byte_start)
                    target = content_length
                    while bytes_sent < target:
                        chunk = mm.read(min(CHUNK, target - bytes_sent))
                        if not chunk:
                            break
                        bytes_sent += len(chunk)
                        yield chunk
                    mm.close()
                except (mmap.error, OSError, ValueError):
                    # fallback: standard read (tmpfs nhỏ / Windows edge-case)
                    f.seek(byte_start)
                    target = content_length
                    empty  = 0
                    while bytes_sent < target:
                        chunk = f.read(min(CHUNK, target - bytes_sent))
                        if not chunk:
                            empty += 1
                            if empty >= 3:
                                _log('err', f'get_result EOF sớm {bytes_sent}/{target}B')
                                break
                            time.sleep(0.003)
                            continue
                        empty = 0
                        bytes_sent += len(chunk)
                        yield chunk
        except GeneratorExit:
            _log('info', f'get_result: disconnect {bytes_sent}/{content_length}B [{task_id[:8]}]')
        except Exception as exc:
            _log('err', f'get_result stream: {exc} [{task_id[:8]}]')

    status_code = 206 if is_partial else 200
    resp = Response(
        stream_with_context(_generate_fast()),
        status=status_code,
        mimetype='video/mp4',
        direct_passthrough=True,
    )
    resp.headers['Content-Length']        = str(content_length)
    resp.headers['Content-Disposition']   = _content_disp
    resp.headers['Accept-Ranges']         = 'bytes'
    resp.headers['Cache-Control']         = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma']                = 'no-cache'
    resp.headers['X-Accel-Buffering']     = 'no'
    resp.headers['Content-Type']          = 'video/mp4'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Access-Control-Allow-Origin']   = '*'
    resp.headers['Access-Control-Expose-Headers'] = 'Content-Disposition, Content-Length, Accept-Ranges'
    if is_partial:
        resp.headers['Content-Range'] = f'bytes {byte_start}-{byte_end}/{file_size}'
    return resp


# ── STATUS check (fallback nếu SSE bị ngắt giữa chừng) ──────────────────────
@app.route('/api/task_status/<task_id>', methods=['GET'])
def task_status(task_id):
    with _task_lock:
        task = TASK_STORE.get(task_id)
    if not task:
        return jsonify({'error': 'Not found', 'task_id': task_id}), 404
    info = task.get('info', {})
    return jsonify({
        'task_id':  task_id,
        'status':   task['status'],
        'filename': task.get('filename', ''),
        'size':     task.get('size', 0),
        'title':    info.get('title', ''),
        'method':   info.get('method', ''),
        'error':    task.get('error', ''),
        'url':      task.get('url', ''),       # ← URL gốc để client re-trigger nếu file expired
    })


@app.route('/api/cancel_task/<task_id>', methods=['POST'])
def cancel_task(task_id):
    """Đánh dấu task là cancelled — background thread sẽ dừng ở lần check tiếp."""
    with _task_lock:
        task = TASK_STORE.get(task_id)
        if task and task.get('status') in ('pending', 'running'):
            task['status'] = 'cancelled'
            task['error']  = 'Đã dừng bởi người dùng'
    _emit(task_id, 'error', {'msg': 'Đã dừng bởi người dùng', 'ts': time.time()})
    try: _emit(task_id, '_end', {})
    except Exception: pass
    return jsonify({'ok': True})


@app.route('/api/cancel_all', methods=['POST'])
def cancel_all():
    """
    Huỷ TẤT CẢ task và batch đang pending/running.
    Gọi khi: trang reload, người dùng rời trang.
    Claude D: endpoint này đảm bảo server sạch sau mỗi reload.
    """
    cancelled_tasks   = 0
    cancelled_batches = 0

    # ── Huỷ tất cả single tasks ──────────────────────────────────────────────
    with _task_lock:
        for tid, task in TASK_STORE.items():
            if task.get('status') in ('pending', 'running'):
                task['status'] = 'cancelled'
                task['error']  = 'Đã dừng khi reload trang'
                cancelled_tasks += 1
                try: _emit(tid, 'error', {'msg': 'Đã dừng khi reload trang', 'ts': time.time()})
                except Exception: pass
                try: _emit(tid, '_end', {})
                except Exception: pass

    # ── Huỷ tất cả batch jobs ─────────────────────────────────────────────────
    with _batch_lock:
        for bid, job in BATCH_STORE.items():
            if not job.cancelled and not job.is_done:
                job.cancel()
                cancelled_batches += 1

    _log('info', f'cancel_all: {cancelled_tasks} tasks, {cancelled_batches} batches cancelled')
    return jsonify({
        'ok': True,
        'cancelled_tasks':   cancelled_tasks,
        'cancelled_batches': cancelled_batches,
    })


# ══════════════════════════════════════════════════════════════════════════════
# BATCH ROUTES — xử lý song song + ordered delivery
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/batch_start', methods=['POST'])
def batch_start():
    """
    POST {urls: [...], audio, logo_enabled, logo_base64, logo_x, logo_y, logo_width, logo_height}
    Trả về ngay: {batch_id, total}
    Client kết nối GET /api/batch_stream/<batch_id> để nhận SSE ordered results.
    """
    data = request.get_json(force=True) or {}
    urls_raw = data.get('urls', [])
    if isinstance(urls_raw, str):
        urls_raw = [u.strip() for u in urls_raw.split('\n') if u.strip()]
    urls = [u for u in urls_raw if is_valid_tiktok_url(u)]
    if not urls:
        return jsonify({'error': 'No valid TikTok URLs'}), 400
    urls = urls[:100]  # hard cap

    audio = data.get('audio', True) in [True, 'true', '1', 'yes']

    # ── KIỂM TRA QUYỀN BATCH ─────────────────────────────────────────────────
    logo_en = bool(data.get('logo_enabled', False))
    allowed, err_msg, err_code = _check_download_permission(
        audio=audio, logo_enabled=logo_en, is_batch=True
    )
    if not allowed:
        return jsonify({'error': err_msg, 'code': err_code}), 403

    logo_params = {
        'enabled':     data.get('logo_enabled', False),
        'logo_base64': data.get('logo_base64', ''),
        'x':           int(data.get('logo_x', 0)),
        'y':           int(data.get('logo_y', 0)),
        'width':       int(data.get('logo_width',  100)),
        'height':      int(data.get('logo_height', 100)),
        'original_aspect': data.get('logo_original_aspect', None),
    }
    # Claude A: recompute height từ aspect ratio gốc để mọi video có logo đồng đều
    _asp2 = logo_params.get('original_aspect')
    if _asp2 and isinstance(_asp2, (int, float)) and _asp2 > 0:
        logo_params['height'] = round(logo_params['width'] * _asp2)

    batch_id = hashlib.md5(
        f"batch{''.join(urls)}{time.time()}{random.random()}".encode()
    ).hexdigest()

    _batch_owner      = session.get('username') or ''
    _save_to_storage  = bool(data.get('save_to_storage', False))
    _download_direct  = bool(data.get('download_direct', True))
    _group_name       = str(data.get('group_name', ''))
    _folder_id        = str(data.get('folder_id', ''))   # ⚡ FIX: nhận folder_id

    # ── BACKGROUND PERSISTENCE: chỉ force khi user chọn storage/both
    # Hoặc khi đây là persist request từ queue_persist API
    _bg_persist_batch = bool(data.get('_bg_persist', False))
    if _batch_owner and (_save_to_storage or _bg_persist_batch):
        _save_to_storage = True   # giữ như cũ nếu user đã chọn

    job = BatchJob(batch_id, urls, audio, logo_params, owner=_batch_owner,
                   save_to_storage=_save_to_storage, download_direct=_download_direct,
                   group_name=_group_name, folder_id=_folder_id)
    with _batch_lock:
        BATCH_STORE[batch_id] = job

    job.start()
    _log('info', f'[batch {batch_id[:8]}] created — {len(urls)} URLs | pipeline-mode')
    return jsonify({'batch_id': batch_id, 'total': len(urls)})


@app.route('/api/batch_stream/<batch_id>', methods=['GET'])
def batch_stream(batch_id):
    """
    SSE endpoint — stream ordered results từ BatchJob.
    Events: progress, result, batch_done, heartbeat
    """
    with _batch_lock:
        job = BATCH_STORE.get(batch_id)
    if not job:
        return jsonify({'error': 'Batch not found'}), 404

    def generate():
        # ⚡ TURBO: heartbeat 1s (từ 3s) — phát hiện disconnect nhanh hơn
        # Queue timeout 0.1s (từ 0.3s) — throughput event cao hơn
        hb_interval = 1
        last_hb     = time.time()
        consecutive_empties = 0   # đếm empty → tự thoát nếu client mất kết nối
        while True:
            try:
                evt = job.sse_q.get(timeout=0.1)
                consecutive_empties = 0
                if evt['event'] == '_end':
                    break
                try:
                    yield _sse(evt['event'], evt['data'])
                except GeneratorExit:
                    return
                except Exception:
                    return
                if evt['event'] == 'batch_done':
                    break
            except _queue_module.Empty:
                consecutive_empties += 1
                now = time.time()
                if now - last_hb >= hb_interval:
                    try:
                        yield _sse('heartbeat', {'ts': now, 'seq': consecutive_empties})
                    except (GeneratorExit, Exception):
                        return
                    last_hb = now

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':        'no-cache',
            'X-Accel-Buffering':    'no',
            'Connection':           'keep-alive',
            'Keep-Alive':           'timeout=120, max=1000',
            'Access-Control-Allow-Origin': '*',
            'Transfer-Encoding':    'chunked',
        }
    )


@app.route('/api/batch_cancel/<batch_id>', methods=['POST'])
def batch_cancel(batch_id):
    """Hủy batch đang chạy."""
    with _batch_lock:
        job = BATCH_STORE.get(batch_id)
    if job:
        job.cancel()
        return jsonify({'ok': True, 'cancelled': True})
    return jsonify({'ok': True, 'cancelled': False})



@app.route('/api/batch_status/<batch_id>', methods=['GET'])
def batch_status(batch_id):
    """
    Polling fallback cho iOS/Safari khi SSE bị browser kill.
    GET /api/batch_status/<batch_id>?since=<N>
    """
    with _batch_lock:
        job = BATCH_STORE.get(batch_id)

    if not job:
        return jsonify({
            'is_done': True, 'total': 0,
            'ok': 0, 'error': 0, 'done_count': 0,
            'results': [], 'log_length': 0,
        })

    since = max(0, int(request.args.get('since', 0)))
    with job._log_lock:
        new_results = list(job.results_log[since:])
        log_length  = len(job.results_log)

    resp_data = jsonify({
        'is_done':    job.is_done,
        'total':      job.total,
        'ok':         job._ok,
        'error':      job._err,
        'done_count': job._done_count,
        'results':    new_results,
        'log_length': log_length,
    })
    # Cho phép browser cache 1s để giảm số request trùng khi poll nhanh
    resp_data.headers['Cache-Control'] = 'no-store'
    resp_data.headers['X-Accel-Buffering'] = 'no'
    return resp_data


@app.route('/api/batch_item_msgs/<batch_id>/<int:index>', methods=['GET'])
def batch_item_msgs(batch_id, index):
    """
    🟡 Trả về progress messages của 1 item cụ thể trong batch.
    Dùng cho queue item detail panel (click để mở).
    GET /api/batch_item_msgs/<batch_id>/<index>
    """
    with _batch_lock:
        job = BATCH_STORE.get(batch_id)
    if not job:
        return jsonify({'msgs': [], 'found': False}), 404
    return jsonify({
        'found':  True,
        'index':  index,
        'msgs':   job.get_item_msgs(index),
        'total':  job.total,
    })


@app.route('/api/check_urls', methods=['POST'])
def check_urls():
    ip = _get_client_ip()
    data = request.get_json()
    urls_raw = data.get('urls', '')
    if isinstance(urls_raw, list):
        urls_text = '\n'.join(urls_raw)
    else:
        urls_text = str(urls_raw)
    urls_text = urls_text.strip()
    if not urls_text:
        return jsonify({'error': 'No URLs provided'}), 400

    urls = [u.strip() for u in urls_text.split('\n') if u.strip()]
    urls = list(dict.fromkeys(urls))[:100]
    valid_urls = [u for u in urls if is_valid_tiktok_url(u)]
    n_valid = len(valid_urls)

    # Đếm links + log
    _session_add_links(ip, n_valid)
    with _link_lock:
        global_total = _global_link_counter[0]
    _log_access(ip, '/api/check_urls', request.headers.get('User-Agent',''),
                extra=f'links_submitted={len(urls)} valid={n_valid} global_total={global_total}')
    print(f"{_CYAN}· [SEARCH] ip={ip} links={n_valid} global={global_total}{_RESET}", flush=True)

    results = []
    valid_count = 0

    with ThreadPoolExecutor(max_workers=min(10, _CPU_COUNT)) as executor:
        future_to_url = {}
        for url in urls:
            if not is_valid_tiktok_url(url):
                results.append({'url': url, 'valid': False, 'error': 'Invalid URL'})
                continue
            future = executor.submit(process_single_url, url)
            future_to_url[future] = url

        for future in as_completed(future_to_url):
            try:
                info = future.result()
                results.append(info)
                if info.get('download_url'):
                    valid_count += 1
            except Exception as e:
                url = future_to_url[future]
                results.append({'url': url, 'valid': False, 'error': str(e)})

    return jsonify({
        'success': True,
        'results': results,
        'total': len(urls),
        'valid': valid_count,
        'invalid': len(urls) - valid_count,
        'global_links_searched': global_total,
    })

def process_single_url(url):
    """Xử lý một URL để lấy thông tin (dùng cho thread pool)"""
    info = get_tiktok_info_parallel(url, audio=True)
    info['url'] = url
    return info

@app.route('/api/download_video', methods=['POST'])
def download_video():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'error': 'Missing URL'}), 400
    if not is_valid_tiktok_url(url):
        return jsonify({'error': 'Invalid URL'}), 400

    audio_param = data.get('audio', True)
    audio = audio_param in [True, 'true', '1', 'yes']

    # Logo parameters
    logo_params = {
        'enabled': data.get('logo_enabled', False),
        'logo_base64': data.get('logo_base64', ''),
        'x': data.get('logo_x', 0),
        'y': data.get('logo_y', 0),
        'width': data.get('logo_width', 100),
        'height': data.get('logo_height', 100)
    }

    user_agent = request.headers.get('User-Agent', '')

    raw_path    = None
    result_path = None
    extra_files = []
    try:
        raw_path, info = _race_download_to_file(url, FAST_TMPDIR, audio=audio)
        result_path = _process_video_file(raw_path, audio, logo_params)
        result_path = _ensure_valid_mp4(result_path, (info or {}).get('duration', 60))

        if result_path != raw_path:
            extra_files.append(raw_path)

        filename = safe_filename(info.get('title', ''), info.get('id', 'unknown'))

        @after_this_request
        def _del(response):
            def _do():
                time.sleep(2)
                _cleanup_file(result_path, *extra_files)
            threading.Thread(target=_do, daemon=True).start()
            return response

        return send_file(
            result_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        _cleanup_file(raw_path, result_path, *extra_files)
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/api/get_video_info', methods=['POST'])
def get_video_info_route():
    data = request.get_json()
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Missing URL'}), 400
    if not is_valid_tiktok_url(url):
        return jsonify({'error': 'Invalid URL'}), 400

    try:
        info = get_tiktok_info_parallel(url, audio=True)
        info['url'] = url
        return jsonify(info)
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)}), 500

@app.route('/api/client_info', methods=['GET'])
def client_info():
    """Ghi IP + device lên terminal, visitors.json, access.log. KHÔNG trả IP về client."""
    ip     = _get_client_ip()
    ua_str = request.headers.get('User-Agent', '')
    dev    = _detect_device_info(ua_str)
    device, os_, browser = dev['device'], dev['os'], dev['browser']

    # Ghi terminal + access.log
    _session_enter(ip)
    _log_access(ip, '/api/client_info', ua_str,
                extra=f'device={device} os={os_} browser={browser}')
    print(f"\033[95m🌐 CLIENT  IP={ip}  {device} · {os_} · {browser}\033[0m", flush=True)

    # 🟡 Ghi visitors.json ngay lập tức (async geo lookup)
    threading.Thread(target=record_visitor, args=(ip, ua_str, '/'), daemon=True).start()
    # 🟡 Claude D: Ghi vào realtime access log cho dashboard terminal
    try: _write_access_realtime(ip, device, os_, browser)
    except Exception: pass

    return jsonify({
        'device':  device,
        'os':      os_,
        'browser': browser,
    })


@app.route('/api/session_exit', methods=['POST'])
def session_exit():
    """Client gọi khi beforeunload — ghi thời gian truy cập vào log."""
    ip = _get_client_ip()
    _session_exit(ip)
    return jsonify({'ok': True})


@app.route('/api/link_stats', methods=['GET'])
def link_stats():
    """Trả về số link đã tìm kiếm (global + session của IP này)."""
    ip = _get_client_ip()
    with _link_lock:
        total = _global_link_counter[0]
    with _session_lock:
        session_links = _session_store.get(ip, {}).get('links_searched', 0)
    return jsonify({'total_global': total, 'session': session_links})

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint với thông tin hệ thống."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '10.3.0-full-featured',
        'service': 'TikTok Downloader - TURBO EDITION',
        'system': {
            'ffmpeg_available': FFMPEG_AVAILABLE,
            'hw_encoder': HW_ENCODER,
            'tiktokapi_available': TIKTOK_API_AVAILABLE,
            'cookies_loaded': len(COOKIES_DICT),
            'proxy_configured': PROXY is not None,
            'cpu_slots': _CPU_COUNT,
            'hardware_tier': _HARDWARE_TIER,
            'tmpdir': FAST_TMPDIR,
        },
    })


# ══════════════════════════════════════════════════════════════════════════════
# ⚡ EYECORE KEEPLINK™ — Hệ thống duy trì kết nối client-server tùy chỉnh
# Công nghệ: Adaptive ping/pong + progressive reconnect + jitter backoff
# Mục tiêu: Không bao giờ bị ngắt kết nối, phục hồi <300ms sau gián đoạn
# ══════════════════════════════════════════════════════════════════════════════
_keeplink_sessions: dict = {}   # session_id → {last_ping, ip, created}
_keeplink_lock = threading.Lock()

@app.route('/api/keeplink/ping', methods=['GET', 'POST'])
def keeplink_ping():
    """
    EYECORE KeepLink™ ping endpoint.
    Client gọi mỗi 5-10s để duy trì session và kiểm tra liveness.
    Response: {pong: true, ts: epoch_ms, latency_hint: ms, server_load: 0-100}
    """
    sid = request.args.get('sid') or request.headers.get('X-KeepLink-Session', '')
    now = time.time()
    ip  = _get_client_ip()

    with _keeplink_lock:
        if sid:
            _keeplink_sessions[sid] = {'last_ping': now, 'ip': ip, 'created': now}
        # Dọn session cũ hơn 5 phút
        stale = [k for k, v in _keeplink_sessions.items() if now - v['last_ping'] > 300]
        for k in stale:
            del _keeplink_sessions[k]

    # Ước tính server load từ batch/task đang chạy
    try:
        with _batch_lock:
            active_batches = sum(1 for j in BATCH_STORE.values() if not j.is_done and not j.cancelled)
        with _task_lock:
            active_tasks = sum(1 for t in TASK_STORE.values() if t.get('status') in ('pending','running'))
        server_load = min(100, (active_batches * 15) + (active_tasks * 5))
    except Exception:
        server_load = 0

    # Gợi ý interval tối ưu dựa trên load: thấp=8s, cao=4s (duy trì kết nối)
    interval_hint = 4 if server_load > 50 else 8

    resp = jsonify({
        'pong':          True,
        'ts':            int(now * 1000),
        'server_load':   server_load,
        'interval_hint': interval_hint,
        'sessions':      len(_keeplink_sessions),
    })
    resp.headers['Cache-Control']     = 'no-store'
    resp.headers['X-KeepLink-Server'] = 'EYECORE/1.0'
    return resp


@app.route('/api/keeplink/stream', methods=['GET'])
def keeplink_stream():
    """
    EYECORE KeepLink™ persistent SSE stream.
    Gửi heartbeat mỗi 2s, kèm server state để client biết server alive.
    Client dùng stream này song song với batch_stream để phát hiện
    server restart / network drop nhanh hơn (< 3s thay vì 10s+).
    """
    sid = request.args.get('sid', f'kl_{int(time.time()*1000)}')
    ip  = _get_client_ip()

    def _kl_generate():
        seq = 0
        with _keeplink_lock:
            _keeplink_sessions[sid] = {'last_ping': time.time(), 'ip': ip, 'created': time.time()}
        try:
            while True:
                seq += 1
                now = time.time()
                # Ước tính load nhẹ
                try:
                    with _batch_lock:
                        ab = sum(1 for j in BATCH_STORE.values() if not j.is_done and not j.cancelled)
                    with _task_lock:
                        at = sum(1 for t in TASK_STORE.values() if t.get('status') in ('pending','running'))
                except Exception:
                    ab = at = 0

                payload = json.dumps({'ts': int(now*1000), 'seq': seq, 'batches': ab, 'tasks': at})
                try:
                    yield f"event: kl_heartbeat\ndata: {payload}\n\n"
                except GeneratorExit:
                    break
                # Cập nhật session
                with _keeplink_lock:
                    if sid in _keeplink_sessions:
                        _keeplink_sessions[sid]['last_ping'] = now
                time.sleep(15)   # 15s heartbeat — tiết kiệm băng thông (~1KB/min)
        finally:
            with _keeplink_lock:
                _keeplink_sessions.pop(sid, None)

    return Response(
        stream_with_context(_kl_generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection':        'keep-alive',
            'Keep-Alive':        'timeout=300, max=9999',
            'Access-Control-Allow-Origin': '*',
        }
    )


# 🔵 Speedtest payload: trả về payload ngẫu nhiên để đo tốc độ mạng thật
_SPEEDTEST_PAYLOAD_512K = os.urandom(512 * 1024)   # 512KB random bytes
_SPEEDTEST_PAYLOAD_1M   = os.urandom(1024 * 1024)  # 1MB random bytes (desktop)

@app.route('/api/speedtest_payload', methods=['GET'])
def speedtest_payload():
    """
    🔵 Trả về payload ngẫu nhiên để client đo tốc độ tải thực.
    ?sz=512 → 512KB (default, mobile)
    ?sz=1024 → 1MB (desktop)
    Client đo thời gian từ lúc bắt đầu fetch đến lúc nhận xong toàn bộ body.
    """
    sz = request.args.get('sz', '512')
    payload = _SPEEDTEST_PAYLOAD_1M if sz == '1024' else _SPEEDTEST_PAYLOAD_512K
    resp = Response(payload, status=200, mimetype='application/octet-stream')
    resp.headers['Content-Length']  = str(len(payload))
    resp.headers['Cache-Control']   = 'no-store, no-cache'
    resp.headers['X-Payload-Size']  = str(len(payload))
    return resp


@app.route('/api/visitors', methods=['GET'])
def get_visitors():
    """Trả về danh sách visitors (admin only — chỉ dùng nội bộ)."""
    with _visitors_lock:
        data = _load_visitors()
    # Sắp xếp theo last_seen mới nhất
    records = sorted(data.values(), key=lambda x: x.get('last_seen_ts', 0), reverse=True)
    return jsonify({'total_unique': len(records), 'visitors': records[:100]})


@app.route('/api/update', methods=['POST'])
def manual_update():
    try:
        check_and_update_dependencies()
        return jsonify({'success': True, 'message': 'Đã kiểm tra và cập nhật thư viện thành công.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    try:
        temp_dir = tempfile.gettempdir()
        now = time.time()
        for f in os.listdir(temp_dir):
            if f.startswith('tiktok_') or f.startswith('overlay_'):
                path = os.path.join(temp_dir, f)
                try:
                    if os.path.getmtime(path) < now - 3600:
                        if os.path.isfile(path):
                            os.remove(path)
                except:
                    continue
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
# SERVER RELOAD — broadcast tới tất cả client đang kết nối
# ══════════════════════════════════════════════════════════════════════
_reload_subscribers = []   # list of queue.Queue, mỗi SSE client 1 queue
_reload_lock = threading.Lock()

def _broadcast_reload():
    """Gửi lệnh reload tới tất cả client đang lắng nghe SSE /api/reload_stream."""
    with _reload_lock:
        dead = []
        for q in _reload_subscribers:
            try:
                q.put_nowait('reload')
            except Exception:
                dead.append(q)
        for q in dead:
            _reload_subscribers.remove(q)

@app.route('/api/reload_stream', methods=['GET'])
def reload_stream():
    """SSE endpoint — client subscribe để nhận lệnh reload từ server."""
    q = _queue_module.Queue(maxsize=5)
    with _reload_lock:
        _reload_subscribers.append(q)

    def generate():
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f"event: {msg}\ndata: {{}}\n\n"
                except _queue_module.Empty:
                    yield ": heartbeat\n\n"  # keep-alive
        except GeneratorExit:
            pass
        finally:
            with _reload_lock:
                try: _reload_subscribers.remove(q)
                except ValueError: pass

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':    'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection':       'keep-alive',
        }
    )

@app.route('/api/server_reload', methods=['POST'])
def server_reload():
    """Admin endpoint: gửi lệnh reload tới tất cả tab đang mở."""
    _broadcast_reload()
    return jsonify({'success': True, 'subscribers': len(_reload_subscribers)})

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Trả về nội dung log file gần nhất (error hoặc process)."""
    log_type = request.args.get('type', 'error')  # error | process
    lines_n  = int(request.args.get('lines', 200))
    fname    = 'error.log' if log_type == 'error' else 'process.log'
    fpath    = os.path.join(_LOG_DIR, fname)
    if not os.path.exists(fpath):
        return jsonify({'lines': [], 'file': fname, 'exists': False})
    with open(fpath, encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()
    return jsonify({
        'file':   fname,
        'exists': True,
        'total':  len(all_lines),
        'lines':  [l.rstrip() for l in all_lines[-lines_n:]],
    })

@app.route('/api/cleanup_ramdisk', methods=['POST'])
def cleanup_ramdisk():
    deleted = 0
    errors  = 0
    try:
        PREFIXES = ('race_', 'proc_', 'tk_', 'tka_', 'overlay_', 'combo_', 'ck_', 'yt_')
        for fname in os.listdir(FAST_TMPDIR):
            if any(fname.startswith(p) for p in PREFIXES):
                fpath = os.path.join(FAST_TMPDIR, fname)
                try:
                    if os.path.isfile(fpath):
                        os.unlink(fpath)
                        deleted += 1
                except Exception:
                    errors += 1
        return jsonify({'success': True, 'deleted': deleted, 'errors': errors,
                        'tmpdir': FAST_TMPDIR})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reload_cookies', methods=['POST'])
def reload_cookies():
    global COOKIES_DICT
    try:
        COOKIES_DICT = get_cookies_dict()
        return jsonify({
            'success': True,
            'cookies_loaded': len(COOKIES_DICT),
            'message': f'Reloaded {len(COOKIES_DICT)} cookies'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/set_cookies', methods=['POST'])
def set_cookies():
    global COOKIES_DICT
    try:
        data = request.get_json()
        cookies = data.get('cookies', {})
        
        if isinstance(cookies, dict):
            COOKIES_DICT.update(cookies)
            return jsonify({
                'success': True,
                'cookies_loaded': len(COOKIES_DICT),
                'message': f'Set {len(cookies)} cookies'
            })
        else:
            return jsonify({'error': 'Invalid cookies format'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════════
# 🔐 AUTH ROUTES — Dr. An Nguyễn + Dr. Bình Trần
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/auth/register', methods=['POST', 'OPTIONS'])
def auth_register():
    """Đăng ký tài khoản mới."""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json(force=True) or {}
    username = (data.get('username') or '').strip().lower()
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    confirm  = data.get('confirm_password') or ''

    # Validation
    err = _validate_username(username)
    if err: return jsonify({'error': err}), 400
    err = _validate_email(email)
    if err: return jsonify({'error': err}), 400
    err = _validate_password(password)
    if err: return jsonify({'error': err}), 400
    if password != confirm:
        return jsonify({'error': 'Mật khẩu xác nhận không khớp'}), 400

    with _users_rw_lock:
        db = _load_users_db()
        # Kiểm tra trùng username
        if username in db['users']:
            return jsonify({'error': 'Tên đăng nhập đã tồn tại'}), 409
        # Kiểm tra trùng email
        for u in db['users'].values():
            if u.get('email') == email:
                return jsonify({'error': 'Email đã được sử dụng'}), 409
        pwd_hash, salt = _hash_password(password)
        db['users'][username] = {
            'username': username,
            'email': email,
            'password': pwd_hash,
            'salt': salt,
            'role': 'user',
            'created_at': datetime.now().isoformat(),
            'locked': False,
            'restrictions': {
                'no_audio_remove': False,
                'no_logo': False,
                'no_batch': False,
            },
            'lock_reason': '',
        }
        _save_users_db(db)

    print(f"✅ [AUTH] Đăng ký thành công: {username} <{email}>")
    return jsonify({'success': True, 'message': f'Đăng ký thành công! Chào mừng {username}.'})


@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def auth_login():
    """Đăng nhập — chấp nhận username hoặc email."""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json(force=True) or {}
    login_id = (data.get('login_id') or '').strip().lower()
    password  = data.get('password') or ''

    if not login_id or not password:
        return jsonify({'error': 'Vui lòng điền đầy đủ thông tin'}), 400

    with _users_rw_lock:
        db = _load_users_db()
        # Tìm theo username hoặc email
        user = db['users'].get(login_id)
        if not user:
            for u in db['users'].values():
                if u.get('email') == login_id:
                    user = u
                    break

    if not user:
        return jsonify({'error': 'Tên đăng nhập hoặc mật khẩu không đúng'}), 401
    if user.get('locked'):
        reason = user.get('lock_reason', '')
        msg = f'Tài khoản bị khóa' + (f': {reason}' if reason else '')
        return jsonify({'error': msg}), 403
    if not _verify_password(password, user['password'], user['salt']):
        return jsonify({'error': 'Tên đăng nhập hoặc mật khẩu không đúng'}), 401

    # Tạo session
    session.permanent = True
    session['username'] = user['username']
    session['role']     = user['role']

    print(f"✅ [AUTH] Đăng nhập: {user['username']} ({user['role']})")
    return jsonify({
        'success': True,
        'user': {
            'username': user['username'],
            'email':    user['email'],
            'role':     user['role'],
        }
    })


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """Đăng xuất."""
    username = session.get('username', 'unknown')
    session.clear()
    print(f"✅ [AUTH] Đăng xuất: {username}")
    return jsonify({'success': True})


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    """Lấy thông tin user hiện tại (hoặc guest nếu chưa đăng nhập)."""
    user = get_current_user()
    ip   = _get_client_ip()
    if user is None:
        can, remaining, reset_at = guest_can_download(ip)
        return jsonify({
            'logged_in': False,
            'role': 'guest',
            'guest_remaining': remaining,
            'guest_limit': _GUEST_DAILY_LIMIT,
            'guest_reset_at': reset_at,
        })
    return jsonify({
        'logged_in': True,
        'username': user['username'],
        'email':    user['email'],
        'role':     user['role'],
        'restrictions': user.get('restrictions', {}),
    })


@app.route('/api/auth/change_password', methods=['POST'])
@require_logged_in
def auth_change_password():
    """Đổi mật khẩu của chính mình."""
    data = request.get_json(force=True) or {}
    current  = data.get('current_password') or ''
    new_pwd  = data.get('new_password') or ''
    confirm  = data.get('confirm_password') or ''

    err = _validate_password(new_pwd)
    if err: return jsonify({'error': err}), 400
    if new_pwd != confirm:
        return jsonify({'error': 'Mật khẩu xác nhận không khớp'}), 400

    username = session.get('username')
    with _users_rw_lock:
        db = _load_users_db()
        user = db['users'].get(username)
        if not user:
            return jsonify({'error': 'Người dùng không tồn tại'}), 404
        if not _verify_password(current, user['password'], user['salt']):
            return jsonify({'error': 'Mật khẩu hiện tại không đúng'}), 401
        pwd_hash, salt = _hash_password(new_pwd)
        user['password'] = pwd_hash
        user['salt']     = salt
        _save_users_db(db)

    return jsonify({'success': True, 'message': 'Đổi mật khẩu thành công!'})


# ── ADMIN ROUTES ──────────────────────────────────────────────────────────────

@app.route('/api/admin/users', methods=['GET'])
@require_admin
def admin_list_users():
    """Lấy danh sách tất cả user."""
    with _users_rw_lock:
        db = _load_users_db()
    users = []
    for u in db['users'].values():
        users.append({
            'username':     u['username'],
            'email':        u['email'],
            'role':         u['role'],
            'locked':       u.get('locked', False),
            'lock_reason':  u.get('lock_reason', ''),
            'restrictions': u.get('restrictions', {}),
            'created_at':   u.get('created_at', ''),
        })
    users.sort(key=lambda x: (x['role'] != 'admin', x['username']))
    return jsonify({'users': users, 'total': len(users)})


@app.route('/api/admin/lock_user', methods=['POST'])
@require_admin
def admin_lock_user():
    """Khóa hoặc mở khóa tài khoản user — hiệu lực ngay lập tức."""
    data     = request.get_json(force=True) or {}
    target   = (data.get('username') or '').strip().lower()
    locked   = bool(data.get('locked', True))
    reason   = (data.get('reason') or '').strip()
    admin_u  = session.get('username')

    if not target:
        return jsonify({'error': 'Thiếu username'}), 400
    if target == admin_u:
        return jsonify({'error': 'Không thể khóa chính mình'}), 400

    with _users_rw_lock:
        db = _load_users_db()
        user = db['users'].get(target)
        if not user:
            return jsonify({'error': f'Không tìm thấy user: {target}'}), 404
        if user.get('role') == 'admin':
            return jsonify({'error': 'Không thể khóa tài khoản admin'}), 403
        user['locked']      = locked
        user['lock_reason'] = reason if locked else ''
        _save_users_db(db)

    action = "Khóa" if locked else "Mở khóa"
    print(f"⚠️ [ADMIN] {admin_u} → {action} user '{target}'" + (f" (lý do: {reason})" if reason else ""))
    # Xóa session của user bị khóa ngay lập tức (Flask sẽ check ở get_current_user)
    return jsonify({'success': True, 'locked': locked,
                    'message': f'{action} tài khoản {target} thành công!'})


@app.route('/api/admin/set_restrictions', methods=['POST'])
@require_admin
def admin_set_restrictions():
    """Hạn chế/bỏ hạn chế chức năng của user — hiệu lực ngay."""
    data        = request.get_json(force=True) or {}
    target      = (data.get('username') or '').strip().lower()
    restrictions = data.get('restrictions', {})
    admin_u     = session.get('username')

    if not target:
        return jsonify({'error': 'Thiếu username'}), 400

    with _users_rw_lock:
        db = _load_users_db()
        user = db['users'].get(target)
        if not user:
            return jsonify({'error': f'Không tìm thấy user: {target}'}), 404
        if user.get('role') == 'admin':
            return jsonify({'error': 'Không thể hạn chế tài khoản admin'}), 403
        # Cập nhật từng restriction được gửi
        cur = user.setdefault('restrictions', {})
        for k, v in restrictions.items():
            if k in ('no_audio_remove', 'no_logo', 'no_batch'):
                cur[k] = bool(v)
        _save_users_db(db)

    print(f"⚠️ [ADMIN] {admin_u} → Set restrictions cho '{target}': {restrictions}")
    return jsonify({'success': True, 'restrictions': user['restrictions'],
                    'message': f'Đã cập nhật hạn chế cho {target}!'})


@app.route('/api/admin/change_user_password', methods=['POST'])
@require_admin
def admin_change_user_password():
    """Admin đổi mật khẩu của user khác."""
    data      = request.get_json(force=True) or {}
    target    = (data.get('username') or '').strip().lower()
    new_pwd   = data.get('new_password') or ''
    admin_u   = session.get('username')

    if not target:
        return jsonify({'error': 'Thiếu username'}), 400
    err = _validate_password(new_pwd)
    if err: return jsonify({'error': err}), 400

    with _users_rw_lock:
        db = _load_users_db()
        user = db['users'].get(target)
        if not user:
            return jsonify({'error': f'Không tìm thấy user: {target}'}), 404
        pwd_hash, salt = _hash_password(new_pwd)
        user['password'] = pwd_hash
        user['salt']     = salt
        _save_users_db(db)

    print(f"⚠️ [ADMIN] {admin_u} → Đổi mật khẩu cho '{target}'")
    return jsonify({'success': True,
                    'message': f'Đổi mật khẩu cho {target} thành công!'})


@app.route('/api/admin/delete_user', methods=['POST'])
@require_admin
def admin_delete_user():
    """Xóa tài khoản user."""
    data    = request.get_json(force=True) or {}
    target  = (data.get('username') or '').strip().lower()
    admin_u = session.get('username')

    if not target:
        return jsonify({'error': 'Thiếu username'}), 400
    if target == admin_u:
        return jsonify({'error': 'Không thể xóa chính mình'}), 400

    with _users_rw_lock:
        db = _load_users_db()
        user = db['users'].get(target)
        if not user:
            return jsonify({'error': f'Không tìm thấy user: {target}'}), 404
        if user.get('role') == 'admin':
            return jsonify({'error': 'Không thể xóa tài khoản admin'}), 403
        del db['users'][target]
        _save_users_db(db)

    print(f"⚠️ [ADMIN] {admin_u} → Xóa user '{target}'")
    return jsonify({'success': True, 'message': f'Đã xóa tài khoản {target}!'})


@app.route('/api/admin/promote_user', methods=['POST'])
@require_admin
def admin_promote_user():
    """Thăng cấp user lên admin hoặc hạ xuống user."""
    data   = request.get_json(force=True) or {}
    target = (data.get('username') or '').strip().lower()
    role   = data.get('role', 'user')
    admin_u = session.get('username')

    if role not in ('admin', 'user'):
        return jsonify({'error': 'Role không hợp lệ (admin/user)'}), 400
    if target == admin_u:
        return jsonify({'error': 'Không thể thay đổi role của chính mình'}), 400

    with _users_rw_lock:
        db = _load_users_db()
        user = db['users'].get(target)
        if not user:
            return jsonify({'error': f'Không tìm thấy user: {target}'}), 404
        user['role'] = role
        _save_users_db(db)

    print(f"⚠️ [ADMIN] {admin_u} → Thay đổi role '{target}' → {role}")
    return jsonify({'success': True,
                    'message': f'Đã thay đổi role {target} thành {role}!'})


# ── PERMISSION CHECK cho các route download ───────────────────────────────────

def _check_download_permission(audio: bool = True, logo_enabled: bool = False,
                                 is_batch: bool = False) -> tuple:
    """
    Kiểm tra quyền tải video.
    Trả về (allowed: bool, error_msg: str, error_code: str)
    """
    role = get_current_role()
    ip   = _get_client_ip()

    if role == 'guest':
        # Guest: chỉ được tải thường
        if not audio:
            return False, 'Guest không được xóa âm thanh. Vui lòng đăng nhập.', 'GUEST_RESTRICTED'
        if logo_enabled:
            return False, 'Guest không được thêm logo. Vui lòng đăng nhập.', 'GUEST_RESTRICTED'
        if is_batch:
            return False, 'Guest không được tải hàng loạt. Vui lòng đăng nhập.', 'GUEST_RESTRICTED'
        # Kiểm tra giới hạn hàng ngày
        can, remaining, reset_at = guest_can_download(ip)
        if not can:
            return False, f'Guest đã đạt giới hạn {_GUEST_DAILY_LIMIT} video/ngày. Reset lúc 0h. Đăng nhập để tải không giới hạn.', 'GUEST_LIMIT'
        return True, '', ''

    if role == 'user':
        user = get_current_user()
        if not user:
            return False, 'Phiên đăng nhập hết hạn', 'LOGIN_REQUIRED'
        # Kiểm tra restrictions
        restr = user.get('restrictions', {})
        if not audio and restr.get('no_audio_remove'):
            return False, 'Tài khoản của bạn bị hạn chế chức năng xóa âm thanh.', 'RESTRICTED'
        if logo_enabled and restr.get('no_logo'):
            return False, 'Tài khoản của bạn bị hạn chế chức năng thêm logo.', 'RESTRICTED'
        if is_batch and restr.get('no_batch'):
            return False, 'Tài khoản của bạn bị hạn chế chức năng tải hàng loạt.', 'RESTRICTED'
        return True, '', ''

    # admin — không giới hạn
    return True, '', ''


# ══════════════════════════════════════════════════════════════════════════════
# 📁 STORAGE API ROUTES — Kho lưu trữ tạm thời của người dùng
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/storage/info', methods=['GET'])
@require_logged_in
def storage_info():
    """Thông tin quota và dung lượng đang dùng của user."""
    username = session.get('username')
    quota    = get_user_quota_bytes(username)
    used     = get_user_storage_used(username)
    pct      = round(used / quota * 100, 1) if quota > 0 else 0
    return jsonify({
        'username':    username,
        'quota_bytes': quota,
        'quota_gb':    round(quota / 1024**3, 1) if quota else 0,
        'used_bytes':  used,
        'used_mb':     round(used / 1024**2, 1),
        'used_gb':     round(used / 1024**3, 3),
        'free_bytes':  max(0, quota - used) if quota else None,
        'unlimited':   quota >= _ADMIN_QUOTA_BYTES,
        'percent':     min(100.0, pct),
    })


@app.route('/api/storage/list', methods=['GET'])
@require_logged_in
def storage_list():
    """Danh sách file trong kho của user (mới nhất trước)."""
    username = session.get('username')
    files    = list_user_storage_files(username)
    used     = get_user_storage_used(username)
    quota    = get_user_quota_bytes(username)
    return jsonify({
        'files':       files,
        'total':       len(files),
        'used_bytes':  used,
        'quota_bytes': quota,
        'unlimited':   quota >= _ADMIN_QUOTA_BYTES,
        'percent':     min(100.0, round(used / quota * 100, 1)) if quota > 0 else 0,
        'ttl_days':    _STORAGE_TTL_DAYS,
    })


@app.route('/api/storage/download/<path:filename>', methods=['GET'])
@require_logged_in
def storage_download(filename):
    """Tải file từ kho của user về máy — giữ nguyên tên đã đặt."""
    username    = session.get('username')
    safe_fn     = os.path.basename(filename)     # chống path traversal
    storage_dir = get_user_storage_dir(username)
    file_path   = os.path.join(storage_dir, safe_fn)
    real_path   = os.path.realpath(file_path)
    real_dir    = os.path.realpath(storage_dir)

    # FIX: dùng real_dir (không cần + os.sep) để tránh miss khi file nằm thẳng trong dir
    if not os.path.isfile(file_path) or not (
        real_path == real_dir or real_path.startswith(real_dir + os.sep)
    ):
        app.logger.warning(f'[storage_download] 404: safe_fn={safe_fn!r} real_path={real_path!r} real_dir={real_dir!r}')
        return jsonify({'error': 'File không tồn tại hoặc không hợp lệ'}), 404

    file_size = os.path.getsize(file_path)

    # Lấy tên đẹp từ metadata (title → tên file hiển thị)
    try:
        import re as _re_fn
        meta     = _load_user_storage_meta(username)
        _entry   = meta.get(safe_fn) or {}
        _title   = (_entry.get('title') or _entry.get('orig_title') or '').strip()
        if _title:
            # Sanitize: giữ tiếng Việt/Unicode, bỏ ký tự nguy hiểm cho filename
            _title = _re_fn.sub(r'[\\/:*?"<>|]', '_', _title)
            _title = _re_fn.sub(r'\s+', ' ', _title).strip()[:120]
            if _title and not _title.lower().endswith('.mp4'):
                _title += '.mp4'
            display_name = _title if _title else safe_fn
        else:
            display_name = safe_fn
    except Exception:
        display_name = safe_fn

    # ── FIX: latin-1 UnicodeEncodeError ─────────────────────────────────────────
    # HTTP header bytes phải latin-1. Dùng filename*= (RFC 5987) cho Unicode,
    # filename= chỉ chứa safe_fn (ASCII uuid như tikdown_XxXxXx.mp4).
    encoded_utf8 = quote(display_name, safe='')          # percent-encode toàn bộ
    ascii_fname  = safe_fn                                # ASCII-safe luôn
    content_disp = f'attachment; filename="{ascii_fname}"; filename*=UTF-8\'\'{encoded_utf8}'

    # ⚡ TURBO: chunk lớn để đạt 50MB/s trên LAN/local
    ua_str    = request.headers.get('User-Agent', '').lower()
    is_mobile = any(k in ua_str for k in ('mobile', 'android', 'iphone', 'ipad'))
    is_safari = 'safari' in ua_str and 'chrome' not in ua_str
    if is_safari:
        CHUNK = 1    * 1024*1024  # 1 MB — Safari
    elif is_mobile:
        CHUNK = 2    * 1024*1024  # 2 MB — mobile
    elif file_size > 200 * 1024*1024:
        CHUNK = 64   * 1024*1024  # 64 MB — file rất lớn
    elif file_size > 50 * 1024*1024:
        CHUNK = 32   * 1024*1024  # 32 MB — file lớn
    else:
        CHUNK = 16   * 1024*1024  # 16 MB — mặc định

    byte_start, byte_end, is_partial = 0, file_size - 1, False
    rng = request.headers.get('Range', '').strip()
    if rng and rng.startswith('bytes='):
        try:
            spec  = rng[6:].split(',')[0].strip()
            parts = spec.split('-', 1)
            s = parts[0].strip()
            e = parts[1].strip() if len(parts) > 1 else ''
            if not s and e:
                byte_start = max(0, file_size - int(e)); byte_end = file_size - 1
            elif s and not e:
                byte_start = int(s); byte_end = file_size - 1
            else:
                byte_start = int(s) if s else 0
                byte_end   = int(e) if e else file_size - 1
            byte_start = max(0, min(byte_start, file_size - 1))
            byte_end   = max(byte_start, min(byte_end, file_size - 1))
            is_partial = True
        except Exception:
            byte_start, byte_end, is_partial = 0, file_size - 1, False

    content_length = byte_end - byte_start + 1

    def _gen():
        with open(file_path, 'rb') as _fh:
            try:
                mm = mmap.mmap(_fh.fileno(), 0, access=mmap.ACCESS_READ)
                mm.seek(byte_start)
                sent = 0
                while sent < content_length:
                    chunk = mm.read(min(CHUNK, content_length - sent))
                    if not chunk:
                        break
                    sent += len(chunk)
                    yield chunk
                mm.close()
            except (mmap.error, OSError):
                _fh.seek(byte_start)
                sent = 0
                while sent < content_length:
                    chunk = _fh.read(min(CHUNK, content_length - sent))
                    if not chunk:
                        break
                    sent += len(chunk)
                    yield chunk

    status = 206 if is_partial else 200
    resp = Response(
        stream_with_context(_gen()), status=status,
        mimetype='video/mp4', direct_passthrough=True
    )
    resp.headers.update({
        'Content-Length':               str(content_length),
        'Content-Disposition':          content_disp,       # ASCII-safe header
        'Accept-Ranges':                'bytes',
        'Cache-Control':                'no-store, no-transform',
        'X-Accel-Buffering':            'no',
        'X-Content-Type-Options':       'nosniff',
        'Vary':                         'Range',
        'Access-Control-Allow-Origin':  '*',
        'Access-Control-Expose-Headers':'Content-Disposition,Content-Length,Accept-Ranges,Content-Range',
    })
    if is_partial:
        resp.headers['Content-Range'] = f'bytes {byte_start}-{byte_end}/{file_size}'
    return resp


@app.route('/api/storage/delete', methods=['POST'])
@require_logged_in
def storage_delete():
    """Xóa một hoặc nhiều file khỏi kho."""
    data      = request.get_json(force=True) or {}
    filenames = data.get('filenames', [])
    if isinstance(filenames, str):
        filenames = [filenames]
    username = session.get('username')
    deleted, errors = [], []
    for fn in filenames:
        r = delete_from_user_storage(username, fn)
        (deleted if r['ok'] else errors).append(fn)
    return jsonify({'deleted': deleted, 'errors': errors,
                    'used_bytes': get_user_storage_used(username)})


@app.route('/api/storage/download_zip', methods=['POST'])
@require_logged_in
def storage_download_zip():
    """Tải nhiều file dưới dạng ZIP."""
    import zipfile as _zip
    data      = request.get_json(force=True) or {}
    filenames = data.get('filenames', [])
    username  = session.get('username')
    storage_dir = get_user_storage_dir(username)

    if not filenames:
        # Lấy tất cả
        filenames = [f['filename'] for f in list_user_storage_files(username)]
    if not filenames:
        return jsonify({'error': 'Không có file nào'}), 400

    zip_path = os.path.join(FAST_TMPDIR, f'tikdown_{username}_{int(time.time())}.zip')
    try:
        with _zip.ZipFile(zip_path, 'w', _zip.ZIP_STORED) as zf:
            for fn in filenames:
                safe = os.path.basename(fn)
                fp   = os.path.join(storage_dir, safe)
                if os.path.isfile(fp):
                    zf.write(fp, safe)

        @after_this_request
        def _del(resp):
            threading.Thread(target=lambda:(time.sleep(10), _cleanup_file(zip_path)),
                             daemon=True).start()
            return resp

        return send_file(zip_path, as_attachment=True,
                         download_name=f'TikDown_{username}_{datetime.now().strftime("%Y%m%d_%H%M")}.zip',
                         mimetype='application/zip')
    except Exception as e:
        _cleanup_file(zip_path)
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/clear_all', methods=['POST'])
@require_logged_in
def storage_clear_all():
    """Xóa tất cả file trong kho."""
    username = session.get('username')
    files    = list_user_storage_files(username)
    deleted  = []
    for f in files:
        r = delete_from_user_storage(username, f['filename'])
        if r['ok']:
            deleted.append(f['filename'])
    return jsonify({'deleted': deleted, 'total': len(deleted)})


@app.route('/api/storage/download_group', methods=['POST'])
@require_logged_in
def storage_download_group():
    """
    Trả danh sách URL để frontend tải tuần tự (cũ→mới), KHÔNG nén ZIP.
    Tương thích backward: JS cũ nhận {'files':[...]} thay vì ZIP stream.
    """
    data      = request.get_json(force=True) or {}
    group_id  = data.get('group_id', '')
    day       = data.get('day', '')
    username  = session.get('username')
    all_files = list_user_storage_files(username)

    if group_id:
        targets = [f for f in all_files if f.get('group_id') == group_id]
    elif day:
        targets = [f for f in all_files if (f.get('saved_at') or '').startswith(day)]
    else:
        return jsonify({'error': 'Cần group_id hoặc day'}), 400

    if not targets:
        return jsonify({'error': 'Không có file nào', 'files': []}), 404

    # Sort từ cũ nhất → mới nhất
    targets.sort(key=lambda x: x.get('saved_at_ts', 0))

    return jsonify({
        'files': [
            {
                'filename': f['filename'],
                'title':    f.get('title', f['filename']),
                'url':      f'/api/storage/download/{quote(f["filename"], safe="")}',
                'size':     f.get('size', 0),
                'saved_at': f.get('saved_at', ''),
            }
            for f in targets
        ],
        'total': len(targets),
        'mode':  'sequential',
    })


# ── ADMIN: quản lý quota người dùng ──────────────────────────────────────────

@app.route('/api/admin/set_quota', methods=['POST'])
@require_admin
def admin_set_quota():
    """Admin cấp quota (GB) cho user. 0 = không giới hạn (_ADMIN_QUOTA_BYTES)."""
    data     = request.get_json(force=True) or {}
    target   = (data.get('username') or '').strip().lower()
    quota_gb = data.get('quota_gb')
    admin_u  = session.get('username')

    if not target:
        return jsonify({'error': 'Thiếu username'}), 400
    try:
        quota_gb = float(quota_gb)
        if quota_gb < 0: raise ValueError
    except (TypeError, ValueError):
        return jsonify({'error': 'quota_gb phải là số không âm (0 = không giới hạn)'}), 400

    with _users_rw_lock:
        db   = _load_users_db()
        user = db['users'].get(target)
        if not user:
            return jsonify({'error': f'Không tìm thấy user: {target}'}), 404
        # 0 = dùng _ADMIN_QUOTA_BYTES (effectively unlimited)
        quota_bytes = int(_ADMIN_QUOTA_BYTES if quota_gb == 0 else quota_gb * 1024**3)
        user['storage_quota_bytes'] = quota_bytes
        _save_users_db(db)

    print(f"⚠️ [ADMIN] {admin_u} → Set quota '{target}': {quota_gb}GB")
    return jsonify({
        'success':     True,
        'quota_bytes': quota_bytes,
        'quota_gb':    quota_gb,
        'message':     f'Đã cấp {"không giới hạn" if quota_gb==0 else str(quota_gb)+"GB"} cho {target}!',
    })


@app.route('/api/admin/storage_overview', methods=['GET'])
@require_admin
def admin_storage_overview():
    """Admin: xem tổng quan kho lưu trữ tất cả user."""
    with _users_rw_lock:
        db = _load_users_db()
    result = []
    for uname, udata in db['users'].items():
        used  = get_user_storage_used(uname)
        quota = get_user_quota_bytes(uname)
        files = list_user_storage_files(uname)
        result.append({
            'username':    uname,
            'role':        udata.get('role','user'),
            'used_bytes':  used,
            'used_mb':     round(used/1024**2, 1),
            'quota_bytes': quota,
            'quota_gb':    round(quota/1024**3, 1),
            'file_count':  len(files),
            'unlimited':   quota >= _ADMIN_QUOTA_BYTES,
        })
    result.sort(key=lambda x: -x['used_bytes'])
    total_used = sum(r['used_bytes'] for r in result)
    return jsonify({'users': result, 'total': len(result),
                    'total_used_bytes': total_used,
                    'total_used_gb': round(total_used/1024**3, 2)})


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

# -------------------- MAIN --------------------
# 🟡 Claude D: Cross-platform dashboard terminal spawner
def _get_local_ip():
    """Lấy IP LAN của máy."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def _spawn_dashboard_terminal(port: int, local_ip: str):
    """
    🟡 Claude D: Mở 1 terminal MỚI hiển thị dashboard (thời gian, IP, thiết bị).
    Không flood terminal chính. Hỗ trợ Windows & Linux.
    """
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    dashboard_lines = [
        f"{'='*60}",
        f"  ⚡ TIKDOWN TURBO v10.3.0 — ĐANG CHẠY",
        f"  🕐 Khởi động: {now_str}",
        f"  🌐 Local:     http://localhost:{port}",
        f"  🌐 LAN:       http://{local_ip}:{port}",
        f"  📁 Tmp dir:   {FAST_TMPDIR}",
        f"  🖥  FFmpeg:    {'✅' if FFMPEG_AVAILABLE else '❌'}  |  Encoder: {HW_ENCODER}",
        f"  🔑 Cookies:   {len(COOKIES_DICT)} loaded",
        f"{'='*60}",
        f"  Truy cập / access log sẽ hiện ở đây...",
        f"{'='*60}",
    ]
    msg = "\n".join(dashboard_lines)

    IS_WINDOWS = sys.platform == 'win32'
    try:
        if IS_WINDOWS:
            # Windows: mở cmd mới
            bat_path = os.path.join(FAST_TMPDIR, 'tikdown_dashboard.bat')
            with open(bat_path, 'w') as f:
                f.write('@echo off\n')
                f.write(f'title TikDown Dashboard\n')
                f.write(f'echo {chr(10).join(dashboard_lines[:8])}\n')
                f.write('echo.\n')
                f.write('echo Giữ cửa sổ này mở để xem access log...\n')
                f.write('pause >nul\n')
            subprocess.Popen(
                ['cmd', '/c', 'start', 'cmd', '/k', bat_path],
                creationflags=0x00000008  # DETACHED_PROCESS
            )
        else:
            # Linux/macOS: thử các terminal phổ biến
            safe_msg = msg.replace("'", "\\'")
            terminals = [
                ['gnome-terminal', '--title=TikDown Dashboard', '--', 'bash', '-c',
                 f'printf "%s\\n" "{safe_msg}"; echo; echo "Ctrl+C to close..."; sleep infinity'],
                ['xterm', '-title', 'TikDown Dashboard', '-e',
                 'bash', '-c', f'printf "%s\\n" "{safe_msg}"; sleep infinity'],
                ['konsole', '--title', 'TikDown Dashboard', '-e',
                 'bash', '-c', f'printf "%s\\n" "{safe_msg}"; sleep infinity'],
                ['xfce4-terminal', '--title=TikDown Dashboard', '-e',
                 'bash', '-c', f'printf "%s\\n" "{safe_msg}"; sleep infinity'],
            ]
            for term_cmd in terminals:
                try:
                    subprocess.Popen(term_cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                    break
                except (FileNotFoundError, PermissionError):
                    continue
    except Exception as e:
        pass  # Nếu không mở được terminal mới, bỏ qua (không crash server)

# ── ACCESS LOG HOOK: In thiết bị khi có kết nối mới ──────────────────────────
_access_log_file_path = os.path.join(_LOG_DIR, 'access_realtime.log')

def _write_access_realtime(ip: str, device: str, os_: str, browser: str):
    """Ghi 1 dòng access vào file realtime log (dashboard terminal đọc)."""
    now_str = datetime.now().strftime('%H:%M:%S')
    line = f"[{now_str}] 🌐 {ip:<15}  {device} · {os_} · {browser}\n"
    try:
        with open(_access_log_file_path, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass



@app.route('/api/security/status', methods=['GET'])
@require_admin
def security_status():
    return jsonify(_behavioral_guard.status())

@app.route('/api/security/unblock', methods=['POST'])
@require_admin
def security_unblock():
    data = request.get_json(force=True) or {}
    ip   = (data.get('ip') or '').strip()
    if not ip: return jsonify({'error':'Thiếu ip'}), 400
    ok = _behavioral_guard.unblock(ip)
    return jsonify({'success':ok,'ip':ip})


# ══════════════════════════════════════════════════════════════════════════════
# ⚡ THUNDERWAVE™ — EYECORE Ultra-Fast Parallel Delivery Protocol v1.0
# Technology: Multi-stream parallel byte-range HTTP/2 + in-browser reassembly
# Target: 50MB/s on LAN for ALL devices (Android, iOS, Desktop)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/thunderwave/manifest/<task_id>', methods=['GET'])
def thunderwave_manifest_task(task_id):
    """THUNDERWAVE™ manifest for a download task."""
    with _task_lock:
        task = TASK_STORE.get(task_id, {})
    if task.get('status') != 'done':
        return jsonify({'error': 'Task not ready', 'status': task.get('status','unknown')}), 404
    result_path = task.get('result_path', '')
    if not result_path or not os.path.exists(result_path):
        return jsonify({'error': 'Result file gone'}), 404
    file_size   = os.path.getsize(result_path)
    dl_filename = task.get('filename', 'video.mp4')
    return _thunderwave_build_manifest(file_size, dl_filename, task_id=task_id, mode='task')


@app.route('/api/thunderwave/manifest/storage/<path:filename>', methods=['GET'])
@require_logged_in
def thunderwave_manifest_storage(filename):
    """THUNDERWAVE™ manifest for a storage file."""
    username    = session.get('username')
    storage_dir = get_user_storage_dir(username)
    safe_fn     = os.path.basename(filename)
    fp          = os.path.join(storage_dir, safe_fn)
    if not os.path.exists(fp):
        return jsonify({'error': 'File not found'}), 404
    return _thunderwave_build_manifest(os.path.getsize(fp), safe_fn, mode='storage')


def _thunderwave_build_manifest(file_size: int, dl_filename: str,
                                 task_id: str = '', mode: str = 'task') -> Response:
    """Build THUNDERWAVE™ manifest response."""
    ua     = request.headers.get('User-Agent', '').lower()
    is_ios = 'iphone' in ua or 'ipad' in ua
    is_mob = 'android' in ua or is_ios

    if is_ios:
        workers = 1   # Safari: single stream
    elif is_mob:
        workers = 4   # Android Chrome: 4 parallel
    elif file_size > 100 * 1024 * 1024:
        workers = 8   # Desktop large file
    else:
        workers = 6   # Desktop normal

    chunk_size = max(1, file_size // workers)
    ranges = []
    for i in range(workers):
        start = i * chunk_size
        end   = (start + chunk_size - 1) if i < workers - 1 else (file_size - 1)
        if start <= file_size - 1:
            ranges.append({'i': i, 'start': start, 'end': min(end, file_size-1),
                           'size': min(end, file_size-1) - start + 1})

    return jsonify({
        'ok': True, 'mode': mode, 'task_id': task_id,
        'filename': dl_filename, 'size': file_size,
        'workers': len(ranges), 'chunk_size': chunk_size,
        'ranges': ranges, 'mime': 'video/mp4',
        'protocol': 'THUNDERWAVE/1.0',
    })


# ══════════════════════════════════════════════════════════════════════════════
# 📡 EYECORE REALTIME PUSH CHANNEL™ — Live State Broadcast (no F5 needed)
# Push tới TẤT CẢ tab của user: storage_update, batch_done, auth_change...
# ══════════════════════════════════════════════════════════════════════════════
_push_subscribers: dict = {}
_push_sub_lock = threading.Lock()


def _push_to_user(username: str, event: str, data: dict):
    """Broadcast event tới tất cả SSE subscribers của user."""
    if not username:
        return
    with _push_sub_lock:
        queues = list(_push_subscribers.get(username, []))
    payload = {'event': event, 'data': data, 'ts': int(time.time() * 1000)}
    for q in queues:
        try:
            q.put_nowait(payload)
        except Exception:
            pass


@app.route('/api/realtime/subscribe', methods=['GET'])
@require_logged_in
def realtime_subscribe():
    """
    EYECORE Realtime Push Channel™ SSE endpoint.
    Events: storage_update | batch_done | auth_change | system_notice
    Client subscribes once and receives all state changes instantly.
    """
    username = session.get('username')
    q = _queue_module.Queue(maxsize=100)

    with _push_sub_lock:
        _push_subscribers.setdefault(username, []).append(q)

    def _gen():
        try:
            yield _sse('rt_connected', {
                'username': username,
                'ts': int(time.time() * 1000),
                'protocol': 'EYECORE-RTPC/1.0',
            })
            while True:
                try:
                    msg = q.get(timeout=12)
                    try:
                        yield _sse(msg['event'], msg['data'])
                    except (GeneratorExit, Exception):
                        return
                except _queue_module.Empty:
                    try:
                        yield _sse('rt_heartbeat', {'ts': int(time.time() * 1000)})
                    except (GeneratorExit, Exception):
                        return
        finally:
            with _push_sub_lock:
                lst = _push_subscribers.get(username, [])
                if q in lst:
                    lst.remove(q)
                if not lst:
                    _push_subscribers.pop(username, None)

    return Response(stream_with_context(_gen()), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive', 'Keep-Alive': 'timeout=300, max=9999',
        'Access-Control-Allow-Origin': '*',
    })


# ── Patch save_to_user_storage để broadcast storage_update sau khi lưu ────────
_orig_save_to_user_storage = save_to_user_storage

def save_to_user_storage(username: str, src_path: str, filename: str,
                          title: str = '', url: str = '',
                          group_id: str = '', group_name: str = '',
                          folder_id: str = '') -> dict:
    result = _orig_save_to_user_storage(
        username, src_path, filename,
        title=title, url=url,
        group_id=group_id, group_name=group_name, folder_id=folder_id
    )
    if result.get('ok'):
        _push_to_user(username, 'storage_update', {
            'action': 'add', 'filename': filename, 'folder_id': folder_id,
            'group_id': group_id, 'used': result.get('used', 0),
        })
    return result


# ── Patch delete_from_user_storage để broadcast storage_update ────────────────
_orig_delete_from_user_storage = delete_from_user_storage

def delete_from_user_storage(username: str, filename: str) -> dict:
    result = _orig_delete_from_user_storage(username, filename)
    if result.get('ok'):
        _push_to_user(username, 'storage_update', {
            'action': 'delete', 'filename': filename,
        })
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 🌐 WEBRTC SIGNALING — EYECORE WebRTC Bridge v1.0
# SDP offer/answer + ICE exchange. Transport: THUNDERWAVE™ fallback.
# ══════════════════════════════════════════════════════════════════════════════
_webrtc_sessions: dict = {}
_webrtc_lock = threading.Lock()


@app.route('/api/webrtc/offer', methods=['POST'])
def webrtc_offer():
    data     = request.get_json(force=True) or {}
    sdp      = data.get('sdp', '')
    sdp_type = data.get('type', 'offer')
    if not sdp:
        return jsonify({'error': 'Missing SDP'}), 400

    sid = hashlib.md5(f"{time.time()}{random.random()}".encode()).hexdigest()[:16]
    # THUNDERWAVE™ answer — server side WebRTC peer indicated via SDP extension
    answer_sdp = (
        "v=0\r\n"
        f"o=EYECORE-BRIDGE {int(time.time())} 0 IN IP4 127.0.0.1\r\n"
        "s=THUNDERWAVE Delivery Session\r\n"
        "t=0 0\r\n"
        "a=thunderwave:enabled\r\n"
        "a=protocol:THUNDERWAVE/1.0\r\n"
        "a=transport:parallel-range-request\r\n"
    )
    with _webrtc_lock:
        _webrtc_sessions[sid] = {
            'offer':      {'sdp': sdp, 'type': sdp_type},
            'answer':     {'sdp': answer_sdp, 'type': 'answer'},
            'candidates': [],
            'task_id':    data.get('task_id', ''),
            'filename':   data.get('filename', ''),
            'created':    time.time(),
        }
        stale = [k for k, v in _webrtc_sessions.items() if time.time() - v['created'] > 300]
        for k in stale:
            del _webrtc_sessions[k]

    return jsonify({
        'ok': True, 'session_id': sid,
        'answer': {'sdp': answer_sdp, 'type': 'answer'},
        'transport': 'THUNDERWAVE/1.0',
    })


@app.route('/api/webrtc/ice', methods=['POST'])
def webrtc_ice():
    data = request.get_json(force=True) or {}
    sid  = data.get('session_id', '')
    with _webrtc_lock:
        if sid in _webrtc_sessions:
            _webrtc_sessions[sid]['candidates'].append(data.get('candidate'))
    return jsonify({'ok': True})


@app.route('/api/webrtc/status/<session_id>', methods=['GET'])
def webrtc_status(session_id):
    with _webrtc_lock:
        sess = dict(_webrtc_sessions.get(session_id, {}))
    if not sess:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify({
        'ok': True, 'has_answer': True,
        'answer': sess.get('answer'),
        'transport': 'THUNDERWAVE/1.0',
        'task_id': sess.get('task_id', ''),
    })


# ══════════════════════════════════════════════════════════════════════════════
# 🎵 GHÉP ÂM THANH VÀO VIDEO — tự lặp audio nếu video dài hơn
# Route: POST /api/audio/merge_video
# Body (multipart): video=<file>, audio=<file>
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/audio/merge_video', methods=['POST', 'OPTIONS'])
def audio_merge_video():
    if request.method == 'OPTIONS':
        return jsonify({'ok': True})

    if not FFMPEG_AVAILABLE:
        return jsonify({'ok': False, 'error': 'FFmpeg không khả dụng trên server này'}), 500

    video_file = request.files.get('video')
    audio_file = request.files.get('audio')

    if not video_file or not audio_file:
        return jsonify({'ok': False, 'error': 'Thiếu file video hoặc audio'}), 400

    allowed_video = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.ts'}
    allowed_audio = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.opus'}

    vid_ext = os.path.splitext(video_file.filename or 'v.mp4')[1].lower() or '.mp4'
    aud_ext = os.path.splitext(audio_file.filename or 'a.mp3')[1].lower() or '.mp3'

    if vid_ext not in allowed_video:
        return jsonify({'ok': False, 'error': f'Định dạng video không hỗ trợ: {vid_ext}'}), 400
    if aud_ext not in allowed_audio:
        return jsonify({'ok': False, 'error': f'Định dạng audio không hỗ trợ: {aud_ext}'}), 400

    tmpdir = _get_fast_tmpdir()
    uid = uuid.uuid4().hex[:12]
    vid_path = os.path.join(tmpdir, f'amthanh_vid_{uid}{vid_ext}')
    aud_path = os.path.join(tmpdir, f'amthanh_aud_{uid}{aud_ext}')
    out_path = os.path.join(tmpdir, f'amthanh_out_{uid}.mp4')

    def _cleanup(*paths):
        for p in paths:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    try:
        video_file.save(vid_path)
        audio_file.save(aud_path)

        # ── Lấy duration video & audio bằng ffprobe ──────────────────────────
        def _get_duration(path):
            try:
                r = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'json', path],
                    capture_output=True, text=True, timeout=20
                )
                return float(json.loads(r.stdout)['format']['duration'])
            except Exception:
                return None

        vid_dur = _get_duration(vid_path)
        aud_dur = _get_duration(aud_path)

        if vid_dur is None or aud_dur is None:
            return jsonify({'ok': False, 'error': 'Không đọc được thời lượng file'}), 400

        # ── Quyết định có cần loop audio không ───────────────────────────────
        if aud_dur > 0 and vid_dur > aud_dur:
            # Số lần cần lặp (làm tròn lên)
            loop_times = int(vid_dur / aud_dur) + 1
            log_process(f'[audio_merge] video={vid_dur:.1f}s audio={aud_dur:.1f}s → loop×{loop_times}')

            # -stream_loop -1 + -t (video duration) để crop đúng
            cmd = [
                'ffmpeg',
                '-i', vid_path,
                '-stream_loop', str(loop_times),
                '-i', aud_path,
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-shortest',
                '-t', str(vid_dur),          # cắt đúng độ dài video gốc
                '-movflags', '+faststart',
                '-y',
                out_path
            ]
        else:
            # Audio dài hơn hoặc bằng video → không cần loop, -shortest tự cắt
            log_process(f'[audio_merge] video={vid_dur:.1f}s audio={aud_dur:.1f}s → no loop')
            cmd = [
                'ffmpeg',
                '-i', vid_path,
                '-i', aud_path,
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-shortest',
                '-movflags', '+faststart',
                '-y',
                out_path
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            log_error(f'[audio_merge] FFmpeg lỗi: {result.stderr[-600:]}')
            _cleanup(vid_path, aud_path, out_path)
            return jsonify({'ok': False, 'error': 'FFmpeg xử lý thất bại', 'detail': result.stderr[-300:]}), 500

        if not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
            _cleanup(vid_path, aud_path, out_path)
            return jsonify({'ok': False, 'error': 'File đầu ra không hợp lệ'}), 500

        out_name = (os.path.splitext(video_file.filename or 'video')[0] + '_merged.mp4').replace(' ', '_')

        @after_this_request
        def _del_files(response):
            threading.Thread(target=_cleanup, args=(vid_path, aud_path, out_path), daemon=True).start()
            return response

        return send_file(
            out_path,
            as_attachment=True,
            download_name=out_name,
            mimetype='video/mp4'
        )

    except subprocess.TimeoutExpired:
        _cleanup(vid_path, aud_path, out_path)
        return jsonify({'ok': False, 'error': 'FFmpeg timeout (>5 phút)'}), 500
    except Exception as e:
        _cleanup(vid_path, aud_path, out_path)
        log_error(f'[audio_merge] exception: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


if __name__ == '__main__':
    # Suppress werkzeug startup messages (giữ log HTTP request, bỏ banner)
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.INFO)

    # 🔵 Stats thread — chạy ngầm, KHÔNG in liên tục ra terminal chính
    threading.Thread(target=_status_bar_worker, daemon=True, name='status-bar').start()

    local_ip = _get_local_ip()
    PORT = 2110

    # 🟡 Mở terminal mới hiển thị dashboard (không flood terminal chính)
    threading.Thread(
        target=_spawn_dashboard_terminal, args=(PORT, local_ip),
        daemon=True, name='dashboard'
    ).start()

    print("=" * 80)
    print("⚡ TIKTOK DOWNLOADER TURBO - v10.4.0 — FULL FEATURED + KEEPLINK™")
    print("=" * 80)
    print(f"  FFmpeg  : {'✅' if FFMPEG_AVAILABLE else '❌ not found'}")
    print(f"  Encoder : {'🚀 ' + HW_ENCODER if HW_ENCODER != 'libx264' else '🔵 libx264 (software)'}")
    print(f"  CPU     : {_CPU_COUNT} slots (100% of {os.cpu_count()} cores) | FFmpeg threads={_FFMPEG_THREADS}")
    _tier_names = ['🟡 WEAK (Celeron/Atom)', '🔵 MEDIUM (i3/i5-old)', '🟢 STRONG (i5-8th+/i7/Ryzen)']
    print(f"  HW Tier : {_tier_names[_HARDWARE_TIER]} | timeout×{_FFMPEG_TIMEOUT_FACTOR}")
    print(f"  Sessions: {len(SESSION_POOL)} pool | Chunk workers: {[3,6,10][_HARDWARE_TIER]} (adaptive)")
    print(f"  Cookies : {'✅ ' + str(len(COOKIES_DICT)) + ' loaded' if COOKIES_DICT else '❌ none'}")
    print(f"  TikTokApi: {'✅' if TIKTOK_API_AVAILABLE else '❌ not installed'}")
    print(f"  Proxy   : {'✅' if PROXY else '❌ none'}")
    _is_custom   = bool(CUSTOM_TMPDIR and FAST_TMPDIR == CUSTOM_TMPDIR.strip())
    _is_fallback = FAST_TMPDIR == '/dev/shm'
    _tmpdir_type = ('🟢 /dev/shm (RAM disk)' if _is_fallback
                    else '🔵 Tùy chỉnh' if _is_custom
                    else '🟡 Fallback (%TEMP%//tmp)')
    print(f"  Tmp dir : {FAST_TMPDIR}  [{_tmpdir_type}]")
    print(f"  Visitors: {_VISITORS_FILE}")
    print(f"  Reqs    : {_REQ_FILE}")
    print(f"  KeepLink: 🟢 EYECORE KeepLink™ — /api/keeplink/ping | /api/keeplink/stream")
    print(f"  Chunk   : 🟢 Max 64MB chunks → ~50MB/s LAN transfer")
    print(f"  Status  : 🟢 Stats in-line mỗi {STATUS_INTERVAL}s — KHÔNG ẩn log nào")
    print("=" * 80)
    print(f"  🌐 Local:     http://localhost:{PORT}")
    print(f"  🌐 LAN:       http://{local_ip}:{PORT}")
    print(f"  🕐 Started:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  💡 Dashboard terminal đã mở (hoặc sẽ mở trong vài giây)")
    print("=" * 80)
    print(f"  🔄 Reload:    curl -X POST http://localhost:{PORT}/api/server_reload")
    print(f"  🧹 Cleanup:   curl -X POST http://localhost:{PORT}/api/cleanup_ramdisk")
    print(f"  📊 Visitors:  curl http://localhost:{PORT}/api/visitors")
    print("=" * 80)

    app.run(debug=False, host='0.0.0.0', port=PORT, threaded=True, use_reloader=False)