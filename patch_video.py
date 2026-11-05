#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vá tự động: thêm menu "TẢI VIDEO MXH" (TikTok + Facebook) vào bot.
Cách dùng:   python patch_video.py ten_file_bot.py
Script sẽ tự tạo bản sao lưu <file>.bak rồi ghi đè file bot đã thêm tính năng.
"""
import sys, shutil, py_compile, os

BLOCK = r'''# ==================== TẢI VIDEO MẠNG XÃ HỘI (TIKTOK / FACEBOOK) ====================
# - TikTok: dùng API tikwm (không logo), nếu lỗi thì tự chuyển sang yt-dlp
# - Facebook: dùng yt-dlp (cần thêm "yt-dlp" vào requirements.txt)
# - Video gửi cho khách tự xóa sau 3 phút (có đếm ngược), link lưu vào lịch sử để gửi lại
VD_DELETE_SECONDS = 180
VD_MAX_BYTES = 49 * 1024 * 1024          # Telegram bot chỉ gửi được file tối đa ~50MB
VD_MAX_HISTORY = 30                       # số link lưu trong lịch sử mỗi khách
VD_HIST_PER_PAGE = 5
VD_TMP_DIR = os.path.join(tempfile.gettempdir(), "smm_bot_videos")
VD_DEL_FILE = os.path.join(DB_DIR, "vd_delete.json")
VD_SEM = threading.Semaphore(3)           # tối đa 3 video tải cùng lúc (tránh tràn RAM Render)
VD_BUSY = set()                           # khách đang có 1 video được xử lý
VD_PLATFORMS = {
    "tt": {"name": "TikTok", "icon": "🎵"},
    "fb": {"name": "Facebook", "icon": "📘"},
}
_VD_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
try:
    os.makedirs(VD_TMP_DIR, exist_ok=True)
except Exception:
    pass

class VideoTooBig(Exception):
    pass

# ---------- Kiểm tra link ----------
_VD_URL_RE = re.compile(r'https?://[^\s<>"\']+', re.I)
_VD_TT_HOST_RE = re.compile(r'^https?://(?:[a-z0-9-]+\.)*tiktok\.com(?=[/?#]|$)', re.I)
_VD_FB_HOST_RE = re.compile(r'^https?://(?:[a-z0-9-]+\.)*(?:facebook\.com|fb\.com|fb\.watch)(?=[/?#]|$)', re.I)
_VD_TT_SHORT_RE = re.compile(r'^https?://(?:vm|vt|vn|v)\.tiktok\.com', re.I)

def validate_video_link(plat, text):
    """Trả về (url, None) nếu link đúng, hoặc (None, mã_lỗi)."""
    m = _VD_URL_RE.search(text or "")
    if not m:
        return None, "no_url"
    url = m.group(0).rstrip(".,;)]}")
    if plat == "tt":
        hm = _VD_TT_HOST_RE.match(url)
        if not hm:
            return None, "bad_host"
        rest = url[hm.end():]
        if _VD_TT_SHORT_RE.match(url):
            if len(rest.split("?")[0].strip("/")) < 3:
                return None, "not_video"
        else:
            low = rest.lower()
            if not any(k in low for k in ("/video/", "/photo/", "/t/", "/v/")):
                return None, "not_video"
        return url, None
    if plat == "fb":
        hm = _VD_FB_HOST_RE.match(url)
        if not hm:
            return None, "bad_host"
        rest = url[hm.end():]
        if len(rest.split("#")[0].strip("/")) < 2:
            return None, "not_video"
        return url, None
    return None, "bad_host"

# ---------- Tải video ----------
def _vd_rm(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def _cleanup_video_files(path):
    """Xóa file video tạm (và các file cùng tên gốc)."""
    if not path:
        return
    base = os.path.splitext(path)[0]
    for f in glob.glob(base + ".*"):
        _vd_rm(f)
    _vd_rm(path)

def _vd_stream_to_file(url, path, headers=None):
    with requests.get(url, stream=True, timeout=(10, 40), headers=headers or _VD_UA) as r:
        r.raise_for_status()
        cl = int(r.headers.get("Content-Length") or 0)
        if cl > VD_MAX_BYTES:
            raise VideoTooBig()
        size = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > VD_MAX_BYTES:
                    raise VideoTooBig()
                f.write(chunk)
    if size < 10 * 1024:
        raise RuntimeError("file quá nhỏ, không phải video")

def _vd_tiktok_tikwm(url, path):
    r = requests.post("https://www.tikwm.com/api/", data={"url": url, "hd": 1}, headers=_VD_UA, timeout=25)
    j = r.json()
    if j.get("code") != 0 or not j.get("data"):
        raise RuntimeError(f"tikwm: {j.get('msg')}")
    d = j["data"]
    cands = []
    for c in (d.get("hdplay"), d.get("play")):
        if c:
            cands.append("https://www.tikwm.com" + c if c.startswith("/") else c)
    if not cands:
        raise RuntimeError("tikwm: không có link video (có thể là bài ảnh)")
    last_err = None
    for c in cands:
        try:
            _vd_stream_to_file(c, path)
            return d.get("title") or ""
        except VideoTooBig as e:
            last_err = e          # thử bản nhẹ hơn
        except Exception as e:
            last_err = e
    raise last_err

def _vd_ytdlp_fetch(url, base):
    import yt_dlp  # ImportError nếu chưa cài
    fmt = ("best[ext=mp4][filesize<48M]/best[ext=mp4][filesize_approx<48M]/"
           "best[filesize<48M]/best[ext=mp4]/best")
    opts = {
        "outtmpl": base + ".%(ext)s",
        "format": fmt,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 25,
        "retries": 2,
        "max_filesize": VD_MAX_BYTES,
        "http_headers": _VD_UA,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if info and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else None
    if not info:
        raise RuntimeError("yt-dlp không lấy được thông tin video")
    files = [f for f in glob.glob(base + ".*") if not f.endswith((".part", ".ytdl", ".tmp"))]
    if not files:
        raise VideoTooBig()       # bị bỏ qua vì vượt max_filesize
    return max(files, key=os.path.getsize), (info.get("title") or "")

def download_video_sync(plat, url):
    """Chạy ở luồng riêng. Trả {'ok': True, 'path', 'title'} hoặc {'ok': False, 'error': mã}."""
    base = os.path.join(VD_TMP_DIR, uuid.uuid4().hex)
    code = "fail"
    with VD_SEM:
        path, title = None, ""
        try:
            if plat == "tt":
                try:
                    path = base + ".mp4"
                    title = _vd_tiktok_tikwm(url, path)
                except VideoTooBig:
                    raise
                except Exception as e:
                    logging.warning(f"tikwm lỗi, chuyển sang yt-dlp: {e}")
                    _vd_rm(path)
                    path = None
            if not path:
                path, title = _vd_ytdlp_fetch(url, base)
            if os.path.getsize(path) > VD_MAX_BYTES:
                raise VideoTooBig()
            return {"ok": True, "path": path, "title": title}
        except VideoTooBig:
            code = "too_big"
        except ImportError:
            code = "no_ytdlp"
            logging.error("❌ Chưa cài yt-dlp: thêm 'yt-dlp' vào requirements.txt")
        except Exception as e:
            code = "fail"
            logging.error(f"❌ Lỗi tải video {plat} {url[:80]}: {type(e).__name__}: {str(e)[:300]}")
        _cleanup_video_files(path or (base + ".mp4"))
        for f in glob.glob(base + ".*"):
            _vd_rm(f)
    return {"ok": False, "error": code}

VD_ERRORS = {
    "too_big": "⚠️ Video quá nặng (trên 50MB) nên Telegram không cho bot gửi. Hãy thử video ngắn hơn.",
    "no_ytdlp": "⚠️ Hệ thống chưa sẵn sàng tải video Facebook, vui lòng liên hệ Admin.",
    "fail": "⚠️ Không tải được video này. Có thể video để riêng tư, đã bị xóa hoặc link không phải video. "
            "Hãy kiểm tra video đang để <b>công khai</b> rồi thử lại.",
    "send": "⚠️ Tải được video nhưng gửi lên Telegram thất bại, vui lòng thử lại.",
}

# ---------- Tự động xóa video sau 3 phút (lưu file để bot khởi động lại vẫn xóa tiếp) ----------
def _vd_del_load():
    try:
        with open(VD_DEL_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

VD_DEL_QUEUE = _vd_del_load()
VD_DEL_LOCK = threading.Lock()

def _vd_del_save():
    try:
        with VD_DEL_LOCK:
            snap = dict(VD_DEL_QUEUE)
        atomic_json_dump(VD_DEL_FILE, snap)
    except Exception as e:
        logging.error(f"Lỗi lưu hàng đợi xóa video: {e}")

def schedule_video_delete(chat_id, message_id, base_caption, seconds=VD_DELETE_SECONDS):
    with VD_DEL_LOCK:
        VD_DEL_QUEUE[f"{chat_id}:{message_id}"] = {
            "chat_id": chat_id, "message_id": message_id,
            "deadline": time.time() + seconds, "caption": base_caption,
        }
    _vd_del_save()

def _vd_delete_worker():
    tick = 0
    while True:
        time.sleep(5)
        tick += 1
        try:
            now = time.time()
            with VD_DEL_LOCK:
                items = list(VD_DEL_QUEUE.items())
            changed = False
            for key, e in items:
                remaining = e["deadline"] - now
                if remaining <= 0:
                    tg_call("deleteMessage", {"chat_id": e["chat_id"], "message_id": e["message_id"]}, bump=False)
                    with VD_DEL_LOCK:
                        VD_DEL_QUEUE.pop(key, None)
                    changed = True
                    continue
                for p in (120, 60):
                    if remaining <= p and not e.get(f"e{p}"):
                        e[f"e{p}"] = True
                        tg_call("editMessageCaption", {
                            "chat_id": e["chat_id"], "message_id": e["message_id"],
                            "caption": f"{e['caption']}\n\n⏱️ <i>Video sẽ tự động xóa sau {p}s...</i>",
                            "parse_mode": "HTML",
                        }, bump=False)
                        changed = True
                        break
            if changed:
                _vd_del_save()
            # Dọn file tạm sót lại (quá 15 phút) mỗi ~1 phút
            if tick % 12 == 0:
                for f in glob.glob(os.path.join(VD_TMP_DIR, "*")):
                    try:
                        if now - os.path.getmtime(f) > 900:
                            os.remove(f)
                    except Exception:
                        pass
        except Exception as e:
            logging.error(f"Lỗi luồng xóa video: {e}")

def start_video_delete_worker():
    Thread(target=_vd_delete_worker, daemon=True).start()
    logging.info("✅ Đã bật tính năng tải video MXH (tự xóa video sau 3 phút).")

# ---------- Lịch sử tải video ----------
def add_video_history(user_id, plat, url, title, file_id, ftype):
    with DB_LOCK:
        d = get_user_data(user_id)
        h = d.setdefault("video_history", [])
        old = next((x for x in h if x.get("platform") == plat and x.get("url") == url), None)
        vid = old["id"] if old else uuid.uuid4().hex[:8]
        if old:
            h.remove(old)
        h.append({
            "id": vid, "platform": plat, "url": url, "title": (title or "")[:150],
            "file_id": file_id, "ftype": ftype, "time": int(time.time()),
        })
        del h[:-VD_MAX_HISTORY]
        save_users_db()

def build_video_menu():
    text = (
        f"📥 <b>TẢI VIDEO MẠNG XÃ HỘI</b>\n"
        f"════════════════════════════════\n\n"
        f"🎵 <b>TikTok</b> — tải video không logo\n"
        f"📘 <b>Facebook</b> — tải video / reels công khai\n\n"
        f"⏱️ <i>Video gửi cho bạn sẽ tự động xóa sau {VD_DELETE_SECONDS // 60} phút, nhớ lưu về máy.</i>\n"
        f"📜 <i>Link đã tải được lưu trong lịch sử, bấm gửi lại video bất cứ lúc nào.</i>\n\n"
        f"👇 <i>Chọn nền tảng:</i>"
    )
    keyboard = [
        [InlineKeyboardButton("🎵 Tải Video TikTok", callback_data="vd_tt")],
        [InlineKeyboardButton("📘 Tải Video Facebook", callback_data="vd_fb")],
        [InlineKeyboardButton("📜 Lịch Sử Tải Video", callback_data="vd_hist:0")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")],
    ]
    return text, InlineKeyboardMarkup(keyboard)

def build_video_prompt(plat, error_text=""):
    info = VD_PLATFORMS[plat]
    if plat == "tt":
        example = "https://www.tiktok.com/@user/video/123...\nhoặc https://vt.tiktok.com/ZSxxxxxx/"
    else:
        example = "https://www.facebook.com/reel/123...\nhoặc https://fb.watch/xxxxxx/"
    text = (
        f"{error_text}"
        f"{info['icon']} <b>TẢI VIDEO {info['name'].upper()}</b>\n"
        f"════════════════════════════════\n\n"
        f"🔗 Gửi <b>link video {info['name']}</b> vào đây, bot sẽ tải và gửi video lại cho bạn.\n\n"
        f"📌 <i>Ví dụ:</i>\n<code>{example}</code>\n\n"
        f"💬 <i>Gửi link của bạn:</i>"
    )
    keyboard = [
        [InlineKeyboardButton("↩️ Menu Tải Video", callback_data="vd_menu")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")],
    ]
    return text, InlineKeyboardMarkup(keyboard)

def build_video_history_view(user_id, page=0):
    hist = list(reversed(get_user_data(user_id).get("video_history", [])))
    total = len(hist)
    pages = max(1, (total + VD_HIST_PER_PAGE - 1) // VD_HIST_PER_PAGE)
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
            f"📜 <b>LỊCH SỬ TẢI VIDEO</b> ({total} link)\n"
            f"════════════════════════════════\n"
            f"📄 Trang {page + 1}/{pages}\n"
        )
        start = page * VD_HIST_PER_PAGE
        for n, e in enumerate(hist[start:start + VD_HIST_PER_PAGE], start=start + 1):
            info = VD_PLATFORMS.get(e.get("platform"), {"name": "?", "icon": "🎬"})
            link = str(e.get("url", ""))
            if len(link) > 80:
                link = link[:77] + "..."
            title = f"\n📝 {html.escape(str(e.get('title')))[:80]}" if e.get("title") else ""
            text += (
                f"\n────────────────────────\n"
                f"<b>{n}.</b> {info['icon']} <b>{info['name']}</b> | 🕒 {_fmt_order_time(e.get('time'))}"
                f"{title}\n"
                f"🔗 <code>{html.escape(link)}</code>\n"
            )
            keyboard.append([InlineKeyboardButton(f"🔁 Gửi lại video #{n}", callback_data=f"vd_re:{e['id']}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"vd_hist:{page - 1}"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton("Sau ➡️", callback_data=f"vd_hist:{page + 1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🗑️ Xóa lịch sử", callback_data="vd_clear")])
    keyboard.append([InlineKeyboardButton("↩️ Menu Tải Video", callback_data="vd_menu"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
    return text, InlineKeyboardMarkup(keyboard)

# ---------- Gửi video cho khách ----------
def _vd_caption_base(plat, title):
    info = VD_PLATFORMS[plat]
    cap = f"{info['icon']} <b>VIDEO {info['name'].upper()}</b>"
    t = (title or "").strip()[:150]
    if t:
        cap += f"\n📝 {html.escape(t)}"
    return cap

async def _vd_send_media(context, chat_id, media, caption, from_file, ftype="video"):
    common = dict(chat_id=chat_id, caption=caption, parse_mode="HTML",
                  read_timeout=180, write_timeout=180, connect_timeout=30, pool_timeout=30)
    if not from_file:
        if ftype == "document":
            return await context.bot.send_document(document=media, **common)
        return await context.bot.send_video(video=media, supports_streaming=True, **common)
    try:
        with open(media, "rb") as f:
            return await context.bot.send_video(video=f, supports_streaming=True, **common)
    except BadRequest as e:
        logging.warning(f"send_video lỗi ({e}), gửi dạng file...")
    with open(media, "rb") as f:
        return await context.bot.send_document(document=f, **common)

def _vd_result_keyboard(plat):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{VD_PLATFORMS[plat]['icon']} Tải video khác", callback_data=f"vd_{plat}")],
        [InlineKeyboardButton("📜 Lịch sử tải video", callback_data="vd_hist:0")],
        [InlineKeyboardButton("↩️ Menu Tải Video", callback_data="vd_menu"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")],
    ])

async def deliver_video(context, chat_id, user_id, plat, url, title="", entry=None, progress=None):
    """Tải (hoặc dùng lại file đã gửi trước đó) rồi gửi video cho khách.
    progress: tin nhắn 'đang tải...' (khi tải mới). entry: bản ghi lịch sử (khi gửi lại)."""
    if user_id in VD_BUSY:
        return False
    VD_BUSY.add(user_id)
    path = None

    async def fail(code):
        text = f"❌ <b>TẢI VIDEO THẤT BẠI!</b>\n\n{VD_ERRORS.get(code, VD_ERRORS['fail'])}"
        if progress is not None:
            try:
                await progress.edit_text(text, parse_mode="HTML", reply_markup=_vd_result_keyboard(plat))
                return
            except Exception:
                pass
        await asyncio.to_thread(send_auto_delete_message, chat_id, text, 15)

    try:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
        except Exception:
            pass

        sent, used_cached = None, False
        if entry and entry.get("file_id"):
            base = _vd_caption_base(plat, title)
            try:
                sent = await _vd_send_media(
                    context, chat_id, entry["file_id"],
                    f"{base}\n\n⏱️ <i>Video sẽ tự động xóa sau {VD_DELETE_SECONDS // 60} phút, hãy lưu về máy!</i>",
                    False, entry.get("ftype", "video"))
                used_cached = True
            except Exception as e:
                logging.warning(f"Gửi lại bằng file_id lỗi, tải lại video: {e}")
                sent = None

        if sent is None:
            res = await asyncio.to_thread(download_video_sync, plat, url)
            if not res["ok"]:
                await fail(res.get("error", "fail"))
                return False
            path = res["path"]
            title = res.get("title") or title
            base = _vd_caption_base(plat, title)
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
            except Exception:
                pass
            try:
                sent = await _vd_send_media(
                    context, chat_id, path,
                    f"{base}\n\n⏱️ <i>Video sẽ tự động xóa sau {VD_DELETE_SECONDS // 60} phút, hãy lưu về máy!</i>",
                    True)
            except Exception as e:
                logging.error(f"❌ Gửi video cho {chat_id} lỗi: {e}")
                await fail("send")
                return False

        schedule_video_delete(chat_id, sent.message_id, base)

        if not used_cached:
            if sent.video:
                fid, ftype = sent.video.file_id, "video"
            elif sent.document:
                fid, ftype = sent.document.file_id, "document"
            else:
                fid, ftype = None, "video"
            add_video_history(user_id, plat, url, title, fid, ftype)

        if progress is not None:
            try:
                await progress.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ <b>ĐÃ GỬI VIDEO {VD_PLATFORMS[plat]['name'].upper()}!</b>\n\n"
                    f"⏱️ Video ở trên sẽ <b>tự động xóa sau {VD_DELETE_SECONDS // 60} phút</b>, hãy lưu về máy.\n"
                    f"📜 Link đã được lưu vào lịch sử, bấm <b>Gửi lại</b> nếu cần xem lại."
                ),
                parse_mode="HTML", reply_markup=_vd_result_keyboard(plat)
            )
        return True
    finally:
        VD_BUSY.discard(user_id)
        _cleanup_video_files(path)

async def receive_video_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw = (update.message.text or "").strip()
    plat = context.user_data.get("vd_platform")

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

    if plat not in VD_PLATFORMS:
        await update.message.reply_text(
            "⚠️ Phiên tải video đã hết hạn, vui lòng chọn lại nền tảng.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📥 Menu Tải Video", callback_data="vd_menu")]])
        )
        return ConversationHandler.END

    url, err = validate_video_link(plat, raw)
    if err:
        name = VD_PLATFORMS[plat]["name"]
        if err == "not_video":
            reason = f"Đây chưa phải link <b>video</b> {name} (link trang cá nhân / trang chủ không tải được)."
        else:
            reason = f"Link bạn gửi <b>không phải link {name}</b>."
        text, markup = build_video_prompt(plat, f"⚠️ <b>Link không hợp lệ!</b>\n{reason}\nVui lòng gửi đúng link {name}.\n\n")
        msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_VIDEO_LINK

    if user.id in VD_BUSY:
        await asyncio.to_thread(send_auto_delete_message, update.effective_chat.id,
                                "⏳ Bạn đang có 1 video được xử lý, vui lòng chờ xong rồi gửi link tiếp.", 10)
        text, markup = build_video_prompt(plat)
        msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_VIDEO_LINK

    progress = await update.message.reply_text(
        f"⏳ <b>Đang tải video {VD_PLATFORMS[plat]['name']}, vui lòng chờ vài giây...</b>", parse_mode="HTML"
    )
    await deliver_video(context, update.effective_chat.id, user.id, plat, url, progress=progress)
    return ConversationHandler.END

'''

BRANCHES = r'''    # ==================== TẢI VIDEO MXH (TIKTOK / FACEBOOK) ====================
    elif data == "vd_menu":
        context.user_data.pop("vd_platform", None)
        text, markup = build_video_menu()
        await query_edit_or_replace_admin(update, context, text=text, parse_mode="HTML", reply_markup=markup)
        return None

    elif data in ("vd_tt", "vd_fb"):
        plat = data[3:]
        context.user_data["vd_platform"] = plat
        text, markup = build_video_prompt(plat)
        msg = await query_edit_or_replace_admin(update, context, text=text, parse_mode="HTML", reply_markup=markup)
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_VIDEO_LINK

    elif data.startswith("vd_hist"):
        try:
            page = int(data.split(":")[1]) if ":" in data else 0
        except ValueError:
            page = 0
        text, markup = build_video_history_view(user.id, page)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        return None

    elif data == "vd_clear":
        with DB_LOCK:
            get_user_data(user.id)["video_history"] = []
            save_users_db()
        text, markup = build_video_history_view(user.id, 0)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        return None

    elif data.startswith("vd_re:"):
        vid = data.split(":", 1)[1]
        entry = next((e for e in get_user_data(user.id).get("video_history", []) if e.get("id") == vid), None)
        chat_id = query.message.chat_id
        if not entry:
            await asyncio.to_thread(send_auto_delete_message, chat_id, "⚠️ Không tìm thấy video này trong lịch sử.", 10)
            return None
        if user.id in VD_BUSY:
            await asyncio.to_thread(send_auto_delete_message, chat_id, "⏳ Bạn đang có 1 video được xử lý, vui lòng chờ xong rồi thử lại.", 10)
            return None
        await deliver_video(context, chat_id, user.id, entry["platform"], entry["url"], entry.get("title", ""), entry=entry)
        return None

'''

def replace_once(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"❌ Không tìm thấy đúng 1 vị trí cho '{label}' (tìm thấy {n}). File bot có thể khác bản tôi đã xem.")
    return src.replace(old, new)

def main():
    if len(sys.argv) < 2:
        sys.exit("Cách dùng: python patch_video.py ten_file_bot.py")
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if "TẢI VIDEO MẠNG XÃ HỘI (TIKTOK / FACEBOOK)" in src:
        sys.exit("ℹ️ File này đã được thêm tính năng tải video rồi.")

    # 1. import
    src = replace_once(src, "import contextvars\n", "import contextvars\nimport tempfile\nimport glob\n", "import")
    # 2. trạng thái hội thoại mới
    src = replace_once(src, "    INPUT_BULK_TOPUP\n) = range(16)", "    INPUT_BULK_TOPUP, INPUT_VIDEO_LINK\n) = range(17)", "states")
    # 3. khối chức năng chính
    anchor = "# ==================== KHUYẾN MÃI NẠP TIỀN (ADMIN CÀI ĐẶT) ===================="
    src = replace_once(src, anchor, BLOCK + "\n" + anchor, "khối chức năng")
    # 4. nút ngoài menu chính
    old = '        [InlineKeyboardButton("✔ TÍCH XANH FACEBOOK", callback_data="tick_xanh_menu")],\n'
    new = old + '        [InlineKeyboardButton("📥 TẢI VIDEO MXH (TikTok / Facebook)", callback_data="vd_menu")],\n'
    src = replace_once(src, old, new, "nút menu chính")
    # 5. xử lý nút bấm
    old = '    elif data == "reselect_qty":\n'
    src = replace_once(src, old, BRANCHES + old, "xử lý nút bấm")
    # 6. đăng ký trạng thái nhập link
    old = "            INPUT_BULK_TOPUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bulk_topup_handler)],\n"
    new = old + "            INPUT_VIDEO_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_video_link_handler)],\n"
    src = replace_once(src, old, new, "conversation handler")
    # 7. luồng tự xóa video
    old = "    start_backup_worker()\n    start_tg_backup_worker()\n    keep_alive()\n"
    new = old + "    start_video_delete_worker()\n"
    src = replace_once(src, old, new, "main()")

    shutil.copyfile(path, path + ".bak")
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.remove(tmp)
        sys.exit(f"❌ Lỗi cú pháp sau khi vá, giữ nguyên file cũ:\n{e}")
    os.replace(tmp, path)
    print("✅ Đã thêm tính năng TẢI VIDEO MXH. Bản gốc lưu ở:", path + ".bak")
    print("👉 Nhớ thêm dòng  yt-dlp  vào requirements.txt rồi deploy lại.")

main()
