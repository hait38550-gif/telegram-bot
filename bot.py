# -*- coding: utf-8 -*-
"""
BOT TELEGRAM SMM TRUNG GIAN  ->  https://topsubre.vn  (API v2)
- Danh sách dịch vụ + giá LẤY TỰ ĐỘNG từ topsubre.vn, cộng % lãi do Admin chỉnh ngay trong bot
- Khách đặt đơn trong bot -> bot trừ tiền khách -> đẩy đơn lên topsubre.vn -> tự theo dõi trạng thái
- Hủy / chạy thiếu (partial) tự hoàn tiền, báo khách + admin
- Nạp tiền tự động SePay, khuyến mãi nạp, gitcode, giới thiệu bạn bè, bậc VIP giảm giá
- Bán tài khoản có kho (file), dịch vụ thủ công (tick xanh, tạo bot) có duyệt/hoàn tiền
- Backup tự động lên Telegram (zip, ghim) + tự khôi phục khi Render chạy lại
"""
import os, io, re, json, time, math, html, hmac, asyncio, logging, zipfile, threading, random, string, urllib.parse
from threading import Thread

import requests
from flask import Flask, request, jsonify
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb, InputFile, Update
from telegram.error import BadRequest
from telegram.ext import (ApplicationBuilder, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)   # URL của httpx chứa BOT_TOKEN

# ============================== CẤU HÌNH ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in re.findall(r"\d+", os.getenv("ADMIN_CHAT_ID", ""))}
ADMIN_MAIN = next(iter(sorted(ADMIN_IDS)), 0)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").lstrip("@")

SMM_API_URL = os.getenv("SMM_API_URL", "https://topsubre.vn/api/v2")
SMM_API_KEY = os.getenv("SMM_API_KEY", "").strip()
RATE_MULTIPLIER = float(os.getenv("RATE_MULTIPLIER", "1"))     # nhân giá gốc (nếu web tính USD thì đặt tỉ giá, VND thì để 1)
DEFAULT_MARKUP = float(os.getenv("MARKUP_PERCENT", "30"))      # % lãi mặc định, Admin chỉnh trong bot
LOW_PROVIDER_BALANCE = float(os.getenv("LOW_PROVIDER_BALANCE", "50000"))
MIN_TOPUP = int(os.getenv("MIN_TOPUP", "10000"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "120"))
DB_DIR = os.getenv("DB_DIR", ".")

BANKS = [
    {"bank": "MBBank", "acc": "3030777777", "name": "NGUYEN TIEN DAT"},
    {"bank": "MBBank", "acc": "308088888", "name": "NGUYEN TIEN DAT"},
]
try:
    if os.getenv("BANKS_JSON"):
        BANKS = json.loads(os.environ["BANKS_JSON"])
except Exception:
    logging.error("BANKS_JSON sai định dạng, dùng danh sách mặc định")

SEPAY_KEYS = [k for k in (os.getenv("SEPAY_API_KEY", "").strip(),
                          os.getenv("SEPAY_API_KEY_1", "").strip(),
                          os.getenv("SEPAY_API_KEY_2", "").strip()) if k]

VIP_TIERS = [(20_000_000, 8), (5_000_000, 5), (1_000_000, 3), (0, 0)]   # (tổng đã chi, % giảm)

ACCOUNT_CATS = [   # kho tài khoản: id, tên, giá mặc định (Admin đổi bằng /setprice)
    {"id": "zalo", "title": "🛡️ Tài khoản Zalo", "price": 15000},
    {"id": "tele", "title": "✈️ Telegram (+84)", "price": 20000},
    {"id": "hotmail", "title": "📧 Hotmail - Outlook", "price": 2000},
    {"id": "gmail", "title": "📮 Gmail", "price": 5000},
    {"id": "tiktok", "title": "🎵 TikTok", "price": 10000},
    {"id": "fb_viet", "title": "🇻🇳 Facebook Việt nuôi", "price": 30000},
    {"id": "fb_ngoai", "title": "🌍 Facebook ngoại nuôi", "price": 25000},
]
MANUAL_SERVICES = {   # dịch vụ làm tay: khách trả tiền -> Admin nhận / từ chối (hoàn tiền)
    "tickfp": {"title": "⭐ Tick xanh Fanpage", "price": 5_000_000, "ask": "Gửi link Fanpage + thông tin liên hệ:"},
    "ticktcn": {"title": "👤 Tick xanh Trang cá nhân", "price": 2_000_000, "ask": "Gửi link trang cá nhân + thông tin liên hệ:"},
    "createbot": {"title": "🤖 Tạo Bot Telegram Premium", "price": 500_000, "ask": "Mô tả tính năng bạn muốn bot có:"},
}

PLATFORMS = [("facebook", "📘 Facebook"), ("tiktok", "🎵 TikTok"), ("instagram", "📸 Instagram"),
             ("youtube", "▶️ YouTube"), ("telegram", "✈️ Telegram"), ("twitter", "🐦 Twitter / X"),
             ("shopee", "🛒 Shopee"), ("threads", "🧵 Threads"), ("google", "🗺️ Google"), ("other", "🌐 Khác")]
PLAT_NAME = dict(PLATFORMS)

# ============================== TELEGRAM HTTP (dùng cho luồng Flask/backup) ==============================
def tg_call(method, payload, timeout=15):
    try:
        return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=timeout).json()
    except Exception as e:
        logging.error(f"tg_call {method}: {e}")
        return None

# ============================== DATABASE (1 file JSON, ghi nền, backup Telegram) ==============================
DB_FILE = os.path.join(DB_DIR, "db.json")
STOCK_DIR = os.path.join(DB_DIR, "stock")
os.makedirs(STOCK_DIR, exist_ok=True)
_lock = threading.RLock()
_dirty = threading.Event()
BK = {"dirty": False, "last": time.time(), "ok": 0.0, "err": "", "msg": None}
BK_ENABLED = os.getenv("TG_BACKUP_ENABLED", "1") != "0" and bool(ADMIN_MAIN and BOT_TOKEN)
BK_CHAT = os.getenv("TG_BACKUP_CHAT_ID", "").strip() or str(ADMIN_MAIN)

def _blank():
    return {"users": {}, "orders": {}, "next_order": 1, "gitcodes": {}, "settings": {}, "tx": {}}

def _zip_extract(raw):
    zf = zipfile.ZipFile(io.BytesIO(raw))
    if "db.json" not in zf.namelist():
        raise ValueError("Zip không có db.json")
    obj = json.loads(zf.read("db.json").decode("utf-8"))
    if not isinstance(obj, dict) or "users" not in obj:
        raise ValueError("db.json sai định dạng")
    files = {"db.json": zf.read("db.json")}
    for n in zf.namelist():
        if re.fullmatch(r"stock/[a-z0-9_]+\.txt", n):
            files[n] = zf.read(n)
    return obj, files

def _write_files(files):
    for n, data in files.items():
        p = os.path.join(DB_DIR, n)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p + ".tmp", "wb") as f:
            f.write(data)
        os.replace(p + ".tmp", p)

def _download_pinned():
    chat = tg_call("getChat", {"chat_id": int(BK_CHAT) if BK_CHAT.lstrip("-").isdigit() else BK_CHAT}) or {}
    doc = ((chat.get("result") or {}).get("pinned_message") or {}).get("document")
    if not doc:
        return None
    info = tg_call("getFile", {"file_id": doc["file_id"]}) or {}
    fp = (info.get("result") or {}).get("file_path")
    if not fp:
        return None
    r = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}", timeout=60)
    r.raise_for_status()
    return r.content

if not os.path.exists(DB_FILE) and BK_ENABLED:   # Render vừa deploy lại -> khôi phục từ tin nhắn ghim
    try:
        raw = _download_pinned()
        if raw:
            _write_files(_zip_extract(raw)[1])
            logging.info("✅ Đã khôi phục dữ liệu từ backup Telegram")
    except Exception as e:
        logging.error(f"Khôi phục backup lỗi: {e}")

def _load():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            for k, v in _blank().items():
                d.setdefault(k, v)
            return d
        except Exception as e:
            logging.error(f"db.json hỏng ({e}) -> đổi tên giữ lại")
            os.replace(DB_FILE, f"{DB_FILE}.corrupt-{int(time.time())}")
    return _blank()

DB = _load()

def save():
    _dirty.set()
    BK["dirty"] = True

def _flush():
    with _lock:
        s = json.dumps(DB, ensure_ascii=False, separators=(",", ":"))
    with open(DB_FILE + ".tmp", "w", encoding="utf-8") as f:
        f.write(s)
    os.replace(DB_FILE + ".tmp", DB_FILE)

def _saver():
    while True:
        _dirty.wait()
        time.sleep(0.3)
        _dirty.clear()
        try:
            _flush()
        except Exception as e:
            logging.error(f"Lỗi ghi db: {e}")

def backup_send(reason="tự động"):
    if not BK_ENABLED or not DB["users"]:
        return False
    try:
        BK["dirty"] = False
        BK["last"] = time.time()
        _flush()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(DB_FILE, "db.json")
            for fn in os.listdir(STOCK_DIR):
                if re.fullmatch(r"[a-z0-9_]+\.txt", fn):
                    zf.write(os.path.join(STOCK_DIR, fn), f"stock/{fn}")
        buf.seek(0)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(time.time() + 7 * 3600))
        cap = (f"💾 AUTO_BACKUP ({reason})\n🕒 {stamp}\n👥 Khách: {len(DB['users'])} | "
               f"💰 Tổng dư: {sum(u.get('balance', 0) for u in DB['users'].values()):,.0f}đ")
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                          data={"chat_id": BK_CHAT, "caption": cap, "disable_notification": "true"},
                          files={"document": (f"backup_{stamp}.zip", buf, "application/zip")}, timeout=60).json()
        if not r.get("ok"):
            raise RuntimeError(str(r)[:200])
        mid = r["result"]["message_id"]
        tg_call("pinChatMessage", {"chat_id": BK_CHAT, "message_id": mid, "disable_notification": True})
        if BK["msg"]:
            tg_call("deleteMessage", {"chat_id": BK_CHAT, "message_id": BK["msg"]})
        BK["msg"], BK["ok"], BK["err"] = mid, time.time(), ""
        return True
    except Exception as e:
        BK["err"], BK["dirty"] = str(e)[:200], True
        logging.error(f"Backup lỗi: {e}")
        return False

def _bk_worker():
    while True:
        time.sleep(10)
        now = time.time()
        if (BK["dirty"] and now - BK["last"] >= 60) or now - BK["last"] >= 3600:
            backup_send()

def restore_zip(raw):
    obj, files = _zip_extract(raw)
    with _lock:
        _write_files(files)
        DB.clear()
        DB.update(obj)
        for k, v in _blank().items():
            DB.setdefault(k, v)
    save()
    return "Đã khôi phục: " + ", ".join(files)

# ---------- tiện ích dữ liệu ----------
def fmt(n):
    return f"{n:,.0f}"

def fmt_rate(x):
    return f"{x:,.2f}".rstrip("0").rstrip(".")

def is_admin(uid):
    return uid in ADMIN_IDS

