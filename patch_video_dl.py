#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cách dùng:   python patch_video_dl.py bot.py
-> Tự tích hợp menu "TẢI VIDEO MXH" vào file bot, ghi ra bot.py (bản cũ được lưu thành bot.py.bak).
"""
import sys, os, shutil

BLOCK = r'''# ==================== TẢI VIDEO MẠNG XÃ HỘI (TIKTOK / FACEBOOK) ====================
# Cần thêm vào requirements.txt:  yt-dlp  và  imageio-ffmpeg  (để ghép video HD/1080p/4K)
# Biến môi trường (tùy chọn): DL_COOKIES_FILE (file cookies.txt nếu FB/TikTok yêu cầu đăng nhập),
#                             DL_MAX_DURATION (giây, mặc định 1800), DL_MAX_PARALLEL (mặc định 2)
import shutil
import tempfile
import glob

try:
    import yt_dlp
except Exception:
    yt_dlp = None
    logging.warning("⚠️ Chưa cài yt-dlp: tính năng TẢI VIDEO MXH sẽ không chạy. Hãy thêm 'yt-dlp' vào requirements.txt")

DL_TMP_DIR = os.path.join(tempfile.gettempdir(), "smm_dl")
DL_DEL_FILE = os.path.join(DB_DIR, "dl_delete_queue.json")   # hàng đợi xóa video (không đưa vào backup)
DL_AUTO_DELETE_SEC = 180                                     # video tự xóa sau 3 phút
DL_MAX_DURATION = int(os.getenv("DL_MAX_DURATION", "1800") or 1800)
DL_MAX_PARALLEL = int(os.getenv("DL_MAX_PARALLEL", "2") or 2)
DL_HIST_MAX = 30                                             # mỗi khách lưu tối đa 30 lượt tải
DL_HIST_PER_PAGE = 5
TG_UPLOAD_LIMIT = 49 * 1000 * 1000                           # Bot Telegram chỉ gửi được file <= 50MB
DL_COOKIES_FILE = os.getenv("DL_COOKIES_FILE", "").strip()
DL_QUALITY_CHAIN = (2160, 1080, 720, 480, 360)
DL_QUALITY_LABELS = {
    480: "📱 SD 480p",
    720: "🎬 HD 720p",
    1080: "📺 Full HD 1080p",
    2160: "💎 4K 2160p",
}
DL_PLATFORMS = {
    "tt": {
        "name": "TikTok", "icon": "🎵",
        "domains": ("tiktok.com",),
        "example": "https://vm.tiktok.com/xxxxxxx/  hoặc  https://www.tiktok.com/@user/video/123...",
    },
    "fb": {
        "name": "Facebook", "icon": "📘",
        "domains": ("facebook.com", "fb.watch", "fb.com"),
        "example": "https://www.facebook.com/watch?v=123...  hoặc  https://fb.watch/xxxxxxx/",
    },
}

try:
    os.makedirs(DL_TMP_DIR, exist_ok=True)
except Exception:
    pass

def _find_ffmpeg():
    """Tìm ffmpeg trên máy; nếu không có thì dùng bản đi kèm gói imageio-ffmpeg."""
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        bindir = os.path.join(tempfile.gettempdir(), "smm_ffmpeg_bin")
        os.makedirs(bindir, exist_ok=True)
        link = os.path.join(bindir, "ffmpeg")
        if not os.path.exists(link):
            try:
                os.symlink(exe, link)
            except Exception:
                shutil.copy2(exe, link)
                os.chmod(link, 0o755)
        return link
    except Exception:
        return None

FFMPEG_PATH = _find_ffmpeg()
if yt_dlp is not None:
    if FFMPEG_PATH:
        logging.info(f"✅ Tải video MXH: yt-dlp + ffmpeg ({FFMPEG_PATH})")
    else:
        logging.warning("⚠️ Tải video MXH: không có ffmpeg -> chỉ tải được định dạng gộp sẵn (chất lượng cao có thể bị hạn chế). Thêm 'imageio-ffmpeg' vào requirements.txt")

# ---------- Lịch sử tải (lưu file, có backup cùng các dữ liệu khác) ----------
_dl_data = _load_json(DL_FILE, {})
DL_DB = _dl_data if isinstance(_dl_data, dict) else {}
if not isinstance(DL_DB.get("hist"), dict):
    DL_DB["hist"] = {}

def save_dl_db():
    _save_json(DL_FILE, DL_DB, "dl_history")

def dl_add_history(user_id, platform, url, quality, height, title):
    rec = {
        "key": uuid.uuid4().hex[:8],
        "platform": platform,
        "url": url,
        "q": int(quality),
        "h": int(height) if height else 0,
        "title": str(title or "")[:120],
        "t": int(time.time()),
    }
    with DB_LOCK:
        lst = DL_DB.setdefault("hist", {}).setdefault(str(user_id), [])
        lst[:] = [r for r in lst if not (r.get("url") == url and r.get("q") == int(quality))]
        lst.insert(0, rec)
        del lst[DL_HIST_MAX:]
        save_dl_db()

def dl_get_history(user_id):
    return list(DL_DB.get("hist", {}).get(str(user_id), []))

# ---------- Hàng đợi tự xóa video sau 3 phút (chịu được việc bot khởi động lại) ----------
_DL_DEL_LOCK = threading.Lock()
_DL_DEL_QUEUE = []   # mỗi phần tử: [chat_id, message_id, thời_điểm_xóa]
try:
    if os.path.exists(DL_DEL_FILE):
        with open(DL_DEL_FILE, "r", encoding="utf-8") as _f:
            _q = json.load(_f)
        if isinstance(_q, list):
            _DL_DEL_QUEUE = [x for x in _q if isinstance(x, list) and len(x) == 3]
except Exception:
    _DL_DEL_QUEUE = []

def _dl_del_save():
    try:
        atomic_json_dump(DL_DEL_FILE, _DL_DEL_QUEUE)
    except Exception as e:
        logging.error(f"Lỗi lưu hàng đợi xóa video: {e}")

def dl_schedule_delete(chat_id, message_id, delay=DL_AUTO_DELETE_SEC):
    with _DL_DEL_LOCK:
        _DL_DEL_QUEUE.append([int(chat_id), int(message_id), time.time() + delay])
        _dl_del_save()

def _dl_sweeper_worker():
    while True:
        time.sleep(5)
        try:
            now = time.time()
            with _DL_DEL_LOCK:
                due = [x for x in _DL_DEL_QUEUE if x[2] <= now]
                if due:
                    _DL_DEL_QUEUE[:] = [x for x in _DL_DEL_QUEUE if x[2] > now]
                    _dl_del_save()
            retry = []
            for chat_id, msg_id, _ in due:
                res = tg_call("deleteMessage", {"chat_id": chat_id, "message_id": msg_id}, bump=False)
                if res is None:   # lỗi mạng -> thử lại sau 30 giây
                    retry.append([chat_id, msg_id, now + 30])
            if retry:
                with _DL_DEL_LOCK:
                    _DL_DEL_QUEUE.extend(retry)
                    _dl_del_save()
            # Dọn file tạm còn sót (quá 15 phút)
            for fp in glob.glob(os.path.join(DL_TMP_DIR, "*")):
                try:
                    if now - os.path.getmtime(fp) > 900:
                        os.remove(fp)
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"Lỗi luồng dọn video: {e}")

def start_dl_sweeper():
    Thread(target=_dl_sweeper_worker, daemon=True).start()
    logging.info("✅ Đã bật tự xóa video tải về sau 3 phút.")

# ---------- Kiểm tra link ----------
def extract_platform_url(text, platform):
    """Lấy link đúng nền tảng trong tin nhắn. Trả None nếu không phải link TikTok/Facebook hợp lệ."""
    domains = DL_PLATFORMS[platform]["domains"]
    for tok in re.split(r"[\s,;]+", (text or "").strip()):
        tok = tok.strip("<>()[]\"'")
        if not tok:
            continue
        cand = tok if re.match(r"^https?://", tok, re.I) else "https://" + tok
        try:
            p = urllib.parse.urlparse(cand)
            host = (p.hostname or "").lower()
        except Exception:
            continue
        if not any(host == d or host.endswith("." + d) for d in domains):
            continue
        if not p.path.strip("/") and not p.query:
            continue   # chỉ là trang chủ, không phải link video
        return cand.rstrip(".,!?)")[:500]
    return None

# ---------- Giao diện ----------
def build_dl_menu():
    text = (
        f"📥 <b>TẢI VIDEO MẠNG XÃ HỘI</b>\n"
        f"════════════════════════════════\n\n"
        f"🎞️ <i>Tải video TikTok / Facebook về Telegram, tự chọn chất lượng HD - Full HD - 4K.</i>\n\n"
        f"🔒 Chỉ tải được video <b>công khai</b>.\n"
        f"⏱️ Video gửi cho bạn sẽ <b>tự động xóa sau 3 phút</b> - hãy lưu về máy ngay.\n\n"
        f"👇 <i>Chọn nền tảng bên dưới:</i>"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 Tải video TikTok", callback_data="dl_start:tt")],
        [InlineKeyboardButton("📘 Tải video Facebook", callback_data="dl_start:fb")],
        [InlineKeyboardButton("📜 Lịch sử tải video", callback_data="dl_history:0")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")],
    ])
    return text, markup

def build_dl_quality_picker(platform, link):
    p = DL_PLATFORMS[platform]
    shown = link if len(link) <= 70 else link[:67] + "..."
    text = (
        f"{p['icon']} <b>TẢI VIDEO {p['name'].upper()}</b>\n"
        f"════════════════════════════════\n"
        f"🔗 <b>Link:</b> <code>{html.escape(shown)}</code>\n\n"
        f"🎞️ <b>Chọn cấu hình / chất lượng muốn tải:</b>\n\n"
        f"ℹ️ <i>Nếu video gốc không có chất lượng cao như bạn chọn, bot sẽ tải chất lượng cao nhất có sẵn. "
        f"Telegram chỉ cho gửi file tối đa 50MB nên nếu video quá nặng bot sẽ tự hạ chất lượng cho vừa.</i>"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(DL_QUALITY_LABELS[480], callback_data="dl_q:480"),
         InlineKeyboardButton(DL_QUALITY_LABELS[720], callback_data="dl_q:720")],
        [InlineKeyboardButton(DL_QUALITY_LABELS[1080], callback_data="dl_q:1080"),
         InlineKeyboardButton(DL_QUALITY_LABELS[2160], callback_data="dl_q:2160")],
        [InlineKeyboardButton("↩️ Đổi link khác", callback_data=f"dl_start:{platform}"),
         InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")],
    ])
    return text, markup

def build_dl_history_view(user_id, page=0):
    items = dl_get_history(user_id)
    total = len(items)
    pages = max(1, (total + DL_HIST_PER_PAGE - 1) // DL_HIST_PER_PAGE)
    page = max(0, min(page, pages - 1))
    keyboard = []
    if total == 0:
        text = (
            f"📜 <b>LỊCH SỬ TẢI VIDEO</b>\n"
            f"════════════════════════════════\n\n"
            f"ℹ️ Bạn chưa tải video nào."
        )
    else:
        text = (
            f"📜 <b>LỊCH SỬ TẢI VIDEO</b> ({total} video)\n"
            f"════════════════════════════════\n"
            f"📄 Trang {page + 1}/{pages}\n"
        )
        start = page * DL_HIST_PER_PAGE
        for i, r in enumerate(items[start:start + DL_HIST_PER_PAGE]):
            n = start + i + 1
            p = DL_PLATFORMS.get(r.get("platform"), {"name": "?", "icon": "🎞️"})
            url = str(r.get("url", ""))
            shown = url if len(url) <= 55 else url[:52] + "..."
            title = str(r.get("title") or "")
            if len(title) > 60:
                title = title[:57] + "..."
            qtxt = f"{r['h']}p" if r.get("h") else f"{r.get('q', '')}p"
            text += (
                f"\n────────────────────────\n"
                f"<b>{n}.</b> {p['icon']} <b>{p['name']}</b> • {qtxt} • 🕒 {_fmt_order_time(r.get('t'))}\n"
                + (f"🎬 {html.escape(title)}\n" if title else "")
                + f"🔗 <a href=\"{html.escape(url, quote=True)}\">{html.escape(shown)}</a>\n"
            )
            keyboard.append([InlineKeyboardButton(f"🔁 Gửi lại video #{n} ({p['name']} {qtxt})", callback_data=f"dl_resend:{r.get('key')}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"dl_history:{page - 1}"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton("Sau ➡️", callback_data=f"dl_history:{page + 1}"))
        if nav:
            keyboard.append(nav)
        text += "\n💡 <i>Bấm \"Gửi lại video\" để bot tải lại và gửi video cho bạn (video cũ đã bị xóa sau 3 phút).</i>"
    keyboard.append([InlineKeyboardButton("📥 Tải video mới", callback_data="dl_menu")])
    keyboard.append([InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
    return text, InlineKeyboardMarkup(keyboard)

async def dl_show(query, context, text, markup):
    """Sửa tin nhắn hiện tại; nếu tin nhắn đang là video/file (không sửa chữ được) thì gửi tin mới."""
    if query.message.text:
        return await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
    return await context.bot.send_message(
        chat_id=query.message.chat_id, text=text, parse_mode="HTML",
        reply_markup=markup, disable_web_page_preview=True
    )

# ---------- Tải video bằng yt-dlp (chạy ở luồng riêng) ----------
class DLError(Exception):
    """Lỗi tải video có nội dung thân thiện để báo cho khách."""

def _human_dl_error(e):
    s = str(e).lower()
    if any(k in s for k in ("private", "login", "log in", "sign in", "cookie", "authentication", "members only", "age")):
        return "🔒 Video riêng tư hoặc yêu cầu đăng nhập nên không tải được. Chỉ tải được video công khai."
    if "unsupported url" in s:
        return "⚠️ Link này không phải link video hợp lệ (có thể là ảnh/bài viết/trang cá nhân)."
    if any(k in s for k in ("not available", "unavailable", "removed", "deleted", "404", "does not exist", "no video", "not found")):
        return "⚠️ Video không tồn tại, đã bị xóa hoặc bị giới hạn khu vực."
    if "ffmpeg" in s:
        return "⚠️ Máy chủ thiếu ffmpeg để ghép video chất lượng cao. Vui lòng chọn chất lượng thấp hơn hoặc báo Admin."
    if any(k in s for k in ("timed out", "timeout", "connection", "network", "resolve")):
        return "⚠️ Lỗi mạng khi tải video, vui lòng thử lại sau ít phút."
    return "⚠️ Không tải được video (link lỗi hoặc nền tảng đang chặn). Vui lòng thử lại sau."

def _dl_opts(q, outtmpl):
    if FFMPEG_PATH:
        fmt = (
            f"bestvideo[height<=?{q}][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"bestvideo[height<=?{q}]+bestaudio/"
            f"best[height<=?{q}]/best"
        )
    else:
        fmt = f"best[height<=?{q}][ext=mp4]/best[height<=?{q}]/best"
    opts = {
        "format": fmt,
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "merge_output_format": "mp4",
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
    }
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH
    if DL_COOKIES_FILE and os.path.exists(DL_COOKIES_FILE):
        opts["cookiefile"] = DL_COOKIES_FILE
    return opts

def _estimate_size(info):
    try:
        rf = info.get("requested_formats")
        if rf:
            return sum(int(f.get("filesize") or f.get("filesize_approx") or 0) for f in rf) or None
        return int(info.get("filesize") or info.get("filesize_approx") or 0) or None
    except Exception:
        return None

def _find_downloaded(job):
    files = [
        f for f in glob.glob(os.path.join(DL_TMP_DIR, job + ".*"))
        if not f.endswith((".part", ".ytdl", ".temp", ".json"))
    ]
    if not files:
        return None
    exact = os.path.join(DL_TMP_DIR, job + ".mp4")
    if exact in files:
        return exact
    return max(files, key=lambda f: os.path.getsize(f))

def _dl_cleanup(job):
    for f in glob.glob(os.path.join(DL_TMP_DIR, job + ".*")):
        try:
            os.remove(f)
        except Exception:
            pass

def _dl_download_inner(url, quality, job):
    if yt_dlp is None:
        raise DLError("⚠️ Hệ thống chưa cài thư viện tải video (yt-dlp). Vui lòng liên hệ Admin.")
    os.makedirs(DL_TMP_DIR, exist_ok=True)
    outtmpl = os.path.join(DL_TMP_DIR, job + ".%(ext)s")
    chain = [q for q in DL_QUALITY_CHAIN if q <= quality] or [DL_QUALITY_CHAIN[-1]]
    last_fid = None
    biggest = 0
    for q in chain:
        try:
            with yt_dlp.YoutubeDL(_dl_opts(q, outtmpl)) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and info.get("entries"):
                    entries = [e for e in info["entries"] if e]
                    if not entries:
                        raise DLError("⚠️ Không tìm thấy video trong link này.")
                    info = entries[0]
                if not info:
                    raise DLError("⚠️ Không lấy được thông tin video từ link này.")
                dur = info.get("duration")
                if dur and dur > DL_MAX_DURATION:
                    raise DLError(f"⚠️ Video quá dài (tối đa {DL_MAX_DURATION // 60} phút).")
                est = _estimate_size(info)
                fid = info.get("format_id")
                if est and est > TG_UPLOAD_LIMIT:
                    biggest = max(biggest, est)
                    if fid is not None and fid == last_fid:
                        break   # hạ chất lượng cũng ra đúng định dạng này -> không còn cách nhỏ hơn
                    last_fid = fid
                    continue
                ydl.extract_info(url, download=True)
        except DLError:
            raise
        except Exception as e:
            logging.error(f"yt-dlp lỗi ({url[:80]}): {e}")
            raise DLError(_human_dl_error(e))

        path = _find_downloaded(job)
        if not path:
            raise DLError("⚠️ Không tải được file video, vui lòng thử lại.")
        size = os.path.getsize(path)
        if size > TG_UPLOAD_LIMIT:
            biggest = max(biggest, size)
            _dl_cleanup(job)
            last_fid = None
            continue
        return {
            "job": job,
            "path": path,
            "title": str(info.get("title") or "Video")[:100],
            "height": info.get("height"),
            "width": info.get("width"),
            "duration": info.get("duration"),
            "size": size,
            "requested": quality,
            "downgraded": q != quality,
        }
    mb = f" (~{biggest / 1024 / 1024:.0f}MB)" if biggest else ""
    raise DLError(f"⚠️ Video quá nặng{mb}, vượt giới hạn 50MB của Telegram ngay cả ở chất lượng thấp nhất nên không gửi được.")

def dl_download_sync(url, quality):
    job = uuid.uuid4().hex[:10]
    try:
        return _dl_download_inner(url, quality, job)
    except BaseException:
        _dl_cleanup(job)
        raise

# ---------- Chạy 1 lượt tải (nền, không chặn bot) ----------
_DL_TASKS = set()
_DL_SEM = None

def _dl_sem():
    global _DL_SEM
    if _DL_SEM is None:
        _DL_SEM = asyncio.Semaphore(DL_MAX_PARALLEL)
    return _DL_SEM

async def _dl_edit(bot, chat_id, msg_id, text, markup=None):
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=text,
            parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )
    except Exception:
        pass

async def dl_run_job(bot, busy, chat_id, status_msg_id, user_id, url, platform, quality):
    p = DL_PLATFORMS[platform]
    fail_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Chọn chất lượng khác", callback_data="dl_pick")],
        [InlineKeyboardButton("📥 Menu tải video", callback_data="dl_menu"),
         InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")],
    ])
    result = None
    try:
        sem = _dl_sem()
        if sem.locked():
            await _dl_edit(bot, chat_id, status_msg_id, "⏳ <b>Hệ thống đang bận, bạn đang trong hàng chờ...</b>\n<i>Video sẽ tự động được tải khi tới lượt.</i>")
        async with sem:
            await _dl_edit(
                bot, chat_id, status_msg_id,
                f"⬇️ <b>Đang tải video {p['name']} ({DL_QUALITY_LABELS.get(quality, str(quality) + 'p')})...</b>\n"
                f"<i>Quá trình có thể mất 10 - 60 giây, vui lòng chờ.</i>"
            )
            try:
                result = await asyncio.to_thread(dl_download_sync, url, quality)
            except DLError as e:
                await _dl_edit(bot, chat_id, status_msg_id, f"❌ <b>TẢI VIDEO THẤT BẠI</b>\n\n{html.escape(str(e))}", fail_markup)
                return
            except Exception as e:
                logging.error(f"Lỗi tải video: {e}")
                await _dl_edit(bot, chat_id, status_msg_id, "❌ <b>TẢI VIDEO THẤT BẠI</b>\n\n⚠️ Có lỗi hệ thống, vui lòng thử lại sau.", fail_markup)
                return

        await _dl_edit(bot, chat_id, status_msg_id, "📤 <b>Đang gửi video cho bạn...</b>")

        h = result.get("height")
        note = ""
        if result.get("downgraded"):
            note = f" <i>(tự hạ từ {result['requested']}p vì file vượt 50MB)</i>"
        elif h and h < result["requested"]:
            note = " <i>(cao nhất của video gốc)</i>"
        caption = (
            f"✅ <b>TẢI VIDEO THÀNH CÔNG!</b>\n"
            f"{p['icon']} <b>Nền tảng:</b> {p['name']}\n"
            f"🎞️ <b>Chất lượng:</b> {str(int(h)) + 'p' if h else 'mặc định'}{note}\n"
            f"📦 <b>Dung lượng:</b> {result['size'] / 1024 / 1024:.1f} MB\n"
            f"🎬 {html.escape(result['title'][:80])}\n\n"
            f"⏱️ <i>Video sẽ tự động xóa sau 3 phút - hãy lưu về máy ngay!</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Lịch sử tải video", callback_data="dl_history:0")],
            [InlineKeyboardButton("📥 Tải video khác", callback_data="dl_menu"),
             InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")],
        ])
        common = dict(
            chat_id=chat_id, caption=caption, parse_mode="HTML", reply_markup=markup,
            read_timeout=180, write_timeout=180, connect_timeout=30, pool_timeout=30
        )
        sent = None
        try:
            with open(result["path"], "rb") as f:
                sent = await bot.send_video(
                    video=f, supports_streaming=True,
                    width=int(result["width"]) if result.get("width") else None,
                    height=int(h) if h else None,
                    duration=int(result["duration"]) if result.get("duration") else None,
                    **common
                )
        except Exception as e:
            logging.error(f"Gửi video lỗi, thử gửi dạng file: {e}")
            try:
                with open(result["path"], "rb") as f:
                    sent = await bot.send_document(
                        document=f, filename=os.path.basename(result["path"]), **common
                    )
            except Exception as e2:
                logging.error(f"Gửi file video lỗi: {e2}")

        if not sent:
            await _dl_edit(bot, chat_id, status_msg_id, "❌ <b>Không gửi được video lên Telegram.</b>\n\n⚠️ Vui lòng thử lại hoặc chọn chất lượng thấp hơn.", fail_markup)
            return

        dl_schedule_delete(chat_id, sent.message_id)
        dl_add_history(user_id, platform, url, quality, h, result["title"])
        try:
            await bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
        except Exception:
            pass
    except Exception as e:
        logging.error(f"Lỗi không mong muốn khi tải video: {e}", exc_info=True)
        await _dl_edit(bot, chat_id, status_msg_id, "❌ <b>TẢI VIDEO THẤT BẠI</b>\n\n⚠️ Có lỗi hệ thống, vui lòng thử lại sau.", fail_markup)
    finally:
        busy.discard(user_id)
        if result:
            _dl_cleanup(result["job"])

def dl_try_launch(context, chat_id, msg_id, user_id, url, platform, quality):
    """Bắt đầu tải ở nền. Trả False nếu khách đang có 1 video khác được xử lý."""
    busy = context.bot_data.setdefault("dl_busy", set())
    if user_id in busy:
        return False
    busy.add(user_id)
    task = asyncio.create_task(dl_run_job(context.bot, busy, chat_id, msg_id, user_id, url, platform, quality))
    _DL_TASKS.add(task)
    task.add_done_callback(_DL_TASKS.discard)
    return True

async def receive_dl_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Khách gửi link TikTok/Facebook -> kiểm tra đúng nền tảng -> hiện bảng chọn chất lượng."""
    chat_id = update.effective_chat.id
    raw = update.message.text or ""
    platform = context.user_data.get("dl_platform")

    try:
        await update.message.delete()
    except Exception:
        pass
    bot_msg_id = context.user_data.get("prompt_msg_id")
    if bot_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=bot_msg_id)
        except Exception:
            pass

    if platform not in DL_PLATFORMS:
        text, markup = build_dl_menu()
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup)
        return ConversationHandler.END

    p = DL_PLATFORMS[platform]
    url = extract_platform_url(raw, platform)
    if not url:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ <b>LINK KHÔNG HỢP LỆ!</b>\n\n"
                f"Bạn đang ở mục tải video <b>{p['name']}</b> nên phải gửi đúng link {p['name']}.\n"
                f"📌 <i>Ví dụ:</i> <code>{html.escape(p['example'])}</code>\n\n"
                f"💬 <i>Vui lòng gửi lại link:</i>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Trở về", callback_data="dl_menu"),
                InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
            ]])
        )
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_DL_LINK

    context.user_data["dl_link"] = url
    text, markup = build_dl_quality_picker(platform, url)
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
    return ConversationHandler.END

