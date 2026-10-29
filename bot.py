import os
import json
import logging
import time
import html
import asyncio
import requests
import re
import base64
import sys
import threading
import zipfile
import io
from threading import Thread
from flask import Flask, request, jsonify
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ConversationHandler,
    filters,
)

# Biến toàn cục cho Bot Application (giữ lại để tương thích)
bot_app = None

# Khóa dùng chung giữa luồng Flask (webhook) và luồng bot khi sửa dữ liệu khách
DB_LOCK = threading.RLock()

# ==================== TÍCH HỢP FLASK & THREADING CHO RENDER ====================
app = Flask('')

@app.route('/')
def home():
    return "Bot SMM & Mua Tài Khoản is running and alive!"

# ==================== GỌI TELEGRAM API ĐỒNG BỘ (DÙNG CHO WEBHOOK) ====================
# Webhook chạy ở luồng Flask riêng, không dùng chung event loop với bot,
# nên gửi thông báo bằng HTTP trực tiếp tới Telegram để luôn gửi được.
def tg_call(method, payload):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload,
            timeout=15
        )
        return r.json()
    except Exception as e:
        logging.error(f"❌ Lỗi gọi Telegram API ({method}): {e}")
        return None

def _countdown_delete_worker(chat_id, message_id, base_text, seconds=30):
    remaining = seconds
    while remaining > 0:
        time.sleep(5)
        remaining -= 5
        if remaining <= 0:
            break
        tg_call("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": f"{base_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau {remaining}s...</i>",
            "parse_mode": "HTML"
        })
    tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def send_auto_delete_message(chat_id, base_text, seconds=30):
    """Gửi tin nhắn rồi tự xóa sau N giây (có đếm ngược)."""
    res = tg_call("sendMessage", {
        "chat_id": chat_id,
        "text": f"{base_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau {seconds}s...</i>",
        "parse_mode": "HTML"
    })
    if res and res.get("ok"):
        message_id = res["result"]["message_id"]
        Thread(
            target=_countdown_delete_worker,
            args=(chat_id, message_id, base_text, seconds),
            daemon=True
        ).start()
        return True
    logging.error(f"❌ Không gửi được thông báo tới {chat_id}: {res}")
    return False

# ==================== TÍNH NĂNG TỰ ĐỘNG CỘNG TIỀN QUA SEPAY ====================
import hmac

# Hỗ trợ 2 tài khoản SePay (mỗi ngân hàng 1 tài khoản SePay riêng)
SEPAY_API_KEYS = {
    "1": os.getenv("SEPAY_API_KEY_1", "").strip(),
    "2": os.getenv("SEPAY_API_KEY_2", "").strip(),
}
# Vẫn hỗ trợ biến cũ SEPAY_API_KEY nếu bạn còn dùng
_legacy_key = os.getenv("SEPAY_API_KEY", "").strip()
if _legacy_key and _legacy_key not in SEPAY_API_KEYS.values():
    SEPAY_API_KEYS["0"] = _legacy_key
SEPAY_API_KEYS = {k: v for k, v in SEPAY_API_KEYS.items() if v}

def identify_sepay_account(auth_header):
    """Trả về '1' / '2' / '0' nếu key khớp, None nếu sai key.
    Nếu chưa cấu hình key nào thì cho qua (trả 'none') giống code cũ."""
    if not SEPAY_API_KEYS:
        return "none"
    token = (auth_header or "").strip()
    if token.lower().startswith("apikey "):
        token = token[7:].strip()
    for name, key in SEPAY_API_KEYS.items():
        if hmac.compare_digest(token.encode(), key.encode()):
            return name
    return None

def notify_sepay_topup_sync(user_id, amount, new_balance, tx_id, bonus=0):
    """Thông báo nạp tiền tự động cho Khách (tự xóa sau 30s) & Admin."""
    bonus_user = f"🎁 <b>Khuyến mãi:</b> <code>+{bonus:,.0f} VNĐ</code>\n" if bonus > 0 else ""
    bonus_admin = f"🎁 <b>Khuyến mãi:</b> +{bonus:,.0f} VNĐ\n" if bonus > 0 else ""
    user_text = (
        f"🎉 <b>NẠP TIỀN TỰ ĐỘNG THÀNH CÔNG (SEPAY)!</b>\n\n"
        f"💵 <b>Số tiền nạp:</b> <code>+{amount:,.0f} VNĐ</code>\n"
        f"{bonus_user}"
        f"💳 <b>Số dư mới:</b> <code>{new_balance:,.0f} VNĐ</code>\n"
        f"🆔 <b>Mã giao dịch:</b> <code>#{tx_id}</code>\n\n"
        f"⚡ <i>Cảm ơn bạn đã sử dụng dịch vụ!</i>"
    )
    if send_auto_delete_message(user_id, user_text, 30):
        logging.info(f"✅ Đã gửi thông báo nạp tiền thành công tới Khách hàng ID: {user_id}")

    try:
        if ADMIN_CHAT_ID and str(ADMIN_CHAT_ID) != "YOUR_ADMIN_CHAT_ID":
            admin_msg = (
                f"🔔 <b>THÔNG BÁO NẠP TIỀN AUTO (SEPAY)</b>\n"
                f"----------------------------------------\n"
                f"👤 <b>Khách hàng ID:</b> <code>{user_id}</code>\n"
                f"💵 <b>Cộng tiền:</b> +{amount:,.0f} VNĐ\n"
                f"{bonus_admin}"
                f"💰 <b>Số dư mới:</b> {new_balance:,.0f} VNĐ\n"
                f"🆔 <b>Mã GD SePay:</b> #{tx_id}"
            )
            tg_call("sendMessage", {"chat_id": int(ADMIN_CHAT_ID), "text": admin_msg, "parse_mode": "HTML"})
    except Exception as e:
        logging.error(f"❌ Lỗi gửi thông báo SePay cho Admin: {e}")

@app.route('/sepay-webhook', methods=['POST'])
def sepay_webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No data"}), 400

        auth_header = request.headers.get("Authorization", "")
        sepay_acc = identify_sepay_account(auth_header)
        logging.info(
            f"📥 SePay webhook nhận: acc={data.get('accountNumber')} | type={data.get('transferType')} | "
            f"amount={data.get('transferAmount')} | content={data.get('content')!r} | key_khop={sepay_acc}"
        )
        if sepay_acc is None:
            logging.warning("⛔ SePay webhook bị từ chối 401: API Key trên SePay KHÔNG khớp biến SEPAY_API_KEY_1/2 trên Render.")
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        transfer_amount = float(data.get("transferAmount", 0))
        content = str(data.get("content", ""))
        transaction_id = data.get("id", "")

        transfer_type = data.get("transferType", "in")
        if transfer_type != "in" or transfer_amount <= 0:
            return jsonify({"status": "success", "message": "Ignored out transaction"}), 200

        tx_key = f"{sepay_acc}:{transaction_id}" if transaction_id not in ("", None) else None
        matched_ids = re.findall(r'(?<!\d)\d{6,12}(?!\d)', content)

        with DB_LOCK:
            # Chống cộng tiền trùng khi SePay gửi lại cùng một giao dịch
            if tx_key and tx_key in PROCESSED_TX:
                return jsonify({"status": "success", "message": "Duplicate transaction ignored"}), 200

            target_user_id = None
            bonus = 0.0
            for uid_str in matched_ids:
                uid = int(uid_str)
                if uid in USERS_DB:
                    target_user_id = uid
                    break

            if target_user_id:
                user_data = get_user_data(target_user_id)
                bonus = calc_bonus(transfer_amount)
                user_data["balance"] += transfer_amount + bonus
                hist = f"Nạp tiền tự động (SePay #{transaction_id}): +{transfer_amount:,.0f}đ"
                if bonus > 0:
                    hist += f" | Khuyến mãi {get_promo_percent():g}%: +{bonus:,.0f}đ"
                user_data["history"].append(hist)
                save_users_db()
                new_balance = user_data["balance"]
                if tx_key:
                    mark_tx_processed(tx_key)

        if target_user_id:
            Thread(
                target=notify_sepay_topup_sync,
                args=(target_user_id, transfer_amount, new_balance, transaction_id, bonus),
                daemon=True
            ).start()
            return jsonify({"status": "success", "message": f"Topup {transfer_amount} for user {target_user_id}"}), 200
        else:
            logging.info(f"SePay Webhook: Không tìm thấy User ID phù hợp trong nội dung '{content}'")
            return jsonify({"status": "success", "message": "User ID not found in content"}), 200

    except Exception as e:
        logging.error(f"Lỗi xử lý SePay Webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

def self_ping_loop():
    """Tự gọi chính mình mỗi 10 phút để Render free không ngủ."""
    url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not url:
        return
    while True:
        time.sleep(600)
        try:
            requests.get(url, timeout=10)
        except Exception:
            pass

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    Thread(target=self_ping_loop, daemon=True).start()

# ==================== LOGGING & CẤU HÌNH CƠ BẢN ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
# Không log URL request của httpx vì URL chứa BOT_TOKEN
logging.getLogger("httpx").setLevel(logging.WARNING)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "YourAdminUsername")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "YOUR_ADMIN_CHAT_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

# Danh sách tài khoản ngân hàng nhận tiền (khách chọn 1 trong các STK khi nạp)
BANK_ACCOUNTS = [
    {"bank_name": "MBBank", "account_no": "3030777777", "account_name": "NGUYEN TIEN DAT"},
    {"bank_name": "MBBank", "account_no": "308088888", "account_name": "NGUYEN TIEN DAT"},
]
BANK_INFO = BANK_ACCOUNTS[0]  # giữ lại để tương thích code cũ

# ==================== LƯU TRỮ DỮ LIỆU BỀN VỮNG ====================
# DB_DIR: thư mục lưu file dữ liệu. Nếu dùng Render Persistent Disk, đặt DB_DIR=/data
DB_DIR = os.getenv("DB_DIR", ".")
try:
    os.makedirs(DB_DIR, exist_ok=True)
except Exception:
    pass

DB_FILE = os.path.join(DB_DIR, "users_db.json")
GITCODE_DB_FILE = os.path.join(DB_DIR, "gitcode_db.json")
SMS_DB_FILE = os.path.join(DB_DIR, "sms_db.json")
SEPAY_TX_FILE = os.path.join(DB_DIR, "sepay_tx.json")
PROMO_FILE = os.path.join(DB_DIR, "promo_db.json")

# ==================== AUTO_BACKUP LÊN TELEGRAM ====================
# Gửi file zip chứa toàn bộ dữ liệu cho Admin và GHIM lại. Khi Render chạy lại sẽ tự khôi phục từ tin ghim.
# Biến môi trường (tùy chọn): TG_BACKUP_CHAT_ID (mặc định = ADMIN_CHAT_ID), TG_BACKUP_ENABLED=0 để tắt.
TG_BACKUP_CHAT_ID = (os.getenv("TG_BACKUP_CHAT_ID", "").strip() or str(ADMIN_CHAT_ID))
TG_BACKUP_ENABLED = os.getenv("TG_BACKUP_ENABLED", "1") != "0"
TG_BACKUP_MIN_INTERVAL = 30     # giây: gộp nhiều thay đổi thành 1 lần gửi
TG_BACKUP_EVERY = 3600          # giây: gửi định kỳ 1 giờ/lần
_TG_STATE = {"dirty": False, "last_sent": time.time(), "last_ok": 0.0, "last_msg_id": None, "last_err": ""}
_TG_LOCK = threading.Lock()
_TG_SEND_LOCK = threading.Lock()
_TG_RESTORED = False

def _tg_files():
    return [DB_FILE, GITCODE_DB_FILE, SMS_DB_FILE, SEPAY_TX_FILE, PROMO_FILE]

def _tg_ready():
    return bool(TG_BACKUP_ENABLED and TG_BACKUP_CHAT_ID and TG_BACKUP_CHAT_ID != "YOUR_ADMIN_CHAT_ID"
                and BOT_TOKEN and BOT_TOKEN != "YOUR_BOT_TOKEN")

def tg_mark_dirty():
    with _TG_LOCK:
        _TG_STATE["dirty"] = True

def tg_backup_send(reason="auto"):
    """Nén dữ liệu và gửi lên Telegram (ghim). Trả True nếu thành công."""
    if not _tg_ready():
        _TG_STATE["last_err"] = "Chưa cấu hình chat nhận backup"
        return False
    with _TG_SEND_LOCK:
        try:
            if not USERS_DB:
                # Dữ liệu rỗng -> không gửi để tránh đè mất bản backup tốt
                _TG_STATE["last_err"] = "Dữ liệu khách đang rỗng, bỏ qua backup"
                return False
            with _TG_LOCK:
                _TG_STATE["dirty"] = False
                _TG_STATE["last_sent"] = time.time()
            flush_saves()  # ghi hết dữ liệu đang chờ xuống file trước khi nén

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in _tg_files():
                    if os.path.exists(p):
                        with open(p, "rb") as f:
                            zf.writestr(os.path.basename(p), f.read())
            buf.seek(0)

            stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(time.time() + 7 * 3600))
            fname = f"backup_{stamp}.zip"
            caption = (
                f"💾 AUTO_BACKUP ({reason})\n"
                f"🕒 {stamp}\n"
                f"👥 Khách: {len(USERS_DB)} | 💰 Tổng số dư: {sum(float(u.get('balance', 0)) for u in USERS_DB.values()):,.0f}đ"
            )
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                data={"chat_id": TG_BACKUP_CHAT_ID, "caption": caption, "disable_notification": "true"},
                files={"document": (fname, buf, "application/zip")},
                timeout=60,
            )
            res = r.json()
            if not res.get("ok"):
                raise RuntimeError(str(res)[:200])

            new_id = res["result"]["message_id"]
            tg_call("pinChatMessage", {"chat_id": TG_BACKUP_CHAT_ID, "message_id": new_id, "disable_notification": True})
            old_id = _TG_STATE.get("last_msg_id")
            if old_id:
                tg_call("deleteMessage", {"chat_id": TG_BACKUP_CHAT_ID, "message_id": old_id})
            _TG_STATE["last_msg_id"] = new_id
            _TG_STATE["last_ok"] = time.time()
            _TG_STATE["last_err"] = ""
            logging.info(f"✅ AUTO_BACKUP Telegram: đã gửi {fname}")
            return True
        except Exception as e:
            _TG_STATE["last_err"] = str(e)[:200]
            logging.error(f"❌ Lỗi AUTO_BACKUP Telegram: {e}")
            with _TG_LOCK:
                _TG_STATE["dirty"] = True
            return False

def tg_backup_async(reason="auto"):
    Thread(target=tg_backup_send, args=(reason,), daemon=True).start()