def U(uid):
    k = str(uid)
    with _lock:
        u = DB["users"].get(k)
        if u is None:
            u = {"balance": 0, "spent": 0, "history": [], "joined": int(time.time()),
                 "ref_by": None, "ref_earn": 0, "banned": False, "name": ""}
            DB["users"][k] = u
            save()
        return u

def hist(u, text):
    u["history"].append(f"{time.strftime('%d/%m %H:%M', time.gmtime(time.time() + 7 * 3600))} | {text}")
    del u["history"][:-100]

def setting(k, default=None):
    return DB["settings"].get(k, default)

def set_setting(k, v):
    with _lock:
        DB["settings"][k] = v
    save()

def markup_pct():
    return float(setting("markup", DEFAULT_MARKUP))

def promo_pct():
    return float(setting("promo", 0) or 0)

def vip_discount(uid):
    spent = U(uid).get("spent", 0)
    for need, pct in VIP_TIERS:
        if spent >= need:
            return pct
    return 0

def acc_price(cat):
    return int(DB["settings"].get("acc_price", {}).get(cat["id"], cat["price"]))

def stock_path(cid):
    return os.path.join(STOCK_DIR, f"{cid}.txt")

def stock_lines(cid):
    try:
        with open(stock_path(cid), "r", encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip()]
    except Exception:
        return []

def write_stock(cid, lines):
    with open(stock_path(cid) + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    os.replace(stock_path(cid) + ".tmp", stock_path(cid))
    BK["dirty"] = True

def credit_topup(uid, amount, source):
    """Cộng tiền nạp (+khuyến mãi, +hoa hồng giới thiệu). Trả (số dư mới, bonus)."""
    with _lock:
        u = U(uid)
        bonus = float(round(amount * promo_pct() / 100)) if promo_pct() > 0 else 0.0
        u["balance"] += amount + bonus
        note = f"Nạp tiền ({source}): +{fmt(amount)}đ" + (f" | KM {promo_pct():g}%: +{fmt(bonus)}đ" if bonus else "")
        hist(u, note)
        ref = u.get("ref_by")
        if ref and str(ref) in DB["users"]:
            commission = float(round(amount * float(setting("ref_pct", 3)) / 100))
            if commission > 0:
                ru = U(ref)
                ru["balance"] += commission
                ru["ref_earn"] = ru.get("ref_earn", 0) + commission
                hist(ru, f"Hoa hồng giới thiệu ID {uid}: +{fmt(commission)}đ")
                tg_call("sendMessage", {"chat_id": ref, "parse_mode": "HTML",
                                        "text": f"🤝 Bạn nhận <b>+{fmt(commission)}đ</b> hoa hồng từ bạn bè đã giới thiệu nạp tiền!"})
        save()
        return u["balance"], bonus

# ============================== SMM API (topsubre.vn) ==============================
def smm(action, data=None):
    d = dict(data or {})
    d["key"], d["action"] = SMM_API_KEY, action
    try:
        return requests.post(SMM_API_URL, data=d, timeout=25).json()
    except Exception as e:
        logging.error(f"SMM API ({action}) lỗi: {type(e).__name__}")
        return None

SVC = {"ts": 0.0, "map": {}, "tree": {}}   # tree: platform -> [(category, [service_id,...]), ...]

def detect_platform(text):
    t = text.lower()
    for key in ("facebook", "tiktok", "instagram", "youtube", "telegram", "twitter", "shopee", "threads", "google"):
        if key in t:
            return key
    if re.search(r"\b(fb)\b", t):
        return "facebook"
    if re.search(r"\b(ig)\b", t):
        return "instagram"
    if re.search(r"\b(yt)\b", t):
        return "youtube"
    if re.search(r"(^|\W)x(\W|$)", t):
        return "twitter"
    return "other"

def refresh_services_sync():
    res = smm("services")
    if not isinstance(res, list) or not res:
        return False
    hidden = set(setting("hidden", []))
    smap, grouped = {}, {}
    for s in res:
        try:
            sid = int(s["service"])
            typ = s.get("type", "Default") or "Default"
            if sid in hidden or typ not in ("Default", "Custom Comments"):
                continue
            cat = (str(s.get("category", "")).strip() or "Khác")
            svc = {"id": sid, "name": str(s["name"]).strip(), "cat": cat, "type": typ,
                   "rate": float(s["rate"]) * RATE_MULTIPLIER, "min": int(float(s.get("min", 1))),
                   "max": int(float(s.get("max", 1000000))), "refill": bool(s.get("refill")), "cancel": bool(s.get("cancel"))}
        except Exception:
            continue
        smap[sid] = svc
        plat = detect_platform(cat + " " + svc["name"])
        grouped.setdefault(plat, {}).setdefault(cat, []).append(sid)
    tree = {}
    for plat, cats in grouped.items():
        tree[plat] = [(c, sorted(ids, key=lambda i: smap[i]["rate"])) for c, ids in sorted(cats.items())]
    SVC.update({"ts": time.time(), "map": smap, "tree": tree})
    return True

async def ensure_services(force=False):
    if force or not SVC["map"] or time.time() - SVC["ts"] > 600:
        await asyncio.to_thread(refresh_services_sync)
    return bool(SVC["map"])

def per1000(s, uid):
    return s["rate"] * (1 + markup_pct() / 100) * (1 - vip_discount(uid) / 100)

def calc_price(s, qty, uid):
    return max(1, math.ceil(per1000(s, uid) * qty / 1000))

# ============================== FLASK (webhook SePay + giữ Render thức) ==============================
flask_app = Flask("bot")

@flask_app.route("/")
def home_page():
    return "SMM bot is running"

def sepay_authorized(header):
    token = (header or "").strip()
    if token.lower().startswith("apikey "):
        token = token[7:].strip()
    return any(hmac.compare_digest(token.encode(), k.encode()) for k in SEPAY_KEYS)

@flask_app.route("/sepay-webhook", methods=["POST"])
def sepay_webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error"}), 400
        if not SEPAY_KEYS or not sepay_authorized(request.headers.get("Authorization", "")):
            logging.warning("⛔ SePay webhook bị từ chối: thiếu/sai SEPAY_API_KEY")
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        amount = float(data.get("transferAmount", 0))
        if data.get("transferType", "in") != "in" or amount <= 0:
            return jsonify({"status": "success"}), 200
        content = str(data.get("content", ""))
        txid = data.get("id")
        tx_key = f"{data.get('accountNumber', '')}:{txid}" if txid not in (None, "") else None
        m = re.search(r"NAP\s*(\d{5,13})", content, re.I)
        cands = [m.group(1)] if m else re.findall(r"(?<!\d)\d{6,12}(?!\d)", content)
        with _lock:
            if tx_key and tx_key in DB["tx"]:
                return jsonify({"status": "success", "message": "duplicate"}), 200
            uid = next((int(c) for c in cands if c in DB["users"]), None)
            if uid is None:
                logging.info(f"SePay: không thấy ID khách trong nội dung {content!r}")
                for a in ADMIN_IDS:
                    tg_call("sendMessage", {"chat_id": a, "parse_mode": "HTML",
                            "text": f"⚠️ Có tiền về <b>{fmt(amount)}đ</b> nhưng không khớp ID khách.\nNội dung: <code>{html.escape(content)}</code>"})
                if tx_key:
                    DB["tx"][tx_key] = int(time.time())
                    save()
                return jsonify({"status": "success", "message": "user not found"}), 200
            new_bal, bonus = credit_topup(uid, amount, f"SePay #{txid}")
            if tx_key:
                DB["tx"][tx_key] = int(time.time())
                if len(DB["tx"]) > 5000:
                    for k in sorted(DB["tx"], key=DB["tx"].get)[:1000]:
                        DB["tx"].pop(k, None)
                save()
        bonus_line = f"🎁 Khuyến mãi: <code>+{fmt(bonus)}đ</code>\n" if bonus else ""
        tg_call("sendMessage", {"chat_id": uid, "parse_mode": "HTML",
                "text": f"🎉 <b>NẠP TIỀN THÀNH CÔNG!</b>\n\n💵 Số tiền: <code>+{fmt(amount)}đ</code>\n{bonus_line}"
                        f"💳 Số dư mới: <code>{fmt(new_bal)}đ</code>"})
        for a in ADMIN_IDS:
            tg_call("sendMessage", {"chat_id": a, "parse_mode": "HTML",
                    "text": f"🔔 <b>NẠP AUTO</b> | ID <code>{uid}</code> | +{fmt(amount)}đ {('(+' + fmt(bonus) + ' KM)') if bonus else ''}| dư {fmt(new_bal)}đ"})
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logging.error(f"Lỗi SePay webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), threaded=True, use_reloader=False)

def self_ping():
    url = os.getenv("RENDER_EXTERNAL_URL", "")
    while url:
        time.sleep(600)
        try:
            requests.get(url, timeout=10)
        except Exception:
            pass

# ============================== GIAO DIỆN ==============================
async def show(update, ctx, text, markup=None):
    q = update.callback_query
    if q:
        m = q.message
        if m.photo or m.video or m.document:
            try:
                await m.delete()
            except Exception:
                pass
            return await ctx.bot.send_message(m.chat_id, text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        try:
            return await q.edit_message_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return m
            raise
    return await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)

def mention(user):
    if user.username:
        return f"@{html.escape(user.username)}"
    return f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "Khách")}</a>'

HOME_BTN = [Btn("🏠 Menu chính", callback_data="home")]

def main_menu(user):
    u = U(user.id)
    vip = vip_discount(user.id)
    promo = f"\n🎉 <b>Khuyến mãi nạp +{promo_pct():g}%</b> đang diễn ra!" if promo_pct() > 0 else ""
    text = (f"✨ <b>HỆ THỐNG DỊCH VỤ MẠNG XÃ HỘI & TÀI KHOẢN</b> ✨\n════════════════════════════════\n\n"
            f"👋 Xin chào <b>{html.escape(user.first_name or 'bạn')}</b>!\n"
            f"🆔 ID: <code>{user.id}</code>\n💰 Số dư: <code>{fmt(u['balance'])}đ</code>\n"
            f"💎 Bậc VIP: giảm <b>{vip}%</b> (đã chi {fmt(u.get('spent', 0))}đ){promo}\n\n"
            f"⚡ Đơn chạy tự động 24/7, lỗi tự hoàn tiền.\n👇 Chọn chức năng:")
    rows = [
        [Btn("🛒 DỊCH VỤ TĂNG TƯƠNG TÁC", callback_data="svc")],
        [Btn("📦 MUA TÀI KHOẢN", callback_data="acc"), Btn("💎 DỊCH VỤ KHÁC", callback_data="man")],
        [Btn("📋 ĐƠN CỦA TÔI", callback_data="orders:0"), Btn("📜 LỊCH SỬ", callback_data="hist")],
        [Btn("💳 NẠP TIỀN AUTO", callback_data="topup"), Btn("🎁 NHẬP GITCODE", callback_data="gc")],
        [Btn("👥 GIỚI THIỆU NHẬN HOA HỒNG", callback_data="ref")],
    ]
    if ADMIN_USERNAME:
        rows.append([Btn("💬 HỖ TRỢ (ADMIN)", url=f"https://t.me/{ADMIN_USERNAME}")])
    if is_admin(user.id):
        rows.append([Btn("⚙️ QUẢN LÝ HỆ THỐNG", callback_data="adm")])
    return text, Kb(rows)