# ==================== HẾT PHẦN TẢI VIDEO MXH ====================

'''

HANDLERS = r'''    # ---------- TẢI VIDEO MXH (TikTok / Facebook) ----------
    elif data == "dl_menu":
        context.user_data.pop("dl_link", None)
        text, markup = build_dl_menu()
        await dl_show(query, context, text, markup)

    elif data.startswith("dl_start:"):
        platform = data.split(":", 1)[1]
        if platform not in DL_PLATFORMS:
            return
        pinfo = DL_PLATFORMS[platform]
        context.user_data["dl_platform"] = platform
        context.user_data.pop("dl_link", None)
        text = (
            f"{pinfo['icon']} <b>TẢI VIDEO {pinfo['name'].upper()}</b>\n"
            f"════════════════════════════════\n\n"
            f"🔗 Vui lòng gửi <b>link video {pinfo['name']}</b> (đúng link {pinfo['name']} mới tải được).\n"
            f"📌 <i>Ví dụ:</i> <code>{html.escape(pinfo['example'])}</code>\n\n"
            f"💬 <i>Gửi link của bạn vào đây:</i>"
        )
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Trở về", callback_data="dl_menu"),
            InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
        ]])
        msg = await dl_show(query, context, text, markup)
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_DL_LINK

    elif data == "dl_pick":
        link = context.user_data.get("dl_link")
        platform = context.user_data.get("dl_platform")
        if not link or platform not in DL_PLATFORMS:
            text, markup = build_dl_menu()
            await dl_show(query, context, text, markup)
            return
        text, markup = build_dl_quality_picker(platform, link)
        await dl_show(query, context, text, markup)

    elif data.startswith("dl_q:"):
        try:
            quality = int(data.split(":", 1)[1])
        except ValueError:
            return
        if quality not in DL_QUALITY_LABELS:
            return
        link = context.user_data.get("dl_link")
        platform = context.user_data.get("dl_platform")
        if not link or platform not in DL_PLATFORMS:
            await dl_show(
                query, context, "⚠️ Phiên tải video đã hết hạn, vui lòng chọn lại.",
                InlineKeyboardMarkup([[InlineKeyboardButton("📥 Menu tải video", callback_data="dl_menu")]])
            )
            return
        if not dl_try_launch(context, query.message.chat_id, query.message.message_id, user.id, link, platform, quality):
            await query.answer("⏳ Bạn đang có 1 video đang được xử lý, vui lòng chờ xong nhé!", show_alert=True)

    elif data.startswith("dl_history"):
        try:
            page = int(data.split(":")[1]) if ":" in data else 0
        except ValueError:
            page = 0
        text, markup = build_dl_history_view(user.id, page)
        await dl_show(query, context, text, markup)

    elif data.startswith("dl_resend:"):
        key = data.split(":", 1)[1]
        rec = next((r for r in dl_get_history(user.id) if r.get("key") == key), None)
        if not rec or rec.get("platform") not in DL_PLATFORMS:
            await query.answer("⚠️ Không tìm thấy video này trong lịch sử!", show_alert=True)
            return
        context.user_data["dl_link"] = rec["url"]
        context.user_data["dl_platform"] = rec["platform"]
        if not dl_try_launch(context, query.message.chat_id, query.message.message_id, user.id, rec["url"], rec["platform"], int(rec.get("q") or 720)):
            await query.answer("⏳ Bạn đang có 1 video đang được xử lý, vui lòng chờ xong nhé!", show_alert=True)