def restore_from_zip_bytes(raw, missing_only=False):
    """Khôi phục dữ liệu từ file zip. missing_only=True: chỉ ghi file đang thiếu (dùng lúc khởi động)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception:
        return False, "File không phải zip hợp lệ"
    allowed = {os.path.basename(p) for p in _tg_files()}
    payloads = {}
    for name in zf.namelist():
        base = os.path.basename(name)
        if base not in allowed:
            continue
        try:
            data = zf.read(name)
            obj = json.loads(data.decode("utf-8"))
        except Exception:
            return False, f"File {base} trong zip bị lỗi"
        if not isinstance(obj, dict):
            return False, f"File {base} sai định dạng"
        payloads[base] = (data, obj)
    if not payloads:
        return False, "Zip không chứa file dữ liệu hợp lệ"

    restored = []
    with DB_LOCK:
        with _SAVE_PENDING_LOCK:
            if not missing_only:
                _SAVE_PENDING.clear()
        for base, (data, obj) in payloads.items():
            path = os.path.join(DB_DIR, base)
            if missing_only and os.path.exists(path):
                continue
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            restored.append(base)
            if missing_only:
                continue
            # Cập nhật thẳng vào bộ nhớ đang chạy
            if base == os.path.basename(DB_FILE):
                USERS_DB.clear(); USERS_DB.update({int(k): v for k, v in obj.items()})
            elif base == os.path.basename(GITCODE_DB_FILE):
                GITCODE_DB.clear(); GITCODE_DB.update(obj)
            elif base == os.path.basename(SMS_DB_FILE):
                SMS_DB.clear(); SMS_DB.update({int(k): v for k, v in obj.items()})
            elif base == os.path.basename(SEPAY_TX_FILE):
                PROCESSED_TX.clear(); PROCESSED_TX.update(obj)
            elif base == os.path.basename(PROMO_FILE):
                PROMO_DB.clear(); PROMO_DB.update(obj)
            mark_dirty(path)
    if not restored:
        return True, "Không có file nào cần khôi phục"
    return True, "Đã khôi phục: " + ", ".join(restored)

def tg_restore_once():
    """Lúc khởi động: nếu thiếu file dữ liệu thì tải zip đang được ghim trên Telegram về."""
    global _TG_RESTORED
    if _TG_RESTORED:
        return
    _TG_RESTORED = True
    if not _tg_ready():
        return
    try:
        try:
            chat_id = int(TG_BACKUP_CHAT_ID)
        except ValueError:
            chat_id = TG_BACKUP_CHAT_ID
        chat = tg_call("getChat", {"chat_id": chat_id}) or {}
        doc = ((chat.get("result") or {}).get("pinned_message") or {}).get("document")
        if not doc:
            logging.info("AUTO_BACKUP: chưa có bản backup được ghim trên Telegram.")
            return
        info = tg_call("getFile", {"file_id": doc["file_id"]}) or {}
        file_path = (info.get("result") or {}).get("file_path")
        if not file_path:
            logging.error(f"AUTO_BACKUP: không lấy được file backup: {info}")
            return
        r = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}", timeout=60)
        r.raise_for_status()
        ok, msg = restore_from_zip_bytes(r.content, missing_only=True)
        logging.info(f"AUTO_BACKUP khôi phục từ Telegram: {msg}")
    except Exception as e:
        logging.error(f"❌ Lỗi khôi phục từ Telegram: {e}")

def _tg_backup_worker():
    while True:
        time.sleep(10)
        now = time.time()
        with _TG_LOCK:
            dirty = _TG_STATE["dirty"]
            last = _TG_STATE["last_sent"]
        if (dirty and now - last >= TG_BACKUP_MIN_INTERVAL) or (now - last >= TG_BACKUP_EVERY):
            tg_backup_send("tự động")

def start_tg_backup_worker():
    if _tg_ready():
        Thread(target=_tg_backup_worker, daemon=True).start()
        logging.info("✅ Đã bật AUTO_BACKUP dữ liệu lên Telegram.")
    else:
        logging.warning("⚠️ AUTO_BACKUP Telegram chưa bật (thiếu ADMIN_CHAT_ID/BOT_TOKEN).")

# Backup tự động lên một repo GitHub RIÊNG (private) để không mất dữ liệu khi Render chạy lại.
# Biến môi trường: BACKUP_GITHUB_TOKEN, BACKUP_GITHUB_REPO (dạng user/repo), BACKUP_GITHUB_BRANCH (mặc định main)
BACKUP_TOKEN = os.getenv("BACKUP_GITHUB_TOKEN", "")
BACKUP_REPO = os.getenv("BACKUP_GITHUB_REPO", "")
BACKUP_BRANCH = os.getenv("BACKUP_GITHUB_BRANCH", "main")
BACKUP_ENABLED = bool(BACKUP_TOKEN and BACKUP_REPO)

_BACKUP_SHA = {}
_BACKUP_DIRTY = set()
_BACKUP_LOCK = threading.Lock()

def _gh_headers(raw=False):
    return {
        "Authorization": f"Bearer {BACKUP_TOKEN}",
        "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
    }

def _gh_url(name):
    return f"https://api.github.com/repos/{BACKUP_REPO}/contents/{name}"

def _github_restore(path):
    """Nếu file local chưa có (Render vừa deploy lại) thì tải bản backup về."""
    if not BACKUP_ENABLED or os.path.exists(path):
        return
    name = os.path.basename(path)
    last_err = None
    for _ in range(3):
        try:
            r = requests.get(_gh_url(name), headers=_gh_headers(), params={"ref": BACKUP_BRANCH}, timeout=20)
            if r.status_code == 404:
                logging.info(f"Backup: chưa có bản sao của {name}, bắt đầu dữ liệu mới.")
                return
            if r.status_code == 200:
                info = r.json()
                _BACKUP_SHA[name] = info.get("sha")
                if info.get("content"):
                    raw = base64.b64decode(info["content"])
                else:
                    rr = requests.get(_gh_url(name), headers=_gh_headers(raw=True), params={"ref": BACKUP_BRANCH}, timeout=30)
                    rr.raise_for_status()
                    raw = rr.content
                with open(path, "wb") as f:
                    f.write(raw)
                logging.info(f"✅ Backup: đã khôi phục {name} từ GitHub.")
                return
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last_err = str(e)
        time.sleep(2)
    # Không khôi phục được -> dừng để Render tự chạy lại, tránh ghi đè backup bằng dữ liệu rỗng
    logging.critical(f"❌ Không thể khôi phục {name} từ backup ({last_err}). Dừng bot để bảo vệ dữ liệu.")
    sys.exit(1)

def backup_restore(path):
    """Khôi phục file dữ liệu: ưu tiên GitHub, nếu vẫn thiếu thì lấy từ bản backup ghim trên Telegram."""
    if os.path.exists(path):
        return
    _github_restore(path)
    if not os.path.exists(path):
        tg_restore_once()

def backup_upload(path):
    if not os.path.exists(path):
        return
    name = os.path.basename(path)
    with open(path, "rb") as f:
        raw = f.read()
    payload = {
        "message": f"backup {name}",
        "content": base64.b64encode(raw).decode(),
        "branch": BACKUP_BRANCH,
    }
    sha = _BACKUP_SHA.get(name)
    if sha:
        payload["sha"] = sha
    r = requests.put(_gh_url(name), headers=_gh_headers(), json=payload, timeout=30)
    if r.status_code in (409, 422):
        g = requests.get(_gh_url(name), headers=_gh_headers(), params={"ref": BACKUP_BRANCH}, timeout=20)
        if g.status_code == 200:
            payload["sha"] = g.json().get("sha")
        else:
            payload.pop("sha", None)
        r = requests.put(_gh_url(name), headers=_gh_headers(), json=payload, timeout=30)
    if r.status_code in (200, 201):
        _BACKUP_SHA[name] = r.json()["content"]["sha"]
    else:
        raise RuntimeError(f"Backup {name} lỗi HTTP {r.status_code}: {r.text[:200]}")

def mark_dirty(path):
    tg_mark_dirty()
    if BACKUP_ENABLED:
        with _BACKUP_LOCK:
            _BACKUP_DIRTY.add(path)

def flush_backup():
    if not BACKUP_ENABLED:
        return
    with _BACKUP_LOCK:
        items = list(_BACKUP_DIRTY)
        _BACKUP_DIRTY.clear()
    for p in items:
        try:
            backup_upload(p)
        except Exception as e:
            logging.error(f"Lỗi backup {p}: {e}")
            with _BACKUP_LOCK:
                _BACKUP_DIRTY.add(p)

def _backup_worker():
    while True:
        time.sleep(15)
        flush_backup()

def start_backup_worker():
    if BACKUP_ENABLED:
        Thread(target=_backup_worker, daemon=True).start()
        logging.info("✅ Đã bật backup dữ liệu lên GitHub.")
    else:
        logging.warning("⚠️ Chưa cấu hình BACKUP_GITHUB_TOKEN/BACKUP_GITHUB_REPO: dữ liệu sẽ mất khi Render deploy lại nếu không dùng Persistent Disk.")

def atomic_json_dump(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


# ==================== CẤU HÌNH SMM API ====================
SMM_SERVICES_FIXED = {
    # --- FACEBOOK ---
    "fb_mc_6683_1": 6683,
    "fb_mc_6631_2": 6631,
    "fb_mc_6683_3": 6683,
    "fb_mc_6683_4": 6683,
    "fb_mc_6444_1": 6444,
    "fb_mc_6444_2": 6444,
    "fb_mc_6444_3": 6444,
    "cmt_s2_sale": 6452,
    "cmt_s1_sale": 6452,
    "fb_mc_6448_1": 6448,
    "fb_mc_6448_2": 6448,
    "fb_mc_6451_1": 6451,
    "fb_mc_6451_2": 6451,
    "fb_mc_6301_1": 6301,
    "fb_mc_6301_2": 6301,
    "fb_mc_6597_1": 6597,
    "fb_mc_6597_2": 6597,
    "fb_mc_6483_1": 6483,
    "fb_mc_6483_2": 6483,
    # --- TIKTOK ---
    "tt_mc_6717_1": 6717,
    "tt_mc_6717_2": 6717,
    "tt_mc_6717_3": 6717,
    "tt_mc_6717_4": 6717,
    "tt_mc_6717_5": 6717,
    "tt_mc_6717_6": 6717,
    "tt_mc_6717_7": 6717,
    "tt_mc_6641_1": 6641,
    "tt_mc_6641_2": 6641,
    "tt_mc_6641_3": 6641,
    "tt_mc_6641_4": 6641,
    "tt_mc_6641_5": 6641,
    "tt_mc_6641_6": 6641,
    "tt_mc_6492_1": 6492,
    "tt_mc_6492_2": 6492,
    "tt_mc_6492_3": 6492,
    "tt_mc_6492_4": 6492,
    "tt_mc_6492_5": 6492,
    "tt_mc_6317_1": 6317,
    "tt_mc_6317_2": 6317,
    "tt_mc_6317_3": 6317,
    "tt_mc_6495_1": 6495,
    "tt_mc_6495_2": 6495,
    "tt_mc_6495_3": 6495,
    "tt_mc_6495_4": 6495,
    "tt_mc_6496_1": 6496,
    "tt_mc_6496_2": 6496,
    "tt_mc_6688_1": 6688,
    "tt_mc_6688_2": 6688,
    "tt_mc_6688_3": 6688,
    "tt_mc_6688_4": 6688,
    "tt_mc_6688_5": 6688,
    "tt_mc_6688_6": 6688,
    # --- YOUTUBE ---
    "yt_mc_6505_1": 6505,
    "yt_mc_6505_2": 6505,
    "yt_mc_6505_3": 6505,
    "yt_mc_6508_1": 6508,
    "yt_mc_6508_2": 6508,
    "yt_mc_6510": 6510,
    # --- INSTAGRAM ---
    "ig_mc_6501_1": 6501,
    "ig_mc_6501_2": 6501,
    "ig_mc_6501_3": 6501,
    "ig_mc_6503_1": 6503,
    "ig_mc_6503_2": 6503,
    "ig_mc_6503_3": 6503,
    "ig_mc_6503_4": 6503,
    "ig_mc_6503_5": 6503,
}

def get_smm_service_id(item_id):
    if item_id in SMM_SERVICES_FIXED:
        return SMM_SERVICES_FIXED[item_id]

    try:
        parts = item_id.split("_")
        for part in parts:
            if part.isdigit() and len(part) >= 4:
                return int(part)
    except Exception:
        pass

    return None

SMM_API_URL = "https://seedingmarketing.net/api/v2"
SMM_API_KEY = os.getenv("SMM_API_KEY")

def call_smm_api(action, data=None):
    if data is None:
        data = {}
    data["key"] = SMM_API_KEY
    data["action"] = action
    try:
        response = requests.post(SMM_API_URL, data=data, timeout=15)
        return response.json()
    except Exception as e:
        logging.error(f"Lỗi kết nối SMM API ({action}): {e}")
        return None

def _load_json(path, default):
    backup_restore(path)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # File hỏng: giữ lại bản hỏng để cứu, không ghi đè mất dữ liệu
            logging.error(f"File {path} bị lỗi ({e}), đã đổi tên để giữ lại.")
            try:
                os.replace(path, f"{path}.corrupt-{int(time.time())}")
            except Exception:
                pass
    return default

def _write_json_now(path, obj, label):
    with DB_LOCK:
        for _ in range(5):
            try:
                atomic_json_dump(path, obj)
                mark_dirty(path)
                return
            except RuntimeError:
                time.sleep(0.01)  # dict đổi kích thước giữa chừng, thử lại
            except Exception as e:
                logging.error(f"Lỗi khi lưu database {label}: {e}")
                return

# Lưu file chạy ở luồng nền để bot không bị khựng khi nhiều người dùng cùng lúc.
# Nhiều lần gọi lưu liên tiếp được gộp thành 1 lần ghi (trễ tối đa ~0.3 giây).
_SAVE_PENDING = {}
_SAVE_PENDING_LOCK = threading.Lock()
_SAVE_EVENT = threading.Event()

def _save_json(path, obj, label):
    with _SAVE_PENDING_LOCK:
        _SAVE_PENDING[path] = (obj, label)
    _SAVE_EVENT.set()

def flush_saves():
    """Ghi ngay tất cả dữ liệu đang chờ (gọi khi tắt bot)."""
    with _SAVE_PENDING_LOCK:
        items = list(_SAVE_PENDING.items())
        _SAVE_PENDING.clear()
    for path, (obj, label) in items:
        _write_json_now(path, obj, label)

def _save_worker():
    while True:
        _SAVE_EVENT.wait()
        time.sleep(0.3)
        _SAVE_EVENT.clear()
        try:
            flush_saves()
        except Exception as e:
            logging.error(f"Lỗi luồng lưu dữ liệu: {e}")

Thread(target=_save_worker, daemon=True).start()
import atexit
atexit.register(flush_saves)

def load_users_db():
    data = _load_json(DB_FILE, {})
    try:
        return {int(k): v for k, v in data.items()}
    except Exception:
        return {}

def save_users_db():
    _save_json(DB_FILE, USERS_DB, "user")

USERS_DB = load_users_db()

def load_gitcode_db():
    data = _load_json(GITCODE_DB_FILE, {})
    return data if isinstance(data, dict) else {}

def save_gitcode_db():
    _save_json(GITCODE_DB_FILE, GITCODE_DB, "gitcode")

GITCODE_DB = load_gitcode_db()

def load_sms_db():
    data = _load_json(SMS_DB_FILE, {})
    try:
        return {int(k): v for k, v in data.items()}
    except Exception:
        return {}

def save_sms_db():
    _save_json(SMS_DB_FILE, SMS_DB, "sms")

SMS_DB = load_sms_db()

# Danh sách mã giao dịch SePay đã xử lý (chống cộng tiền 2 lần)
_tx_data = _load_json(SEPAY_TX_FILE, {})
PROCESSED_TX = _tx_data if isinstance(_tx_data, dict) else {}

# ==================== KHUYẾN MÃI NẠP TIỀN (ADMIN CÀI ĐẶT) ====================
_promo_data = _load_json(PROMO_FILE, {})
PROMO_DB = _promo_data if isinstance(_promo_data, dict) else {}

def get_promo_percent():
    try:
        pct = float(PROMO_DB.get("percent", 0))
    except Exception:
        pct = 0.0
    return pct if pct > 0 else 0.0

def set_promo_percent(pct):
    with DB_LOCK:
        PROMO_DB["percent"] = float(pct)
        _save_json(PROMO_FILE, PROMO_DB, "promo")

def calc_bonus(amount):
    """Tiền thưởng khuyến mãi = % x số tiền khách nạp."""
    pct = get_promo_percent()
    if pct <= 0:
        return 0.0
    return float(round(float(amount) * pct / 100))

def mark_tx_processed(tx_key):
    with DB_LOCK:
        PROCESSED_TX[tx_key] = int(time.time())
        if len(PROCESSED_TX) > 5000:
            for k in sorted(PROCESSED_TX, key=PROCESSED_TX.get)[:1000]:
                PROCESSED_TX.pop(k, None)
        _save_json(SEPAY_TX_FILE, PROCESSED_TX, "sepay_tx")

GROUPS_PAGE_1 = [
    {"id": "gr_1", "name": "tay ( ten zin )", "link": "https://www.facebook.com/groups/689086271422497?locale=vi_VN", "mem": 1800000},
    {"id": "gr_2", "name": "Mua Ban Acc Playtogether", "link": "https://www.facebook.com/groups/1438781170008706?locale=vi_VN", "mem": 1700000},
    {"id": "gr_3", "name": "tay ( ten zin )", "link": "https://www.facebook.com/groups/manchaliladkiyan?locale=vi_VN", "mem": 1600000},
    {"id": "gr_4", "name": "tay ( ten zin )", "link": "https://www.facebook.com/groups/3480088572306674?locale=vi_VN", "mem": 1600000},
    {"id": "gr_5", "name": "Mua Ban Acc Playtogether", "link": "https://www.facebook.com/groups/161510555971506", "mem": 1500000},
    {"id": "gr_6", "name": "tay ( ten zin )", "link": "https://www.facebook.com/groups/887995696353613?locale=vi_VN", "mem": 1400000},
    {"id": "gr_7", "name": "tay ( ten zin )", "link": "https://www.facebook.com/groups/185994147837943?locale=vi_VN", "mem": 1300000},
    {"id": "gr_8", "name": "tay ( ten zin )", "link": "https://www.facebook.com/groups/7985277011546263?locale=vi_VN", "mem": 1100000},
    {"id": "gr_9", "name": "tay ( ten zin )", "link": "https://www.facebook.com/groups/1381057159109257", "mem": 1100000},
    {"id": "gr_10", "name": "Dien Chau - A Day Roi", "link": "https://www.facebook.com/groups/298182716262940?locale=vi_VN", "mem": 1000000},
    {"id": "gr_11", "name": "Review Du Lich Phu Quoc", "link": "https://www.facebook.com/groups/greatsingerkk", "mem": 738000},
    {"id": "gr_12", "name": "Hoi Ga Tre Sai Gon", "link": "https://www.facebook.com/groups/3273435586305961?locale=vi_VN", "mem": 323000},
    {"id": "gr_13", "name": "mua ban nick lien quan", "link": "https://www.facebook.com/share/g/1BDrX39GNg/", "mem": 245000},
    {"id": "gr_14", "name": "Mua Ban Acc Lien Quan Garena", "link": "https://www.facebook.com/share/g/1CsvY8mFUw/", "mem": 242000},
    {"id": "gr_15", "name": "Van Chuyen Hang Quoc Te Viet - Nhat", "link": "https://www.facebook.com/groups/fbccibd?locale=vi_VN", "mem": 229000},
    {"id": "gr_16", "name": "Mua Ban Acc Play Together VNG", "link": "https://www.facebook.com/groups/BRTI2017?locale=vi_VN", "mem": 188000},
    {"id": "gr_17", "name": "Du Lich Ha Giang", "link": "https://www.facebook.com/share/g/18pzo2TLyS/", "mem": 179000},
    {"id": "gr_18", "name": "Du Lich Nhat Ban Hom Nay An Gi", "link": "https://www.facebook.com/groups/983317666180522", "mem": 172000},
    {"id": "gr_19", "name": "Du Lich Nhat Ban Hom Nay An Gi", "link": "https://www.facebook.com/groups/983317666180522?locale=vi_VN", "mem": 171000},
    {"id": "gr_20", "name": "Du Lich Nha Trang", "link": "https://www.facebook.com/groups/557094589109113?locale=vi_VN", "mem": 171000},
    {"id": "gr_21", "name": "Du Lich Da Lat", "link": "https://www.facebook.com/groups/375132383055054?locale=vi_VN", "mem": 164000},
    {"id": "gr_22", "name": "Du Lich Da Lat - An Uong 24/7", "link": "https://www.facebook.com/groups/CelineDionLovers?locale=vi_VN", "mem": 162000},
    {"id": "gr_23", "name": "Du Lich Phu Quoc", "link": "https://www.facebook.com/groups/wildlifeandnatureworld?locale=vi_VN", "mem": 153000},
    {"id": "gr_24", "name": "Mua Ban Acc Lien Quan Garena", "link": "https://www.facebook.com/groups/ngolongolsyo?locale=vi_VN", "mem": 141000},
    {"id": "gr_25", "name": "Du Lich Da Lat - San May", "link": "https://www.facebook.com/share/g/1E3ba8W155/", "mem": 139000},
    {"id": "gr_26", "name": "Mua Ban Acc Lien Quan Garena", "link": "https://www.facebook.com/groups/DU7Collegestudent?locale=vi_VN", "mem": 139000},
    {"id": "gr_27", "name": "Review Do An Ngon Hai Phong", "link": "https://www.facebook.com/groups/909945396604595", "mem": 138000},
    {"id": "gr_28", "name": "Du Lich Nhat Ban", "link": "https://www.facebook.com/share/g/195Fx9K57t/", "mem": 133000},
    {"id": "gr_29", "name": "Review Du Lich Phu Quoc", "link": "https://www.facebook.com/groups/769740409862377?locale=vi_VN", "mem": 130000},
    {"id": "gr_30", "name": "Review Du Lich Hue", "link": "https://www.facebook.com/groups/hikmatodanai?locale=vi_VN", "mem": 129000},
]

GROUPS_PAGE_2 = [
    {"id": "gr_31", "name": "Du lich Nhat Ban tat tan tat", "link": "https://www.facebook.com/groups/736302034203087?locale=vi_VN", "mem": 94000},
    {"id": "gr_32", "name": "Dien Dan Co Vua Viet Nam", "link": "https://www.facebook.com/groups/1695531627365300?locale=vi_VN", "mem": 91000},
    {"id": "gr_33", "name": "Son La An Gi - O dau", "link": "https://www.facebook.com/groups/thirimingalar?locale=vi_VN", "mem": 89000},
    {"id": "gr_34", "name": "Lam Dep Dung Cach", "link": "https://www.facebook.com/groups/357324438763492?locale=vi_VN", "mem": 86000},
    {"id": "gr_35", "name": "CHO DO CU HA NOI", "link": "https://www.facebook.com/groups/757596628675181?locale=vi_VN", "mem": 83000},
    {"id": "gr_36", "name": "THANH LY BAN PHIM CO", "link": "https://www.facebook.com/groups/288619541292061?locale=vi_VN", "mem": 80000},
    {"id": "gr_37", "name": "Hoi thanh ly DO GIA DUNG", "link": "https://www.facebook.com/groups/501098514539408", "mem": 79000},
    {"id": "gr_38", "name": "DAY HOC LAM BANH", "link": "https://www.facebook.com/groups/281081399811830?locale=vi_VN", "mem": 73000},
    {"id": "gr_39", "name": "Review Phu Quoc - An Uong", "link": "https://www.facebook.com/share/g/1FseeFsizg/", "mem": 73000},
    {"id": "gr_40", "name": "Ha Giang Review", "link": "https://www.facebook.com/groups/868810833768716?locale=vi_VN", "mem": 72000},
    {"id": "gr_41", "name": "thanh pho vinh nghe an", "link": "https://www.facebook.com/groups/giriullapi", "mem": 72000},
    {"id": "gr_42", "name": "Review Da Nang", "link": "https://www.facebook.com/groups/2536108593085986?locale=vi_VN", "mem": 72000},
    {"id": "gr_43", "name": "DAY HOC LAM BANH KEM", "link": "https://www.facebook.com/groups/281081399811830?locale=vi_VN", "mem": 71000},
    {"id": "gr_44", "name": "thanh pho vinh", "link": "https://www.facebook.com/share/g/1JMXpop7Nw/", "mem": 68000},
    {"id": "gr_45", "name": "Cong Dong Mua Ban - Pass Ve", "link": "https://www.facebook.com/share/g/1Cb1jfmWtg/", "mem": 67000},
    {"id": "gr_46", "name": "Decor Ban Hoc", "link": "https://www.facebook.com/groups/2537360503182840?locale=vi_VN", "mem": 66000},
    {"id": "gr_47", "name": "Du Lich SAPA", "link": "https://www.facebook.com/groups/738174983534414?locale=vi_VN", "mem": 64000},
    {"id": "gr_48", "name": "Thanh Ly Do Dung Quan Tra Sua", "link": "https://www.facebook.com/groups/913131818727026", "mem": 64000},
    {"id": "gr_49", "name": "Sinh vien Dai Hoc Vinh", "link": "https://www.facebook.com/groups/491509203373042?locale=vi_VN", "mem": 64000},
    {"id": "gr_50", "name": "Da Lat Travel", "link": "https://www.facebook.com/groups/1537460047202274?locale=vi_VN", "mem": 63000},
    {"id": "gr_51", "name": "Cho Laptop & PC", "link": "https://www.facebook.com/groups/1656524734596570?locale=vi_VN", "mem": 62000},
    {"id": "gr_52", "name": "Vietnam Travel Guide", "link": "https://www.facebook.com/groups/250058642687175", "mem": 61000},
    {"id": "gr_53", "name": "Mua Ban Ban Phim Co", "link": "https://www.facebook.com/groups/1574398229285291?locale=vi_VN", "mem": 61000},
    {"id": "gr_54", "name": "Chia se meo tiet kiem", "link": "https://www.facebook.com/groups/kedma.tn.tunisie?locale=vi_VN", "mem": 50000},
    {"id": "gr_55", "name": "cho tien giang", "link": "https://www.facebook.com/groups/bscbuksu?locale=vi_VN", "mem": 46000},
    {"id": "gr_56", "name": "Mua Ban Trang Suc Da Quy", "link": "https://www.facebook.com/groups/mowahebe3rf?locale=vi_VN", "mem": 48000},
    {"id": "gr_57", "name": "ซื้อขาย โทรศัพท์มือถือ", "link": "https://www.facebook.com/groups/1645001565772954?locale=vi_VN", "mem": 41000},
    {"id": "gr_58", "name": "Viec Lam Online", "link": "https://www.facebook.com/groups/7971682599509216?locale=vi_VN", "mem": 39000},
    {"id": "gr_59", "name": "Du Lich Tam Dao", "link": "https://www.facebook.com/groups/666959094009922?locale=vi_VN", "mem": 30000},
]

ALL_GROUPS = GROUPS_PAGE_1 + GROUPS_PAGE_2

CATEGORIES_PAGE_1 = [
    {"id": "cat_zalo", "title": "🛡️ TÀI KHOẢN ZALO"},
    {"id": "cat_tele", "title": "✈️ TELEGRAM (+84)"},
    {"id": "cat_hotmail", "title": "📧 HOTMAIL - OUTLOOK"},
    {"id": "cat_gmail", "title": "📮 TÀI KHOẢN GMAIL"},
    {"id": "cat_vpn", "title": "🌐 TÀI KHOẢN VPN"},
    {"id": "cat_proxy", "title": "🔌 TÀI KHOẢN PROXY"},
    {"id": "cat_tiktok", "title": "🎵 TÀI KHOẢN TIKTOK"},
    {"id": "cat_fb_ngoai", "title": "🌍 FACEBOOK NGOẠI NUÔI"},
]

CATEGORIES_PAGE_2 = [
    {"id": "cat_fb_viet", "title": "🇻🇳 FACEBOOK VIỆT NUÔI"},
    {"id": "cat_fb_co", "title": "💎 FACEBOOK CỔ - SIÊU CỔ"},
    {"id": "cat_fanpage", "title": "⭐ FANPAGE"},
    {"id": "cat_gemini", "title": "🤖 GEMINI PRO"},
    {"id": "cat_youtube", "title": "▶️ YOUTUBE PREMIUM"},
    {"id": "cat_groups", "title": "📋 DANH SÁCH NHÓM (GROUP)"},
]

SERVICES = {
    "fb_like": {
        "title": "👍 TĂNG LIKE BÀI VIẾT",
        "items": [
            {"id": "fb_mc_6683_1", "name": "✨ S1 Like clone xịn", "price": 99.0},
            {"id": "fb_mc_6631_2", "name": "👆 S1 Like bấm tay vn   buff 100 trở lên", "price": 130.4},
            {"id": "fb_mc_6683_3", "name": "🛡️ S2 Like post dự phòng", "price": 110.35},
            {"id": "fb_mc_6683_4", "name": "⚡ S2 Like clone nhanh", "price": 90.0},
        ]
    },
    "fb_follow": {
        "title": "👤 Tăng follow Profile & Page",
        "items": [
            {"id": "fb_mc_6444_1", "name": "👑 S8 Follow Clone + Vip", "price": 69.72},
            {"id": "fb_mc_6444_2", "name": "✋ Follow clone TAY", "price": 73.43},
            {"id": "fb_mc_6444_3", "name": "🇻🇳 Follow clone Việt", "price": 86.0},
        ]
    },
    "fb_cmt": {
        "title": "💬 TĂNG BÌNH LUẬN",
        "items": [
            {"id": "cmt_s2_sale", "name": "🏷️ S2 Cmt Sale", "price": 1480.4},
            {"id": "cmt_s1_sale", "name": "🔥 S1 Cmt Sale", "price": 1640.0},
        ]
    },
    "fb_page": {
        "title": "⭐ TĂNG LIKE & FOLLOW PAGE",
        "items": [
            {"id": "fb_mc_6448_1", "name": "✍️ S2 Like page + follow TAY", "price": 70.3},
            {"id": "fb_mc_6448_2", "name": "🌟 Like + Follow Page Bấm Tay", "price": 99.0},
        ]
    },
    "fb_group": {
        "title": "👥 TĂNG THÀNH VIÊN NHÓM (GROUP)",
        "items": [
            {"id": "fb_mc_6451_1", "name": "💎 S1 Member Group Chất Lượng", "price": 120.0},
            {"id": "fb_mc_6451_2", "name": "🛡️ Member Group Bấm Tay Uy Tín", "price": 180.0},
        ]
    },
    "fb_share": {
        "title": "🔄 Tăng chia sẻ bài viết",
        "items": [
            {"id": "fb_mc_6301_1", "name": "🌐 Share bài viết ( acc có nhiều bạn bè - lên nhanh)", "price": 210.62},
            {"id": "fb_mc_6301_2", "name": "👻 S68 - Share - (Profile-Page-Group)- Không áp dụng video", "price": 102.06},
        ]
    },
    "fb_view": {
        "title": "👁️ Tăng view video",
        "items": [
            {"id": "fb_mc_6597_1", "name": "🎬 View reel độc quyền", "price": 61.2},
            {"id": "fb_mc_6597_2", "name": "⏱️  View /Reels 3s tốc độ nhanh [ Vip ]", "price": 106.8},
        ]
    },
    "fb_story": {
        "title": "👁️ TĂNG VIEW STORY",
        "items": [
            {"id": "fb_mc_6483_1", "name": "📱 S1 View Story Facebook", "price": 50.0},
            {"id": "fb_mc_6483_2", "name": "📱 S32 - view story - tây clone", "price": 76.0},
        ]
    },
    "tt_like": {
        "title": "🎵 TIKTOK - TĂNG TIM (LIKE)",
        "items": [
            {"id": "tt_mc_6717_1", "name": "⚡ S6 Like tiktok Tây Nhanh", "price": 25.51},
            {"id": "tt_mc_6717_2", "name": "🌍 S7 Like Tiktok tây- Không BH", "price": 25.98},
            {"id": "tt_mc_6717_3", "name": "🛡️ S5 Like tiktok Tây Nhanh | BH 30 ngày", "price": 39.32},
            {"id": "tt_mc_6717_4", "name": "👁️ S9 TikTok- ( Like ) tây + VIEW", "price": 26.34},
            {"id": "tt_mc_6717_5", "name": "🇻🇳 S4 like tiktok việt", "price": 30.79},
            {"id": "tt_mc_6717_6", "name": "🔥 S2 Like tiktok việt high", "price": 39.5},
            {"id": "tt_mc_6717_7", "name": "💸 Like TikTok việt giá rẻ", "price": 28.45},
        ]
    },
    "tt_follow": {
        "title": "👤 TIKTOK - TĂNG THEO DÕI",
        "items": [
            {"id": "tt_mc_6641_1", "name": "🤖 Tiktok Follow clone (19-6)", "price": 87.03},
            {"id": "tt_mc_6641_2", "name": "🇻🇳 S4 Follow TikTok Việt", "price": 59.0},
            {"id": "tt_mc_6641_3", "name": "✨ S5 Follow TikTok sale new", "price": 51.2},
            {"id": "tt_mc_6641_4", "name": "📈 S6 Follow tiktok việt ổn định", "price": 47.3},
            {"id": "tt_mc_6641_5", "name": "🚀 Follow TikTok Việt High", "price": 75.9},
            {"id": "tt_mc_6641_6", "name": "⭐ S2 Follow TikTok Việt High", "price": 109.7},
        ]
    },
    "tt_view": {
        "title": "👁️ TIKTOK - TĂNG LƯỢT XEM (VIEW)",
        "items": [
            {"id": "tt_mc_6492_1", "name": "📊 S64 View Tiktok | KBH | min:100", "price": 22.15},
            {"id": "tt_mc_6492_2", "name": "📉 S11 View Tiktok | KBH | min:100 | Không BH", "price": 21.0},
            {"id": "tt_mc_6492_3", "name": "📌 S6 View Tiktok | KBH | min:100 | Không BH", "price": 22.18},
            {"id": "tt_mc_6492_4", "name": "🚀 View tiktok siêu tốc | KBH | dự phòng", "price": 22.15},
            {"id": "tt_mc_6492_5", "name": "💎 S3 view tiktok sale | Không tụt", "price": 1645.0},
        ]
    },
    "tt_cmt": {
        "title": "💬 TIKTOK - TĂNG BÌNH LUẬN",
        "items": [
            {"id": "tt_mc_6317_1", "name": "⚡ S4 Cmt Tiktok Việt nhanh", "price": 215.0},
            {"id": "tt_mc_6317_2", "name": "🛡️ S6 cmt tiktok Việt High ổn định", "price": 169.5},
            {"id": "tt_mc_6317_3", "name": "✨ S7 cmt tiktok Việt New", "price": 163.0},
        ]
    },
    "tt_share": {
        "title": "🔄 TIKTOK - TĂNG SHARE",
        "items": [
            {"id": "tt_mc_6495_1", "name": "🏷️ S2 Share video tiktok Sale", "price": 13020.0},
            {"id": "tt_mc_6495_2", "name": "🔴 Share tiktok live Việt Nam", "price": 38.85},
            {"id": "tt_mc_6495_3", "name": "🇻🇳 Share video tiktok Việt Nam", "price": 35.6},
            {"id": "tt_mc_6495_4", "name": "💸 S2 Share video tiktok giá rẻ | KBH", "price": 24.9},
        ]
    },
    "tt_save": {
        "title": "💾 TIKTOK - TĂNG SAVE (LƯU VIDEO)",
        "items": [
            {"id": "tt_mc_6496_1", "name": "⚡ S2 save video Việt nhanh", "price": 31.05},
            {"id": "tt_mc_6496_2", "name": "🌍 S3 save video [Tài nguyên Tây] | KBH", "price": 21.39},
        ]
    },
    "tt_live_vn": {
        "title": "🔴 TIKTOK - LIVE VIỆT NAM",
        "items": [
            {"id": "tt_mc_6688_1", "name": "⏱️ Live Tiktok việt - 30 phút (New - Nên dùng)", "price": 1234.89},
            {"id": "tt_mc_6688_2", "name": "⏱️ Live Tiktok việt - 60 phút (New - Nên dùng)", "price": 1377.36},
            {"id": "tt_mc_6688_3", "name": "⏱️ Live Tiktok việt - 90 phút (New - Nên dùng)", "price": 1556.04},
            {"id": "tt_mc_6688_4", "name": "⏱️ Live Tiktok việt - 120 phút (New - Nên dùng)", "price": 1734.71},
            {"id": "tt_mc_6688_5", "name": "⏱️ Live Tiktok việt - 180 phút (New - Nên dùng)", "price": 1592.07},
            {"id": "tt_mc_6688_6", "name": "⏱️ Live Tiktok việt - 360 phút (New - Nên dùng)", "price": 1549.43},
        ]
    },
    "yt_sub": {
        "title": "▶️ YOUTUBE - TĂNG ĐĂNG KÝ KÊNH",
        "items": [
            {"id": "yt_mc_6505_1", "name": "LÊN CỰC NHANH - Tuột 100% -YouTube Subscribers | Không bảo hành", "price": 590.14},
            {"id": "yt_mc_6505_2", "name": "S23 - Sub youtube - new - Tài khoản cực trâu - Kênh bắt buộc có video trên 2 phút", "price": 1048.09},
            {"id": "yt_mc_6505_3", "name": "Youtube sub Max 1k Lên nhanh", "price": 870.3},
        ]
    },
    "yt_like": {
        "title": "👍 YOUTUBE - TĂNG LIKE",
        "items": [
            {"id": "yt_mc_6508_1", "name": "Like rẻ nhanh | 20k/Day | Không bảo hành", "price": 90.42},
            {"id": "yt_mc_6508_2", "name": "S4 like nhanh chất lượng cao | Không bảo hành", "price": 105.58},
        ]
    },
    "yt_view": {
        "title": "👁️ YOUTUBE - TĂNG VIEW & LIVESTREAM",
        "items": [
            {"id": "yt_mc_6510", "name": "S1 Mắt Live YTB", "price": 50.2},
        ]
    },
    "ig_like": {
        "title": "❤️ INSTAGRAM - TĂNG LIKE",
        "items": [
            {"id": "ig_mc_6501_1", "name": "Like Instagram Việt xịn", "price": 70.5},
            {"id": "ig_mc_6501_2", "name": "S6 Like tây | Không bảo hành", "price": 100.93},
            {"id": "ig_mc_6501_3", "name": "S7 Like tây | Bảo hành 7 ngày", "price": 130.59},
        ]
    },
    "ig_follow": {
        "title": "👤 INSTAGRAM - TĂNG THEO DÕI",
        "items": [
            {"id": "ig_mc_6503_1", "name": "S1 Follower instagram Việt", "price": 47.5},
            {"id": "ig_mc_6503_2", "name": "Sv2 Follow việt giá rẻ", "price": 57.25},
            {"id": "ig_mc_6503_3", "name": "S5 follow Instagram Việt high", "price": 107.71},
            {"id": "ig_mc_6503_4", "name": "S2 Follower tây nhanh | Không bảo hành", "price": 56.49},
            {"id": "ig_mc_6503_5", "name": "Follow instagram - tây | Bảo hành 7 ngày", "price": 70.69},
        ]
    }
}

SMS_PACKAGES = {
    "sms_thuong": {
        "title": "📱 SMS THƯỜNG",
        "packages": [
            {"id": "sms_t_1h", "name": "Gói 1 giờ", "duration": 3600, "price": 20000},
            {"id": "sms_t_1d", "name": "Gói 1 ngày", "duration": 86400, "price": 80000},
            {"id": "sms_t_1w", "name": "Gói 1 tuần", "duration": 604800, "price": 380000},
            {"id": "sms_t_perm", "name": "Gói vĩnh viễn", "duration": 3153600000, "price": 700000},
        ]
    },
    "sms_vip": {
        "title": "👑 SMS VIP",
        "packages": [
            {"id": "sms_v_1h", "name": "Gói 1 giờ VIP", "duration": 3600, "price": 45000},
            {"id": "sms_v_1d", "name": "Gói 1 ngày VIP", "duration": 86400, "price": 120000},
            {"id": "sms_v_1w", "name": "Gói 1 tuần VIP", "duration": 604800, "price": 500000},
            {"id": "sms_v_perm", "name": "Gói vĩnh viễn VIP", "duration": 3153600000, "price": 1120000},
        ]
    }
}

# Khai báo các trạng thái Conversation
(
    INPUT_LINK, INPUT_QUANTITY, INPUT_TOPUP_AMOUNT, INPUT_GITCODE, 
    INPUT_CREATE_CODE_CUSTOM, INPUT_ADMIN_EDIT_USER, INPUT_SMS_PHONE, 
    INPUT_BROADCAST_PHOTO, INPUT_BROADCAST_TEXT, 
    INPUT_PRIVATE_MSG_USER_ID, INPUT_PRIVATE_MSG_PHOTO, INPUT_PRIVATE_MSG_TEXT,
    INPUT_CREATE_BOT_REQUIREMENTS, INPUT_USER_FEEDBACK, INPUT_PROMO_PERCENT,
    INPUT_BULK_TOPUP
) = range(16)

# ==================== CỘNG SỐ DƯ HÀNG LOẠT (ADMIN, KHÔNG THÔNG BÁO CHO KHÁCH) ====================
def _parse_bulk_amount(tok):
    """Đọc số tiền: 50000, 50.000, 50,000, 50k, 50000đ ..."""
    t = tok.lower().replace(".", "").replace(",", "").replace("đ", "").replace("vnd", "").strip()
    mult = 1
    if t.endswith("k"):
        mult, t = 1000, t[:-1]
    val = float(t) * mult
    if val <= 0:
        raise ValueError
    return val

def parse_bulk_topup(text):
    """Trả về (mode, data, errors). mode = 'all' | 'list'."""
    entries, errors, all_amount = {}, [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p for p in re.split(r"[\s:|=;]+", line) if p]
        if len(parts) < 2:
            errors.append(f"Dòng sai cú pháp: {line}")
            continue
        try:
            amount = _parse_bulk_amount(parts[-1])
        except ValueError:
            errors.append(f"Số tiền không hợp lệ: {line}")
            continue
        if parts[0].lower() in ("all", "tatca", "tất_cả"):
            all_amount = amount
            continue
        try:
            uid = int(parts[0])
            if uid <= 0 or len(str(uid)) > 13:
                raise ValueError
        except ValueError:
            errors.append(f"ID không hợp lệ: {line}")
            continue
        entries[uid] = entries.get(uid, 0) + amount
    if all_amount is not None:
        if entries:
            return "error", None, ["Dòng ALL phải dùng riêng, không trộn với danh sách ID."]
        return "all", all_amount, errors
    return "list", entries, errors

async def receive_bulk_topup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    mode, data, errors = parse_bulk_topup(update.message.text or "")
    back_kb = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]

    if mode == "error" or (mode == "list" and not data):
        err_txt = "\n".join(errors) if errors else "Không có dòng hợp lệ nào."
        await update.message.reply_text(
            f"⚠️ <b>Không đọc được dữ liệu:</b>\n{html.escape(err_txt)}\n\n💬 Vui lòng gửi lại theo mẫu:\n<code>ID SỐ_TIỀN</code> (mỗi khách 1 dòng)",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(back_kb)
        )
        return INPUT_BULK_TOPUP

    missing = []
    if mode == "all":
        context.user_data["bulk_topup"] = {"mode": "all", "amount": data}
        total_users = len(USERS_DB)
        summary = (
            f"👥 Áp dụng cho <b>TẤT CẢ {total_users} khách</b>\n"
            f"💵 Mỗi khách: <code>+{data:,.0f}đ</code>\n"
            f"💰 Tổng cộng: <code>{data * total_users:,.0f}đ</code>"
        )
    else:
        # ID chưa có trong dữ liệu (khách cũ bị mất dữ liệu) vẫn được cộng: bot sẽ tạo lại tài khoản cho ID đó
        valid = dict(data)
        missing = [uid for uid in data if uid not in USERS_DB]
        context.user_data["bulk_topup"] = {"mode": "list", "entries": valid}
        lines = [f"• <code>{uid}</code>: +{amt:,.0f}đ" for uid, amt in list(valid.items())[:30]]
        if len(valid) > 30:
            lines.append(f"... và {len(valid) - 30} khách khác")
        summary = (
            f"👥 Số khách: <b>{len(valid)}</b>\n"
            f"💰 Tổng cộng: <code>{sum(valid.values()):,.0f}đ</code>\n\n" + "\n".join(lines)
        )

    warn = ""
    if missing:
        warn += f"\n\n🆕 <b>{len(missing)} ID chưa có dữ liệu (sẽ được tạo lại khi cộng):</b> " + ", ".join(f"<code>{m}</code>" for m in missing[:20])
    if errors:
        warn += "\n\n⚠️ <b>Dòng lỗi (bỏ qua):</b>\n" + html.escape("\n".join(errors[:10]))

    await update.message.reply_text(
        f"📋 <b>XÁC NHẬN CỘNG SỐ DƯ HÀNG LOẠT</b>\n----------------------------------------\n{summary}{warn}\n\n"
        f"🔕 <i>Khách hàng sẽ KHÔNG nhận thông báo.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Xác nhận cộng", callback_data="bulk_topup_confirm")],
            [InlineKeyboardButton("❌ Hủy", callback_data="admin_panel")]
        ])
    )
    return ConversationHandler.END

# Các dịch vụ bình luận: KHÔNG chạy tự động, gửi đơn về Admin để chạy tay
MANUAL_ORDER_CATS = ("fb_cmt", "tt_cmt")

def build_bank_choice(amount):
    """Màn hình cho khách chọn 1 trong các STK để chuyển khoản."""
    pct = get_promo_percent()
    promo_text = ""
    if pct > 0:
        bonus = calc_bonus(amount)
        promo_text = (
            f"🎉 <b>HÔM NAY KHUYẾN MÃI NẠP +{pct:g}%</b>\n"
            f"🎁 Nạp <code>{amount:,.0f}đ</code> nhận thêm <code>+{bonus:,.0f}đ</code> "
            f"(tổng <code>{amount + bonus:,.0f}đ</code>)\n\n"
        )
    text = (
        f"🏦 <b>CHỌN TÀI KHOẢN NGÂN HÀNG</b>\n"
        f"════════════════════════════════\n"
        f"{promo_text}"
        f"💵 <b>Số tiền nạp:</b> <code>{amount:,.0f} VNĐ</code>\n\n"
        f"👇 <i>Vui lòng chọn số tài khoản bạn muốn chuyển khoản:</i>"
    )
    keyboard = []
    for i, b in enumerate(BANK_ACCOUNTS):
        keyboard.append([InlineKeyboardButton(f"🏦 {b['bank_name']} - {b['account_no']}", callback_data=f"bank:{i}:{int(amount)}")])
    keyboard.append([InlineKeyboardButton("🔄 Chọn Lại Mệnh Giá", callback_data="nap_tien")])
    return text, InlineKeyboardMarkup(keyboard)

def build_topup_qr(user_id, amount, bank_idx):
    """Tạo link QR + nội dung chuyển khoản (có hiển thị khuyến mãi nếu admin đang bật)."""
    if bank_idx < 0 or bank_idx >= len(BANK_ACCOUNTS):
        bank_idx = 0
    bank = BANK_ACCOUNTS[bank_idx]
    qr_url = (
        f"https://img.vietqr.io/image/{bank['bank_name']}-{bank['account_no']}-compact2.png"
        f"?amount={int(amount)}&addInfo={user_id}&accountName={bank['account_name'].replace(' ', '%20')}"
    )
    pct = get_promo_percent()
    promo_text = ""
    if pct > 0:
        bonus = calc_bonus(amount)
        promo_text = (
            f"🎉 <b>HÔM NAY KHUYẾN MÃI NẠP +{pct:g}%</b>\n"
            f"🎁 Thưởng thêm: <code>+{bonus:,.0f} VNĐ</code>\n"
            f"💰 Tổng nhận được: <code>{amount + bonus:,.0f} VNĐ</code>\n"
            f"────────────────────────\n"
        )
    caption = (
        f"💳 <b>THÔNG TIN CHUYỂN KHOẢN NẠP TIỀN</b>\n"
        f"════════════════════════════════\n"
        f"{promo_text}"
        f"🏦 <b>Ngân hàng:</b> <code>{bank['bank_name']}</code>\n"
        f"🔢 <b>STK:</b> <code>{bank['account_no']}</code>\n"
        f"👤 <b>Chủ TK:</b> <code>{bank['account_name']}</code>\n"
        f"💵 <b>Số tiền:</b> <code>{amount:,.0f} VNĐ</code>\n"
        f"📝 <b>Nội dung ck (BẮT BUỘC):</b> <code>{user_id}</code>\n\n"
        f"⚠️ <i>LƯU Ý: Vui lòng chuyển chính xác nội dung ID <code>{user_id}</code> để hệ thống cộng tiền tự động!</i>"
    )
    return qr_url, caption

def is_admin(user_id, username):
    return str(user_id) == str(ADMIN_CHAT_ID) or (username and username == ADMIN_USERNAME.replace('@',''))

def get_stock_count(cat_id):
    if cat_id == "cat_groups":
        return len(ALL_GROUPS)
    file_path = f"data/{cat_id}.txt"
    if not os.path.exists(file_path):
        return 0
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
            return len(lines)
    except Exception:
        return 0

def get_user_data(user_id):
    if user_id not in USERS_DB:
        USERS_DB[user_id] = {"balance": 0, "history": []}
        save_users_db()
    if "history" not in USERS_DB[user_id]:
        USERS_DB[user_id]["history"] = []
    return USERS_DB[user_id]

def get_user_balance(user_id):
    return get_user_data(user_id)["balance"]

def get_user_mention(user):
    if user.username:
        return f"@{html.escape(user.username)}"
    else:
        name = html.escape(user.first_name if user.first_name else "Khách hàng")
        return f'<a href="tg://user?id={user.id}">{name}</a>'

async def auto_delete_with_countdown(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, base_text: str, seconds: int = 30):
    async def countdown_task():
        current_sec = seconds
        while current_sec > 0:
            await asyncio.sleep(5)
            current_sec -= 5
            if current_sec <= 0:
                break
            try:
                countdown_text = f"{base_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau {current_sec}s...</i>"
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=countdown_text,
                    parse_mode="HTML"
                )
            except Exception:
                pass
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass

    asyncio.create_task(countdown_task())

def main_menu_keyboard(user_id, username, first_name="bạn"):
    balance = get_user_balance(user_id)
    text = (
        f"✨ <b>HỆ THỐNG DỊCH VỤ SMM & DIGITAL ACCOUNTS</b> ✨\n"
        f"════════════════════════════════\n\n"
        f"👋 <b>Xin chào,</b> {html.escape(str(first_name))}!\n"
        f"💎 <b>Trạng thái:</b> Thành Viên Chính Thức\n\n"
        f"💳 <b>TÀI KHOẢN CỦA BẠN:</b>\n"
        f" ┣ 🆔 <b>ID Telegram:</b> <code>{user_id}</code>\n"
        f" ┗ 💰 <b>Số dư hiện tại:</b> <code>{balance:,.0f} VNĐ</code>\n\n"
        f"⚡ <b>Hệ thống hoàn tất xử lý tự động 24/7.</b>\n"
        f"👇 <b>Vui lòng chọn danh mục dịch vụ bên dưới:</b>"
    )
    
    keyboard = [
        [InlineKeyboardButton("📦 SẢN PHẨM TÀI KHOẢN (ACCOUNT)", callback_data="products_p1")],
        [InlineKeyboardButton("🤖 TẠO BOT TELE", callback_data="create_bot_tele_menu")],
        [InlineKeyboardButton("✔ TÍCH XANH FACEBOOK", callback_data="tick_xanh_menu")],
        [
            InlineKeyboardButton("📘 FACEBOOK", callback_data="cat_fb"),
            InlineKeyboardButton("🎵 TIKTOK", callback_data="cat_tt")
        ],
        [
            InlineKeyboardButton("▶️ YOUTUBE", callback_data="cat_yt"),
            InlineKeyboardButton("📸 INSTAGRAM", callback_data="cat_ig")
        ],
        [
            InlineKeyboardButton("💣 SPAM SMS AUTO", callback_data="sms_menu_main"),
            InlineKeyboardButton("🎁 NHẬP GITCODE", callback_data="menu_gitcode")
        ],
        [
            InlineKeyboardButton("💳 NẠP TIỀN AUTO", callback_data="nap_tien"),
            InlineKeyboardButton("📜 LỊCH SỬ DÙNG", callback_data="view_history")
        ],
        [
            InlineKeyboardButton("💬 HỖ TRỢ KĨ THUẬT (ADMIN)", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
        ]
    ]
    
    if is_admin(user_id, username):
        keyboard.append([InlineKeyboardButton("⚙️ QUẢN LÝ HỆ THỐNG [ADMIN]", callback_data="admin_panel")])

    return text, InlineKeyboardMarkup(keyboard)

def products_menu_keyboard(page=1):
    items = CATEGORIES_PAGE_1 if page == 1 else CATEGORIES_PAGE_2
    keyboard = []
    for item in items:
        if item['id'] == "cat_groups":
            display_name = f"{item['title']} (Kho: {len(ALL_GROUPS)})"
        else:
            stock = get_stock_count(item['id'])
            display_name = f"{item['title']} (Còn: {stock})"
        
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"item_{item['id']}")])
    
    text = (
        f"📦 <b>KHO SẢN PHẨM & TÀI KHOẢN DIGITAL</b>\n"
        f"════════════════════════════════\n"
        f"📄 Trang {page}/2\n\n"
        f"👇 <i>Chọn chuyên mục sản phẩm để mua:</i> "
    )
    
    nav_buttons = []
    if page == 1:
        nav_buttons.append(InlineKeyboardButton("🔴 1/2", callback_data="none"))
        nav_buttons.append(InlineKeyboardButton("Trang sau ➡️", callback_data="products_p2"))
    else:
        nav_buttons.append(InlineKeyboardButton("⬅️ Trang trước", callback_data="products_p1"))
        nav_buttons.append(InlineKeyboardButton("🔴 2/2", callback_data="none"))
    
    keyboard.append(nav_buttons)
    keyboard.append([
        InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
    ])
    
    return text, InlineKeyboardMarkup(keyboard)

def groups_menu_keyboard(page=1):
    items = GROUPS_PAGE_1 if page == 1 else GROUPS_PAGE_2
    keyboard = []
    for item in items:
        mem_str = f"{item['mem'] / 1000:.0f}k" if item['mem'] < 1000000 else f"{item['mem'] / 1000000:.1f}M"
        display_name = f"👥 {item['name']} ── [{mem_str}]"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"group_detail_{item['id']}")])
    
    text = (
        f"📋 <b>DANH SÁCH NHÓM FACEBOOK</b>\n"
        f"════════════════════════════════\n"
        f"📄 Trang {page}/2\n\n"
        f"👇 <i>Chọn nhóm bên dưới để xem thông tin chi tiết & mua:</i> "
    )
    
    nav_buttons = []
    if page == 1:
        nav_buttons.append(InlineKeyboardButton("🔴 1/2", callback_data="none"))
        nav_buttons.append(InlineKeyboardButton("Trang sau ➡️", callback_data="groups_p2"))
    else:
        nav_buttons.append(InlineKeyboardButton("⬅️ Trang trước", callback_data="groups_p1"))
        nav_buttons.append(InlineKeyboardButton("🔴 2/2", callback_data="none"))
    
    keyboard.append(nav_buttons)
    keyboard.append([
        InlineKeyboardButton("↩️ Quản Lý SP", callback_data="products_p2"),
        InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
    ])
    
    return text, InlineKeyboardMarkup(keyboard)

def fb_menu_keyboard():
    text = (
        f"📘 <b>DỊCH VỤ FACEBOOK AUTO</b>\n"
        f"════════════════════════════════\n\n"
        f"✨ <i>Hệ thống buff tương tác FB chuyên nghiệp & tốc độ cao.</i> \n"
        f"👇 <i>Vui lòng lựa chọn dịch vụ:</i> "
    )
    keyboard = [
        [InlineKeyboardButton("👍 Tăng Like Bài Viết", callback_data="subcat_fb_like"), InlineKeyboardButton("👤 Tăng theo dõi tcn ", callback_data="subcat_fb_follow")],
        [InlineKeyboardButton("💬 Tăng Bình Luận", callback_data="subcat_fb_cmt"), InlineKeyboardButton("⭐ Tăng like & FOLLOW PAGE", callback_data="subcat_fb_page")],
        [InlineKeyboardButton("👥 Tăng Thành Viên Group", callback_data="subcat_fb_group"), InlineKeyboardButton("🔄 Tăng chia sẻ bài viết(Share)", callback_data="subcat_fb_share")],
        [InlineKeyboardButton("👁️  Tăng lượt xem video fb", callback_data="subcat_fb_view"), InlineKeyboardButton("👁️ Tăng lượt xem Story(lượt xem tin)", callback_data="subcat_fb_story")],
        [InlineKeyboardButton("🏠 Trở Về Menu Chính", callback_data="menu_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

def tiktok_menu_keyboard():
    text = (
        f"🎵 <b>DỊCH VỤ TIKTOK AUTO</b>\n"
        f"════════════════════════════════\n\n"
        f"⚡ <i>Buff View, Tim, Sub TikTok siêu tốc độ.</i> \n"
        f"👇 <i>Vui lòng lựa chọn dịch vụ:</i> "
    )
    keyboard = [
        [InlineKeyboardButton("❤️ Tăng Tim (Like)", callback_data="subcat_tt_like"), InlineKeyboardButton("👤 Tăng Theo Dõi", callback_data="subcat_tt_follow")],
        [InlineKeyboardButton("👁️ Tăng Lượt Xem", callback_data="subcat_tt_view"), InlineKeyboardButton("💬 Tăng Bình Luận", callback_data="subcat_tt_cmt")],
        [InlineKeyboardButton("🔄 Tăng Lượt Share", callback_data="subcat_tt_share"), InlineKeyboardButton("💾 Tăng Save Video", callback_data="subcat_tt_save")],
        [InlineKeyboardButton("🔴 Live Việt Nam", callback_data="subcat_tt_live_vn"), InlineKeyboardButton("👀 Mắt Livestream", callback_data="subcat_tt_mat_live")],
        [InlineKeyboardButton("🌍 Mắt Live Tây", callback_data="subcat_tt_mat_tay"), InlineKeyboardButton("👑 VIP Mắt Livestream", callback_data="subcat_tt_vip_mat")],
        [InlineKeyboardButton("🏠 Trở Về Menu Chính", callback_data="menu_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

def youtube_menu_keyboard():
    text = (
        f"▶️ <b>DỊCH VỤ YOUTUBE AUTO</b>\n"
        f"════════════════════════════════\n\n"
        f"🚀 <i>Dịch vụ tăng Sub, Like, View YouTube chuẩn chất lượng.</i> \n"
        f"👇 <i>Vui lòng lựa chọn dịch vụ:</i> "
    )
    keyboard = [
        [InlineKeyboardButton("📥 Tăng Đăng Ký Kênh (Sub)", callback_data="subcat_yt_sub")],
        [InlineKeyboardButton("👍 Tăng Like Video", callback_data="subcat_yt_like"), InlineKeyboardButton("👁️ View & Mắt Livestream", callback_data="subcat_yt_view")],
        [InlineKeyboardButton("🏠 Trở Về Menu Chính", callback_data="menu_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

def instagram_menu_keyboard():
    text = (
        f"📸 <b>DỊCH VỤ INSTAGRAM AUTO</b>\n"
        f"════════════════════════════════\n\n"
        f"🌟 <i>Đột phá tương tác Trang Cá Nhân Instagram.</i> \n"
        f"👇 <i>Vui lòng lựa chọn dịch vụ:</i> "
    )
    keyboard = [
        [InlineKeyboardButton("❤️ Tăng Like Bài Viết", callback_data="subcat_ig_like"), InlineKeyboardButton("👤 Tăng Theo Dõi (Follow)", callback_data="subcat_ig_follow")],
        [InlineKeyboardButton("🏠 Trở Về Menu Chính", callback_data="menu_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

def service_items_keyboard(cat_key):
    cat_data = SERVICES.get(cat_key, {})
    text = (
        f"🛠️ <b>{html.escape(cat_data.get('title', 'DỊCH VỤ'))}</b>\n"
        f"════════════════════════════════\n\n"
        f"👇 <i>Chọn server / gói dịch vụ bạn muốn khởi chạy:</i> "
    )
    keyboard = []
    for item in cat_data.get("items", []):
        btn_text = f"🔹 {item['name']} ── [{item['price']}đ]"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"buy:{cat_key}:{item['id']}")])
    
    if cat_key.startswith("tt_"):
        back_target = "cat_tt"
    elif cat_key.startswith("yt_"):
        back_target = "cat_yt"
    elif cat_key.startswith("ig_"):
        back_target = "cat_ig"
    else:
        back_target = "cat_fb"
        
    keyboard.append([
        InlineKeyboardButton("↩️ Trở về", callback_data=back_target),
        InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
    ])
    return text, InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user_data(user.id)
        
    text, reply_markup = main_menu_keyboard(user.id, user.username, user.first_name)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
    return ConversationHandler.END

async def admin_topup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        await update.message.reply_text("❌ Bạn không phải là Admin!")
        return

    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
        
        user_data = get_user_data(target_id)
        user_data["balance"] += amount
        save_users_db() 
        tg_backup_async("admin cộng tiền")
        
        new_bal = user_data["balance"]

        try:
            target_user = await context.bot.get_chat(target_id)
            user_tag = f"@{html.escape(target_user.username)}" if target_user.username else f"ID <code>{target_id}</code>"
        except Exception:
            user_tag = f"ID <code>{target_id}</code>"

        admin_base_text = f"✅ Đã cộng {amount:,.0f}đ cho khách {user_tag}\n💰 Số dư mới: {new_bal:,.0f} VND"
        admin_msg = await update.message.reply_text(f"{admin_base_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau 30s...</i>", parse_mode="HTML")
        await auto_delete_with_countdown(context, update.effective_chat.id, admin_msg.message_id, admin_base_text, 30)

        try:
            user_base_text = f"🎉 <b>BẠN ĐÃ ĐƯỢC CỘNG TIỀN THÀNH CÔNG!</b>\n\n💰 <b>Số tiền nạp:</b> +{amount:,.0f} VND\n💳 <b>Số dư hiện tại:</b> {new_bal:,.0f} VND"
            user_msg = await context.bot.send_message(
                chat_id=target_id,
                text=f"{user_base_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau 30s...</i>",
                parse_mode="HTML"
            )
            await auto_delete_with_countdown(context, target_id, user_msg.message_id, user_base_text, 30)
        except Exception:
            pass
    except Exception:
        await update.message.reply_text("⚠️ Cú pháp sai! Nhập: `/topup <ID> <Số_Tiền>`")

async def custom_topup_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Số tiền không hợp lệ! Vui lòng nhập lại số tiền (Ví dụ: 100000):")
        return INPUT_TOPUP_AMOUNT

    text_out, markup = build_bank_choice(amount)
    await update.message.reply_text(text_out, parse_mode="HTML", reply_markup=markup)
    return ConversationHandler.END

async def receive_promo_percent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    raw = update.message.text.strip().replace("%", "").replace(",", ".")
    try:
        pct = float(raw)
        if pct < 0 or pct > 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Phần trăm không hợp lệ! Nhập số từ 0 đến 100 (ví dụ: 10):")
        return INPUT_PROMO_PERCENT

    set_promo_percent(pct)
    status = f"🟢 Đang bật khuyến mãi <b>+{pct:g}%</b>" if pct > 0 else "🔴 Đã tắt khuyến mãi"
    await update.message.reply_text(
        f"✅ <b>ĐÃ CẬP NHẬT KHUYẾN MÃI NẠP</b>\n\n{status}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎉 Cài đặt khuyến mãi", callback_data="admin_promo_menu")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ])
    )
    return ConversationHandler.END

async def receive_gitcode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    user = update.effective_user

    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    if code not in GITCODE_DB:
        await update.message.reply_text(
            "❌ Mã Gitcode không tồn tại hoặc đã hết hạn!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]])
        )
        return ConversationHandler.END

    git_data = GITCODE_DB[code]
    if user.id in git_data["used_by"]:
        await update.message.reply_text(
            "⚠️ Bạn đã sử dụng mã Gitcode này rồi! Mỗi tài khoản chỉ được dùng 1 lần.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]])
        )
        return ConversationHandler.END

    amount = git_data["amount"]
    git_data["used_by"].append(user.id)
    save_gitcode_db()

    user_data = get_user_data(user.id)
    user_data["balance"] += amount
    user_data["history"].append(f"Nhận Gitcode [{code}]: +{amount:,.0f}đ")
    save_users_db()

    new_balance = user_data["balance"]
    await update.message.reply_text(
        f"🎉 <b>NHẬP GITCODE THÀNH CÔNG!</b>\n\n"
        f"🎁 <b>Mã:</b> <code>{html.escape(code)}</code>\n"
        f"💰 <b>Cộng:</b> <code>+{amount:,.0f} VNĐ</code>\n"
        f"💳 <b>Số dư mới:</b> <code>{new_balance:,.0f} VNĐ</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]])
    )
    return ConversationHandler.END

async def receive_custom_gitcode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("⚠️ Sai cú pháp! Nhập theo định dạng: `<MÃ_CODE> <SỐ_TIỀN>`\nVí dụ: `KM100K 50000`")
        return INPUT_CREATE_CODE_CUSTOM

    code = parts[0].upper()
    try:
        amount = float(parts[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Số tiền không hợp lệ! Vui lòng nhập lại số tiền hợp lệ:")
        return INPUT_CREATE_CODE_CUSTOM

    GITCODE_DB[code] = {"amount": amount, "used_by": []}
    save_gitcode_db()

    await update.message.reply_text(
        f"✅ TẠO GITCODE THÀNH CÔNG!\n\n"
        f"🎁 Mã: <code>{html.escape(code)}</code>\n"
        f"💵 Giá trị: {amount:,.0f} VND",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]])
    )
    return ConversationHandler.END

async def receive_admin_edit_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("⚠️ Sai cú pháp! Nhập: `<ID_KHÁCH> <SỐ_TIỀN_MỚI>`")
        return INPUT_ADMIN_EDIT_USER

    try:
        target_id = int(parts[0])
        new_balance = float(parts[1])
    except ValueError:
        await update.message.reply_text("⚠️ ID hoặc Số tiền không hợp lệ! Vui lòng nhập lại:")
        return INPUT_ADMIN_EDIT_USER

    user_data = get_user_data(target_id)
    user_data["balance"] = new_balance
    save_users_db()
    tg_backup_async("admin sửa số dư")

    await update.message.reply_text(
        f"✅ ĐÃ CẬP NHẬT SỐ DƯ CHO KHÁCH <code>{target_id}</code>\n"
        f"💰 Số dư mới: {new_balance:,.0f} VND",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]])
    )
    return ConversationHandler.END

async def receive_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    context.user_data["order_link"] = link
    
    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass
    
    selected_item = context.user_data.get("buying_service", {})
    item_name = selected_item.get("name", "Dịch vụ")
    cat_key = context.user_data.get("current_cat_key", "fb_like")
    
    text = (
        f"🔗 <b>ĐÃ NHẬN LINK TƯƠNG TÁC:</b>\n<code>{html.escape(link)}</code>\n\n"
        f"📦 <b>Gói dịch vụ chọn:</b> {html.escape(item_name)}\n\n"
        f"👇 <i>Vui lòng nhập số lượng cần mua (Ví dụ: 100, 500, 1000):</i>"
    )
    
    subcat_target = f"subcat_{cat_key}"

    keyboard = [
        [
            InlineKeyboardButton("↩️ Chọn lại gói", callback_data=subcat_target),
            InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
        ]
    ]
    
    msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data["prompt_msg_id"] = msg.message_id
    return INPUT_QUANTITY

async def receive_quantity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty_text = update.message.text.strip()
    
    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    try:
        quantity = int(qty_text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        cat_key = context.user_data.get("current_cat_key", "fb_like")
        keyboard = [
            [
                InlineKeyboardButton("↩️ Chọn lại gói", callback_data=f"subcat_{cat_key}"),
                InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
            ]
        ]
        msg = await update.message.reply_text("⚠️ Số lượng phải là số nguyên lớn hơn 0! Vui lòng nhập lại số lượng:", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_QUANTITY

    context.user_data["order_quantity"] = quantity
    cat_key = context.user_data.get("current_cat_key", "")

    if cat_key in ["fb_cmt", "tt_cmt"]:
        text = (
            f"📊 <b>Số lượng:</b> {quantity:,}\n\n"
            f"👇 <i>Vui lòng chọn phong cách bình luận:</i> "
        )
        keyboard = [
            [
                InlineKeyboardButton("💬 Bình luận Khen", callback_data="cmt_type:Khen"),
                InlineKeyboardButton("💬 Bình luận Chê", callback_data="cmt_type:Chê")
            ],
            [
                InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
            ]
        ]
        msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return ConversationHandler.END
    else:
        return await process_final_order(update, context, "Mặc định")

async def background_order_status_checker(context: ContextTypes.DEFAULT_TYPE, order_id: int, admin_chat_id: int, admin_msg_id: int, user_id: int, user_name: str, package_name: str, link: str, quantity: int, total_price: float):
    """Tiến trình kiểm tra trạng thái đơn hàng tự động 24/7 qua SMM API cứ mỗi 1 tiếng."""
    while True:
        await asyncio.sleep(3600)  # Đợi 1 tiếng kiểm tra lại
        res = await asyncio.to_thread(call_smm_api, "status", {"order": order_id})
        if res and isinstance(res, dict):
            status = res.get("status", "").lower()
            if status in ["completed", "hoàn thành"]:
                new_admin_text = (
                    f"🔔 <b>ĐƠN HÀNG TĂNG TƯƠNG TÁC ĐÃ HOÀN THÀNH!</b>\n"
                    f"----------------------------------------\n"
                    f"👤 Khách hàng: {user_name} (ID: <code>{user_id}</code>)\n"
                    f"📦 Gói: {html.escape(str(package_name))}\n"
                    f"🆔 SMM Order ID: <code>{order_id}</code>\n"
                    f"🔗 Link: <code>{html.escape(str(link))}</code>\n"
                    f"📊 Số lượng: {quantity:,}\n"
                    f"💵 Tổng tiền: {total_price:,.0f}đ\n\n"
                    f"✅ <b>STATUS: HOÀN THÀNH</b>"
                )
                try:
                    await context.bot.edit_message_text(
                        chat_id=admin_chat_id,
                        message_id=admin_msg_id,
                        text=new_admin_text,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 ĐÃ HOÀN THÀNH", callback_data="none")]])
                    )
                except Exception:
                    pass
                break
            elif status in ["canceled", "cancelled", "hủy"]:
                new_admin_text = (
                    f"🔔 <b>ĐƠN HÀNG TĂNG TƯƠNG TÁC ĐÃ BỊ HỦY!</b>\n"
                    f"----------------------------------------\n"
                    f"👤 Khách hàng: {user_name} (ID: <code>{user_id}</code>)\n"
                    f"📦 Gói: {html.escape(str(package_name))}\n"
                    f"🆔 SMM Order ID: <code>{order_id}</code>\n"
                    f"🔗 Link: <code>{html.escape(str(link))}</code>\n"
                    f"📊 Số lượng: {quantity:,}\n"
                    f"💵 Tổng tiền: {total_price:,.0f}đ\n\n"
                    f"❌ <b>STATUS: ĐÃ HỦY</b>"
                )
                try:
                    await context.bot.edit_message_text(
                        chat_id=admin_chat_id,
                        message_id=admin_msg_id,
                        text=new_admin_text,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔴 ĐÃ HỦY", callback_data="none")]])
                    )
                except Exception:
                    pass
                break

async def process_final_order(update: Update, context: ContextTypes.DEFAULT_TYPE, cmt_type="Mặc định"):
    user = update.effective_user
    selected_item = context.user_data.get("buying_service", {})
    link = context.user_data.get("order_link", "")
    quantity = context.user_data.get("order_quantity", 0)
    item_id_str = selected_item.get("id")
    
    # Lấy giá của 1 đơn vị từ cấu hình gói dịch vụ đã chọn
    price_per_unit = float(selected_item.get("price", 0))
    
    # 💡 SỬA LỖI TÍNH TIỀN: Lấy đơn giá nhân chính xác với số lượng khách nhập
    total_price = float(quantity) * price_per_unit
    
    user_data = get_user_data(user.id)
    if user_data["balance"] < total_price:
        msg_text = (
            f"❌ <b>SỐ DƯ KHÔNG ĐỦ THANH TOÁN!</b>\n\n"
            f"💳 Số dư hiện tại: <code>{user_data['balance']:,.0f}đ</code>\n"
            f"💵 Cần thanh toán: <code>{total_price:,.0f}đ</code>\n\n"
            f"⚠️ <i>Vui lòng nạp thêm tiền để tiếp tục.</i>"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Nạp Tiền Ngay", callback_data="nap_tien"), InlineKeyboardButton("🏠 Menu", callback_data="menu_main")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(msg_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=keyboard)
        return ConversationHandler.END

    # Trừ tiền tài khoản người dùng sau khi đã tính toán chính xác
    user_data["balance"] -= total_price
    
    if cmt_type != "Mặc định":
        history_item = f"SMM: {selected_item.get('name')} ({cmt_type}) | SL: {quantity:,} | Giá: {total_price:,.0f}đ | Link: {link}"
    else:
        history_item = f"SMM: {selected_item.get('name')} | SL: {quantity:,} | Giá: {total_price:,.0f}đ | Link: {link}"
        
    user_data["history"].append(history_item)
    save_users_db()
    
    new_bal = user_data["balance"]

    # ================= ĐƠN BÌNH LUẬN: GỬI VỀ ADMIN CHẠY TAY =================
    cat_key_now = context.user_data.get("current_cat_key", "")
    if cat_key_now in MANUAL_ORDER_CATS:
        user_mention = get_user_mention(user)
        admin_notice = (
            f"💬 <b>ĐƠN BÌNH LUẬN MỚI - CẦN CHẠY TAY!</b>\n"
            f"----------------------------------------\n"
            f"👤 Khách hàng: {user_mention} (ID: <code>{user.id}</code>)\n"
            f"📦 Gói: {html.escape(str(selected_item.get('name')))}\n"
            f"🆔 Mã dịch vụ SMM: <code>{get_smm_service_id(item_id_str) or 'N/A'}</code>\n"
            f"💬 Loại cmt: {html.escape(str(cmt_type))}\n"
            f"🔗 Link: <code>{html.escape(str(link))}</code>\n"
            f"📊 Số lượng: {quantity:,}\n"
            f"💵 Khách đã thanh toán: {total_price:,.0f}đ\n\n"
            f"⏳ <b>STATUS: CHỜ ADMIN XỬ LÝ</b>"
        )
        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Đã chạy xong", callback_data=f"admin_cmt_done:{user.id}")],
            [InlineKeyboardButton("❌ Từ chối & hoàn tiền", callback_data=f"admin_cmt_refund:{user.id}:{int(round(total_price))}")]
        ])
        try:
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_notice, parse_mode="HTML", reply_markup=admin_keyboard)
        except Exception as e:
            # Không gửi được cho Admin -> hoàn tiền khách để không mất đơn
            logging.error(f"❌ Không gửi được đơn cmt cho Admin: {e}")
            with DB_LOCK:
                user_data["balance"] += total_price
                user_data["history"].append(f"Hoàn tiền đơn cmt lỗi: {selected_item.get('name')} | +{total_price:,.0f}đ")
            save_users_db()
            fail_text = (
                f"❌ <b>ĐẶT ĐƠN THẤT BẠI!</b>\n\n"
                f"💵 Đã hoàn lại <code>{total_price:,.0f}đ</code> vào số dư.\n"
                f"⚠️ <i>Vui lòng thử lại sau hoặc liên hệ Admin.</i>"
            )
            fail_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]])
            if update.callback_query:
                await update.callback_query.edit_message_text(fail_text, reply_markup=fail_markup, parse_mode="HTML")
            else:
                await update.message.reply_text(fail_text, reply_markup=fail_markup, parse_mode="HTML")
            return ConversationHandler.END

        success_text = (
            f"🎉 <b>ĐẶT ĐƠN BÌNH LUẬN THÀNH CÔNG!</b>\n\n"
            f"📦 <b>Gói:</b> {html.escape(str(selected_item.get('name')))}\n"
            f"💬 <b>Loại:</b> {html.escape(str(cmt_type))}\n"
            f"🔗 <b>Link:</b> <code>{html.escape(str(link))}</code>\n"
            f"📊 <b>Số lượng:</b> <code>{quantity:,}</code>\n"
            f"💵 <b>Thanh toán:</b> <code>{total_price:,.0f}đ</code>\n"
            f"💳 <b>Số dư còn lại:</b> <code>{new_bal:,.0f}đ</code>\n\n"
            f"⏳ <i>Đơn bình luận đã được chuyển cho Admin xử lý thủ công. Bạn sẽ nhận thông báo khi hoàn thành.</i>"
        )
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode="HTML")
        return ConversationHandler.END

    # ================= TỰ ĐỘNG GỌI SMM API MUA ĐƠN =================
    smm_service_id = get_smm_service_id(item_id_str) or 6683

    payload_data = {
        "service": smm_service_id,
        "link": link,
        "quantity": quantity
    }

    if "like" in item_id_str:
        payload_data["comments"] = "👍, ❤️, 😆"

    # Báo khách biết bot đang xử lý (API có thể chậm vài giây)
    processing_msg = None
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text("⏳ <b>Đang xử lý đơn hàng, vui lòng chờ vài giây...</b>", parse_mode="HTML")
        elif update.message:
            processing_msg = await update.message.reply_text("⏳ <b>Đang xử lý đơn hàng, vui lòng chờ vài giây...</b>", parse_mode="HTML")
    except Exception:
        pass

    # Chạy trong thread riêng để bot không bị đứng khi API chậm
    smm_res = await asyncio.to_thread(call_smm_api, "add", payload_data)

    if processing_msg:
        try:
            await processing_msg.delete()
        except Exception:
            pass

    smm_order_id = None
    if smm_res and isinstance(smm_res, dict) and "order" in smm_res:
        smm_order_id = smm_res.get("order")

    if smm_order_id is None:
        # Đặt đơn thất bại -> hoàn tiền lại cho khách
        with DB_LOCK:
            user_data["balance"] += total_price
            user_data["history"].append(f"Hoàn tiền đơn lỗi: {selected_item.get('name')} | +{total_price:,.0f}đ")
        save_users_db()

        err_msg = ""
        if isinstance(smm_res, dict) and smm_res.get("error"):
            err_msg = f"\n📝 <b>Chi tiết:</b> {html.escape(str(smm_res.get('error')))}"
        fail_text = (
            f"❌ <b>ĐẶT ĐƠN THẤT BẠI!</b>\n\n"
            f"📦 <b>Gói:</b> {html.escape(str(selected_item.get('name')))}\n"
            f"💵 Đã hoàn lại <code>{total_price:,.0f}đ</code> vào số dư.\n"
            f"💳 <b>Số dư hiện tại:</b> <code>{user_data['balance']:,.0f}đ</code>{err_msg}\n\n"
            f"⚠️ <i>Vui lòng thử lại sau hoặc liên hệ Admin.</i>"
        )
        fail_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(fail_text, reply_markup=fail_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(fail_text, reply_markup=fail_markup, parse_mode="HTML")
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"⚠️ <b>ĐƠN SMM LỖI - ĐÃ HOÀN TIỀN</b>\n"
                    f"👤 Khách ID: <code>{user.id}</code>\n"
                    f"📦 Gói: {html.escape(str(selected_item.get('name')))}\n"
                    f"🔗 Link: <code>{html.escape(str(link))}</code>\n"
                    f"📊 SL: {quantity:,} | 💵 {total_price:,.0f}đ{err_msg}"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass
        return ConversationHandler.END

    success_text = (
        f"🎉 <b>ĐẶT HÀNG THÀNH CÔNG!</b>\n\n"
        f"📦 <b>Gói:</b> {html.escape(str(selected_item.get('name')))}\n"
        f"💬 <b>Loại:</b> {html.escape(str(cmt_type))}\n"
        f"🔗 <b>Link:</b> <code>{html.escape(str(link))}</code>\n"
        f"📊 <b>Số lượng:</b> <code>{quantity:,}</code>\n"
        f"🆔 <b>Mã đơn hệ thống (ID):</b> <code>{smm_order_id}</code>\n"
        f"💵 <b>Thanh toán:</b> <code>{total_price:,.0f}đ</code>\n"
        f"💳 <b>Số dư còn lại:</b> <code>{new_bal:,.0f}đ</code>\n\n"
        f"⏳ <i>Đơn hàng đã được tự động đẩy lên hệ thống SMM thành công.</i>"
    )
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]])

    if update.callback_query:
        await update.callback_query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode="HTML")

    user_mention = get_user_mention(user)

    admin_notice = (
        f"🔔 <b>ĐƠN HÀNG TĂNG TƯƠNG TÁC MỚI (TỰ ĐỘNG MUA)!</b>\n"
        f"----------------------------------------\n"
        f"👤 Khách hàng: {user_mention} (ID: <code>{user.id}</code>)\n"
        f"📦 Gói: {html.escape(str(selected_item.get('name')))}\n"
        f"🆔 SMM Order ID: <code>{smm_order_id}</code>\n"
        f"💬 Loại cmt: {html.escape(str(cmt_type))}\n"
        f"🔗 Link: <code>{html.escape(str(link))}</code>\n"
        f"📊 Số lượng: {quantity:,}\n"
        f"💵 Tổng tiền: {total_price:,.0f}đ\n\n"
        f"⏳ <b>STATUS: ĐÃ NHẬN ĐƠN ĐANG BUFF</b>"
    )
    
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 ĐÃ NHẬN ĐƠN ĐANG BUFF", callback_data="none")]
    ])
    
    try:
        sent_admin_msg = await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notice, parse_mode="HTML", reply_markup=admin_keyboard)
        if smm_order_id != "Không rõ":
            asyncio.create_task(background_order_status_checker(
                context, int(smm_order_id), int(ADMIN_CHAT_ID), sent_admin_msg.message_id, 
                user.id, user_mention, selected_item.get('name'), link, quantity, total_price
            ))
    except Exception:
        pass

    return ConversationHandler.END

# ==================== HÀM XỬ LÝ PHẢN HỒI CỦA KHÁCH TỚI ADMIN ====================
async def receive_user_feedback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    feedback_text = update.message.text.strip()
    user_mention = get_user_mention(user)

    admin_msg = (
        f"💬 <b>CÓ PHẢN HỒI MỚI TỪ KHÁCH HÀNG!</b>\n"
        f"----------------------------------------\n"
        f"👤 Khách hàng: {user_mention}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📝 <b>Nội dung phản hồi:</b>\n<code>{html.escape(feedback_text)}</code>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Gửi tin nhắn riêng lại cho khách", callback_data=f"admin_reply_user:{user.id}")]
    ])

    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="HTML", reply_markup=keyboard)
        await update.message.reply_text(
            "✅ <b>Gửi phản hồi thành công!</b>\nAdmin đã nhận được tin nhắn của bạn và sẽ phản hồi sớm nhất.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]])
        )
    except Exception:
        await update.message.reply_text("❌ Gửi phản hồi thất bại, vui lòng thử lại sau!")

    return ConversationHandler.END

async def receive_bot_requirements_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req_text = update.message.text.strip()
    user = update.effective_user
    price = 500000.0

    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    user_data = get_user_data(user.id)
    if user_data["balance"] < price:
        msg_text = (
            f"❌ <b>SỐ DƯ KHÔNG ĐỦ THANH TOÁN!</b>\n\n"
            f"💳 Số dư hiện tại: <code>{user_data['balance']:,.0f}đ</code>\n"
            f"💵 Cần thanh toán: <code>500,000đ</code>\n\n"
            f"⚠️ <i>Vui lòng nạp thêm tiền để tiếp tục tạo bot.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Nạp Tiền Ngay", callback_data="nap_tien"), InlineKeyboardButton("🏠 Menu", callback_data="menu_main")],
            [InlineKeyboardButton("↩️ Trở Về Menu Tạo Bot", callback_data="create_bot_tele_menu")]
        ])
        await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=keyboard)
        return ConversationHandler.END

    user_data["balance"] -= price
    user_data["history"].append(f"Tạo Bot Telegram Premium | Giá: 500,000đ | Yêu cầu: {req_text}")
    save_users_db()

    success_text = (
        f"🎉 <b>ĐẶT YÊU CẦU TẠO BOT THÀNH CÔNG!</b>\n"
        f"════════════════════════════════\n"
        f"🤖 <b>Dịch vụ:</b> Bot Telegram Premium\n"
        f"📝 <b>Yêu cầu:</b> {html.escape(req_text)}\n"
        f"💵 <b>Đã thanh toán:</b> <code>500,000 VNĐ</code>\n"
        f"💳 <b>Số dư còn lại:</b> <code>{user_data['balance']:,.0f} VNĐ</code>\n\n"
        f"⏳ <i>Đơn hàng đã được chuyển tới Admin duyệt và tiến hành code bot theo yêu cầu của bạn!</i>"
    )
    keyboard = [
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
    ]
    await update.message.reply_text(success_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    user_mention = get_user_mention(user)
    admin_notice = (
        f"🔔 <b>CÓ ĐƠN YÊU CẦU TẠO BOT TELEGRAM MỚI!</b>\n"
        f"----------------------------------------\n"
        f"👤 Khách: {user_mention} (ID: <code>{user.id}</code>)\n"
        f"🤖 Gói: Bot Telegram Premium\n"
        f"📝 Yêu cầu tính năng:\n<code>{html.escape(req_text)}</code>\n"
        f"💵 Giá: 500,000đ"
    )
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Đã nhận đơn", callback_data=f"admin_accept_order:{user.id}")],
        [InlineKeyboardButton("❌ Từ chối đơn", callback_data=f"admin_reject_order:{user.id}")]
    ])
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notice, parse_mode="HTML", reply_markup=admin_keyboard)
    except Exception:
        pass

    return ConversationHandler.END

async def receive_sms_phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    user = update.effective_user
    
    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    user_sms_list = SMS_DB.get(user.id, [])
    active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]

    if context.user_data.get("is_adding_free_phone", False) and active_sms:
        current_pkg = active_sms[0]
        expire_time = current_pkg["expire_time"]
        pkg_name = current_pkg["package"]

        sms_entry = {
            "phone": phone,
            "package": pkg_name,
            "price": 0,
            "expire_time": expire_time
        }
        SMS_DB[user.id].append(sms_entry)
        save_sms_db()

        context.user_data["is_adding_free_phone"] = False

        success_text = (
            f"✅ <b>THÊM SỐ ĐIỆN THOẠI THÀNH CÔNG!</b>\n\n"
            f"📦 Áp dụng gói: {html.escape(pkg_name)}\n"
            f"📱 SĐT: <code>{html.escape(phone)}</code>\n"
            f"⏳ Trạng thái: Đang tiến hành spam."
        )
        success_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💣 Quản lý danh sách SMS", callback_data="sms_menu_main")],
            [InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]
        ])
        await update.message.reply_text(success_text, parse_mode="HTML", reply_markup=success_keyboard)
        return ConversationHandler.END

    pkg_info = context.user_data.get("buying_sms_pkg")
    if not pkg_info:
        await update.message.reply_text("❌ Lỗi phiên giao dịch, vui lòng thử lại từ đầu!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]))
        return ConversationHandler.END

    pkg_name = pkg_info["name"]
    pkg_price = pkg_info["price"]
    duration = pkg_info["duration"]

    user_data = get_user_data(user.id)
    if user_data["balance"] < pkg_price:
        await update.message.reply_text(
            f"❌ SỐ DƯ KHÔNG ĐỦ!\n\n"
            f"💳 Số dư của bạn: {user_data['balance']:,.0f}đ\n"
            f"💵 Giá gói {pkg_name}: {pkg_price:,.0f}đ\n\n"
            f"⚠️ Vui lòng nạp thêm tiền để mua gói!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Nạp tiền ngay", callback_data="nap_tien"), InlineKeyboardButton("🏠 Menu", callback_data="menu_main")]])
        )
        return ConversationHandler.END

    user_data["balance"] -= pkg_price
    expire_time = time.time() + duration if duration < 3000000000 else time.time() + (365 * 100 * 86400)
    
    if user.id not in SMS_DB:
        SMS_DB[user.id] = []
    
    sms_entry = {
        "phone": phone,
        "package": pkg_name,
        "price": pkg_price,
        "expire_time": expire_time
    }
    SMS_DB[user.id].append(sms_entry)
    save_sms_db()

    user_data["history"].append(f"Mua Spam SMS: {pkg_name} | SĐT: {phone} | Giá: {pkg_price:,.0f}đ")
    save_users_db()

    new_bal = user_data["balance"]

    success_text = (
        f"✅ <b>MUA GÓI SPAM SMS THÀNH CÔNG!</b>\n\n"
        f"📦 Gói: {html.escape(pkg_name)}\n"
        f"📱 SĐT cần spam: <code>{html.escape(phone)}</code>\n"
        f"💵 Đã trừ: {pkg_price:,.0f} VND\n"
        f"💳 Số dư còn lại: {new_bal:,.0f} VND\n"
        f"⏳ Trạng thái: Đang tiến hành spam."
    )
    
    success_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💣 Quản lý danh sách SMS", callback_data="sms_menu_main")],
        [InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]
    ])
    await update.message.reply_text(success_text, parse_mode="HTML", reply_markup=success_keyboard)
    return ConversationHandler.END

async def query_edit_or_replace_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode=None):
    query = update.callback_query
    if query.message.photo or query.message.video:
        await query.message.delete()
        return await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        return await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)

async def receive_broadcast_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        context.user_data["broadcast_media_type"] = "photo"
        context.user_data["broadcast_media_id"] = photo_id
    elif update.message.video:
        video_id = update.message.video.file_id
        context.user_data["broadcast_media_type"] = "video"
        context.user_data["broadcast_media_id"] = video_id
    else:
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
        await update.message.reply_text("⚠️ Vui lòng gửi <b>Hình ảnh</b>, <b>Video</b> hoặc bấm <b>Bỏ qua (Chỉ gửi chữ)</b>!", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return INPUT_BROADCAST_PHOTO

    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    text = (
        f"📢 <b>TẠO THÔNG BÁO CHO NGƯỜI DÙNG</b>\n"
        f"----------------------------------------\n"
        f"✅ Đã nhận đính kèm media thành công.\n\n"
        f"💬 Vui lòng gửi <b>Nội dung văn bản (caption)</b> cho thông báo (Hỗ trợ định dạng Markdown):"
    )
    keyboard = [
        [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
    ]
    msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data["prompt_msg_id"] = msg.message_id
    return INPUT_BROADCAST_TEXT

async def receive_broadcast_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    text_content = update.message.text
    if not text_content:
        return INPUT_BROADCAST_TEXT

    context.user_data["broadcast_text"] = text_content

    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    media_type = context.user_data.get("broadcast_media_type", "none")
    media_id = context.user_data.get("broadcast_media_id")

    preview_caption = (
        f"📋 *XEM TRƯỚC NỘI DUNG THÔNG BÁO BROADCAST:*\n"
        f"----------------------------------------\n\n"
        f"{text_content}"
    )
    keyboard = [
        [InlineKeyboardButton("🚀 Xác nhận gửi thông báo", callback_data="confirm_send_broadcast")],
        [InlineKeyboardButton("🔄 Gửi lại từ đầu", callback_data="admin_broadcast_menu")],
        [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
    ]

    async def _send_preview(pm):
        if media_type == "photo":
            return await update.message.reply_photo(photo=media_id, caption=preview_caption, parse_mode=pm, reply_markup=InlineKeyboardMarkup(keyboard))
        elif media_type == "video":
            return await update.message.reply_video(video=media_id, caption=preview_caption, parse_mode=pm, reply_markup=InlineKeyboardMarkup(keyboard))
        return await update.message.reply_text(preview_caption, parse_mode=pm, reply_markup=InlineKeyboardMarkup(keyboard))

    try:
        msg = await _send_preview("Markdown")
    except BadRequest:
        # Nội dung có ký tự Markdown lỗi -> gửi dạng văn bản thường
        msg = await _send_preview(None)

    context.user_data["prompt_msg_id"] = msg.message_id
    return ConversationHandler.END

async def receive_private_msg_user_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    target_id_str = update.message.text.strip()
    
    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    try:
        target_id = int(target_id_str)
    except ValueError:
        msg = await update.message.reply_text("⚠️ ID không hợp lệ! Vui lòng nhập lại ID (chỉ bao gồm số):")
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_PRIVATE_MSG_USER_ID

    context.user_data["private_target_id"] = target_id

    text = (
        f"👤 <b>GỬI THÔNG BÁO RIÊNG CHO ID:</b> <code>{target_id}</code>\n"
        f"----------------------------------------\n"
        f"ℹ️ Bạn có thể gửi thông báo kèm <b>Ảnh</b>, <b>Video</b> hoặc <b>Chỉ văn bản</b>.\n\n"
        f"💬 <i>Vui lòng gửi 01 HÌNH ẢNH hoặc 01 VIDEO đính kèm (hoặc bấm nút Bỏ qua bên dưới để chỉ gửi chữ):</i>"
    )
    keyboard = [
        [InlineKeyboardButton("⏩ Bỏ qua (Chỉ gửi văn bản)", callback_data="skip_private_media")],
        [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
    ]
    msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data["prompt_msg_id"] = msg.message_id
    return INPUT_PRIVATE_MSG_PHOTO

async def receive_private_msg_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    if update.message.photo:
        context.user_data["private_media_type"] = "photo"
        context.user_data["private_media_id"] = update.message.photo[-1].file_id
    elif update.message.video:
        context.user_data["private_media_type"] = "video"
        context.user_data["private_media_id"] = update.message.video.file_id
    else:
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        await update.message.reply_text("⚠️ Vui lòng gửi <b>Hình ảnh</b>, <b>Video</b> hoặc dùng nút <b>Bỏ qua</b>!", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return INPUT_PRIVATE_MSG_PHOTO

    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    target_id = context.user_data.get("private_target_id", "Không rõ")
    text = (
        f"👤 <b>GỬI THÔNG BÁO RIÊNG TỚI:</b> <code>{target_id}</code>\n"
        f"----------------------------------------\n"
        f"✅ Đã nhận đính kèm media thành công.\n\n"
        f"💬 <i>Vui lòng gửi <b>Nội dung văn bản</b> cho thông báo:</i>"
    )
    keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
    msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data["prompt_msg_id"] = msg.message_id
    return INPUT_PRIVATE_MSG_TEXT

async def receive_private_msg_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END

    text_content = update.message.text
    if not text_content:
        return INPUT_PRIVATE_MSG_TEXT

    try:
        await update.message.delete()
    except Exception:
        pass

    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_msg_id)
        except Exception:
            pass

    target_id = context.user_data.get("private_target_id")
    media_type = context.user_data.get("private_media_type", "none")
    media_id = context.user_data.get("private_media_id")

    reply_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Phản hồi Admin", callback_data="user_click_reply")]
    ])

    success = False
    try:
        if media_type == "photo":
            await context.bot.send_photo(chat_id=target_id, photo=media_id, caption=text_content, parse_mode="HTML", reply_markup=reply_keyboard)
        elif media_type == "video":
            await context.bot.send_video(chat_id=target_id, video=media_id, caption=text_content, parse_mode="HTML", reply_markup=reply_keyboard)
        else:
            await context.bot.send_message(chat_id=target_id, text=text_content, parse_mode="HTML", reply_markup=reply_keyboard)
        success = True
    except Exception as e:
        logging.error(f"Lỗi gửi tin nhắn riêng cho {target_id}: {e}")

    if success:
        result_text = f"✅ <b>GỬI THÀNH CÔNG!</b>\nĐã gửi tin nhắn riêng (có đính kèm nút Phản hồi) cho ID: <code>{target_id}</code>"
    else:
        result_text = f"❌ <b>GỬI THẤT BẠI!</b>\nKhông thể gửi tin nhắn. Có thể ID không tồn tại hoặc khách hàng đã chặn Bot."

    keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
    await update.message.reply_text(result_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def _button_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    get_user_data(user.id)

    if data.startswith("cmt_type:"):
        cmt_type = data.split(":")[1]
        await process_final_order(update, context, cmt_type)
        return

    elif data == "user_click_reply":
        text = (
            f"💬 <b>NHẬP NỘI DUNG PHẢN HỒI CHO ADMIN</b>\n"
            f"----------------------------------------\n"
            f"💬 <i>Vui lòng nhập tin nhắn hoặc nội dung bạn muốn phản hồi lại tới Admin:</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ])
        msg = await query_edit_or_replace_admin(update, context, text=text, parse_mode="HTML", reply_markup=keyboard)
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_USER_FEEDBACK

    elif data.startswith("admin_reply_user:"):
        if not is_admin(user.id, user.username):
            return
        target_uid = data.split(":")[1]
        context.user_data["private_target_id"] = int(target_uid)
        context.user_data["private_media_type"] = "none"
        context.user_data["private_media_id"] = None
        text = (
            f"👤 <b>GỬI TIN NHẮN TRẢ LỜI CHO KHÁCH ID:</b> <code>{target_uid}</code>\n"
            f"----------------------------------------\n"
            f"💬 <i>Vui lòng nhập nội dung văn bản phản hồi lại khách hàng:</i>"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        msg = await query_edit_or_replace_admin(update, context, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_PRIVATE_MSG_TEXT

    elif data == "create_bot_tele_menu":
        text = (
            f"🤖 <b>DỊCH VỤ TẠO BOT TELEGRAM THEO YÊU CẦU</b>\n"
            f"════════════════════════════════\n\n"
            f"⚡ Lập trình và thiết kế bot Telegram chuyên nghiệp, hoạt động 24/7.\n"
            f"👇 <i>Vui lòng chọn gói dịch vụ dưới đây:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("⭐ Bot Telegram Premium (500k)", callback_data="buy_create_bot_prem")],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "buy_create_bot_prem":
        text = (
            f"🤖 <b>ĐĂNG KÝ TẠO BOT TELEGRAM PREMIUM</b>\n"
            f"----------------------------------------\n"
            f"💵 <b>Chi phí:</b> <code>500,000 VNĐ</code>\n\n"
            f"💬 <i>Hãy gửi những tính năng và yêu cầu của bot bạn muốn tạo vào đây:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("↩️ Trở Về Menu Tạo Bot", callback_data="create_bot_tele_menu")],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        msg = await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_CREATE_BOT_REQUIREMENTS

    elif data == "tick_xanh_menu":
        text = (
            f"✔ <b>DỊCH VỤ TÍCH XANH FACEBOOK CHÍNH HÃNG</b>\n"
            f"════════════════════════════════\n\n"
            f"⭐ Cấp tích xanh uy tín, bảo hành đầy đủ.\n"
            f"👇 <i>Vui lòng chọn loại tích xanh bạn muốn đăng ký:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("⭐ Tick Xanh Fanpage (5.000.000đ)", callback_data="buy_tick:fanpage:5000000")],
            [InlineKeyboardButton("👤 Tick Xanh Trang Cá Nhân (2.000.000đ)", callback_data="buy_tick:tcn:2000000")],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("buy_tick:"):
        _, tick_type, price_str = data.split(":")
        price = float(price_str)
        name = "⭐ Tick Xanh Fanpage" if tick_type == "fanpage" else "👤 Tick Xanh Trang Cá Nhân"
        
        user_data = get_user_data(user.id)
        if user_data["balance"] < price:
            msg_text = (
                f"❌ <b>SỐ DƯ KHÔNG ĐỦ THANH TOÁN!</b>\n\n"
                f"💳 Số dư hiện tại: <code>{user_data['balance']:,.0f}đ</code>\n"
                f"💵 Cần thanh toán: <code>{price:,.0f}đ</code>\n\n"
                f"⚠️ <i>Vui lòng nạp thêm tiền để tiếp tục.</i>"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Nạp Tiền Ngay", callback_data="nap_tien"), InlineKeyboardButton("🏠 Menu", callback_data="menu_main")],
                [InlineKeyboardButton("↩️ Trở Về Menu Tích Xanh", callback_data="tick_xanh_menu")]
            ])
            await query.edit_message_text(msg_text, parse_mode="HTML", reply_markup=keyboard)
            return

        user_data["balance"] -= price
        user_data["history"].append(f"Mua Tích Xanh: {name} | Giá: {price:,.0f}đ")
        save_users_db()

        success_text = (
            f"🎉 <b>ĐẶT MUA TÍCH XANH THÀNH CÔNG!</b>\n"
            f"════════════════════════════════\n"
            f"📦 <b>Gói:</b> {name}\n"
            f"💵 <b>Đã thanh toán:</b> <code>{price:,.0f} VNĐ</code>\n"
            f"💳 <b>Số dư còn lại:</b> <code>{user_data['balance']:,.0f} VNĐ</code>\n\n"
            f"⏳ <i>Đơn hàng đã được chuyển tới Admin duyệt và xử lý liên hệ bạn sớm nhất.</i>"
        )
        keyboard = [
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        await query.edit_message_text(success_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

        user_mention = get_user_mention(user)
        admin_notice = (
            f"🔔 <b>CÓ ĐƠN ĐĂNG KÝ TÍCH XANH MỚI!</b>\n"
            f"----------------------------------------\n"
            f"👤 Khách: {user_mention} (ID: <code>{user.id}</code>)\n"
            f"📦 Gói: {name}\n"
            f"💵 Giá: {price:,.0f}đ"
        )
        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Đã nhận đơn", callback_data=f"admin_accept_order:{user.id}")],
            [InlineKeyboardButton("❌ Từ chối đơn", callback_data=f"admin_reject_order:{user.id}")]
        ])
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notice, parse_mode="HTML", reply_markup=admin_keyboard)
        except Exception:
            pass

    elif data.startswith("group_detail_"):
        gr_id = data.replace("group_detail_", "")
        group_info = next((g for g in ALL_GROUPS if g["id"] == gr_id), None)
        if group_info:
            mem_str = f"{group_info['mem']:,}".replace(",", ".")
            price_val = group_info["mem"] * 18
            text = (
                f"👥 <b>THÔNG TIN CHI TIẾT NHÓM FACEBOOK</b>\n"
                f"════════════════════════════════\n"
                f"🏷️ <b>Tên nhóm:</b> {html.escape(group_info['name'])}\n"
                f"👥 <b>Thành viên:</b> <code>{mem_str} thành viên</code>\n"
                f"🔗 <b>Đường dẫn:</b> <a href=\"{group_info['link']}\">Truy cập Group gốc</a>\n"
                f"💵 <b>Giá sở hữu:</b> <code>{price_val:,.0f} VNĐ</code>\n"
                f"════════════════════════════════\n"
                f"👇 <i>Bấm nút bên dưới để tiến hành thanh toán mua nhóm tự động:</i>"
            )
            keyboard = [
                [InlineKeyboardButton(f"💳 Mua Nhóm Ngay ({price_val:,.0f}đ)", callback_data=f"buy_group_now:{gr_id}")],
                [InlineKeyboardButton("↩️ Trở về danh sách nhóm", callback_data="item_cat_groups")],
                [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
            ]
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)
        else:
            await query.answer("⚠️ Không tìm thấy thông tin nhóm!", show_alert=True)

    elif data.startswith("buy_group_now:"):
        gr_id = data.replace("buy_group_now:", "")
        group_info = next((g for g in ALL_GROUPS if g["id"] == gr_id), None)
        if group_info:
            price_val = group_info["mem"] * 18
            user_data = get_user_data(user.id)
            
            if user_data["balance"] < price_val:
                msg_text = (
                    f"❌ <b>SỐ DƯ KHÔNG ĐỦ THANH TOÁN!</b>\n\n"
                    f"💳 Số dư hiện tại: <code>{user_data['balance']:,.0f}đ</code>\n"
                    f"💵 Cần thanh toán: <code>{price_val:,.0f}đ</code>\n\n"
                    f"⚠️ <i>Vui lòng nạp thêm tiền để tiếp tục.</i>"
                )
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Nạp Tiền Ngay", callback_data="nap_tien"), InlineKeyboardButton("🏠 Menu", callback_data="menu_main")],
                    [InlineKeyboardButton("↩️ Trở về danh sách nhóm", callback_data="item_cat_groups")]
                ])
                await query.edit_message_text(msg_text, parse_mode="HTML", reply_markup=keyboard)
                return

            user_data["balance"] -= price_val
            user_data["history"].append(f"Mua Nhóm FB: {group_info['name']} | Giá: {price_val:,.0f}đ | Link: {group_info['link']}")
            save_users_db()

            success_text = (
                f"🎉 <b>MUA NHÓM FACEBOOK THÀNH CÔNG!</b>\n"
                f"════════════════════════════════\n"
                f"🏷️ <b>Tên nhóm:</b> {html.escape(group_info['name'])}\n"
                f"🔗 <b>Link quản trị nhóm:</b> <code>{group_info['link']}</code>\n"
                f"💵 <b>Đã thanh toán:</b> <code>{price_val:,.0f} VNĐ</code>\n"
                f"💳 <b>Số dư còn lại:</b> <code>{user_data['balance']:,.0f} VNĐ</code>\n\n"
                f"📌 <i>Admin đã nhận yêu cầu bàn giao quyền sở hữu nhóm cho bạn qua tài khoản Telegram này.</i>"
            )
            keyboard = [
                [InlineKeyboardButton("📋 Xem danh sách nhóm khác", callback_data="item_cat_groups")],
                [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
            ]
            await query.edit_message_text(success_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

            user_mention = get_user_mention(user)
            admin_notice = (
                f"🔔 <b>CÓ KHÁCH MUA NHÓM FACEBOOK!</b>\n"
                f"----------------------------------------\n"
                f"👤 Khách: {user_mention} (ID: <code>{user.id}</code>)\n"
                f"🏷️ Nhóm: {html.escape(group_info['name'])}\n"
                f"🔗 Link: {group_info['link']}\n"
                f"💵 Giá: {price_val:,.0f}đ"
            )
            try:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notice, parse_mode="HTML")
            except Exception:
                pass
        else:
            await query.answer("⚠️ Giao dịch thất bại, nhóm không tồn tại!", show_alert=True)

    elif data == "sms_menu_main":
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]
        
        if active_sms:
            text = "💣 <b>QUẢN LÝ DỊCH VỤ SPAM SMS</b>\n----------------------------------------\n📜 <i>Danh sách số điện thoại đang chạy:</i> \n"
            keyboard = []
            for idx, item in enumerate(active_sms):
                remaining_time = int(item["expire_time"] - time.time())
                hours = remaining_time // 3600
                time_str = f"Còn {hours} giờ" if hours < 48 else f"Còn {hours//24} ngày"
                if item["expire_time"] > time.time() + 3000000000:
                    time_str = "Vĩnh viễn"
                
                text += f"\n{idx+1}. SĐT: <code>{html.escape(item['phone'])}</code> ({html.escape(item['package'])}) - {time_str}"
                keyboard.append([
                    InlineKeyboardButton(f"➕ Gia hạn ({item['phone']})", callback_data=f"sms_renew:{idx}"),
                    InlineKeyboardButton(f"❌ Hủy ({item['phone']})", callback_data=f"sms_cancel:{idx}")
                ])
            keyboard.append([InlineKeyboardButton("➕ Thêm SĐT Khác", callback_data="sms_add_another")])
            keyboard.append([InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            text = (
                f"💣 <b>DỊCH VỤ SPAM SMS AUTO</b>\n"
                f"════════════════════════════════\n\n"
                f"👇 <i>Chọn phân loại dịch vụ bên dưới:</i> "
            )
            keyboard = [
                [InlineKeyboardButton("📱 SMS Thường", callback_data="sms_cat_thuong")],
                [InlineKeyboardButton("👑 SMS VIP", callback_data="sms_cat_vip")],
                [InlineKeyboardButton("📋 Danh Sách Đã Spam", callback_data="sms_list_history")],
                [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
            ]
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "sms_add_another":
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]

        if active_sms:
            context.user_data["is_adding_free_phone"] = True
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="sms_menu_main"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
            msg = await query.edit_message_text(
                f"➕ <b>THÊM SỐ ĐIỆN THOẠI KHÁC</b>\n"
                f"----------------------------------------\n"
                f"ℹ️ Bạn đang có gói dịch vụ còn hạn, số điện thoại này sẽ được thêm hoàn toàn miễn phí.\n\n"
                f"💬 <i>Vui lòng gửi số điện thoại cần spam vào đây:</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["prompt_msg_id"] = msg.message_id
            return INPUT_SMS_PHONE
        else:
            text = (
                f"💣 <b>HỆ THỐNG SPAM SMS (MUA GÓI MỚI)</b>\n"
                f"----------------------------------------\n"
                f"⏳ Gói cũ của bạn đã hết hạn. Vui lòng chọn gói dịch vụ SMS mới:"
            )
            keyboard = [
                [InlineKeyboardButton("📱 SMS Thường", callback_data="sms_cat_thuong")],
                [InlineKeyboardButton("👑 SMS VIP", callback_data="sms_cat_vip")],
                [InlineKeyboardButton("↩️ Trở về quản lý SMS", callback_data="sms_menu_main")],
                [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
            ]
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data in ["sms_cat_thuong", "sms_cat_vip"]:
        cat_key = "sms_thuong" if data == "sms_cat_thuong" else "sms_vip"
        cat_data = SMS_PACKAGES[cat_key]
        text = f"🛠️ <b>{html.escape(cat_data['title'])}</b>\n\n👇 <i>Chọn gói dịch vụ cụ thể bên dưới:</i>"
        keyboard = []
        for pkg in cat_data["packages"]:
            keyboard.append([InlineKeyboardButton(f"{pkg['name']} ── [{pkg['price']:,.0f}đ]", callback_data=f"buy_sms:{cat_key}:{pkg['id']}")])
        keyboard.append([
            InlineKeyboardButton("↩️ Trở về", callback_data="sms_menu_main"),
            InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("buy_sms:"):
        _, cat_key, pkg_id = data.split(":")
        pkg_info = next((p for p in SMS_PACKAGES[cat_key]["packages"] if p["id"] == pkg_id), None)
        if pkg_info:
            context.user_data["buying_sms_pkg"] = pkg_info
            context.user_data["is_adding_free_phone"] = False
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data=f"sms_cat_{'thuong' if cat_key=='sms_thuong' else 'vip'}"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
            msg = await query.edit_message_text(
                f"📦 <b>ĐÃ CHỌN:</b> {html.escape(pkg_info['name'])}\n"
                f"💵 <b>GIÁ:</b> <code>{pkg_info['price']:,.0f}đ</code>\n\n"
                f"💬 <i>Vui lòng nhập số điện thoại cần spam vào đây:</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["prompt_msg_id"] = msg.message_id
            return INPUT_SMS_PHONE

    elif data == "sms_list_history":
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]
        if not active_sms:
            text = "ℹ️ Bạn chưa có số điện thoại nào đang trong tiến trình spam."
            keyboard = [
                [InlineKeyboardButton("➕ Thêm SĐT Khác", callback_data="sms_add_another")],
                [InlineKeyboardButton("↩️ Trở về", callback_data="sms_menu_main"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
            ]
        else:
            text = "📋 <b>DANH SÁCH SỐ ĐIỆN THOẠI ĐÃ SPAM:</b>\n----------------------------------------\n"
            keyboard = []
            for idx, item in enumerate(active_sms):
                text += f"{idx+1}. SĐT: <code>{html.escape(item['phone'])}</code> | Gói: {html.escape(item['package'])}\n"
                keyboard.append([
                    InlineKeyboardButton(f"➕ Gia hạn {item['phone']}", callback_data=f"sms_renew:{idx}"),
                    InlineKeyboardButton(f"❌ Hủy {item['phone']}", callback_data=f"sms_cancel:{idx}")
                ])
            keyboard.append([InlineKeyboardButton("➕ Thêm SĐT Khác", callback_data="sms_add_another")])
            keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="sms_menu_main"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("sms_cancel:"):
        idx = int(data.split(":")[1])
        if user.id in SMS_DB and len(SMS_DB[user.id]) > idx:
            removed = SMS_DB[user.id].pop(idx)
            save_sms_db()
            await query.answer(f"✅ Đã hủy spam số {removed['phone']}!", show_alert=True)
        else:
            await query.answer("⚠️ Không tìm thấy số điện thoại!", show_alert=True)
        
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]
        if active_sms:
            text = "💣 <b>QUẢN LÝ DỊCH VỤ SPAM SMS</b>\n----------------------------------------\n📜 Danh sách số điện thoại đang spam của bạn:\n"
            keyboard = []
            for i, item in enumerate(active_sms):
                text += f"\n{i+1}. SĐT: <code>{html.escape(item['phone'])}</code> ({html.escape(item['package'])})"
                keyboard.append([
                    InlineKeyboardButton(f"➕ Gia hạn ({item['phone']})", callback_data=f"sms_renew:{i}"),
                    InlineKeyboardButton(f"❌ Hủy ({item['phone']})", callback_data=f"sms_cancel:{i}")
                ])
            keyboard.append([InlineKeyboardButton("➕ Thêm SĐT Khác", callback_data="sms_add_another")])
            keyboard.append([InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            text, reply_markup = main_menu_keyboard(user.id, user.username, user.first_name)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("sms_renew:"):
        idx = int(data.split(":")[1])
        if user.id in SMS_DB and len(SMS_DB[user.id]) > idx:
            item = SMS_DB[user.id][idx]
            item["expire_time"] += 86400
            save_sms_db()
            await query.answer(f"✅ Đã gia hạn thành công số {item['phone']} thêm 1 ngày!", show_alert=True)
        else:
            await query.answer("⚠️ Không tìm thấy số điện thoại!", show_alert=True)
        
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]
        text = "💣 <b>QUẢN LÝ DỊCH VỤ SPAM SMS</b>\n----------------------------------------\n📜 Danh sách số điện thoại đang spam của bạn:\n"
        keyboard = []
        for i, item in enumerate(active_sms):
            text += f"\n{i+1}. SĐT: <code>{html.escape(item['phone'])}</code> ({html.escape(item['package'])})"
            keyboard.append([
                InlineKeyboardButton(f"➕ Gia hạn ({item['phone']})", callback_data=f"sms_renew:{i}"),
                InlineKeyboardButton(f"❌ Hủy ({item['phone']})", callback_data=f"sms_cancel:{i}")
            ])
        keyboard.append([InlineKeyboardButton("➕ Thêm SĐT Khác", callback_data="sms_add_another")])
        keyboard.append([InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "admin_panel":
        if not is_admin(user.id, user.username):
            await query.answer("❌ Bạn không có quyền truy cập!", show_alert=True)
            return
        
        text = (
            f"⚙️ <b>QUẢN LÝ HỆ THỐNG (ADMIN PANEL)</b>\n"
            f"----------------------------------------\n"
            f"👇 <i>Lựa chọn chức năng quản trị bên dưới:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("👥 Danh sách Khách & Số Dư", callback_data="admin_list_users")],
            [InlineKeyboardButton("➕ Cộng Số Dư Hàng Loạt", callback_data="admin_bulk_topup_menu")],
            [InlineKeyboardButton("🎁 Tạo & Quản lý Gitcode", callback_data="admin_gitcode_menu")],
            [InlineKeyboardButton("📱 Xem các gói SMS đang chạy", callback_data="admin_sms_list_all")],
            [InlineKeyboardButton("🎉 Cài Đặt Khuyến Mãi Nạp", callback_data="admin_promo_menu")],
            [InlineKeyboardButton("📢 Tạo Thông Báo Broadcast", callback_data="admin_broadcast_menu")],
            [InlineKeyboardButton("👤 Gửi Thông Báo Riêng (Cá Nhân)", callback_data="admin_private_msg_menu")],
            [InlineKeyboardButton("💾 AUTO_BACKUP (Telegram)", callback_data="admin_backup_menu")],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_bulk_topup_menu":
        if not is_admin(user.id, user.username):
            return
        context.user_data.pop("bulk_topup", None)
        text = (
            f"➕ <b>CỘNG SỐ DƯ HÀNG LOẠT</b>\n"
            f"----------------------------------------\n"
            f"💬 Gửi danh sách, <b>mỗi khách 1 dòng</b>:\n"
            f"<code>ID SỐ_TIỀN</code>\n\n"
            f"Ví dụ:\n"
            f"<code>6900793565 50000\n"
            f"1234567890 100k\n"
            f"5555555555 20.000</code>\n\n"
            f"👥 Muốn cộng cho <b>TẤT CẢ khách</b> thì gửi 1 dòng:\n"
            f"<code>ALL 10000</code>\n\n"
            f"🔕 <i>Khách hàng sẽ không nhận thông báo. Bạn sẽ được xem lại và xác nhận trước khi cộng.</i>"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_BULK_TOPUP

    elif data == "bulk_topup_confirm":
        if not is_admin(user.id, user.username):
            return
        job = context.user_data.pop("bulk_topup", None)
        if not job:
            await query.edit_message_text(
                "⚠️ Phiên cộng tiền đã hết hạn hoặc đã được xử lý rồi.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]])
            )
            return
        count, total = 0, 0.0
        with DB_LOCK:
            if job["mode"] == "all":
                plan = {uid: job["amount"] for uid in list(USERS_DB.keys())}
            else:
                plan = job["entries"]
            for uid, amt in plan.items():
                ud = get_user_data(uid)  # ID chưa có sẽ được tạo mới
                ud["balance"] += amt
                ud["history"].append(f"Admin cộng số dư: +{amt:,.0f}đ")
                count += 1
                total += amt
            save_users_db()
        tg_backup_async("admin cộng hàng loạt")
        await query.edit_message_text(
            f"✅ <b>ĐÃ CỘNG SỐ DƯ HÀNG LOẠT!</b>\n\n"
            f"👥 Số khách đã cộng: <code>{count}</code>\n"
            f"💰 Tổng tiền: <code>{total:,.0f}đ</code>\n"
            f"🔕 <i>Không gửi thông báo cho khách.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]])
        )

    elif data in ("admin_backup_menu", "admin_backup_now"):
        if not is_admin(user.id, user.username):
            return
        note = ""
        if data == "admin_backup_now":
            ok = await asyncio.to_thread(tg_backup_send, "thủ công")
            note = "✅ <b>Đã gửi backup vào chat Telegram!</b>\n\n" if ok else \
                   f"❌ <b>Backup thất bại:</b> {html.escape(_TG_STATE.get('last_err') or 'không rõ')}\n\n"
        last_ok = _TG_STATE.get("last_ok", 0)
        last_txt = time.strftime("%H:%M:%S %d/%m/%Y", time.gmtime(last_ok + 7 * 3600)) if last_ok else "chưa có"
        state_txt = "🟢 Đang bật" if _tg_ready() else "🔴 Chưa bật"
        text = (
            f"💾 <b>AUTO_BACKUP DỮ LIỆU (TELEGRAM)</b>\n"
            f"----------------------------------------\n"
            f"{note}"
            f"📌 <b>Trạng thái:</b> {state_txt}\n"
            f"🕒 <b>Backup gần nhất:</b> {last_txt}\n"
            f"👥 <b>Số khách:</b> {len(USERS_DB)}\n\n"
            f"ℹ️ Mỗi khi cộng/sửa tiền, nạp SePay, gitcode... bot tự gửi file <code>backup_*.zip</code> và ghim trong chat này.\n"
            f"♻️ <b>Khôi phục:</b> gửi file <code>backup_*.zip</code> cho bot (chỉ Admin), dữ liệu hiện tại sẽ bị thay bằng bản backup."
        )
        keyboard = [
            [InlineKeyboardButton("📤 Backup ngay", callback_data="admin_backup_now")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_promo_menu" or data.startswith("set_promo:"):
        if not is_admin(user.id, user.username):
            return
        if data.startswith("set_promo:"):
            set_promo_percent(float(data.split(":")[1]))
        pct = get_promo_percent()
        status = f"🟢 Đang bật: <b>+{pct:g}%</b> trên số tiền khách nạp" if pct > 0 else "🔴 Đang tắt"
        text = (
            f"🎉 <b>CÀI ĐẶT KHUYẾN MÃI NẠP TIỀN</b>\n"
            f"----------------------------------------\n"
            f"📌 <b>Trạng thái:</b> {status}\n\n"
            f"ℹ️ Khi bật, mã QR của khách sẽ hiện khuyến mãi và khách nạp bao nhiêu sẽ được cộng thêm đúng % đó.\n\n"
            f"👇 <i>Chọn nhanh mức khuyến mãi hoặc nhập tùy ý:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("5%", callback_data="set_promo:5"), InlineKeyboardButton("10%", callback_data="set_promo:10"), InlineKeyboardButton("20%", callback_data="set_promo:20")],
            [InlineKeyboardButton("30%", callback_data="set_promo:30"), InlineKeyboardButton("50%", callback_data="set_promo:50"), InlineKeyboardButton("100%", callback_data="set_promo:100")],
            [InlineKeyboardButton("✍️ Nhập % tùy ý", callback_data="promo_custom")],
            [InlineKeyboardButton("🚫 Tắt khuyến mãi", callback_data="set_promo:0")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "promo_custom":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"✍️ <b>NHẬP % KHUYẾN MÃI NẠP</b>\n"
            f"----------------------------------------\n"
            f"💬 Nhắn số phần trăm (0 - 100). Ví dụ: <code>15</code>\n"
            f"<i>Nhập 0 để tắt khuyến mãi.</i>"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="admin_promo_menu")]]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_PROMO_PERCENT

    elif data.startswith("admin_cmt_done:"):
        if not is_admin(user.id, user.username):
            return
        done_msgs = context.bot_data.setdefault("done_msgs", set())
        msg_key = (query.message.chat_id, query.message.message_id)
        if msg_key in done_msgs:
            return
        done_msgs.add(msg_key)
        target_uid = int(data.split(":")[1])
        try:
            await query.edit_message_text(
                f"{query.message.text_html}\n\n✅ <b>ADMIN ĐÃ CHẠY XONG ĐƠN</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 ĐÃ HOÀN THÀNH", callback_data="none")]])
            )
        except BadRequest:
            pass
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text="✅ <b>Đơn bình luận của bạn đã được Admin chạy xong!</b> Cảm ơn bạn đã sử dụng dịch vụ.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    elif data.startswith("admin_cmt_refund:"):
        if not is_admin(user.id, user.username):
            return
        done_msgs = context.bot_data.setdefault("done_msgs", set())
        msg_key = (query.message.chat_id, query.message.message_id)
        if msg_key in done_msgs:
            return
        done_msgs.add(msg_key)
        _, uid_str, amt_str = data.split(":")
        target_uid, refund_amt = int(uid_str), float(amt_str)
        with DB_LOCK:
            target_data = get_user_data(target_uid)
            target_data["balance"] += refund_amt
            target_data["history"].append(f"Hoàn tiền đơn cmt bị từ chối: +{refund_amt:,.0f}đ")
            save_users_db()
            new_bal = target_data["balance"]
        try:
            await query.edit_message_text(
                f"{query.message.text_html}\n\n❌ <b>ĐÃ TỪ CHỐI - HOÀN {refund_amt:,.0f}đ CHO KHÁCH</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔴 ĐÃ HOÀN TIỀN", callback_data="none")]])
            )
        except BadRequest:
            pass
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=(
                    f"❌ <b>Đơn bình luận của bạn đã bị Admin từ chối.</b>\n"
                    f"💵 Đã hoàn lại <code>{refund_amt:,.0f}đ</code> vào số dư.\n"
                    f"💳 Số dư hiện tại: <code>{new_bal:,.0f}đ</code>\n"
                    f"Liên hệ Admin {html.escape(ADMIN_USERNAME)} để được hỗ trợ."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    elif data == "admin_private_msg_menu":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"👤 <b>GỬI THÔNG BÁO RIÊNG CHO KHÁCH</b>\n"
            f"----------------------------------------\n"
            f"💬 <i>Vui lòng nhập ID Telegram của khách hàng bạn muốn gửi tin nhắn riêng:</i>"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        msg = await query_edit_or_replace_admin(update, context, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_PRIVATE_MSG_USER_ID

    elif data == "skip_private_media":
        if not is_admin(user.id, user.username):
            return
        context.user_data["private_media_type"] = "none"
        context.user_data["private_media_id"] = None
        target_id = context.user_data.get("private_target_id", "Không rõ")
        
        text = (
            f"👤 <b>GỬI THÔNG BÁO RIÊNG (CHỈ VĂN BẢN)</b>\n"
            f"----------------------------------------\n"
            f"🎯 <b>Người nhận:</b> <code>{target_id}</code>\n"
            f"💬 <i>Vui lòng nhập nội dung văn bản cho thông báo:</i>"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        msg = await query_edit_or_replace_admin(update, context, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_PRIVATE_MSG_TEXT

    elif data == "admin_broadcast_menu":
        if not is_admin(user.id, user.username):
            return
        
        context.user_data["broadcast_media_type"] = "none"
        context.user_data["broadcast_media_id"] = None

        text = (
            f"📢 <b>TẠO THÔNG BÁO BROADCAST</b>\n"
            f"----------------------------------------\n"
            f"ℹ️ Cho phép gửi thông báo kèm <b>Ảnh</b>, <b>Video</b> hoặc <b>Chỉ văn bản</b>.\n\n"
            f"💬 <i>Vui lòng gửi 01 HÌNH ẢNH hoặc 01 VIDEO đính kèm cho thông báo (hoặc bấm nút Bỏ qua bên dưới):</i>"
        )
        keyboard = [
            [InlineKeyboardButton("⏩ Bỏ qua (Chỉ gửi văn bản)", callback_data="skip_broadcast_media")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        
        msg = await query_edit_or_replace_admin(update, context, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_BROADCAST_PHOTO

    elif data == "skip_broadcast_media":
        if not is_admin(user.id, user.username):
            return
        context.user_data["broadcast_media_type"] = "none"
        context.user_data["broadcast_media_id"] = None

        text = (
            f"📢 <b>TẠO THÔNG BÁO BROADCAST (CHỈ VĂN BẢN)</b>\n"
            f"----------------------------------------\n"
            f"💬 <i>Vui lòng nhập nội dung văn bản cho thông báo:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        msg = await query_edit_or_replace_admin(update, context, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_BROADCAST_TEXT

    elif data == "confirm_send_broadcast":
        if not is_admin(user.id, user.username):
            return

        media_type = context.user_data.get("broadcast_media_type", "none")
        media_id = context.user_data.get("broadcast_media_id")
        text_content = context.user_data.get("broadcast_text")

        if not text_content:
            await query.answer("⚠️ Dữ liệu thông báo chưa đầy đủ!", show_alert=True)
            return

        await query_edit_or_replace_admin(update, context, text="⏳ Đang tiến hành phát thông báo broadcast đến người dùng...", reply_markup=None)

        success_count = 0
        fail_count = 0

        async def _broadcast_one(uid, pm):
            if media_type == "photo":
                await context.bot.send_photo(chat_id=uid, photo=media_id, caption=text_content, parse_mode=pm)
            elif media_type == "video":
                await context.bot.send_video(chat_id=uid, video=media_id, caption=text_content, parse_mode=pm)
            else:
                await context.bot.send_message(chat_id=uid, text=text_content, parse_mode=pm)

        for uid in list(USERS_DB.keys()):
            try:
                try:
                    await _broadcast_one(uid, "Markdown")
                except BadRequest:
                    await _broadcast_one(uid, None)
                success_count += 1
            except Exception:
                fail_count += 1
            await asyncio.sleep(0.05)

        result_text = (
            f"✅ <b>GỬI THÔNG BÁO BROADCAST HOÀN TẤT!</b>\n\n"
            f"📨 Gửi thành công: <code>{success_count}</code> người dùng\n"
            f"❌ Thất bại: <code>{fail_count}</code> người dùng"
        )
        keyboard = [
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        await query_edit_or_replace_admin(update, context, text=result_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_sms_list_all":
        if not is_admin(user.id, user.username):
            return
        
        if not SMS_DB:
            text = "ℹ️ Hiện chưa có khách hàng nào mua gói spam SMS."
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="admin_panel")]]
        else:
            text = "📱 <b>QUẢN LÝ GÓI SPAM SMS KHÁCH HÀNG:</b>\n----------------------------------------\n"
            keyboard = []
            for uid, sms_list in SMS_DB.items():
                for i, s in enumerate(sms_list):
                    if s["expire_time"] > time.time():
                        text += f"• ID: <code>{uid}</code> | SĐT: <code>{html.escape(s['phone'])}</code> | Gói: {html.escape(s['package'])}\n"
                        keyboard.append([
                            InlineKeyboardButton(f"➕ Gia hạn (ID {uid})", callback_data=f"admin_sms_renew:{uid}:{i}"),
                            InlineKeyboardButton(f"❌ Hủy (ID {uid})", callback_data=f"admin_sms_cancel:{uid}:{i}")
                        ])
            keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_panel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("admin_sms_cancel:"):
        if not is_admin(user.id, user.username):
            return
        _, uid_str, idx_str = data.split(":")
        uid, idx = int(uid_str), int(idx_str)
        if uid in SMS_DB and len(SMS_DB[uid]) > idx:
            removed = SMS_DB[uid].pop(idx)
            save_sms_db()
            await query.answer(f"✅ Đã hủy spam số {removed['phone']} của khách {uid}!", show_alert=True)
        else:
            await query.answer("⚠️ Không tìm thấy dữ liệu!", show_alert=True)
        
        text = "📱 <b>QUẢN LÝ GÓI SPAM SMS KHÁCH HÀNG:</b>\n----------------------------------------\n"
        keyboard = []
        for uid, sms_list in SMS_DB.items():
            for i, s in enumerate(sms_list):
                if s["expire_time"] > time.time():
                    text += f"• ID: <code>{uid}</code> | SĐT: <code>{html.escape(s['phone'])}</code> | Gói: {html.escape(s['package'])}\n"
                    keyboard.append([
                        InlineKeyboardButton(f"➕ Gia hạn (ID {uid})", callback_data=f"admin_sms_renew:{uid}:{i}"),
                        InlineKeyboardButton(f"❌ Hủy (ID {uid})", callback_data=f"admin_sms_cancel:{uid}:{i}")
                    ])
        keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_panel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("admin_sms_renew:"):
        if not is_admin(user.id, user.username):
            return
        _, uid_str, idx_str = data.split(":")
        uid, idx = int(uid_str), int(idx_str)
        if uid in SMS_DB and len(SMS_DB[uid]) > idx:
            SMS_DB[uid][idx]["expire_time"] += 86400
            save_sms_db()
            await query.answer(f"✅ Đã gia hạn thành công cho ID {uid}!", show_alert=True)
        else:
            await query.answer("⚠️ Không tìm thấy dữ liệu!", show_alert=True)
        
        text = "📱 <b>QUẢN LÝ GÓI SPAM SMS KHÁCH HÀNG:</b>\n----------------------------------------\n"
        keyboard = []
        for uid, sms_list in SMS_DB.items():
            for i, s in enumerate(sms_list):
                if s["expire_time"] > time.time():
                    text += f"• ID: <code>{uid}</code> | SĐT: <code>{html.escape(s['phone'])}</code> | Gói: {html.escape(s['package'])}\n"
                    keyboard.append([
                        InlineKeyboardButton(f"➕ Gia hạn (ID {uid})", callback_data=f"admin_sms_renew:{uid}:{i}"),
                        InlineKeyboardButton(f"❌ Hủy (ID {uid})", callback_data=f"admin_sms_cancel:{uid}:{i}")
                    ])
        keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_panel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "menu_main":
        text, reply_markup = main_menu_keyboard(user.id, user.username, user.first_name)
        if query.message.photo or query.message.video:
            await query.message.delete()
            await query.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "cat_fb":
        text, reply_markup = fb_menu_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "cat_tt":
        text, reply_markup = tiktok_menu_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "cat_yt":
        text, reply_markup = youtube_menu_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "cat_ig":
        text, reply_markup = instagram_menu_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("subcat_fb_") or data.startswith("subcat_tt_") or data.startswith("subcat_yt_") or data.startswith("subcat_ig_"):
        cat_key = data.replace("subcat_", "")
        context.user_data["current_cat_key"] = cat_key
        if cat_key in SERVICES:
            text, reply_markup = service_items_keyboard(cat_key)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await query.answer("⚠️ Dịch vụ này đang được cập nhật, vui lòng quay lại sau!", show_alert=True)

    elif data == "menu_gitcode":
        text = (
            f"🎁 <b>NHẬP MÃ GITCODE ĐỔI THƯỞNG</b>\n"
            f"----------------------------------------\n"
            f"💬 <i>Vui lòng gửi mã Gitcode của bạn vào đây để cộng số dư:</i> "
        )
        keyboard = [[InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
        msg = await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_GITCODE

    elif data == "admin_list_users":
        if not is_admin(user.id, user.username):
            return
        
        if not USERS_DB:
            text = "ℹ️ Hiện chưa có khách hàng nào sử dụng bot."
        else:
            text = "👥 <b>DANH SÁCH KHÁCH HÀNG:</b>\n----------------------------------------\n"
            for uid, info in USERS_DB.items():
                text += f"• 🆔 ID: <code>{uid}</code> | 💵 Số dư: <code>{info.get('balance', 0):,.0f}đ</code>\n"

        keyboard = [
            [InlineKeyboardButton("✏️ Sửa / Xóa số dư khách", callback_data="admin_prompt_edit_balance")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "admin_prompt_edit_balance":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"✏️ <b>CHỈNH SỬA / XÓA SỐ DƯ KHÁCH HÀNG</b>\n"
            f"----------------------------------------\n"
            f"💬 Gửi tin nhắn theo cú pháp: <code>&lt;ID_KHÁCH&gt; &lt;SỐ_TIỀN_MỚI&gt;</code>\n"
            f"*(Ví dụ set 500k: <code>6900793565 500000</code>)*"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_ADMIN_EDIT_USER

    elif data == "admin_gitcode_menu":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"🎁 <b>QUẢN LÝ MÃ GITCODE KHUYẾN MÃI</b>\n"
            f"----------------------------------------\n"
            f"👇 <i>Thực hiện các thao tác quản lý bên dưới:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("➕ Tạo Gitcode Mới", callback_data="admin_create_gc_sub")],
            [InlineKeyboardButton("📋 Xem Danh Sách Gitcode", callback_data="admin_list_gitcodes")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_create_gc_sub":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"➕ <b>TẠO MÃ GITCODE MỚI</b>\n"
            f"----------------------------------------\n"
            f"👇 <i>Tạo nhanh theo mệnh giá hoặc viết tùy ý:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("💵 10.000 đ", callback_data="create_gc:10000"), InlineKeyboardButton("💵 20.000 đ", callback_data="create_gc:20000"), InlineKeyboardButton("💵 50.000 đ", callback_data="create_gc:50000")],
            [InlineKeyboardButton("💵 100.000 đ", callback_data="create_gc:100000")],
            [InlineKeyboardButton("✍️ Tự Viết Mã & Mệnh Giá Tùy Ý", callback_data="create_gc_custom")],
            [InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_list_gitcodes":
        if not is_admin(user.id, user.username):
            return
        
        if not GITCODE_DB:
            text = "ℹ️ Hiện tại hệ thống chưa có mã Gitcode nào."
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")]]
        else:
            text = f"📋 <b>DANH SÁCH MÃ GITCODE ({len(GITCODE_DB)} mã):</b>\n----------------------------------------\n"
            keyboard = []
            for code, info in GITCODE_DB.items():
                used_count = len(info.get("used_by", []))
                text += f"• 🎁 Mã: <code>{html.escape(code)}</code> | 💵 Mệnh giá: <code>{info.get('amount', 0):,.0f}đ</code> | 👤 Đã dùng: <code>{used_count}</code>\n"
                keyboard.append([InlineKeyboardButton(f"🗑️ Xóa mã: {code}", callback_data=f"delete_gc:{code}")])
            
            keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")])

        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("delete_gc:"):
        if not is_admin(user.id, user.username):
            return
        code_to_delete = data.split(":")[1]
        if code_to_delete in GITCODE_DB:
            del GITCODE_DB[code_to_delete]
            save_gitcode_db()
            await query.answer(f"✅ Đã xóa thành công mã {code_to_delete}!", show_alert=True)
        else:
            await query.answer("⚠️ Mã không tồn tại!", show_alert=True)
        
        if not GITCODE_DB:
            text = "ℹ️ Hiện tại hệ thống chưa có mã Gitcode nào."
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")]]
        else:
            text = f"📋 <b>DANH SÁCH MÃ GITCODE ({len(GITCODE_DB)} mã):</b>\n----------------------------------------\n"
            keyboard = []
            for code, info in GITCODE_DB.items():
                used_count = len(info.get("used_by", []))
                text += f"• 🎁 Mã: <code>{html.escape(code)}</code> | 💵 Mệnh giá: <code>{info.get('amount', 0):,.0f}đ</code> | 👤 Đã dùng: <code>{used_count}</code>\n"
                keyboard.append([InlineKeyboardButton(f"🗑️ Xóa mã: {code}", callback_data=f"delete_gc:{code}")])
            keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")])

        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("create_gc:"):
        if not is_admin(user.id, user.username):
            return
        amount = int(data.split(":")[1])
        import random
        import string
        code = "KM" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        GITCODE_DB[code] = {"amount": float(amount), "used_by": []}
        save_gitcode_db()

        text = (
            f"✅ <b>ĐÃ TẠO GITCODE THÀNH CÔNG!</b>\n\n"
            f"🎁 Mã: <code>{html.escape(code)}</code>\n"
            f"💵 Mệnh giá: <code>{amount:,.0f} VND</code>"
        )
        keyboard = [
            [InlineKeyboardButton("📋 Xem Danh Sách Gitcode", callback_data="admin_list_gitcodes")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "create_gc_custom":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"✍️ <b>TẠO MÃ GITCODE TÙY CHỈNH</b>\n"
            f"----------------------------------------\n"
            f"💬 Nhắn tin theo cú pháp: <code>&lt;MÃ_CODE&gt; &lt;SỐ_TIỀN&gt;</code>\n"
            f"*(Ví dụ: <code>TET2026 100000</code>)*"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_CREATE_CODE_CUSTOM

    elif data == "view_history":
        user_data = get_user_data(user.id)
        history = user_data.get("history", [])
        
        if not history:
            history_text = "ℹ️ Bạn chưa có lịch sử giao dịch nào."
        else:
            history_text = "📜 <b>LỊCH SỬ GIAO DỊCH GẦN ĐÂY:</b>\n----------------------------------------\n"
            for idx, item in enumerate(reversed(history[-15:]), 1):
                safe_item = html.escape(str(item))
                history_text += f"<b>{idx}.</b> {safe_item}\n\n"

        keyboard = [[InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
        await query.edit_message_text(
            history_text, 
            parse_mode="HTML", 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            disable_web_page_preview=True
        )

    elif data.startswith("buy:"):
        _, cat_key, item_id = data.split(":")
        context.user_data["current_cat_key"] = cat_key
        cat_data = SERVICES.get(cat_key, {})
        selected_item = next((i for i in cat_data.get("items", []) if i["id"] == item_id), None)
        if selected_item:
            context.user_data["buying_service"] = selected_item
            
            keyboard = [
                [
                    InlineKeyboardButton("↩️ Chọn lại gói", callback_data=f"subcat_{cat_key}"),
                    InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
                ]
            ]
            
            msg = await query.edit_message_text(
                f"📦 <b>ĐÃ CHỌN GÓI:</b> {html.escape(selected_item['name'])}\n"
                f"💵 <b>GIÁ CƯỚC:</b> <code>{selected_item['price']}đ</code> / lượt\n\n"
                f"🔗 <b>GỬI LINK TƯƠNG TÁC:</b>\n"
                f"• Vui lòng gửi đường dẫn bài viết/kênh/trang cần buff.\n"
                f"• <i>Ví dụ:</i> <code>https://...</code>\n\n"
                f"💬 <i>Gửi link của bạn vào đây:</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["prompt_msg_id"] = msg.message_id
            return INPUT_LINK

    elif data == "nap_tien":
        keyboard = [
            [InlineKeyboardButton("💵 10.000 đ", callback_data="amount:10000"), InlineKeyboardButton("💵 50.000 đ", callback_data="amount:50000"), InlineKeyboardButton("💵 100.000 đ", callback_data="amount:100000")],
            [InlineKeyboardButton("💵 200.000 đ", callback_data="amount:200000"), InlineKeyboardButton("💵 500.000 đ", callback_data="amount:500000"), InlineKeyboardButton("💵 1.000.000 đ", callback_data="amount:1000000")],
            [InlineKeyboardButton("⌨️ Nhập Số Tiền Tùy Ý", callback_data="custom_amount")],
            [InlineKeyboardButton("🏠 Trở Về Menu", callback_data="menu_main")]
        ]
        text = (
            f"💳 <b>NẠP TIỀN TỰ ĐỘNG</b>\n"
            f"════════════════════════════════\n\n"
            f"👇 <i>Chọn nhanh mệnh giá nạp bên dưới:</i> "
        )
        if query.message.photo or query.message.video:
            await query.message.delete()
            await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "custom_amount":
        await query.edit_message_text("⌨️ <b>NHẬP SỐ TIỀN MUỐN NẠP</b>\n\n💬 Nhắn số tiền muốn nạp (Ví dụ: 150000):", parse_mode="HTML")
        return INPUT_TOPUP_AMOUNT

    elif data.startswith("amount:"):
        amount = int(data.split(":")[1])
        text, markup = build_bank_choice(amount)
        if query.message.photo:
            await query.message.delete()
            await context.bot.send_message(chat_id=user.id, text=text, parse_mode="HTML", reply_markup=markup)
        else:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)

    elif data.startswith("bank:"):
        _, idx_str, amount_str = data.split(":")
        bank_idx, amount = int(idx_str), int(amount_str)
        qr_url, text = build_topup_qr(user.id, amount, bank_idx)
        keyboard = [
            [InlineKeyboardButton("✅ Đã Chuyển Khoản", callback_data=f"confirm_trans:{amount}")],
            [InlineKeyboardButton("🏦 Đổi Số Tài Khoản", callback_data=f"amount:{amount}")],
            [InlineKeyboardButton("🔄 Chọn Lại Mệnh Giá", callback_data="nap_tien")]
        ]
        await context.bot.send_photo(chat_id=user.id, photo=qr_url, caption=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        try:
            await query.message.delete()
        except Exception:
            pass

    elif data.startswith("confirm_trans:"):
        amount = float(data.split(":")[1])
        await query.edit_message_caption(
            caption=f"⏳ Đã gửi yêu cầu nạp <code>{amount:,.0f} VNĐ</code>. Hệ thống đang xử lý duyệt tiền...",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Trở Về Menu", callback_data="menu_main")]])
        )
        user_mention = get_user_mention(user)

        admin_notice = (
            f"🔔 <b>YÊU CẦU NẠP TIỀN MỚI!</b>\n"
            f"----------------------------------------\n"
            f"👤 Khách: {user_mention} (ID: <code>{user.id}</code>)\n"
            f"💵 Số tiền: <code>{amount:,.0f} VNĐ</code>\n"
            f"📝 Nội dung CK: <code>{user.id}</code>"
        )
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Duyệt cộng {amount:,.0f}đ", callback_data=f"admin_approve_topup:{user.id}:{amount}")],
            [InlineKeyboardButton("❌ Chưa nhận được tiền", callback_data=f"admin_reject_topup:{user.id}:{amount}")]
        ])
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notice, parse_mode="HTML", reply_markup=btn)
        except Exception:
            pass

    elif data.startswith("admin_approve_topup:"):
        if not is_admin(user.id, user.username):
            return
        done_msgs = context.bot_data.setdefault("done_msgs", set())
        msg_key = (query.message.chat_id, query.message.message_id)
        if msg_key in done_msgs:
            return
        done_msgs.add(msg_key)
        _, target_id_str, amount_str = data.split(":")
        target_id, amount = int(target_id_str), float(amount_str)
        user_data = get_user_data(target_id)
        bonus = calc_bonus(amount)
        user_data["balance"] += amount + bonus
        hist = f"Nạp tiền (Admin duyệt): +{amount:,.0f}đ"
        if bonus > 0:
            hist += f" | Khuyến mãi {get_promo_percent():g}%: +{bonus:,.0f}đ"
        user_data["history"].append(hist)
        save_users_db() 
        tg_backup_async("admin duyệt nạp tiền")
        
        new_bal = user_data["balance"]
        
        try:
            target_user = await context.bot.get_chat(target_id)
            user_tag = f"@{html.escape(target_user.username)}" if target_user.username else f"ID <code>{target_id}</code>"
        except Exception:
            user_tag = f"ID <code>{target_id}</code>"

        bonus_admin = f" (+{bonus:,.0f}đ khuyến mãi)" if bonus > 0 else ""
        admin_base_text = f"✅ Đã cộng {amount:,.0f}đ{bonus_admin} cho khách {user_tag}"
        await query.edit_message_text(f"{admin_base_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau 30s...</i>", parse_mode="HTML")
        await auto_delete_with_countdown(context, query.message.chat_id, query.message.message_id, admin_base_text, 30)

        try:
            bonus_line = f"🎁 <b>Khuyến mãi:</b> +{bonus:,.0f} VND\n" if bonus > 0 else ""
            user_base_text = f"🎉 <b>BẠN ĐÃ ĐƯỢC CỘNG TIỀN THÀNH CÔNG!</b>\n\n💰 <b>Số tiền nạp:</b> +{amount:,.0f} VND\n{bonus_line}💳 <b>Số dư hiện tại:</b> {new_bal:,.0f} VND"
            user_notify = await context.bot.send_message(
                chat_id=target_id,
                text=f"{user_base_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau 30s...</i>",
                parse_mode="HTML"
            )
            await auto_delete_with_countdown(context, target_id, user_notify.message_id, user_base_text, 30)
        except Exception:
            pass

    elif data.startswith("admin_reject_topup:"):
        if not is_admin(user.id, user.username):
            return
        done_msgs = context.bot_data.setdefault("done_msgs", set())
        msg_key = (query.message.chat_id, query.message.message_id)
        if msg_key in done_msgs:
            return
        done_msgs.add(msg_key)
        _, target_id_str, amount_str = data.split(":")
        target_id, amount = int(target_id_str), float(amount_str)
        
        try:
            target_user = await context.bot.get_chat(target_id)
            user_link_str = get_user_mention(target_user)
        except Exception:
            user_link_str = f"ID <code>{target_id}</code>"

        reject_base_text = f"❌ Đã từ chối/báo chưa nhận được tiền cho giao dịch {amount:,.0f}đ của khách {user_link_str} (ID: <code>{target_id}</code>)."
        await query.edit_message_text(f"{reject_base_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau 30s...</i>", parse_mode="HTML")
        await auto_delete_with_countdown(context, query.message.chat_id, query.message.message_id, reject_base_text, 30)
        
        try:
            user_reject_text = f"⚠️ Giao dịch nạp {amount:,.0f} VND của bạn chưa được xác nhận tiền về tài khoản. Vui lòng liên hệ Admin {ADMIN_USERNAME} để được hỗ trợ!"
            user_notify = await context.bot.send_message(
                chat_id=target_id,
                text=f"{user_reject_text}\n\n⏱️ <i>Tin nhắn này sẽ tự động xóa sau 30s...</i>",
                parse_mode="HTML"
            )
            await auto_delete_with_countdown(context, target_id, user_notify.message_id, user_reject_text, 30)
        except Exception:
            pass

    elif data.startswith("admin_accept_order:") or data.startswith("admin_reject_order:"):
        if not is_admin(user.id, user.username):
            return
        action, uid_str = data.split(":")
        accepted = action == "admin_accept_order"
        status_line = "✅ <b>ADMIN ĐÃ NHẬN ĐƠN</b>" if accepted else "❌ <b>ADMIN ĐÃ TỪ CHỐI ĐƠN</b>"
        try:
            await query.edit_message_text(f"{query.message.text_html}\n\n{status_line}", parse_mode="HTML")
        except BadRequest:
            pass
        try:
            if accepted:
                notify_text = "✅ <b>Đơn hàng của bạn đã được Admin tiếp nhận</b> và đang được xử lý. Vui lòng chờ Admin liên hệ!"
            else:
                notify_text = f"❌ <b>Đơn hàng của bạn đã bị Admin từ chối.</b> Vui lòng liên hệ Admin {html.escape(ADMIN_USERNAME)} để được hỗ trợ."
            await context.bot.send_message(chat_id=int(uid_str), text=notify_text, parse_mode="HTML")
        except Exception:
            pass

    elif data == "products_p1":
        text, reply_markup = products_menu_keyboard(page=1)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "products_p2":
        text, reply_markup = products_menu_keyboard(page=2)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "item_cat_groups":
        text, reply_markup = groups_menu_keyboard(page=1)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "groups_p1":
        text, reply_markup = groups_menu_keyboard(page=1)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data == "groups_p2":
        text, reply_markup = groups_menu_keyboard(page=2)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("item_") and data != "item_cat_groups":
        cat_id = data.replace("item_", "")
        stock = get_stock_count(cat_id)
        text = (
            f"📦 <b>CHI TIẾT SẢN PHẨM</b>\n"
            f"----------------------------------------\n"
            f"📂 Chuyên mục: <code>{html.escape(cat_id)}</code>\n"
            f"📦 Tồn kho hiện tại: <code>{stock}</code> sản phẩm\n"
            f"----------------------------------------\n"
            f"💬 <i>Vui lòng liên hệ Admin để tiến hành mua hàng nhanh nhất!</i>"
        )
        keyboard = [
            [InlineKeyboardButton("↩️ Trở về", callback_data=("products_p2" if cat_id in [c["id"] for c in CATEGORIES_PAGE_2] else "products_p1"))],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# ==================== BỌC XỬ LÝ NÚT BẤM (CHỐNG SPAM, KHÔNG BỊ TREO) ====================
# Các nút có hiện cảnh báo (alert) thì trả lời query sau khi xử lý xong
ALERT_PREFIXES = (
    "sms_cancel:", "sms_renew:", "admin_sms_cancel:", "admin_sms_renew:",
    "delete_gc:", "group_detail_", "buy_group_now:", "admin_panel", "subcat_",
)
CLICK_COOLDOWN = 0.2
_LAST_CLICK = {}

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    uid = query.from_user.id

    # Bấm quá nhanh liên tục -> bỏ qua lượt thừa, giữ nguyên trạng thái hội thoại
    now = time.monotonic()
    if now - _LAST_CLICK.get(uid, 0) < CLICK_COOLDOWN:
        try:
            await query.answer()
        except Exception:
            pass
        return None
    _LAST_CLICK[uid] = now

    needs_alert = data.startswith(ALERT_PREFIXES)
    if not needs_alert:
        try:
            await query.answer()
        except Exception:
            pass

    try:
        result = await _button_handler_impl(update, context)
    except BadRequest as e:
        # Bấm lại đúng nút đang hiển thị -> Telegram báo "not modified", bỏ qua
        if "message is not modified" in str(e).lower():
            result = None
        else:
            raise
    finally:
        if needs_alert:
            try:
                await query.answer()
            except Exception:
                pass

    # Không có trạng thái nhập liệu mới -> kết thúc hội thoại cũ để tránh nhận nhầm tin nhắn
    return ConversationHandler.END if result is None else result

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    err_name = type(err).__name__
    if err_name == "Conflict":
        logging.warning("⚠️ Conflict getUpdates: có bản bot khác đang chạy (thường xảy ra ngắn lúc Render deploy lại).")
        return
    logging.error("Lỗi không bắt được trong bot:", exc_info=err)

async def admin_restore_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin gửi file backup_*.zip cho bot -> khôi phục toàn bộ dữ liệu."""
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return
    doc = update.message.document
    if not doc or not (doc.file_name or "").lower().endswith(".zip") or not doc.file_name.startswith("backup_"):
        return
    try:
        f = await context.bot.get_file(doc.file_id)
        raw = bytes(await f.download_as_bytearray())
        ok, msg = await asyncio.to_thread(restore_from_zip_bytes, raw, False)
    except Exception as e:
        ok, msg = False, str(e)
    await update.message.reply_text(
        ("✅ " if ok else "❌ ") + html.escape(msg),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]])
    )