async def go_home(update, ctx):
    text, kb = main_menu(update.effective_user)
    await show(update, ctx, text, kb)

STATUS_ICON = {"pending": "⏳", "processing": "🔄", "in progress": "🔄", "completed": "✅",
               "partial": "⚠️", "canceled": "❌", "cancelled": "❌", "refunded": "❌", "fail": "❌", "failed": "❌"}
FINAL = {"completed", "canceled", "cancelled", "partial", "refunded", "fail", "failed"}

def st_icon(status):
    return STATUS_ICON.get(str(status).lower(), "❔")

def pager(prefix, page, total, per):
    pages = max(1, math.ceil(total / per))
    row = []
    if page > 0:
        row.append(Btn("⬅️", callback_data=f"{prefix}:{page - 1}"))
    row.append(Btn(f"{page + 1}/{pages}", callback_data="none"))
    if page < pages - 1:
        row.append(Btn("➡️", callback_data=f"{prefix}:{page + 1}"))
    return row

# ============================== DỊCH VỤ SMM: DUYỆT & ĐẶT ĐƠN ==============================
async def menu_platforms(update, ctx):
    if not await ensure_services():
        return await show(update, ctx, "⚠️ Hệ thống đang đồng bộ dịch vụ, vui lòng thử lại sau ít giây.", Kb([HOME_BTN]))
    rows = []
    for key, name in PLATFORMS:
        if key in SVC["tree"]:
            n = sum(len(ids) for _, ids in SVC["tree"][key])
            rows.append([Btn(f"{name}  ({n})", callback_data=f"pl:{key}:0")])
    rows.append(HOME_BTN)
    await show(update, ctx, "🛒 <b>DỊCH VỤ TĂNG TƯƠNG TÁC</b>\n════════════════════════════════\n👇 Chọn nền tảng:", Kb(rows))

async def menu_categories(update, ctx, plat, page):
    await ensure_services()
    cats = SVC["tree"].get(plat, [])
    per = 10
    rows = [[Btn(f"{c[:45]} [{len(ids)}]", callback_data=f"ct:{plat}:{i}:0")]
            for i, (c, ids) in enumerate(cats) if page * per <= i < (page + 1) * per]
    if len(cats) > per:
        rows.append(pager(f"pl:{plat}", page, len(cats), per))
    rows.append([Btn("↩️ Nền tảng", callback_data="svc"), *HOME_BTN])
    await show(update, ctx, f"{PLAT_NAME.get(plat, plat)}\n════════════════════════════════\n👇 Chọn nhóm dịch vụ:", Kb(rows))

async def menu_services(update, ctx, plat, ci, page):
    await ensure_services()
    cats = SVC["tree"].get(plat, [])
    if ci >= len(cats):
        return await menu_categories(update, ctx, plat, 0)
    cname, ids = cats[ci]
    uid = update.effective_user.id
    per = 8
    rows = []
    for sid in ids[page * per:(page + 1) * per]:
        s = SVC["map"][sid]
        rows.append([Btn(f"{s['name'][:40]} • {fmt_rate(per1000(s, uid))}đ/1k", callback_data=f"sv:{sid}")])
    if len(ids) > per:
        rows.append(pager(f"ct:{plat}:{ci}", page, len(ids), per))
    rows.append([Btn("↩️ Nhóm", callback_data=f"pl:{plat}:0"), *HOME_BTN])
    await show(update, ctx, f"🛠️ <b>{html.escape(cname)}</b>\n════════════════════════════════\n"
                            f"💡 Giá tính theo <b>1000</b> lượt (đã gồm giảm VIP).\n👇 Chọn gói:", Kb(rows))

async def service_detail(update, ctx, sid):
    s = SVC["map"].get(sid)
    if not s:
        await ensure_services(True)
        s = SVC["map"].get(sid)
    if not s:
        return await show(update, ctx, "⚠️ Dịch vụ không còn tồn tại.", Kb([[Btn("↩️ Quay lại", callback_data="svc")], HOME_BTN]))
    uid = update.effective_user.id
    plat = detect_platform(s["cat"] + " " + s["name"])
    text = (f"📦 <b>{html.escape(s['name'])}</b>\n════════════════════════════════\n"
            f"🆔 Mã dịch vụ: <code>{s['id']}</code>\n💵 Giá: <code>{fmt_rate(per1000(s, uid))}đ</code> / 1000\n"
            f"📊 Tối thiểu: <code>{fmt(s['min'])}</code> • Tối đa: <code>{fmt(s['max'])}</code>\n"
            f"♻️ Bảo hành/refill: {'Có' if s['refill'] else 'Không'} • 🚫 Hủy đơn: {'Có' if s['cancel'] else 'Không'}\n"
            f"{'💬 Gói này nhập nội dung bình luận (mỗi dòng 1 bình luận).' + chr(10) if s['type'] == 'Custom Comments' else ''}"
            f"\n⚠️ Chỉ dùng link <b>công khai</b>. Không cần mật khẩu.")
    await show(update, ctx, text, Kb([[Btn("🛒 MUA NGAY", callback_data=f"buy:{sid}")],
                                      [Btn("↩️ Quay lại", callback_data=f"pl:{plat}:0"), *HOME_BTN]]))

async def start_buy(update, ctx, sid):
    s = SVC["map"].get(sid)
    if not s:
        return await service_detail(update, ctx, sid)
    ctx.user_data["order"] = {"sid": sid}
    ctx.user_data["st"] = "link"
    await show(update, ctx, f"📦 <b>{html.escape(s['name'])}</b>\n\n🔗 <b>Gửi link</b> bài viết / trang / kênh cần tăng:\n<i>Ví dụ: https://...</i>",
               Kb([[Btn("❌ Hủy", callback_data="home")]]))

def confirm_text(s, od, price, bal):
    return (f"🧾 <b>XÁC NHẬN ĐƠN HÀNG</b>\n════════════════════════════════\n"
            f"📦 {html.escape(s['name'])}\n🔗 <code>{html.escape(od['link'])}</code>\n"
            f"📊 Số lượng: <code>{fmt(od['qty'])}</code>\n💵 Thành tiền: <code>{fmt(price)}đ</code>\n"
            f"💳 Số dư: <code>{fmt(bal)}đ</code>")

async def place_order(update, ctx):
    user = update.effective_user
    od = ctx.user_data.pop("order", None)
    if not od or "qty" not in od:
        return await show(update, ctx, "⚠️ Phiên đặt đơn đã hết hạn.", Kb([HOME_BTN]))
    s = SVC["map"].get(od["sid"])
    if not s or not (s["min"] <= od["qty"] <= s["max"]):
        return await show(update, ctx, "⚠️ Dịch vụ vừa thay đổi, vui lòng chọn lại.", Kb([[Btn("🛒 Dịch vụ", callback_data="svc")]]))
    qty, link = od["qty"], od["link"]
    price = calc_price(s, qty, user.id)
    with _lock:
        u = U(user.id)
        if u["balance"] < price:
            ok = False
        else:
            ok = True
            u["balance"] -= price
            u["spent"] += price
            save()
    if not ok:
        return await show(update, ctx, f"❌ <b>SỐ DƯ KHÔNG ĐỦ!</b>\n\n💳 Số dư: <code>{fmt(u['balance'])}đ</code>\n💵 Cần: <code>{fmt(price)}đ</code>",
                          Kb([[Btn("💳 Nạp tiền", callback_data="topup"), *HOME_BTN]]))
    await show(update, ctx, "⏳ <b>Đang gửi đơn lên hệ thống, vui lòng chờ...</b>")
    payload = {"service": s["id"], "link": link, "quantity": qty}
    if s["type"] == "Custom Comments":
        payload["comments"] = "\n".join(od.get("comments", []))
    res = await asyncio.to_thread(smm, "add", payload)
    smm_id = res.get("order") if isinstance(res, dict) else None
    if not smm_id:
        with _lock:
            u["balance"] += price
            u["spent"] -= price
            save()
        err = str(res.get("error")) if isinstance(res, dict) and res.get("error") else "Không kết nối được"
        logging.error(f"Đặt đơn lỗi user {user.id}: {err}")
        for a in ADMIN_IDS:
            try:
                await ctx.bot.send_message(a, f"⚠️ <b>ĐƠN LỖI (đã hoàn tiền khách)</b>\n👤 <code>{user.id}</code>\n📦 {html.escape(s['name'])}\n"
                                              f"🔗 {html.escape(link)}\n📝 Lỗi từ web: <code>{html.escape(err)}</code>", parse_mode="HTML")
            except Exception:
                pass
        return await show(update, ctx, f"❌ <b>ĐẶT ĐƠN THẤT BẠI</b>\n\n💵 Đã hoàn <code>{fmt(price)}đ</code> vào số dư.\n"
                                       f"⚠️ <i>Link sai/không công khai hoặc dịch vụ đang bảo trì. Vui lòng kiểm tra lại hoặc chọn gói khác.</i>",
                          Kb([[Btn("🛒 Chọn lại", callback_data="svc"), *HOME_BTN]]))
    with _lock:
        lid = DB["next_order"]
        DB["next_order"] += 1
        DB["orders"][str(lid)] = {"id": lid, "kind": "smm", "uid": user.id, "smm_id": int(smm_id), "sid": s["id"], "name": s["name"],
                                  "link": link, "qty": qty, "price": price, "status": "Pending", "remains": qty,
                                  "time": int(time.time()), "refill": s["refill"]}
        hist(u, f"Đơn #{lid} {s['name'][:40]} x{fmt(qty)} = -{fmt(price)}đ")
        save()
        bal = u["balance"]
    await show(update, ctx, f"🎉 <b>ĐẶT HÀNG THÀNH CÔNG!</b>\n\n🧾 Mã đơn: <code>#{lid}</code>\n📦 {html.escape(s['name'])}\n"
                            f"🔗 <code>{html.escape(link)}</code>\n📊 SL: <code>{fmt(qty)}</code>\n💵 Thanh toán: <code>{fmt(price)}đ</code>\n"
                            f"💳 Còn lại: <code>{fmt(bal)}đ</code>\n\n⏳ <i>Bot sẽ tự báo khi đơn hoàn thành. Xem tại mục Đơn của tôi.</i>",
               Kb([[Btn("📋 Đơn của tôi", callback_data="orders:0"), *HOME_BTN]]))
    for a in ADMIN_IDS:
        try:
            await ctx.bot.send_message(a, f"🔔 <b>ĐƠN MỚI #{lid}</b>\n👤 {mention(user)} (<code>{user.id}</code>)\n📦 {html.escape(s['name'])}\n"
                                          f"🔗 <code>{html.escape(link)}</code>\n📊 {fmt(qty)} • 💵 {fmt(price)}đ • 🆔 web: <code>{smm_id}</code>", parse_mode="HTML")
        except Exception:
            pass