'''

def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"❌ Không tìm thấy đúng 1 vị trí để chèn [{label}] (tìm thấy {n}). File bot khác bản mình đã đọc - hãy gửi lại file cho mình.")
    return src.replace(old, new)

def main():
    if len(sys.argv) < 2:
        sys.exit("Dùng: python patch_video_dl.py ten_file_bot.py")
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        src = f.read().replace("\r\n", "\n")
    if "TẢI VIDEO MẠNG XÃ HỘI" in src:
        sys.exit("ℹ️ File này đã được tích hợp tính năng tải video rồi, không cần chạy lại.")

    src = sub(src,
        'ORDERS_FILE = os.path.join(DB_DIR, "orders_db.json")',
        'DL_FILE = os.path.join(DB_DIR, "dl_history.json")           # lịch sử tải video MXH\nORDERS_FILE = os.path.join(DB_DIR, "orders_db.json")',
        "đường dẫn file lịch sử")

    src = sub(src,
        "    return [DB_FILE, GITCODE_DB_FILE, SMS_DB_FILE, SEPAY_TX_FILE, PROMO_FILE, PENDING_FILE, ORDERS_FILE]",
        "    return [DB_FILE, GITCODE_DB_FILE, SMS_DB_FILE, SEPAY_TX_FILE, PROMO_FILE, PENDING_FILE, ORDERS_FILE, DL_FILE]",
        "danh sách file backup")

    src = sub(src,
        "            elif base == os.path.basename(ORDERS_FILE):\n                ORDERS_DB.clear(); ORDERS_DB.update(obj)\n",
        "            elif base == os.path.basename(ORDERS_FILE):\n                ORDERS_DB.clear(); ORDERS_DB.update(obj)\n"
        "            elif base == os.path.basename(DL_FILE):\n                DL_DB.clear(); DL_DB.update(obj)\n                if not isinstance(DL_DB.get(\"hist\"), dict):\n                    DL_DB[\"hist\"] = {}\n",
        "khôi phục backup")

    src = sub(src,
        "    INPUT_BULK_TOPUP\n) = range(16)",
        "    INPUT_BULK_TOPUP, INPUT_DL_LINK\n) = range(17)",
        "trạng thái hội thoại")

    src = sub(src,
        '        [InlineKeyboardButton("🤖 TẠO BOT TELE", callback_data="create_bot_tele_menu")],\n',
        '        [InlineKeyboardButton("🤖 TẠO BOT TELE", callback_data="create_bot_tele_menu")],\n'
        '        [InlineKeyboardButton("📥 TẢI VIDEO MXH", callback_data="dl_menu")],\n',
        "nút ở menu chính")

    src = sub(src,
        "async def _button_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):",
        BLOCK + "async def _button_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):",
        "khối chức năng")

    src = sub(src,
        '    elif data == "create_bot_tele_menu":',
        HANDLERS + '    elif data == "create_bot_tele_menu":',
        "xử lý nút bấm")

    src = sub(src,
        '    "delete_gc:", "group_detail_", "buy_group_now:", "admin_panel", "subcat_",',
        '    "delete_gc:", "group_detail_", "buy_group_now:", "admin_panel", "subcat_", "dl_q:", "dl_resend:",',
        "danh sách nút có cảnh báo")

    src = sub(src,
        '    elif data == "menu_main":\n        text, reply_markup = main_menu_keyboard(user.id, user.username, user.first_name)\n        if query.message.photo or query.message.video:',
        '    elif data == "menu_main":\n        text, reply_markup = main_menu_keyboard(user.id, user.username, user.first_name)\n        if query.message.photo or query.message.video or query.message.document:',
        "nút về menu chính khi đang ở tin nhắn video")

    src = sub(src,
        "            INPUT_BULK_TOPUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bulk_topup_handler)],\n",
        "            INPUT_BULK_TOPUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bulk_topup_handler)],\n"
        "            INPUT_DL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_dl_link_handler)],\n",
        "đăng ký trạng thái nhập link")

    src = sub(src,
        "    start_tg_backup_worker()\n    keep_alive()",
        "    start_tg_backup_worker()\n    start_dl_sweeper()\n    keep_alive()",
        "khởi động luồng dọn video")

    compile(src, path, "exec")   # kiểm tra cú pháp trước khi ghi
    shutil.copy2(path, path + ".bak")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("✅ Tích hợp xong! Đã lưu bản cũ:", path + ".bak")
    print("👉 Nhớ thêm vào requirements.txt:  yt-dlp  và  imageio-ffmpeg")

main()