def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("⚠️ Vui lòng cấu hình BOT_TOKEN chính xác trước khi chạy bot!")
        return

    global bot_app
    start_backup_worker()
    start_tg_backup_worker()
    keep_alive()

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)      # xử lý nhiều người cùng lúc, không xếp hàng
        .connection_pool_size(64)
        .pool_timeout(15)
        .connect_timeout(15)
        .read_timeout(20)
        .write_timeout(20)
        .build()
    )
    bot_app = application

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler)
        ],
        states={
            INPUT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link_handler)],
            INPUT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quantity_handler)],
            INPUT_TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_topup_input_handler)],
            INPUT_GITCODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gitcode_handler)],
            INPUT_CREATE_CODE_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_gitcode_handler)],
            INPUT_ADMIN_EDIT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_edit_user_handler)],
            INPUT_SMS_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_sms_phone_handler)],
            INPUT_BROADCAST_PHOTO: [
                MessageHandler(filters.PHOTO | filters.VIDEO, receive_broadcast_media_handler),
                CallbackQueryHandler(button_handler, pattern="^skip_broadcast_media$")
            ],
            INPUT_BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_broadcast_text_handler)],
            INPUT_PRIVATE_MSG_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_private_msg_user_id_handler)],
            INPUT_PRIVATE_MSG_PHOTO: [
                MessageHandler(filters.PHOTO | filters.VIDEO, receive_private_msg_media_handler),
                CallbackQueryHandler(button_handler, pattern="^skip_private_media$")
            ],
            INPUT_PRIVATE_MSG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_private_msg_text_handler)],
            INPUT_CREATE_BOT_REQUIREMENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_requirements_handler)],
            INPUT_USER_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_user_feedback_handler)],
            INPUT_PROMO_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_promo_percent_handler)],
            INPUT_BULK_TOPUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bulk_topup_handler)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler)
        ],
        per_message=False
    )

    application.add_handler(CommandHandler("topup", admin_topup_cmd))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Document.ALL, admin_restore_document_handler), group=1)
    application.add_error_handler(error_handler)

    print("🤖 Bot đang chạy...")
    application.run_polling(drop_pending_updates=True)
    flush_saves()   # ghi nốt dữ liệu đang chờ xuống file
    flush_backup()  # đẩy dữ liệu lên backup lần cuối khi bị tắt (SIGTERM)

if __name__ == "__main__":
 main()