# ---------- Đơn của tôi ----------
async def my_orders(update, ctx, page):
    uid = update.effective_user.id
    mine = sorted((o for o in DB["orders"].values() if o["uid"] == uid), key=lambda o: -o["id"])
    if not mine:
        return await show(update, ctx, "ℹ️ Bạn chưa có đơn hàng nào.", Kb([[Btn("🛒 Đặt đơn", callback_data="svc"), *HOME_BTN]]))
    per = 8
    rows = [[Btn(f"{st_icon(o['status'])} #{o['id']} • {o['name'][:26]} • {fmt(o['qty'])}", callback_data=f"ord:{o['id']}")]
            for o in mine[page * per:(page + 1) * per]]
    if len(mine) > per:
        rows.append(pager("orders", page, len(mine), per))
    rows.append(HOME_BTN)
    await show(update, ctx, f"📋 <b>ĐƠN HÀNG CỦA BẠN</b> ({len(mine)} đơn)\n👇 Bấm để xem chi tiết:", Kb(rows))

async def order_detail(update, ctx, lid, refresh=False):
    o = DB["orders"].get(str(lid))
    if not o or o["uid"] != update.effective_user.id:
        return await show(update, ctx, "⚠️ Không tìm thấy đơn.", Kb([HOME_BTN]))
    if refresh and o["kind"] == "smm" and o["status"].lower() not in FINAL:
        res = await asyncio.to_thread(smm, "status", {"order": o["smm_id"]})
        if isinstance(res, dict) and res.get("status"):
            await apply_status(ctx.application, str(lid), res)
            o = DB["orders"][str(lid)]
    text = (f"🧾 <b>ĐƠN #{o['id']}</b>\n════════════════════════════════\n📦 {html.escape(o['name'])}\n"
            f"{('🔗 <code>' + html.escape(o['link']) + '</code>' + chr(10)) if o.get('link') else ''}"
            f"📊 SL: <code>{fmt(o['qty'])}</code> • 💵 <code>{fmt(o['price'])}đ</code>\n"
            f"🕒 {time.strftime('%H:%M %d/%m/%Y', time.gmtime(o['time'] + 7 * 3600))}\n{st_icon(o['status'])} Trạng thái: <b>{html.escape(o['status'])}</b>\n")
    if o["kind"] == "smm":
        text += f"📉 Còn lại: <code>{fmt(o.get('remains', 0))}</code>\n"
    if o.get("refund_amount"):
        text += f"💸 Đã hoàn: <code>{fmt(o['refund_amount'])}đ</code>\n"
    if o.get("result"):
        text += "\n📥 <b>Hàng đã nhận:</b>\n<code>" + html.escape("\n".join(o["result"])[:2500]) + "</code>"
    rows = []
    if o["kind"] == "smm" and o["status"].lower() not in FINAL:
        rows.append([Btn("🔄 Cập nhật trạng thái", callback_data=f"ordr:{lid}")])
    if o["kind"] == "smm" and o["status"].lower() == "completed" and o.get("refill"):
        rows.append([Btn("♻️ Yêu cầu bảo hành (refill)", callback_data=f"refill:{lid}")])
    rows.append([Btn("↩️ Danh sách đơn", callback_data="orders:0"), *HOME_BTN])
    await show(update, ctx, text, Kb(rows))

async def do_refill(update, ctx, lid):
    o = DB["orders"].get(str(lid))
    if not o or o["uid"] != update.effective_user.id or o["kind"] != "smm":
        return
    if time.time() - o.get("refill_ts", 0) < 86400:
        return await show(update, ctx, "⏳ Mỗi đơn chỉ yêu cầu bảo hành 1 lần / 24 giờ.", Kb([[Btn("↩️ Quay lại", callback_data=f"ord:{lid}")]]))
    res = await asyncio.to_thread(smm, "refill", {"order": o["smm_id"]})
    ok = isinstance(res, dict) and res.get("refill") and not res.get("error")
    if ok:
        o["refill_ts"] = time.time()
        save()
    await show(update, ctx, "✅ Đã gửi yêu cầu bảo hành, hệ thống sẽ xử lý." if ok else
               "❌ Chưa thể bảo hành lúc này (đơn chưa đủ điều kiện hoặc hết hạn). Liên hệ Admin nếu cần.",
               Kb([[Btn("↩️ Quay lại", callback_data=f"ord:{lid}")]]))

# ---------- Theo dõi trạng thái đơn ----------
async def apply_status(app, lid, r):
    status = str(r.get("status", "")).strip()
    low = status.lower()
    refund, finished_msg, uid = 0, None, None
    with _lock:
        o = DB["orders"].get(lid)
        if not o or not status:
            return
        o["status"] = status
        try:
            o["remains"] = int(float(r.get("remains") or 0))
        except Exception:
            pass
        uid = o["uid"]
        if low in ("canceled", "cancelled", "refunded", "fail", "failed") and not o.get("refund_done"):
            refund = o["price"]
        elif low == "partial" and not o.get("refund_done"):
            refund = min(o["price"], math.ceil(o["price"] * o.get("remains", 0) / max(o["qty"], 1)))
        if low in FINAL and not o.get("refund_done"):
            o["refund_done"] = True
            if refund > 0:
                u = U(uid)
                u["balance"] += refund
                u["spent"] = max(0, u["spent"] - refund)
                o["refund_amount"] = refund
                hist(u, f"Hoàn tiền đơn #{lid} ({status}): +{fmt(refund)}đ")
            if low == "completed":
                finished_msg = f"✅ <b>Đơn #{lid} đã HOÀN THÀNH!</b>\n📦 {html.escape(o['name'])}\n📊 SL: {fmt(o['qty'])}\nCảm ơn bạn đã sử dụng dịch vụ 💙"
            elif low == "partial":
                finished_msg = (f"⚠️ <b>Đơn #{lid} chạy một phần</b>\n📦 {html.escape(o['name'])}\n"
                                f"📉 Chưa chạy: {fmt(o.get('remains', 0))}\n💸 Đã hoàn <code>{fmt(refund)}đ</code> vào số dư.")
            else:
                finished_msg = (f"❌ <b>Đơn #{lid} đã bị hủy</b>\n📦 {html.escape(o['name'])}\n💸 Đã hoàn <code>{fmt(refund)}đ</code> vào số dư.")
        save()
    if finished_msg:
        try:
            await app.bot.send_message(uid, finished_msg, parse_mode="HTML")
        except Exception:
            pass
        if low != "completed":
            for a in ADMIN_IDS:
                try:
                    await app.bot.send_message(a, f"ℹ️ Đơn #{lid} của <code>{uid}</code>: <b>{html.escape(status)}</b>, đã hoàn {fmt(refund)}đ.", parse_mode="HTML")
                except Exception:
                    pass

async def poll_once(app):
    with _lock:
        pending = [(k, o) for k, o in DB["orders"].items()
                   if o.get("kind") == "smm" and o.get("smm_id") and o["status"].lower() not in FINAL
                   and time.time() - o["time"] < 30 * 86400]
    for i in range(0, len(pending), 50):
        chunk = pending[i:i + 50]
        res = await asyncio.to_thread(smm, "status", {"orders": ",".join(str(o["smm_id"]) for _, o in chunk)})
        if not isinstance(res, dict):
            continue
        for lid, o in chunk:
            r = res.get(str(o["smm_id"]))
            if isinstance(r, dict) and not r.get("error"):
                await apply_status(app, lid, r)

async def provider_watch(app):
    res = await asyncio.to_thread(smm, "balance")
    try:
        bal = float(res["balance"])
    except Exception:
        return
    if bal < LOW_PROVIDER_BALANCE and time.time() - setting("low_alert_ts", 0) > 6 * 3600:
        set_setting("low_alert_ts", time.time())
        for a in ADMIN_IDS:
            try:
                await app.bot.send_message(a, f"🚨 <b>Số dư topsubre.vn sắp hết:</b> <code>{fmt(bal)}</code> {res.get('currency', '')}\nNạp thêm để đơn khách không bị lỗi!", parse_mode="HTML")
            except Exception:
                pass

async def background_loop(app):
    await ensure_services(True)
    n = 0
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            await poll_once(app)
            n += 1
            if n % 15 == 0:
                await provider_watch(app)
        except Exception:
            logging.exception("Lỗi vòng theo dõi đơn")

# ============================== NẠP TIỀN ==============================
async def menu_topup(update, ctx):
    ctx.user_data.pop("st", None)
    promo = f"🎉 <b>Khuyến mãi nạp +{promo_pct():g}%</b>\n\n" if promo_pct() > 0 else ""
    rows = [[Btn(f"💵 {fmt(a)}đ", callback_data=f"amt:{a}") for a in row] for row in ((10000, 50000, 100000), (200000, 500000, 1000000))]
    rows += [[Btn("⌨️ Nhập số tiền khác", callback_data="amt_custom")], HOME_BTN]
    await show(update, ctx, f"💳 <b>NẠP TIỀN TỰ ĐỘNG</b>\n════════════════════════════════\n{promo}👇 Chọn mệnh giá:", Kb(rows))

async def choose_bank(update, ctx, amount):
    if len(BANKS) == 1:
        return await send_qr(update, ctx, amount, 0)
    bonus = f"🎁 Nạp {fmt(amount)}đ nhận thêm <code>+{fmt(amount * promo_pct() / 100)}đ</code>\n" if promo_pct() > 0 else ""
    rows = [[Btn(f"🏦 {b['bank']} - {b['acc']}", callback_data=f"bank:{i}:{amount}")] for i, b in enumerate(BANKS)]
    rows.append([Btn("🔄 Chọn lại mệnh giá", callback_data="topup")])
    await show(update, ctx, f"🏦 <b>CHỌN TÀI KHOẢN NHẬN TIỀN</b>\n💵 Số tiền: <code>{fmt(amount)}đ</code>\n{bonus}", Kb(rows))

def fetch_img(url):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and (r.content[:8] == b"\x89PNG\r\n\x1a\n" or r.content[:2] == b"\xff\xd8"):
            return r.content
    except Exception:
        pass
    return None

async def send_qr(update, ctx, amount, bank_idx):
    user = update.effective_user
    b = BANKS[bank_idx if 0 <= bank_idx < len(BANKS) else 0]
    memo = f"NAP{user.id}"
    url = (f"https://img.vietqr.io/image/{b['bank']}-{b['acc']}-compact2.png?amount={int(amount)}"
           f"&addInfo={memo}&accountName={urllib.parse.quote(b['name'])}")
    promo = ""
    if promo_pct() > 0:
        bonus = amount * promo_pct() / 100
        promo = f"🎉 <b>KM +{promo_pct():g}%</b> → thưởng <code>+{fmt(bonus)}đ</code>, nhận <code>{fmt(amount + bonus)}đ</code>\n────────────────\n"
    cap = (f"💳 <b>THÔNG TIN CHUYỂN KHOẢN</b>\n════════════════════════════════\n{promo}"
           f"🏦 Ngân hàng: <code>{b['bank']}</code>\n🔢 STK: <code>{b['acc']}</code>\n👤 Chủ TK: <code>{b['name']}</code>\n"
           f"💵 Số tiền: <code>{fmt(amount)}đ</code>\n📝 Nội dung (BẮT BUỘC): <code>{memo}</code>\n\n"
           f"⚠️ <i>Chuyển đúng nội dung để hệ thống cộng tiền tự động trong vài giây.</i>")
    kb = Kb([[Btn("✅ Đã chuyển khoản", callback_data=f"paid:{amount}")],
             [Btn("🏦 Đổi tài khoản", callback_data=f"amt:{amount}"), Btn("🔄 Đổi mệnh giá", callback_data="topup")]])
    try:
        await update.callback_query.edit_message_text("⏳ <b>Đang tạo mã QR...</b>", parse_mode="HTML")
    except Exception:
        pass
    img = await asyncio.to_thread(fetch_img, url)
    try:
        await ctx.bot.send_photo(user.id, InputFile(io.BytesIO(img), "qr.png") if img else url, caption=cap, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logging.error(f"Gửi QR lỗi: {e}")
        await ctx.bot.send_message(user.id, cap + f'\n\n🔗 <a href="{html.escape(url, quote=True)}">Mở mã QR</a>', parse_mode="HTML", reply_markup=kb)
    try:
        await update.callback_query.message.delete()
    except Exception:
        pass

# ============================== TÀI KHOẢN & DỊCH VỤ THỦ CÔNG ==============================
async def menu_accounts(update, ctx):
    rows = [[Btn(f"{c['title']} • {fmt(acc_price(c))}đ (còn {len(stock_lines(c['id']))})", callback_data=f"accv:{c['id']}")] for c in ACCOUNT_CATS]
    rows.append(HOME_BTN)
    await show(update, ctx, "📦 <b>KHO TÀI KHOẢN</b>\n════════════════════════════════\n👇 Chọn loại tài khoản:", Kb(rows))

async def account_view(update, ctx, cid):
    c = next((x for x in ACCOUNT_CATS if x["id"] == cid), None)
    if not c:
        return
    n = len(stock_lines(cid))
    rows = [[Btn(f"Mua {q}", callback_data=f"accb:{cid}:{q}") for q in (1, 5, 10) if q <= n]]
    rows = [r for r in rows if r] + [[Btn("↩️ Kho tài khoản", callback_data="acc"), *HOME_BTN]]
    await show(update, ctx, f"{c['title']}\n💵 Giá: <code>{fmt(acc_price(c))}đ</code>/tài khoản\n📦 Còn: <code>{n}</code>" + ("" if n else "\n\n❌ <i>Tạm hết hàng.</i>"), Kb(rows))

async def account_buy(update, ctx, cid, qty):
    user = update.effective_user
    c = next((x for x in ACCOUNT_CATS if x["id"] == cid), None)
    if not c or qty not in (1, 5, 10):
        return
    total = acc_price(c) * qty
    with _lock:
        u = U(user.id)
        lines = stock_lines(cid)
        if len(lines) < qty:
            err = "⚠️ Kho không đủ hàng."
        elif u["balance"] < total:
            err = f"❌ Số dư không đủ. Cần <code>{fmt(total)}đ</code>, bạn có <code>{fmt(u['balance'])}đ</code>."
        else:
            err = None
            items, rest = lines[:qty], lines[qty:]
            write_stock(cid, rest)
            u["balance"] -= total
            u["spent"] += total
            lid = DB["next_order"]
            DB["next_order"] += 1
            DB["orders"][str(lid)] = {"id": lid, "kind": "acc", "uid": user.id, "name": f"{c['title']} x{qty}", "qty": qty, "price": total,
                                      "status": "Completed", "time": int(time.time()), "result": items, "refund_done": True}
            hist(u, f"Mua {c['title']} x{qty}: -{fmt(total)}đ (đơn #{lid})")
            save()
    if err:
        return await show(update, ctx, err, Kb([[Btn("💳 Nạp tiền", callback_data="topup"), Btn("↩️ Quay lại", callback_data="acc")]]))
    body = "\n".join(items)
    await show(update, ctx, f"🎉 <b>MUA THÀNH CÔNG</b> (đơn #{lid})\n{c['title']} x{qty} • -{fmt(total)}đ\n\n<code>{html.escape(body)}</code>\n\n"
                            f"💾 <i>Dữ liệu cũng được lưu trong mục Đơn của tôi.</i>", Kb([[Btn("📋 Đơn của tôi", callback_data="orders:0"), *HOME_BTN]]))

async def menu_manual(update, ctx):
    rows = [[Btn(f"{m['title']} • {fmt(m['price'])}đ", callback_data=f"mb:{k}")] for k, m in MANUAL_SERVICES.items()] + [HOME_BTN]
    await show(update, ctx, "💎 <b>DỊCH VỤ KHÁC</b> (Admin xử lý thủ công)\n════════════════════════════════\n👇 Chọn dịch vụ:", Kb(rows))

# ============================== ADMIN ==============================
def admin_panel_kb():
    return Kb([
        [Btn("📊 Thống kê", callback_data="adm_stats"), Btn("👥 Khách hàng", callback_data="adm_users:0")],
        [Btn("➕ Cộng số dư hàng loạt", callback_data="adm_bulk"), Btn("✏️ Sửa số dư", callback_data="adm_edit")],
        [Btn("💹 Chỉnh % lãi", callback_data="adm_mk"), Btn("🎉 Khuyến mãi nạp", callback_data="adm_promo")],
        [Btn("🎁 Gitcode", callback_data="adm_gc"), Btn("🏦 Số dư topsubre", callback_data="adm_prov")],
        [Btn("🔄 Đồng bộ dịch vụ", callback_data="adm_refresh"), Btn("💾 Backup", callback_data="adm_bk")],
        [Btn("📢 Broadcast", callback_data="adm_bc"), Btn("👤 Nhắn riêng", callback_data="adm_pm")],
        HOME_BTN])

BACK_ADM = [Btn("↩️ Quản lý", callback_data="adm")]

def stats_text():
    day0 = int((time.time() + 7 * 3600) // 86400 * 86400 - 7 * 3600)
    orders = [o for o in DB["orders"].values() if o["status"].lower() not in ("canceled", "cancelled", "failed", "fail")]
    today = [o for o in orders if o["time"] >= day0]
    rev = lambda lst: sum(o["price"] - o.get("refund_amount", 0) for o in lst)
    return (f"📊 <b>THỐNG KÊ</b>\n════════════════════════════════\n👥 Khách: <code>{len(DB['users'])}</code>\n"
            f"💰 Tổng số dư khách: <code>{fmt(sum(u['balance'] for u in DB['users'].values()))}đ</code>\n"
            f"🧾 Đơn hôm nay: <code>{len(today)}</code> • Doanh thu: <code>{fmt(rev(today))}đ</code>\n"
            f"🧾 Tổng đơn: <code>{len(orders)}</code> • Tổng doanh thu: <code>{fmt(rev(orders))}đ</code>\n"
            f"💹 % lãi hiện tại: <code>{markup_pct():g}%</code> • Dịch vụ đồng bộ: <code>{len(SVC['map'])}</code>")

def parse_amount(tok):
    t = tok.lower().replace(".", "").replace(",", "").replace("đ", "").replace("vnd", "").strip()
    mult = 1
    if t.endswith("k"):
        mult, t = 1000, t[:-1]
    v = float(t) * mult
    if v <= 0:
        raise ValueError
    return v

def parse_bulk(text):
    entries, errors, all_amt = {}, [], None
    for raw in text.splitlines():
        parts = [p for p in re.split(r"[\s:|=;]+", raw.strip()) if p]
        if not parts:
            continue
        if len(parts) < 2:
            errors.append(raw)
            continue
        try:
            amt = parse_amount(parts[-1])
            if parts[0].lower() in ("all", "tatca"):
                all_amt = amt
                continue
            uid = int(parts[0])
            if uid <= 0:
                raise ValueError
            entries[uid] = entries.get(uid, 0) + amt
        except ValueError:
            errors.append(raw)
    if all_amt is not None:
        return ("all", all_amt, errors) if not entries else ("err", None, ["Dòng ALL phải dùng riêng"])
    return "list", entries, errors

async def admin_callbacks(update, ctx, d):
    """Trả True nếu đã xử lý."""
    q = update.callback_query
    if d == "adm":
        ctx.user_data.pop("st", None)
        await show(update, ctx, "⚙️ <b>QUẢN LÝ HỆ THỐNG</b>\n👇 Chọn chức năng:", admin_panel_kb())
    elif d == "adm_stats":
        await show(update, ctx, stats_text(), Kb([BACK_ADM]))
    elif d.startswith("adm_users:"):
        page = int(d.split(":")[1])
        users = sorted(DB["users"].items(), key=lambda kv: -kv[1].get("balance", 0))
        per = 25
        text = "👥 <b>KHÁCH HÀNG</b> (xếp theo số dư)\n" + "\n".join(
            f"• <code>{k}</code> | {fmt(v.get('balance', 0))}đ | chi {fmt(v.get('spent', 0))}đ{' 🚫' if v.get('banned') else ''}"
            for k, v in users[page * per:(page + 1) * per])
        rows = [pager("adm_users", page, len(users), per)] if len(users) > per else []
        await show(update, ctx, text, Kb(rows + [BACK_ADM]))
    elif d == "adm_bulk":
        ctx.user_data["st"] = "bulk"
        await show(update, ctx, "➕ <b>CỘNG SỐ DƯ HÀNG LOẠT</b>\nMỗi khách 1 dòng:\n<code>ID SỐ_TIỀN</code>\nVí dụ:\n<code>6900793565 50000\n1234567890 100k</code>\n"
                                "Cộng cho tất cả: <code>ALL 10000</code>\n🔕 Khách không nhận thông báo.", Kb([BACK_ADM]))
    elif d == "bulk_ok":
        job = ctx.user_data.pop("bulk", None)
        if not job:
            return await show(update, ctx, "⚠️ Phiên đã hết hạn.", Kb([BACK_ADM]))
        n, tot = 0, 0.0
        with _lock:
            plan = {int(k): job["amount"] for k in DB["users"]} if job["mode"] == "all" else job["entries"]
            for uid, amt in plan.items():
                u = U(uid)
                u["balance"] += amt
                hist(u, f"Admin cộng số dư: +{fmt(amt)}đ")
                n, tot = n + 1, tot + amt
            save()
        await show(update, ctx, f"✅ Đã cộng cho <code>{n}</code> khách, tổng <code>{fmt(tot)}đ</code>.", Kb([BACK_ADM]))
    elif d == "adm_edit":
        ctx.user_data["st"] = "edit"
        await show(update, ctx, "✏️ Gửi: <code>ID SỐ_DƯ_MỚI</code>\nVí dụ: <code>6900793565 500000</code>", Kb([BACK_ADM]))
    elif d == "adm_mk" or d.startswith("mk:"):
        if d.startswith("mk:"):
            set_setting("markup", float(d.split(":")[1]))
        rows = [[Btn(f"{p}%", callback_data=f"mk:{p}") for p in (10, 20, 30, 40, 50)], [Btn("✍️ Nhập % khác", callback_data="mk_custom")], BACK_ADM]
        await show(update, ctx, f"💹 <b>% LÃI TRÊN GIÁ GỐC topsubre.vn</b>\nHiện tại: <b>{markup_pct():g}%</b>\n"
                                f"<i>Giá bán = giá gốc × (1 + %lãi), áp dụng ngay cho toàn bộ dịch vụ.</i>", Kb(rows))
    elif d == "mk_custom":
        ctx.user_data["st"] = "markup"
        await show(update, ctx, "✍️ Nhập % lãi (ví dụ 35):", Kb([BACK_ADM]))
    elif d == "adm_promo" or d.startswith("promo:"):
        if d.startswith("promo:"):
            set_setting("promo", float(d.split(":")[1]))
        rows = [[Btn(f"{p}%", callback_data=f"promo:{p}") for p in (5, 10, 20)], [Btn(f"{p}%", callback_data=f"promo:{p}") for p in (30, 50, 100)],
                [Btn("✍️ Nhập % khác", callback_data="promo_custom"), Btn("🚫 Tắt", callback_data="promo:0")], BACK_ADM]
        await show(update, ctx, f"🎉 <b>KHUYẾN MÃI NẠP</b>\nTrạng thái: {('🟢 +' + format(promo_pct(), 'g') + '%') if promo_pct() > 0 else '🔴 Tắt'}", Kb(rows))
    elif d == "promo_custom":
        ctx.user_data["st"] = "promo"
        await show(update, ctx, "✍️ Nhập % khuyến mãi (0-100, 0 = tắt):", Kb([BACK_ADM]))
    elif d == "adm_gc":
        rows = [[Btn(f"💵 {fmt(a)}đ", callback_data=f"gcnew:{a}") for a in (10000, 20000, 50000)], [Btn("💵 100.000đ", callback_data="gcnew:100000")],
                [Btn("✍️ Mã & mệnh giá tùy ý", callback_data="gc_custom"), Btn("📋 Danh sách", callback_data="gclist")], BACK_ADM]
        await show(update, ctx, "🎁 <b>GITCODE</b>", Kb(rows))
    elif d.startswith("gcnew:"):
        amt = float(d.split(":")[1])
        code = "KM" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        DB["gitcodes"][code] = {"amount": amt, "used_by": []}
        save()
        await show(update, ctx, f"✅ Mã: <code>{code}</code> • {fmt(amt)}đ", Kb([[Btn("📋 Danh sách", callback_data="gclist")], BACK_ADM]))
    elif d == "gc_custom":
        ctx.user_data["st"] = "gc_custom"
        await show(update, ctx, "✍️ Gửi: <code>MÃ SỐ_TIỀN</code> (ví dụ <code>TET2027 100000</code>)", Kb([BACK_ADM]))
    elif d == "gclist" or d.startswith("gcdel:"):
        if d.startswith("gcdel:"):
            DB["gitcodes"].pop(d.split(":", 1)[1], None)
            save()
        if not DB["gitcodes"]:
            return await show(update, ctx, "ℹ️ Chưa có gitcode.", Kb([BACK_ADM]))
        text = f"📋 <b>GITCODE ({len(DB['gitcodes'])})</b>\n" + "\n".join(
            f"• <code>{html.escape(c)}</code> {fmt(i['amount'])}đ | dùng {len(i['used_by'])}" for c, i in list(DB["gitcodes"].items())[:40])
        rows = [[Btn(f"🗑️ {c}", callback_data=f"gcdel:{c}")] for c in list(DB["gitcodes"])[:40]]
        await show(update, ctx, text, Kb(rows + [BACK_ADM]))
    elif d == "adm_prov":
        res = await asyncio.to_thread(smm, "balance")
        txt = (f"🏦 Số dư topsubre.vn: <b>{html.escape(str(res.get('balance')))}</b> {html.escape(str(res.get('currency', '')))}"
               if isinstance(res, dict) and "balance" in res else f"❌ Không lấy được số dư: <code>{html.escape(str(res))}</code>")
        await show(update, ctx, txt, Kb([BACK_ADM]))
    elif d == "adm_refresh":
        ok = await ensure_services(True)
        await show(update, ctx, f"{'✅ Đã đồng bộ' if ok else '❌ Đồng bộ lỗi (kiểm tra SMM_API_KEY)'}: <b>{len(SVC['map'])}</b> dịch vụ.", Kb([BACK_ADM]))
    elif d in ("adm_bk", "bk_now"):
        note = ""
        if d == "bk_now":
            ok = await asyncio.to_thread(backup_send, "thủ công")
            note = "✅ Đã gửi backup!\n\n" if ok else f"❌ Lỗi: {html.escape(BK['err'] or 'không rõ')}\n\n"
        last = time.strftime("%H:%M:%S %d/%m", time.gmtime(BK["ok"] + 7 * 3600)) if BK["ok"] else "chưa có"
        await show(update, ctx, f"💾 <b>AUTO_BACKUP</b>\n{note}Trạng thái: {'🟢 bật' if BK_ENABLED else '🔴 tắt'}\nLần gần nhất: {last}\n"
                                f"♻️ Khôi phục: gửi file <code>backup_*.zip</code> cho bot.", Kb([[Btn("📤 Backup ngay", callback_data="bk_now")], BACK_ADM]))
    elif d == "adm_bc":
        ctx.user_data["st"] = "bc"
        await show(update, ctx, "📢 Gửi nội dung broadcast (văn bản HTML hoặc 1 ảnh kèm caption):", Kb([BACK_ADM]))
    elif d == "bc_ok":
        bc = ctx.user_data.pop("bc", None)
        if not bc:
            return await show(update, ctx, "⚠️ Phiên hết hạn.", Kb([BACK_ADM]))
        await show(update, ctx, "⏳ Đang gửi broadcast...")
        ok = bad = 0
        for k in list(DB["users"]):
            try:
                try:
                    await send_media_or_text(ctx, int(k), bc, "HTML")
                except BadRequest:
                    await send_media_or_text(ctx, int(k), bc, None)
                ok += 1
            except Exception:
                bad += 1
            await asyncio.sleep(0.05)
        await ctx.bot.send_message(q.message.chat_id, f"✅ Broadcast xong: {ok} thành công, {bad} lỗi.", reply_markup=Kb([BACK_ADM]))
    elif d == "adm_pm":
        ctx.user_data["st"] = "pm_uid"
        await show(update, ctx, "👤 Nhập ID khách cần nhắn riêng:", Kb([BACK_ADM]))
    elif d.startswith("reply:"):
        ctx.user_data.update({"st": "pm_text", "pm_uid": int(d.split(":")[1])})
        await show(update, ctx, f"💬 Nhập nội dung gửi cho <code>{d.split(':')[1]}</code>:", Kb([BACK_ADM]))
    else:
        return False
    return True

async def send_media_or_text(ctx, chat_id, bc, pm):
    if bc.get("photo"):
        await ctx.bot.send_photo(chat_id, bc["photo"], caption=bc["text"], parse_mode=pm)
    else:
        await ctx.bot.send_message(chat_id, bc["text"], parse_mode=pm)

# ============================== BỘ ĐIỀU PHỐI NÚT BẤM ==============================
_LAST = {}

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user, d = q.from_user, q.data or ""
    now = time.monotonic()
    if now - _LAST.get(user.id, 0) < 0.25:
        return await q.answer()
    _LAST[user.id] = now
    try:
        await q.answer()
    except Exception:
        pass
    u = U(user.id)
    if u.get("banned") and not is_admin(user.id):
        return
    if setting("maint") and not is_admin(user.id):
        return await show(update, ctx, "🛠️ Hệ thống đang bảo trì, vui lòng quay lại sau.")
    try:
        if d == "none":
            return
        if d == "home":
            ctx.user_data.clear()
            return await go_home(update, ctx)
        if d.startswith(("adm", "bulk_ok", "mk", "promo", "gcnew", "gc_custom", "gclist", "gcdel", "bk_now", "bc_ok", "reply:")):
            if not is_admin(user.id):
                return
            if await admin_callbacks(update, ctx, d):
                return
        if d == "svc":
            return await menu_platforms(update, ctx)
        if d.startswith("pl:"):
            _, plat, page = d.split(":")
            return await menu_categories(update, ctx, plat, int(page))
        if d.startswith("ct:"):
            _, plat, ci, page = d.split(":")
            return await menu_services(update, ctx, plat, int(ci), int(page))
        if d.startswith("sv:"):
            return await service_detail(update, ctx, int(d[3:]))
        if d.startswith("buy:"):
            return await start_buy(update, ctx, int(d[4:]))
        if d == "ord_ok":
            return await place_order(update, ctx)
        if d.startswith("orders:"):
            return await my_orders(update, ctx, int(d.split(":")[1]))
        if d.startswith("ordr:"):
            return await order_detail(update, ctx, int(d[5:]), refresh=True)
        if d.startswith("ord:"):
            return await order_detail(update, ctx, int(d[4:]))
        if d.startswith("refill:"):
            return await do_refill(update, ctx, int(d[7:]))
        if d == "hist":
            h = u.get("history", [])
            text = "📜 <b>LỊCH SỬ GẦN ĐÂY</b>\n════════════════════════════════\n" + ("\n".join(html.escape(x) for x in reversed(h[-15:])) if h else "Chưa có giao dịch.")
            return await show(update, ctx, text, Kb([HOME_BTN]))
        if d == "topup":
            return await menu_topup(update, ctx)
        if d == "amt_custom":
            ctx.user_data["st"] = "amt"
            return await show(update, ctx, f"⌨️ Nhắn số tiền muốn nạp (tối thiểu {fmt(MIN_TOPUP)}đ, ví dụ 150000):", Kb([[Btn("↩️ Quay lại", callback_data="topup")]]))
        if d.startswith("amt:"):
            return await choose_bank(update, ctx, int(d[4:]))
        if d.startswith("bank:"):
            _, i, amt = d.split(":")
            if time.time() - ctx.user_data.get("qr_busy", 0) < 15:
                return
            ctx.user_data["qr_busy"] = time.time()
            try:
                return await send_qr(update, ctx, int(amt), int(i))
            finally:
                ctx.user_data["qr_busy"] = 0
        if d.startswith("paid:"):
            amount = float(d.split(":")[1])
            wait = f"⏳ Đã ghi nhận yêu cầu nạp <code>{fmt(amount)}đ</code>. Tiền sẽ được cộng tự động khi ngân hàng báo về (thường vài giây)."
            kb = Kb([HOME_BTN])
            if q.message.photo:
                await q.edit_message_caption(caption=wait, parse_mode="HTML", reply_markup=kb)
            else:
                await show(update, ctx, wait, kb)
            for a in ADMIN_IDS:
                try:
                    await ctx.bot.send_message(a, f"🔔 <b>KHÁCH BÁO ĐÃ CHUYỂN</b>\n👤 {mention(user)} (<code>{user.id}</code>)\n💵 {fmt(amount)}đ",
                                               parse_mode="HTML", reply_markup=Kb([[Btn(f"✅ Duyệt cộng {fmt(amount)}đ", callback_data=f"ap:{user.id}:{int(amount)}")],
                                                                                   [Btn("❌ Chưa nhận được", callback_data=f"rj:{user.id}:{int(amount)}")]]))
                except Exception:
                    pass
            return
        if d.startswith(("ap:", "rj:")):
            if not is_admin(user.id):
                return
            done = ctx.bot_data.setdefault("done", set())
            key = (q.message.chat_id, q.message.message_id)
            if key in done:
                return
            done.add(key)
            act, tid, amt = d.split(":")
            tid, amt = int(tid), float(amt)
            if act == "ap":
                nb, bonus = credit_topup(tid, amt, "Admin duyệt")
                await q.edit_message_text(f"✅ Đã cộng {fmt(amt)}đ (+{fmt(bonus)}đ KM) cho <code>{tid}</code>", parse_mode="HTML")
                try:
                    await ctx.bot.send_message(tid, f"🎉 <b>Nạp tiền thành công</b> +{fmt(amt + bonus)}đ\n💳 Số dư: <code>{fmt(nb)}đ</code>", parse_mode="HTML")
                except Exception:
                    pass
            else:
                await q.edit_message_text(f"❌ Đã báo chưa nhận được tiền {fmt(amt)}đ của <code>{tid}</code>", parse_mode="HTML")
                try:
                    await ctx.bot.send_message(tid, f"⚠️ Giao dịch nạp {fmt(amt)}đ chưa thấy tiền về. Liên hệ Admin @{ADMIN_USERNAME} để được hỗ trợ.")
                except Exception:
                    pass
            return
        if d == "gc":
            ctx.user_data["st"] = "gitcode"
            return await show(update, ctx, "🎁 <b>NHẬP GITCODE</b>\n💬 Gửi mã của bạn vào đây:", Kb([HOME_BTN]))
        if d == "ref":
            link = f"https://t.me/{ctx.bot.username}?start=ref_{user.id}"
            n = sum(1 for x in DB["users"].values() if x.get("ref_by") == user.id)
            return await show(update, ctx, f"👥 <b>GIỚI THIỆU BẠN BÈ</b>\n════════════════════════════════\n"
                                           f"Nhận <b>{float(setting('ref_pct', 3)):g}%</b> mỗi lần bạn bè nạp tiền, mãi mãi!\n\n🔗 Link của bạn:\n<code>{link}</code>\n\n"
                                           f"👤 Đã giới thiệu: <b>{n}</b> người\n💰 Đã nhận: <b>{fmt(u.get('ref_earn', 0))}đ</b>", Kb([HOME_BTN]))
        if d == "acc":
            return await menu_accounts(update, ctx)
        if d.startswith("accv:"):
            return await account_view(update, ctx, d[5:])
        if d.startswith("accb:"):
            _, cid, n = d.split(":")
            return await account_buy(update, ctx, cid, int(n))
        if d == "man":
            return await menu_manual(update, ctx)
        if d.startswith("mb:"):
            m = MANUAL_SERVICES.get(d[3:])
            if not m:
                return
            ctx.user_data.update({"st": "manual", "manual": d[3:]})
            return await show(update, ctx, f"{m['title']}\n💵 Giá: <code>{fmt(m['price'])}đ</code>\n\n💬 {m['ask']}", Kb([[Btn("❌ Hủy", callback_data="man")]]))
        if d.startswith(("mdone:", "mrej:")):
            if not is_admin(user.id):
                return
            act, lid = d.split(":")
            o = DB["orders"].get(lid)
            if not o or o["status"] != "Pending":
                return
            with _lock:
                if act == "mdone":
                    o["status"] = "Completed"
                else:
                    o["status"] = "Canceled"
                    ru = U(o["uid"])
                    ru["balance"] += o["price"]
                    ru["spent"] = max(0, ru["spent"] - o["price"])
                    o["refund_amount"] = o["price"]
                    hist(ru, f"Hoàn tiền đơn #{lid}: +{fmt(o['price'])}đ")
                o["refund_done"] = True
                save()
            await q.edit_message_text(f"{q.message.text_html}\n\n{'✅ ĐÃ XỬ LÝ XONG' if act == 'mdone' else '❌ ĐÃ TỪ CHỐI & HOÀN TIỀN'}", parse_mode="HTML")
            try:
                await ctx.bot.send_message(o["uid"], f"✅ Đơn #{lid} ({html.escape(o['name'])}) đã được Admin xử lý xong!" if act == "mdone" else
                                           f"❌ Đơn #{lid} bị từ chối, đã hoàn <code>{fmt(o['price'])}đ</code> vào số dư.", parse_mode="HTML")
            except Exception:
                pass
            return
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise

# ============================== NHẬN TIN NHẮN ==============================
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user, msg = update.effective_user, update.message
    st = ctx.user_data.get("st")
    if not st or not msg or not msg.text:
        return
    text = msg.text.strip()
    u = U(user.id)
    if u.get("banned") and not is_admin(user.id):
        return
    cancel_kb = Kb([[Btn("❌ Hủy", callback_data="home")]])

    # ----- đặt đơn SMM -----
    if st == "link":
        od = ctx.user_data.get("order") or {}
        s = SVC["map"].get(od.get("sid"))
        if not s:
            ctx.user_data.clear()
            return await msg.reply_text("⚠️ Phiên hết hạn, vui lòng chọn lại dịch vụ.", reply_markup=Kb([[Btn("🛒 Dịch vụ", callback_data="svc")]]))
        if len(text) > 500 or not re.search(r"[\w@]", text):
            return await msg.reply_text("⚠️ Link không hợp lệ, gửi lại link công khai:", reply_markup=cancel_kb)
        od["link"] = text
        if s["type"] == "Custom Comments":
            ctx.user_data["st"] = "comments"
            return await msg.reply_text(f"💬 Gửi nội dung bình luận, <b>mỗi dòng 1 bình luận</b> ({fmt(s['min'])}–{fmt(s['max'])} dòng):", parse_mode="HTML", reply_markup=cancel_kb)
        ctx.user_data["st"] = "qty"
        return await msg.reply_text(f"📊 Nhập <b>số lượng</b> ({fmt(s['min'])} – {fmt(s['max'])}):\n💵 Giá: <code>{fmt_rate(per1000(s, user.id))}đ</code>/1000",
                                    parse_mode="HTML", reply_markup=cancel_kb)
    if st in ("qty", "comments"):
        od = ctx.user_data.get("order") or {}
        s = SVC["map"].get(od.get("sid"))
        if not s:
            ctx.user_data.clear()
            return await msg.reply_text("⚠️ Phiên hết hạn.", reply_markup=Kb([[Btn("🛒 Dịch vụ", callback_data="svc")]]))
        if st == "qty":
            try:
                qty = int(parse_amount(text))
            except ValueError:
                return await msg.reply_text("⚠️ Nhập số nguyên hợp lệ:", reply_markup=cancel_kb)
        else:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            od["comments"], qty = lines, len(lines)
        if not (s["min"] <= qty <= s["max"]):
            return await msg.reply_text(f"⚠️ Số lượng phải từ {fmt(s['min'])} đến {fmt(s['max'])}. Nhập lại:", reply_markup=cancel_kb)
        od["qty"] = qty
        ctx.user_data.pop("st", None)
        price = calc_price(s, qty, user.id)
        return await msg.reply_text(confirm_text(s, od, price, u["balance"]), parse_mode="HTML", disable_web_page_preview=True,
                                    reply_markup=Kb([[Btn(f"✅ Thanh toán {fmt(price)}đ", callback_data="ord_ok")], [Btn("❌ Hủy", callback_data="home")]]))

    # ----- nạp tiền / gitcode / dịch vụ thủ công -----
    if st == "amt":
        try:
            amount = int(parse_amount(text))
            if amount < MIN_TOPUP or amount > 500_000_000:
                raise ValueError
        except ValueError:
            return await msg.reply_text(f"⚠️ Số tiền không hợp lệ (tối thiểu {fmt(MIN_TOPUP)}đ). Nhập lại:")
        ctx.user_data.pop("st", None)
        rows = [[Btn(f"🏦 {b['bank']} - {b['acc']}", callback_data=f"bank:{i}:{amount}")] for i, b in enumerate(BANKS)]
        return await msg.reply_text(f"🏦 Chọn tài khoản nhận tiền cho <code>{fmt(amount)}đ</code>:", parse_mode="HTML", reply_markup=Kb(rows))
    if st == "gitcode":
        code = text.upper()
        ctx.user_data.pop("st", None)
        with _lock:
            g = DB["gitcodes"].get(code)
            if not g:
                res = "❌ Mã không tồn tại hoặc đã hết hạn!"
            elif user.id in g["used_by"]:
                res = "⚠️ Bạn đã dùng mã này rồi!"
            else:
                g["used_by"].append(user.id)
                u["balance"] += g["amount"]
                hist(u, f"Gitcode {code}: +{fmt(g['amount'])}đ")
                save()
                res = f"🎉 <b>NHẬP GITCODE THÀNH CÔNG!</b>\n💰 +<code>{fmt(g['amount'])}đ</code>\n💳 Số dư: <code>{fmt(u['balance'])}đ</code>"
        return await msg.reply_text(res, parse_mode="HTML", reply_markup=Kb([HOME_BTN]))
    if st == "manual":
        m = MANUAL_SERVICES.get(ctx.user_data.get("manual"))
        ctx.user_data.clear()
        if not m:
            return
        with _lock:
            if u["balance"] < m["price"]:
                return await msg.reply_text(f"❌ Số dư không đủ. Cần <code>{fmt(m['price'])}đ</code>, bạn có <code>{fmt(u['balance'])}đ</code>.",
                                            parse_mode="HTML", reply_markup=Kb([[Btn("💳 Nạp tiền", callback_data="topup"), *HOME_BTN]]))
            u["balance"] -= m["price"]
            u["spent"] += m["price"]
            lid = DB["next_order"]
            DB["next_order"] += 1
            DB["orders"][str(lid)] = {"id": lid, "kind": "manual", "uid": user.id, "name": m["title"], "link": text[:300], "qty": 1,
                                      "price": m["price"], "status": "Pending", "time": int(time.time())}
            hist(u, f"Đặt {m['title']} (#{lid}): -{fmt(m['price'])}đ")
            save()
        await msg.reply_text(f"🎉 <b>ĐÃ ĐẶT {html.escape(m['title'])}</b> (đơn #{lid})\n💵 -{fmt(m['price'])}đ\n⏳ Admin sẽ liên hệ bạn sớm.",
                             parse_mode="HTML", reply_markup=Kb([HOME_BTN]))
        for a in ADMIN_IDS:
            try:
                await ctx.bot.send_message(a, f"🔔 <b>ĐƠN THỦ CÔNG #{lid}</b>\n👤 {mention(user)} (<code>{user.id}</code>)\n📦 {html.escape(m['title'])}\n"
                                              f"📝 <code>{html.escape(text[:1500])}</code>\n💵 {fmt(m['price'])}đ", parse_mode="HTML",
                                           reply_markup=Kb([[Btn("✅ Đã xử lý xong", callback_data=f"mdone:{lid}")], [Btn("❌ Từ chối & hoàn tiền", callback_data=f"mrej:{lid}")],
                                                            [Btn("💬 Nhắn khách", callback_data=f"reply:{user.id}")]]))
            except Exception:
                pass
        return

    # ----- các trạng thái dành cho Admin -----
    if not is_admin(user.id):
        return
    back = Kb([BACK_ADM])
    if st == "bulk":
        mode, data, errs = parse_bulk(text)
        if mode == "err" or (mode == "list" and not data):
            return await msg.reply_text("⚠️ Không đọc được dữ liệu:\n" + html.escape("\n".join(errs) or "không có dòng hợp lệ") + "\nGửi lại theo mẫu <code>ID SỐ_TIỀN</code>", parse_mode="HTML")
        if mode == "all":
            ctx.user_data["bulk"] = {"mode": "all", "amount": data}
            summ = f"👥 TẤT CẢ <b>{len(DB['users'])}</b> khách • mỗi khách +{fmt(data)}đ"
        else:
            ctx.user_data["bulk"] = {"mode": "list", "entries": data}
            summ = f"👥 <b>{len(data)}</b> khách • tổng {fmt(sum(data.values()))}đ\n" + "\n".join(f"• <code>{k}</code>: +{fmt(v)}đ" for k, v in list(data.items())[:30])
        ctx.user_data.pop("st", None)
        return await msg.reply_text(f"📋 <b>XÁC NHẬN CỘNG SỐ DƯ</b>\n{summ}" + (f"\n⚠️ Bỏ qua dòng lỗi: {len(errs)}" if errs else ""), parse_mode="HTML",
                                    reply_markup=Kb([[Btn("✅ Xác nhận", callback_data="bulk_ok")], BACK_ADM]))
    if st == "edit":
        try:
            tid, nb = text.split()[:2]
            tid, nb = int(tid), float(nb.replace(".", "").replace(",", ""))
        except Exception:
            return await msg.reply_text("⚠️ Sai cú pháp: <code>ID SỐ_DƯ_MỚI</code>", parse_mode="HTML")
        with _lock:
            tu = U(tid)
            tu["balance"] = nb
            hist(tu, f"Admin đặt số dư: {fmt(nb)}đ")
            save()
        ctx.user_data.pop("st", None)
        return await msg.reply_text(f"✅ Số dư của <code>{tid}</code> = {fmt(nb)}đ", parse_mode="HTML", reply_markup=back)
    if st in ("markup", "promo"):
        try:
            v = float(text.replace("%", "").replace(",", "."))
            if v < 0 or (st == "promo" and v > 100) or v > 1000:
                raise ValueError
        except ValueError:
            return await msg.reply_text("⚠️ Giá trị không hợp lệ, nhập lại:")
        set_setting(st, v)
        ctx.user_data.pop("st", None)
        return await msg.reply_text(f"✅ Đã cập nhật {'% lãi' if st == 'markup' else 'khuyến mãi'}: <b>{v:g}%</b>", parse_mode="HTML", reply_markup=back)
    if st == "gc_custom":
        p = text.split()
        try:
            code, amt = p[0].upper(), parse_amount(p[1])
        except Exception:
            return await msg.reply_text("⚠️ Sai cú pháp: <code>MÃ SỐ_TIỀN</code>", parse_mode="HTML")
        DB["gitcodes"][code] = {"amount": amt, "used_by": []}
        save()
        ctx.user_data.pop("st", None)
        return await msg.reply_text(f"✅ Tạo mã <code>{html.escape(code)}</code> = {fmt(amt)}đ", parse_mode="HTML", reply_markup=back)
    if st == "bc":
        ctx.user_data["bc"] = {"photo": None, "text": text}
        ctx.user_data.pop("st", None)
        return await msg.reply_text(f"📋 <b>XEM TRƯỚC</b>\n\n{text}", parse_mode="HTML",
                                    reply_markup=Kb([[Btn("🚀 Gửi cho tất cả khách", callback_data="bc_ok")], BACK_ADM]))
    if st == "pm_uid":
        try:
            ctx.user_data["pm_uid"] = int(text)
        except ValueError:
            return await msg.reply_text("⚠️ ID không hợp lệ:")
        ctx.user_data["st"] = "pm_text"
        return await msg.reply_text("💬 Nhập nội dung gửi cho khách:", reply_markup=back)
    if st == "pm_text":
        tid = ctx.user_data.get("pm_uid")
        ctx.user_data.pop("st", None)
        try:
            await ctx.bot.send_message(tid, text, parse_mode="HTML", reply_markup=Kb([[Btn("💬 Phản hồi Admin", url=f"https://t.me/{ADMIN_USERNAME}")]]) if ADMIN_USERNAME else None)
            res = f"✅ Đã gửi cho <code>{tid}</code>"
        except Exception:
            res = "❌ Gửi thất bại (ID sai hoặc khách đã chặn bot)."
        return await msg.reply_text(res, parse_mode="HTML", reply_markup=back)

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user, msg = update.effective_user, update.message
    if is_admin(user.id) and ctx.user_data.get("st") == "bc" and msg.photo:
        ctx.user_data["bc"] = {"photo": msg.photo[-1].file_id, "text": msg.caption or ""}
        ctx.user_data.pop("st", None)
        await msg.reply_photo(msg.photo[-1].file_id, caption=f"📋 XEM TRƯỚC\n\n{msg.caption or ''}"[:1000],
                              reply_markup=Kb([[Btn("🚀 Gửi cho tất cả khách", callback_data="bc_ok")], BACK_ADM]))

async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user, doc = update.effective_user, update.message.document
    if not is_admin(user.id) or not doc or not (doc.file_name or "").startswith("backup_") or not doc.file_name.endswith(".zip"):
        return
    try:
        f = await ctx.bot.get_file(doc.file_id)
        raw = bytes(await f.download_as_bytearray())
        res = "✅ " + await asyncio.to_thread(restore_zip, raw)
    except Exception as e:
        res = "❌ " + html.escape(str(e))
    await update.message.reply_text(res, parse_mode="HTML")

# ============================== LỆNH ==============================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ctx.user_data.clear()
    is_new = str(user.id) not in DB["users"]
    u = U(user.id)
    u["name"] = user.first_name or ""
    if u.get("banned") and not is_admin(user.id):
        return
    if is_new and ctx.args and ctx.args[0].startswith("ref_"):
        try:
            r = int(ctx.args[0][4:])
        except ValueError:
            r = 0
        if r and r != user.id and str(r) in DB["users"]:
            u["ref_by"] = r
            save()
    if setting("maint") and not is_admin(user.id):
        return await update.message.reply_text("🛠️ Hệ thống đang bảo trì, vui lòng quay lại sau.")
    text, kb = main_menu(user)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)

def admin_only(fn):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if is_admin(update.effective_user.id):
            return await fn(update, ctx)
    return wrapper

@admin_only
async def cmd_topup(update, ctx):
    try:
        tid, amt = int(ctx.args[0]), parse_amount(ctx.args[1])
    except Exception:
        return await update.message.reply_text("Cú pháp: /topup <ID> <Số_tiền>")
    with _lock:
        u = U(tid)
        u["balance"] += amt
        hist(u, f"Admin cộng: +{fmt(amt)}đ")
        save()
    await update.message.reply_text(f"✅ Đã cộng {fmt(amt)}đ cho {tid}. Dư: {fmt(u['balance'])}đ")
    try:
        await ctx.bot.send_message(tid, f"🎉 Bạn được cộng <b>+{fmt(amt)}đ</b>\n💳 Số dư: <code>{fmt(u['balance'])}đ</code>", parse_mode="HTML")
    except Exception:
        pass

@admin_only
async def cmd_ban(update, ctx):
    try:
        tid = int(ctx.args[0])
    except Exception:
        return await update.message.reply_text("Cú pháp: /ban <ID>  hoặc  /unban <ID>")
    U(tid)["banned"] = update.message.text.startswith("/ban")
    save()
    await update.message.reply_text(f"{'🚫 Đã chặn' if U(tid)['banned'] else '✅ Đã bỏ chặn'} {tid}")

@admin_only
async def cmd_addstock(update, ctx):
    parts = update.message.text.split("\n")
    head = parts[0].split()
    ids = [c["id"] for c in ACCOUNT_CATS]
    if len(head) < 2 or head[1] not in ids:
        return await update.message.reply_text("Cú pháp:\n/addstock <loại>\ntaikhoan1|matkhau\ntaikhoan2|matkhau\n\nLoại: " + ", ".join(ids))
    new = [l.strip() for l in parts[1:] if l.strip()]
    with _lock:
        write_stock(head[1], stock_lines(head[1]) + new)
    await update.message.reply_text(f"✅ Đã thêm {len(new)} tài khoản. Kho {head[1]}: {len(stock_lines(head[1]))}")

@admin_only
async def cmd_setprice(update, ctx):
    try:
        cid, price = ctx.args[0], int(parse_amount(ctx.args[1]))
        assert cid in [c["id"] for c in ACCOUNT_CATS]
    except Exception:
        return await update.message.reply_text("Cú pháp: /setprice <loại> <giá>")
    DB["settings"].setdefault("acc_price", {})[cid] = price
    save()
    await update.message.reply_text(f"✅ Giá {cid} = {fmt(price)}đ")

@admin_only
async def cmd_hide(update, ctx):
    try:
        sid = int(ctx.args[0])
    except Exception:
        return await update.message.reply_text("Cú pháp: /hide <mã dịch vụ> (bỏ ẩn: /unhide <mã>)")
    hidden = set(setting("hidden", []))
    hidden.add(sid) if update.message.text.startswith("/hide") else hidden.discard(sid)
    set_setting("hidden", sorted(hidden))
    await ensure_services(True)
    await update.message.reply_text(f"✅ Đã cập nhật. Đang ẩn: {sorted(hidden) or 'không có'}")

@admin_only
async def cmd_maint(update, ctx):
    set_setting("maint", not setting("maint", False))
    await update.message.reply_text("🛠️ Bảo trì: " + ("BẬT" if setting("maint") else "TẮT"))

async def on_error(update, ctx):
    if type(ctx.error).__name__ == "Conflict":
        logging.warning("Conflict getUpdates (có bản bot khác đang chạy, thường chỉ lúc deploy)")
        return
    logging.error("Lỗi không bắt được:", exc_info=ctx.error)

async def post_init(app):
    asyncio.create_task(background_loop(app))

def main():
    if not BOT_TOKEN or not SMM_API_KEY or not ADMIN_IDS:
        print("⚠️ Cần đặt biến môi trường: BOT_TOKEN, SMM_API_KEY, ADMIN_CHAT_ID")
        return
    Thread(target=_saver, daemon=True).start()
    if BK_ENABLED:
        Thread(target=_bk_worker, daemon=True).start()
    Thread(target=run_flask, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    import atexit
    atexit.register(_flush)
    if not SEPAY_KEYS:
        logging.warning("⚠️ Chưa đặt SEPAY_API_KEY: webhook nạp tiền tự động sẽ bị từ chối.")

    app = (ApplicationBuilder().token(BOT_TOKEN).concurrent_updates(True).connection_pool_size(64)
           .pool_timeout(15).connect_timeout(15).read_timeout(20).write_timeout(20).post_init(post_init).build())
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("topup", cmd_topup))
    app.add_handler(CommandHandler(["ban", "unban"], cmd_ban))
    app.add_handler(CommandHandler("addstock", cmd_addstock))
    app.add_handler(CommandHandler("setprice", cmd_setprice))
    app.add_handler(CommandHandler(["hide", "unhide"], cmd_hide))
    app.add_handler(CommandHandler("maint", cmd_maint))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    logging.info("🟢 Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)
    _flush()

if __name__ == "__main__":
    main()
