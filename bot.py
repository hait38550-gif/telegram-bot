import os
import json
import logging
import time
from threading import Thread
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

# ==================== TÍCH HỢP FLASK & THREADING CHO RENDER ====================
app = Flask('')

@app.route('/')
def home():
    return "Bot SMM & Mua Tài Khoản is running and alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
# ==============================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.INFO)

# Sử dụng biến môi trường (Environment Variables) để bảo mật thông tin
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "YourAdminUsername")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "YOUR_ADMIN_CHAT_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

BANK_INFO = {
    "bank_name": "MBBank",
    "account_no": "5054999999999",
    "account_name": "NGUYEN TIEN DAT"
}

DB_FILE = "users_db.json"
GITCODE_DB_FILE = "gitcode_db.json"
SMS_DB_FILE = "sms_db.json"

def load_users_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception:
            return {}
    return {}

def save_users_db():
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(USERS_DB, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Lỗi khi lưu database user: {e}")

USERS_DB = load_users_db()

def load_gitcode_db():
    if os.path.exists(GITCODE_DB_FILE):
        try:
            with open(GITCODE_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_gitcode_db():
    try:
        with open(GITCODE_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(GITCODE_DB, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Lỗi khi lưu database gitcode: {e}")

GITCODE_DB = load_gitcode_db()

# ==================== DATABASE SMS SPAM ====================
def load_sms_db():
    if os.path.exists(SMS_DB_FILE):
        try:
            with open(SMS_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception:
            return {}
    return {}

def save_sms_db():
    try:
        with open(SMS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(SMS_DB, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Lỗi khi lưu database sms: {e}")

SMS_DB = load_sms_db()

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
            {"id": "like_s1_clone", "name": "✨ S1 Like clone xịn", "price": 99.0},
            {"id": "like_s1_tay", "name": "👆 S1 Like bấm tay", "price": 130.4},
            {"id": "like_s2_duphong", "name": "🛡️ S2 Like post dự phòng", "price": 110.35},
            {"id": "like_s2_clone", "name": "⚡ S2 Like clone nhanh", "price": 90.0},
        ]
    },
    "fb_follow": {
        "title": "👤 TĂNG FOLLOW / SUB",
        "items": [
            {"id": "fol_s8_clone", "name": "👑 S8 Follow Clone + Vip", "price": 69.72},
            {"id": "fol_clone_tay", "name": "✋ Follow clone TAY", "price": 73.43},
            {"id": "fol_clone_vn", "name": "🇻🇳 Follow clone Việt", "price": 86.0},
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
            {"id": "page_s2_tay", "name": "✍️ S2 Like page + follow TAY", "price": 70.3},
            {"id": "page_real_tay", "name": "🌟 Like + Follow Page Bấm Tay", "price": 99.0},
        ]
    },
    "fb_group": {
        "title": "👥 TĂNG THÀNH VIÊN NHÓM (GROUP)",
        "items": [
            {"id": "group_mem_s1", "name": "💎 S1 Member Group Chất Lượng", "price": 120.0},
            {"id": "group_mem_tay", "name": "🛡️ Member Group Bấm Tay Uy Tín", "price": 180.0},
        ]
    },
    "fb_share": {
        "title": "🔄 TĂNG SHARE & MEM GROUP",
        "items": [
            {"id": "share_s68", "name": "🌐 S68 Share Profile/Page/Group", "price": 83.62},
            {"id": "share_s69_ao", "name": "👻 S69 Share ảo All Link", "price": 102.06},
        ]
    },
    "fb_view": {
        "title": "👁️ TĂNG VIEW & MẮT LIVE",
        "items": [
            {"id": "view_reel_dq", "name": "🎬 View reel độc quyền", "price": 61.2},
            {"id": "view_fb_3s", "name": "⏱️ View facebook 3s chạy Reel", "price": 106.8},
        ]
    },
    "fb_story": {
        "title": "👁️ TĂNG VIEW STORY",
        "items": [
            {"id": "story_view_s1", "name": "📱 S1 View Story Facebook", "price": 50.0},
        ]
    },
    "tt_like": {
        "title": "🎵 TIKTOK - TĂNG TIM (LIKE)",
        "items": [
            {"id": "tt_like_s6", "name": "⚡ S6 Like tiktok Tây Nhanh", "price": 5.51 + 20},
            {"id": "tt_like_s7", "name": "🌍 S7 Like Tiktok tây- Không BH", "price": 5.98 + 20},
            {"id": "tt_like_s5", "name": "🛡️ S5 Like tiktok Tây Nhanh | BH 30 ngày", "price": 19.32 + 20},
            {"id": "tt_like_s9", "name": "👁️ S9 TikTok- ( Like ) tây + VIEW", "price": 6.34 + 20},
            {"id": "tt_like_s4", "name": "🇻🇳 S4 like tiktok việt", "price": 10.79 + 20},
            {"id": "tt_like_s2", "name": "🔥 S2 Like tiktok việt high", "price": 19.5 + 20},
            {"id": "tt_like_re", "name": "💸 Like TikTok việt giá rẻ", "price": 8.45 + 20},
        ]
    },
    "tt_follow": {
        "title": "👤 TIKTOK - TĂNG THEO DÕI",
        "items": [
            {"id": "tt_fol_clone", "name": "🤖 Tiktok Follow clone (19-6)", "price": 67.03 + 20},
            {"id": "tt_fol_s4", "name": "🇻🇳 S4 Follow TikTok Việt", "price": 39.0 + 20},
            {"id": "tt_fol_s5", "name": "✨ S5 Follow TikTok sale new", "price": 31.2 + 20},
            {"id": "tt_fol_s6", "name": "📈 S6 Follow tiktok việt ổn định", "price": 27.3 + 20},
            {"id": "tt_fol_high", "name": "🚀 Follow TikTok Việt High", "price": 55.9 + 20},
            {"id": "tt_fol_s2_high", "name": "⭐ S2 Follow TikTok Việt High", "price": 89.7 + 20},
        ]
    },
    "tt_view": {
        "title": "👁️ TIKTOK - TĂNG LƯỢT XEM (VIEW)",
        "items": [
            {"id": "tt_view_s64", "name": "📊 S64 View Tiktok | KBH | min:100", "price": 2.15 + 20},
            {"id": "tt_view_s11", "name": "📉 S11 View Tiktok | KBH | min:100 | Không BH", "price": 1.0 + 20},
            {"id": "tt_view_s6", "name": "📌 S6 View Tiktok | KBH | min:100 | Không BH", "price": 2.18 + 20},
            {"id": "tt_view_st", "name": "🚀 View tiktok siêu tốc | KBH | dự phòng", "price": 2.15 + 20},
            {"id": "tt_view_s3", "name": "💎 S3 view tiktok sale | Không tụt", "price": 1625.0 + 20},
        ]
    },
    "tt_cmt": {
        "title": "💬 TIKTOK - TĂNG BÌNH LUẬN",
        "items": [
            {"id": "tt_cmt_s4", "name": "⚡ S4 Cmt Tiktok Việt nhanh", "price": 195.0 + 20},
            {"id": "tt_cmt_s6", "name": "🛡️ S6 cmt tiktok Việt High ổn định", "price": 149.5 + 20},
            {"id": "tt_cmt_s7", "name": "✨ S7 cmt tiktok Việt New", "price": 143.0 + 20},
        ]
    },
    "tt_share": {
        "title": "🔄 TIKTOK - TĂNG SHARE",
        "items": [
            {"id": "tt_share_s2_sale", "name": "🏷️ S2 Share video tiktok Sale", "price": 13000.0 + 20},
            {"id": "tt_share_live", "name": "🔴 Share tiktok live Việt Nam", "price": 18.85 + 20},
            {"id": "tt_share_video", "name": "🇻🇳 Share video tiktok Việt Nam", "price": 15.6 + 20},
            {"id": "tt_share_s2_cheap", "name": "💸 S2 Share video tiktok giá rẻ | KBH", "price": 4.9 + 20},
        ]
    },
    "tt_save": {
        "title": "💾 TIKTOK - TĂNG SAVE (LƯU VIDEO)",
        "items": [
            {"id": "tt_save_s2", "name": "⚡ S2 save video Việt nhanh", "price": 11.05 + 20},
            {"id": "tt_save_s3", "name": "🌍 S3 save video [Tài nguyên Tây] | KBH", "price": 1.39 + 20},
        ]
    },
    "tt_live_vn": {
        "title": "🔴 TIKTOK - LIVE VIỆT NAM",
        "items": [
            {"id": "live_vn_30p", "name": "⏱️ Live Tiktok việt - 30 phút (New - Nên dùng)", "price": 214.89 + 20},
            {"id": "live_vn_60p", "name": "⏱️ Live Tiktok việt - 60 phút (New - Nên dùng)", "price": 357.36 + 20},
            {"id": "live_vn_90p", "name": "⏱️ Live Tiktok việt - 90 phút (New - Nên dùng)", "price": 536.04 + 20},
            {"id": "live_vn_120p", "name": "⏱️ Live Tiktok việt - 120 phút (New - Nên dùng)", "price": 714.71 + 20},
            {"id": "live_vn_180p", "name": "⏱️ Live Tiktok việt - 180 phút (New - Nên dùng)", "price": 1072.07 + 20},
            {"id": "live_vn_360p", "name": "⏱️ Live Tiktok việt - 360 phút (New - Nên dùng)", "price": 1429.43 + 20},
        ]
    },
    "tt_mat_live": {
        "title": "👀 TIKTOK - MẮT LIVESTREAM",
        "items": [
            {"id": "mat_live_30p", "name": "🛡️ Mắt live 30 phút (Ổn định)", "price": 72.15 + 20},
            {"id": "mat_live_60p", "name": "⭐ Mắt live 60 phút (Nên dùng)", "price": 118.95 + 20},
            {"id": "mat_live_90p", "name": "⭐ Mắt live 90 phút (Nên dùng)", "price": 176.15 + 20},
            {"id": "mat_live_120p", "name": "⭐ Mắt live 120 phút (Nên dùng)", "price": 260.0 + 20},
            {"id": "mat_live_180p", "name": "⭐ Mắt live 180 phút (Nên dùng)", "price": 392.6 + 20},
        ]
    },
    "tt_mat_tay": {
        "title": "🌍 TIKTOK - MẮT LIVE TÂY",
        "items": [
            {"id": "mat_tay_30p", "name": "⚡ Mắt live Tiktok Tây | Gói 30p (Nhanh)", "price": 130.0 + 20},
            {"id": "mat_tay_60p", "name": "⚡ Mắt live Tiktok Tây | Gói 60p (Nhanh)", "price": 257.4 + 20},
            {"id": "mat_tay_90p", "name": "⚡ Mắt live Tiktok Tây | Gói 90p (Nhanh)", "price": 383.5 + 20},
            {"id": "mat_tay_120p", "name": "⚡ Mắt live Tiktok Tây | Gói 120p (Nhanh)", "price": 500.5 + 20},
            {"id": "mat_tay_180p", "name": "⚡ Mắt live Tiktok Tây | Gói 180p (Nhanh)", "price": 734.5 + 20},
            {"id": "mat_tay_240p", "name": "⚡ Mắt live Tiktok Tây | Gói 240p (Nhanh)", "price": 968.5 + 20},
            {"id": "mat_tay_270p", "name": "⚡ Mắt live Tiktok Tây | Gói 270p (Nhanh)", "price": 1072.5 + 20},
        ]
    },
    "tt_vip_mat": {
        "title": "👑 TIKTOK - VIP MẮT LIVE STREAM",
        "items": [
            {"id": "vip_mat_15p", "name": "⭐ Vip mắt Tiktok 15 phút", "price": 234.0 + 20},
            {"id": "vip_mat_30p", "name": "⭐ Vip mắt Tiktok 30 phút", "price": 461.5 + 20},
            {"id": "vip_mat_60p", "name": "⭐ Vip mắt Tiktok 60 phút", "price": 728.0 + 20},
            {"id": "vip_mat_90p", "name": "⭐ Vip mắt Tiktok 90 phút", "price": 936.0 + 20},
            {"id": "vip_mat_120p", "name": "⭐ Vip mắt Tiktok 120 phút", "price": 1131.0 + 20},
            {"id": "vip_live", "name": "❤️ Tim Live stream (Nên dùng tăng mắt)", "price": 0.5 + 20},
        ]
    },
    "yt_sub": {
        "title": "▶️ YOUTUBE - TĂNG ĐĂNG KÝ KÊNH",
        "items": [
            {"id": "yt_mc_6505", "name": "MC 6505 LÊN CỰC NHANH - Tuột 100% -YouTube Subscribers | Không bảo hành", "price": 190.14},
            {"id": "yt_mc_6506", "name": "MC 6506 S23 - Sub youtube - new - Tài khoản cực trâu - Kênh bắt buộc có video trên 2 phút", "price": 948.09},
            {"id": "yt_mc_6661", "name": "MC 6661 Youtube sub Max 1k Lên nhanh", "price": 870.3},
        ]
    },
    "yt_like": {
        "title": "👍 YOUTUBE - TĂNG LIKE",
        "items": [
            {"id": "yt_mc_6508", "name": "MC 6508 Like rẻ nhanh | 20k/Day | Không bảo hành", "price": 29.42},
            {"id": "yt_mc_6509", "name": "MC 6509 S4 like nhanh chất lượng cao | Không bảo hành", "price": 30.58},
        ]
    },
    "yt_view": {
        "title": "👁️ YOUTUBE - TĂNG VIEW & LIVESTREAM",
        "items": [
            {"id": "yt_mc_6510", "name": "MC 6510 S1 Mắt Live YTB", "price": 22.2},
        ]
    },
    "ig_like": {
        "title": "❤️ INSTAGRAM - TĂNG LIKE",
        "items": [
            {"id": "ig_mc_6274", "name": "MC 6274 Like Instagram Việt xịn", "price": 31.5},
            {"id": "ig_mc_6500", "name": "MC 6500 S6 Like tây | Không bảo hành", "price": 23.93},
            {"id": "ig_mc_6501", "name": "MC 6501 S7 Like tây | Bảo hành 7 ngày", "price": 22.59},
        ]
    },
    "ig_follow": {
        "title": "👤 INSTAGRAM - TĂNG THEO DÕI",
        "items": [
            {"id": "ig_mc_6270", "name": "MC 6270 S1 Follower instagram Việt", "price": 54.5},
            {"id": "ig_mc_6271", "name": "MC 6271 Sv2 Follow việt giá rẻ", "price": 37.25},
            {"id": "ig_mc_6276", "name": "MC 6276 S5 follow Instagram Việt high", "price": 107.71},
            {"id": "ig_mc_6502", "name": "MC 6502 S2 Follower tây nhanh | Không bảo hành", "price": 46.49},
            {"id": "ig_mc_6503", "name": "MC 6503 Follow instagram - tây | Bảo hành 7 ngày", "price": 48.69},
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

INPUT_LINK, INPUT_QUANTITY, INPUT_TOPUP_AMOUNT, INPUT_GITCODE, INPUT_CREATE_CODE_CUSTOM, INPUT_ADMIN_EDIT_USER, INPUT_SMS_PHONE, INPUT_BROADCAST_TEXT, INPUT_BROADCAST_PHOTO = range(9)

def is_admin(user_id, username):
    return str(user_id) == str(ADMIN_CHAT_ID) or (username and username == ADMIN_USERNAME.replace('@',''))

def get_stock_count(cat_id):
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
        return f"@{user.username}"
    else:
        name = user.first_name if user.first_name else "Khách hàng"
        return f"[{name}](tg://user?id={user.id})"

def main_menu_keyboard(user_id, username, first_name="bạn"):
    balance = get_user_balance(user_id)
    text = (
        f"👋 Xin chào {first_name}!\n"
        f"🚀 Chào mừng bạn đến với Hệ thống Dịch vụ Auto!\n"
        f"========================================\n\n"
        f"🤖 BOT DỊCH VỤ SMM & MUA TÀI KHOẢN\n"
        f"----------------------------------------\n"
        f"🆔 ID Telegram: `{user_id}`\n"
        f"💰 Số dư hiện tại: {balance:,.0f} VND\n"
        f"----------------------------------------\n"
        f"👇 Vui lòng chọn tính năng bên dưới:"
    )
    
    keyboard = [
        [InlineKeyboardButton("📦 SẢN PHẨM TÀI KHOẢN", callback_data="products_p1")],
        [
            InlineKeyboardButton("📘 DỊCH VỤ FACEBOOK", callback_data="cat_fb"),
            InlineKeyboardButton("🎵 DỊCH VỤ TIKTOK", callback_data="cat_tt")
        ],
        [
            InlineKeyboardButton("▶️ DỊCH VỤ YOUTUBE", callback_data="cat_yt"),
            InlineKeyboardButton("📸 DỊCH VỤ INSTAGRAM", callback_data="cat_ig")
        ],
        [InlineKeyboardButton("💣 DỊCH VỤ SPAM SMS", callback_data="sms_menu_main")],
        [InlineKeyboardButton("🎁 NHẬP GITCODE KHUYẾN MÃI", callback_data="menu_gitcode")],
        [InlineKeyboardButton("📜 LỊCH SỬ ĐÃ DÙNG", callback_data="view_history")],
        [
            InlineKeyboardButton("💳 NẠP TIỀN AUTO", callback_data="nap_tien"),
            InlineKeyboardButton("📞 HỖ TRỢ ADMIN", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")
        ],
    ]
    
    if is_admin(user_id, username):
        keyboard.append([InlineKeyboardButton("⚙️ [ADMIN] QUẢN LÝ HỆ THỐNG", callback_data="admin_panel")])

    return text, InlineKeyboardMarkup(keyboard)

def products_menu_keyboard(page=1):
    items = CATEGORIES_PAGE_1 if page == 1 else CATEGORIES_PAGE_2
    keyboard = []
    for item in items:
        if item['id'] == "cat_groups":
            display_name = item['title']
        else:
            stock = get_stock_count(item['id'])
            display_name = f"{item['title']} ({stock})"
        
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"item_{item['id']}")])
    
    text = f"📂 CHỌN CHUYÊN MỤC SẢN PHẨM\n📄 Trang {page}/2\n\n👇 Chọn chuyên mục:"
    
    nav_buttons = []
    if page == 1:
        nav_buttons.append(InlineKeyboardButton("📄 1/2", callback_data="none"))
        nav_buttons.append(InlineKeyboardButton("➡️ Trang sau", callback_data="products_p2"))
    else:
        nav_buttons.append(InlineKeyboardButton("⬅️ Trang trước", callback_data="products_p1"))
        nav_buttons.append(InlineKeyboardButton("📄 2/2", callback_data="none"))
    
    keyboard.append(nav_buttons)
    keyboard.append([
        InlineKeyboardButton("↩️ Trở về", callback_data="products_p2"),
        InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
    ])
    
    return text, InlineKeyboardMarkup(keyboard)

def groups_menu_keyboard(page=1):
    items = GROUPS_PAGE_1 if page == 1 else GROUPS_PAGE_2
    keyboard = []
    for item in items:
        mem_str = f"{item['mem'] / 1000:.0f}k" if item['mem'] < 1000000 else f"{item['mem'] / 1000000:.1f}M"
        display_name = f"👥 {item['name']} ({mem_str})"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"group_detail_{item['id']}")])
    
    text = f"📋 DANH SÁCH NHÓM (GROUP) FACEBOOK\n📄 Trang {page}/2\n\n👇 Chọn nhóm để xem chi tiết và tiến hành mua:"
    
    nav_buttons = []
    if page == 1:
        nav_buttons.append(InlineKeyboardButton("📄 1/2", callback_data="none"))
        nav_buttons.append(InlineKeyboardButton("➡️ Trang sau", callback_data="groups_p2"))
    else:
        nav_buttons.append(InlineKeyboardButton("⬅️ Trang trước", callback_data="groups_p1"))
        nav_buttons.append(InlineKeyboardButton("📄 2/2", callback_data="none"))
    
    keyboard.append(nav_buttons)
    keyboard.append([
        InlineKeyboardButton("↩️ Trở về", callback_data="products_p2"),
        InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
    ])
    
    return text, InlineKeyboardMarkup(keyboard)

def fb_menu_keyboard():
    text = "📘 DANH MỤC DỊCH VỤ FACEBOOK\n\n👇 Chọn loại dịch vụ bạn muốn sử dụng:"
    keyboard = [
        [InlineKeyboardButton("👍 Tăng Like Bài Viết", callback_data="subcat_fb_like"), InlineKeyboardButton("👤 Tăng Follow / Sub", callback_data="subcat_fb_follow")],
        [InlineKeyboardButton("💬 Tăng Bình Luận", callback_data="subcat_fb_cmt"), InlineKeyboardButton("⭐ Tăng Like Page", callback_data="subcat_fb_page")],
        [InlineKeyboardButton("👥 Tăng Mem Group", callback_data="subcat_fb_group"), InlineKeyboardButton("🔄 Share / Mem Group", callback_data="subcat_fb_share")],
        [InlineKeyboardButton("👁️ View / Mắt Live", callback_data="subcat_fb_view"), InlineKeyboardButton("👁️ Tăng View Story", callback_data="subcat_fb_story")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

def tiktok_menu_keyboard():
    text = "🎵 DANH MỤC DỊCH VỤ TIKTOK\n\n👇 Chọn loại dịch vụ bạn muốn sử dụng:"
    keyboard = [
        [InlineKeyboardButton("❤️ Tăng Tim (Like)", callback_data="subcat_tt_like"), InlineKeyboardButton("👤 Tăng Theo Dõi", callback_data="subcat_tt_follow")],
        [InlineKeyboardButton("👁️ Tăng Lượt Xem", callback_data="subcat_tt_view"), InlineKeyboardButton("💬 Tăng Bình Luận", callback_data="subcat_tt_cmt")],
        [InlineKeyboardButton("🔄 Tăng Share", callback_data="subcat_tt_share"), InlineKeyboardButton("💾 Tăng Save (Lưu)", callback_data="subcat_tt_save")],
        [InlineKeyboardButton("🔴 Live Việt Nam", callback_data="subcat_tt_live_vn"), InlineKeyboardButton("👀 Mắt Livestream", callback_data="subcat_tt_mat_live")],
        [InlineKeyboardButton("🌍 Mắt Live Tây", callback_data="subcat_tt_mat_tay"), InlineKeyboardButton("👑 Vip Mắt Live", callback_data="subcat_tt_vip_mat")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

def youtube_menu_keyboard():
    text = "▶️ DANH MỤC DỊCH VỤ YOUTUBE\n\n👇 Chọn loại dịch vụ bạn muốn sử dụng:"
    keyboard = [
        [InlineKeyboardButton("📥 Tăng Đăng Ký Kênh", callback_data="subcat_yt_sub")],
        [InlineKeyboardButton("👍 Tăng Like", callback_data="subcat_yt_like"), InlineKeyboardButton("👁️ Tăng View & Live", callback_data="subcat_yt_view")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

def instagram_menu_keyboard():
    text = "📸 DANH MỤC DỊCH VỤ INSTAGRAM\n\n👇 Chọn loại dịch vụ bạn muốn sử dụng:"
    keyboard = [
        [InlineKeyboardButton("❤️ Tăng Like", callback_data="subcat_ig_like"), InlineKeyboardButton("👤 Tăng Theo Dõi", callback_data="subcat_ig_follow")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

def service_items_keyboard(cat_key):
    cat_data = SERVICES.get(cat_key, {})
    text = f"🛠️ DỊCH VỤ: {cat_data.get('title', 'DỊCH VỤ')}\n\n👇 Chọn gói cụ thể bên dưới:"
    keyboard = []
    for item in cat_data.get("items", []):
        btn_text = f"{item['name']} - {item['price']}đ"
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
    await update.message.reply_text(text, reply_markup=reply_markup)

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
        
        new_bal = user_data["balance"]

        try:
            target_user = await context.bot.get_chat(target_id)
            user_tag = f"@{target_user.username}" if target_user.username else f"ID `{target_id}`"
        except Exception:
            user_tag = f"ID `{target_id}`"

        await update.message.reply_text(f"✅ Đã cộng {amount:,.0f}đ cho khách {user_tag}\n💰 Số dư mới: {new_bal:,.0f} VND")

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🎉 BẠN ĐÃ ĐƯỢC CỘNG TIỀN THÀNH CÔNG!\n\n💰 Số tiền nạp: +{amount:,.0f} VND\n💳 Số dư hiện tại: {new_bal:,.0f} VND"
            )
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

    user = update.effective_user
    qr_url = f"https://img.vietqr.io/image/{BANK_INFO['bank_name']}-{BANK_INFO['account_no']}-compact2.png?amount={int(amount)}&addInfo={user.id}&accountName={BANK_INFO['account_name'].replace(' ', '%20')}"
    
    caption_text = (
        f"💳 THÔNG TIN CHUYỂN KHOẢN NẠP TIỀN\n"
        f"----------------------------------------\n"
        f"🏦 Ngân hàng: {BANK_INFO['bank_name']}\n"
        f"🔢 Số tài khoản: `{BANK_INFO['account_no']}`\n"
        f"👤 Chủ tài khoản: {BANK_INFO['account_name']}\n"
        f"💵 Số tiền: {amount:,.0f} VND\n"
        f"📝 Nội dung chuyển khoản (BẮT BUỘC): `{user.id}`\n\n"
        f"⚠️ LƯU Ý QUAN TRỌNG:\n"
        f"• Vui lòng kiểm tra kỹ Nội dung chuyển khoản phải chính xác là ID của bạn (`{user.id}`) để hệ thống tự động cộng tiền.\n"
        f"• Nếu sai nội dung, hãy liên hệ ngay Admin để được hỗ trợ thủ công!\n"
        f"----------------------------------------\n"
        f"👇 Sau khi chuyển khoản xong, bấm nút [Đã chuyển khoản] bên dưới!"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Đã chuyển khoản", callback_data=f"confirm_trans:{amount}")],
        [InlineKeyboardButton("🔄 Chọn lại mệnh giá", callback_data="nap_tien")]
    ]
    await update.message.reply_photo(photo=qr_url, caption=caption_text, reply_markup=InlineKeyboardMarkup(keyboard))
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
        f"🎉 NHẬP GITCODE THÀNH CÔNG!\n\n"
        f"🎁 Mã code: `{code}`\n"
        f"💰 Số tiền được cộng: +{amount:,.0f} VND\n"
        f"💳 Số dư hiện tại: {new_balance:,.0f} VND",
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
        f"🎁 Mã: `{code}`\n"
        f"💵 Giá trị: {amount:,.0f} VND",
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

    await update.message.reply_text(
        f"✅ ĐÃ CẬP NHẬT SỐ DƯ CHO KHÁCH `{target_id}`\n"
        f"💰 Số dư mới: {new_balance:,.0f} VND",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]])
    )
    return ConversationHandler.END

# ==================== TÍNH NĂNG MỚI: TẠO & GỬI THÔNG BÁO CHO ADMIN ====================
async def receive_broadcast_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END
    
    msg_text = update.message.text
    context.user_data["broadcast_text"] = msg_text
    
    keyboard = [
        [InlineKeyboardButton("🚀 Gửi thông báo tới tất cả người dùng", callback_data="exec_broadcast_text")],
        [InlineKeyboardButton("↩️ Quay về Menu Quản Lý", callback_data="admin_panel")]
    ]
    await update.message.reply_text(
        f"📋 NỘI DUNG THÔNG BÁO VĂN BẢN:\n"
        f"----------------------------------------\n"
        f"{msg_text}\n"
        f"----------------------------------------\n"
        f"👇 Bấm nút bên dưới để tiến hành gửi:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def receive_broadcast_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id, user.username):
        return ConversationHandler.END
    
    if not update.message.photo:
        await update.message.reply_text("⚠️ Vui lòng gửi một hình ảnh hợp lệ cho thông báo!")
        return INPUT_BROADCAST_PHOTO
    
    photo_file_id = update.message.photo[-1].file_id
    caption = update.message.caption or ""
    
    context.user_data["broadcast_photo"] = photo_file_id
    context.user_data["broadcast_caption"] = caption
    
    keyboard = [
        [InlineKeyboardButton("🚀 Gửi thông báo tới tất cả người dùng", callback_data="exec_broadcast_photo")],
        [InlineKeyboardButton("↩️ Quay về Menu Quản Lý", callback_data="admin_panel")]
    ]
    await update.message.reply_photo(
        photo=photo_file_id,
        caption=(
            f"📸 ẢNH VÀ VĂN BẢN THÔNG BÁO:\n"
            f"----------------------------------------\n"
            f"{caption}\n"
            f"----------------------------------------\n"
            f"👇 Bấm nút bên dưới để tiến hành gửi:"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END
# ====================================================================================

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
        f"🔗 ĐÃ NHẬN LINK TĂNG TƯƠNG TÁC:\n`{link}`\n\n"
        f"📦 Gói đã chọn: {item_name}\n\n"
        f"👇 Vui lòng nhập số lượng bạn muốn chạy (Ví dụ: 100, 500, 1000):"
    )
    
    if cat_key.startswith("tt_"):
        subcat_target = f"subcat_{cat_key}"
    elif cat_key.startswith("yt_"):
        subcat_target = f"subcat_{cat_key}"
    elif cat_key.startswith("ig_"):
        subcat_target = f"subcat_{cat_key}"
    else:
        subcat_target = f"subcat_{cat_key}"

    keyboard = [
        [
            InlineKeyboardButton("↩️ Chọn lại gói", callback_data=subcat_target),
            InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
        ]
    ]
    
    msg = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
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
            f"📊 Số lượng: {quantity:,}\n\n"
            f"👇 Vui lòng chọn loại bình luận bạn muốn:"
        )
        keyboard = [
            [
                InlineKeyboardButton("💬 Cmt khen", callback_data="cmt_type:Khen"),
                InlineKeyboardButton("💬 Cmt chê", callback_data="cmt_type:Chê")
            ],
            [
                InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
            ]
        ]
        msg = await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["prompt_msg_id"] = msg.message_id
        return ConversationHandler.END
    else:
        return await process_final_order(update, context, "Mặc định")

async def process_final_order(update: Update, context: ContextTypes.DEFAULT_TYPE, cmt_type="Mặc định"):
    user = update.effective_user
    selected_item = context.user_data.get("buying_service", {})
    link = context.user_data.get("order_link", "")
    quantity = context.user_data.get("order_quantity", 0)
    
    price_per_unit = selected_item.get("price", 0)
    total_price = quantity * price_per_unit
    
    user_data = get_user_data(user.id)
    if user_data["balance"] < total_price:
        msg_text = (
            f"❌ SỐ DƯ KHÔNG ĐỦ!\n\n"
            f"💳 Số dư của bạn: {user_data['balance']:,.0f}đ\n"
            f"💵 Tổng tiền cần thanh toán: {total_price:,.0f}đ\n\n"
            f"⚠️ Vui lòng nạp thêm tiền để tiếp tục đặt hàng!"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Nạp tiền ngay", callback_data="nap_tien"), InlineKeyboardButton("🏠 Menu", callback_data="menu_main")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(msg_text, reply_markup=keyboard)
        else:
            await update.message.reply_text(msg_text, reply_markup=keyboard)
        return ConversationHandler.END

    user_data["balance"] -= total_price
    
    if cmt_type != "Mặc định":
        history_item = f"SMM: {selected_item.get('name')} ({cmt_type}) | SL: {quantity:,} | Giá: {total_price:,.0f}đ | Link: {link}"
    else:
        history_item = f"SMM: {selected_item.get('name')} | SL: {quantity:,} | Giá: {total_price:,.0f}đ | Link: {link}"
        
    user_data["history"].append(history_item)
    save_users_db()
    
    new_bal = user_data["balance"]

    success_text = (
        f"✅ ĐẶT HÀNG TĂNG TƯƠNG TÁC THÀNH CÔNG!\n\n"
        f"📦 Gói: {selected_item.get('name')}\n"
        f"💬 Loại cmt: {cmt_type}\n"
        f"🔗 Link: `{link}`\n"
        f"📊 Số lượng: {quantity:,}\n"
        f"💵 Tổng tiền đã trừ: {total_price:,.0f}đ\n"
        f"💳 Số dư còn lại: {new_bal:,.0f}đ\n\n"
        f"⏳ Hệ thống đang xử lý đơn hàng của bạn."
    )
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]])

    if update.callback_query:
        await update.callback_query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode="Markdown")

    user_mention = get_user_mention(user)

    admin_notice = (
        f"🔔 ĐƠN HÀNG TĂNG TƯƠNG TÁC MỚI!\n"
        f"----------------------------------------\n"
        f"👤 Khách hàng: {user_mention} (ID: `{user.id}`)\n"
        f"📦 Gói: {selected_item.get('name')}\n"
        f"💬 Loại cmt: {cmt_type}\n"
        f"🔗 Link: `{link}`\n"
        f"📊 Số lượng: {quantity:,}\n"
        f"💵 Tổng tiền: {total_price:,.0f}đ"
    )
    
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Đã nhận đơn", callback_data=f"admin_accept_order:{user.id}")],
        [InlineKeyboardButton("❌ Từ chối đơn", callback_data=f"admin_reject_order:{user.id}")]
    ])
    
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notice, parse_mode="Markdown", reply_markup=admin_keyboard)
    except Exception:
        pass

    return ConversationHandler.END

# ==================== XỬ LÝ DỊCH VỤ SPAM SMS ====================
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
            f"✅ THÊM SỐ ĐIỆN THOẠI SPAM THÀNH CÔNG!\n\n"
            f"📦 Áp dụng theo gói đang hoạt động: {pkg_name}\n"
            f"📱 SĐT mới thêm: `{phone}`\n"
            f"⏳ Trạng thái: Đang tiến hành spam."
        )
        success_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💣 Quản lý danh sách SMS", callback_data="sms_menu_main")],
            [InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]
        ])
        await update.message.reply_text(success_text, parse_mode="Markdown", reply_markup=success_keyboard)
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
        f"✅ MUA GÓI SPAM SMS THÀNH CÔNG!\n\n"
        f"📦 Gói: {pkg_name}\n"
        f"📱 SĐT cần spam: `{phone}`\n"
        f"💵 Đã trừ: {pkg_price:,.0f} VND\n"
        f"💳 Số dư còn lại: {new_bal:,.0f} VND\n"
        f"⏳ Trạng thái: Đang tiến hành spam."
    )
    
    success_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💣 Quản lý danh sách SMS", callback_data="sms_menu_main")],
        [InlineKeyboardButton("🏠 Về Menu Chính", callback_data="menu_main")]
    ])
    await update.message.reply_text(success_text, parse_mode="Markdown", reply_markup=success_keyboard)
    return ConversationHandler.END

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    get_user_data(user.id)

    if data.startswith("cmt_type:"):
        cmt_type = data.split(":")[1]
        await process_final_order(update, context, cmt_type)
        return

    if data == "sms_menu_main":
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]
        
        if active_sms:
            text = "💣 QUẢN LÝ DỊCH VỤ SPAM SMS\n----------------------------------------\n📜 Danh sách số điện thoại đang spam của bạn:\n"
            keyboard = []
            for idx, item in enumerate(active_sms):
                remaining_time = int(item["expire_time"] - time.time())
                hours = remaining_time // 3600
                time_str = f"Còn {hours} giờ" if hours < 48 else f"Còn {hours//24} ngày"
                if item["expire_time"] > time.time() + 3000000000:
                    time_str = "Vĩnh viễn"
                
                text += f"\n{idx+1}. SĐT: `{item['phone']}` ({item['package']}) - {time_str}"
                keyboard.append([
                    InlineKeyboardButton(f"➕ Gia hạn ({item['phone']})", callback_data=f"sms_renew:{idx}"),
                    InlineKeyboardButton(f"❌ Hủy ({item['phone']})", callback_data=f"sms_cancel:{idx}")
                ])
            keyboard.append([InlineKeyboardButton("➕ Thêm SĐT khác", callback_data="sms_add_another")])
            keyboard.append([InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            text = (
                f"💣 HỆ THỐNG SPAM SMS\n"
                f"----------------------------------------\n"
                f"👇 Vui lòng chọn loại dịch vụ SMS muốn sử dụng:"
            )
            keyboard = [
                [InlineKeyboardButton("📱 SMS Thường", callback_data="sms_cat_thuong")],
                [InlineKeyboardButton("👑 SMS Vip", callback_data="sms_cat_vip")],
                [InlineKeyboardButton("📋 Danh sách đã spam", callback_data="sms_list_history")],
                [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "sms_add_another":
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]

        if active_sms:
            context.user_data["is_adding_free_phone"] = True
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="sms_menu_main"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
            msg = await query.edit_message_text(
                f"➕ THÊM SỐ ĐIỆN THOẠI KHÁC\n"
                f"----------------------------------------\n"
                f"ℹ️ Bạn đang có gói dịch vụ còn hạn, số điện thoại này sẽ được thêm vào hệ thống spam hoàn toàn miễn phí.\n\n"
                f"💬 Vui lòng gửi số điện thoại cần spam vào đây:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["prompt_msg_id"] = msg.message_id
            return INPUT_SMS_PHONE
        else:
            text = (
                f"💣 HỆ THỐNG SPAM SMS (MUA GÓI MỚI)\n"
                f"----------------------------------------\n"
                f"⏳ Gói cũ của bạn đã hết hạn. Vui lòng chọn gói dịch vụ SMS mới:"
            )
            keyboard = [
                [InlineKeyboardButton("📱 SMS Thường", callback_data="sms_cat_thuong")],
                [InlineKeyboardButton("👑 SMS Vip", callback_data="sms_cat_vip")],
                [InlineKeyboardButton("↩️ Trở về quản lý SMS", callback_data="sms_menu_main")],
                [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data in ["sms_cat_thuong", "sms_cat_vip"]:
        cat_key = "sms_thuong" if data == "sms_cat_thuong" else "sms_vip"
        cat_data = SMS_PACKAGES[cat_key]
        text = f"🛠️ {cat_data['title']}\n\n👇 Chọn gói dịch vụ bên dưới:"
        keyboard = []
        for pkg in cat_data["packages"]:
            keyboard.append([InlineKeyboardButton(f"{pkg['name']} - {pkg['price']:,.0f}đ", callback_data=f"buy_sms:{cat_key}:{pkg['id']}")])
        keyboard.append([
            InlineKeyboardButton("↩️ Trở về", callback_data="sms_menu_main"),
            InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
        ])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("buy_sms:"):
        _, cat_key, pkg_id = data.split(":")
        pkg_info = next((p for p in SMS_PACKAGES[cat_key]["packages"] if p["id"] == pkg_id), None)
        if pkg_info:
            context.user_data["buying_sms_pkg"] = pkg_info
            context.user_data["is_adding_free_phone"] = False
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data=f"sms_cat_{'thuong' if cat_key=='sms_thuong' else 'vip'}"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
            msg = await query.edit_message_text(
                f"📦 ĐÃ CHỌN: {pkg_info['name']}\n"
                f"💵 GIÁ: {pkg_info['price']:,.0f}đ\n\n"
                f"💬 Vui lòng gửi số điện thoại cần spam vào đây:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["prompt_msg_id"] = msg.message_id
            return INPUT_SMS_PHONE

    elif data == "sms_list_history":
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]
        if not active_sms:
            text = "ℹ️ Bạn chưa có số điện thoại nào đang spam."
            keyboard = [
                [InlineKeyboardButton("➕ Thêm SĐT khác", callback_data="sms_add_another")],
                [InlineKeyboardButton("↩️ Trở về", callback_data="sms_menu_main"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
            ]
        else:
            text = "📋 DANH SÁCH ĐÃ SPAM SMS:\n----------------------------------------\n"
            keyboard = []
            for idx, item in enumerate(active_sms):
                text += f"{idx+1}. SĐT: `{item['phone']}` | Gói: {item['package']}\n"
                keyboard.append([
                    InlineKeyboardButton(f"➕ Gia hạn {item['phone']}", callback_data=f"sms_renew:{idx}"),
                    InlineKeyboardButton(f"❌ Hủy {item['phone']}", callback_data=f"sms_cancel:{idx}")
                ])
            keyboard.append([InlineKeyboardButton("➕ Thêm SĐT khác", callback_data="sms_add_another")])
            keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="sms_menu_main"), InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
            text = "💣 QUẢN LÝ DỊCH VỤ SPAM SMS\n----------------------------------------\n📜 Danh sách số điện thoại đang spam của bạn:\n"
            keyboard = []
            for i, item in enumerate(active_sms):
                text += f"\n{i+1}. SĐT: `{item['phone']}` ({item['package']})"
                keyboard.append([
                    InlineKeyboardButton(f"➕ Gia hạn ({item['phone']})", callback_data=f"sms_renew:{i}"),
                    InlineKeyboardButton(f"❌ Hủy ({item['phone']})", callback_data=f"sms_cancel:{i}")
                ])
            keyboard.append([InlineKeyboardButton("➕ Thêm SĐT khác", callback_data="sms_add_another")])
            keyboard.append([InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            text, reply_markup = main_menu_keyboard(user.id, user.username, user.first_name)
            await query.edit_message_text(text, reply_markup=reply_markup)

    elif data.startswith("sms_renew:"):
        idx = int(data.split(":")[1])
        if user.id in SMS_DB and len(SMS_DB[user.id]) > idx:
            item = SMS_DB[user.id][idx]
            item["expire_time"] += 86400
            save_sms_db()
            await query.answer(f"✅ Đã gia hạn thành công cho số {item['phone']} thêm 1 ngày!", show_alert=True)
        else:
            await query.answer("⚠️ Không tìm thấy số điện thoại!", show_alert=True)
        
        user_sms_list = SMS_DB.get(user.id, [])
        active_sms = [s for s in user_sms_list if s["expire_time"] > time.time()]
        text = "💣 QUẢN LÝ DỊCH VỤ SPAM SMS\n----------------------------------------\n📜 Danh sách số điện thoại đang spam của bạn:\n"
        keyboard = []
        for i, item in enumerate(active_sms):
            text += f"\n{i+1}. SĐT: `{item['phone']}` ({item['package']})"
            keyboard.append([
                InlineKeyboardButton(f"➕ Gia hạn ({item['phone']})", callback_data=f"sms_renew:{i}"),
                InlineKeyboardButton(f"❌ Hủy ({item['phone']})", callback_data=f"sms_cancel:{i}")
            ])
        keyboard.append([InlineKeyboardButton("➕ Thêm SĐT khác", callback_data="sms_add_another")])
        keyboard.append([InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_panel":
        if not is_admin(user.id, user.username):
            await query.answer("❌ Bạn không có quyền truy cập!", show_alert=True)
            return
        
        text = (
            f"⚙️ QUẢN LÝ HỆ THỐNG DÀNH CHO ADMIN\n"
            f"----------------------------------------\n"
            f"👇 Chọn chức năng quản lý bên dưới:"
        )
        keyboard = [
            [InlineKeyboardButton("👥 Danh sách khách hàng & Số dư", callback_data="admin_list_users")],
            [InlineKeyboardButton("🎁 Tạo & Quản lý Mã Gitcode", callback_data="admin_gitcode_menu")],
            [InlineKeyboardButton("📱 Xem gói spam sms khách hàng", callback_data="admin_sms_list_all")],
            [InlineKeyboardButton("📢 Tạo thông báo cho người dùng", callback_data="admin_broadcast_menu")],
            [InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]
        ]
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    # ==================== MENU TẠO THÔNG BÁO CHO ADMIN ====================
    elif data == "admin_broadcast_menu":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"📢 TẠO THÔNG BÁO CHO NGƯỜI DÙNG\n"
            f"----------------------------------------\n"
            f"👇 Vui lòng chọn hình thức thông báo bạn muốn gửi:"
        )
        keyboard = [
            [InlineKeyboardButton("📝 Gửi Mỗi Văn Bản", callback_data="broadcast_mode_text")],
            [InlineKeyboardButton("🖼️ Gửi Vừa Ảnh Vừa Văn Bản", callback_data="broadcast_mode_photo")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "broadcast_mode_text":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"📝 TẠO THÔNG BÁO VĂN BẢN\n"
            f"----------------------------------------\n"
            f"💬 Vui lòng gửi nội dung thông báo (thông báo bảo trì, ưu đãi,...) vào đây:"
        )
        keyboard = [
            [InlineKeyboardButton("↩️ Quay về Menu Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_BROADCAST_TEXT

    elif data == "broadcast_mode_photo":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"🖼️ TẠO THÔNG BÁO ẢNH & VĂN BẢN\n"
            f"----------------------------------------\n"
            f"💬 Vui lòng gửi bức ảnh kèm phần chú thích (caption) văn bản thông báo của bạn vào đây:"
        )
        keyboard = [
            [InlineKeyboardButton("↩️ Quay về Menu Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_BROADCAST_PHOTO

    elif data == "exec_broadcast_text":
        if not is_admin(user.id, user.username):
            return
        msg_text = context.user_data.get("broadcast_text", "")
        if not msg_text:
            await query.answer("⚠️ Chưa có nội dung thông báo!", show_alert=True)
            return
        
        success_count = 0
        fail_count = 0
        for uid in USERS_DB.keys():
            try:
                await context.bot.send_message(chat_id=int(uid), text=f"📢 **THÔNG BÁO TỪ HỆ THỐNG**\n\n{msg_text}", parse_mode="Markdown")
                success_count += 1
            except Exception:
                fail_count + 1

        text = (
            f"✅ ĐÃ GỬI THÔNG BÁO THÀNH CÔNG!\n"
            f"----------------------------------------\n"
            f"👥 Gửi thành công tới: {success_count} người dùng\n"
            f"❌ Thất bại: {fail_count} người dùng"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "exec_broadcast_photo":
        if not is_admin(user.id, user.username):
            return
        photo_id = context.user_data.get("broadcast_photo", "")
        caption = context.user_data.get("broadcast_caption", "")
        if not photo_id:
            await query.answer("⚠️ Chưa có ảnh thông báo!", show_alert=True)
            return
        
        full_caption = f"📢 **THÔNG BÁO TỪ HỆ THỐNG**\n\n{caption}"
        success_count = 0
        fail_count = 0
        for uid in USERS_DB.keys():
            try:
                await context.bot.send_photo(chat_id=int(uid), photo=photo_id, caption=full_caption, parse_mode="Markdown")
                success_count += 1
            except Exception:
                fail_count += 1

        text = (
            f"✅ ĐÃ GỬI THÔNG BÁO KÈM ẢNH THÀNH CÔNG!\n"
            f"----------------------------------------\n"
            f"👥 Gửi thành công tới: {success_count} người dùng\n"
            f"❌ Thất bại: {fail_count} người dùng"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    # ======================================================================

    elif data == "admin_sms_list_all":
        if not is_admin(user.id, user.username):
            return
        
        if not SMS_DB:
            text = "ℹ️ Hiện chưa có khách hàng nào mua gói spam SMS."
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="admin_panel")]]
        else:
            text = "📱 QUẢN LÝ GÓI SPAM SMS KHÁCH HÀNG:\n----------------------------------------\n"
            keyboard = []
            for uid, sms_list in SMS_DB.items():
                for i, s in enumerate(sms_list):
                    if s["expire_time"] > time.time():
                        text += f"• ID: `{uid}` | SĐT: `{s['phone']}` | Gói: {s['package']}\n"
                        keyboard.append([
                            InlineKeyboardButton(f"➕ Gia hạn (ID {uid})", callback_data=f"admin_sms_renew:{uid}:{i}"),
                            InlineKeyboardButton(f"❌ Hủy (ID {uid})", callback_data=f"admin_sms_cancel:{uid}:{i}")
                        ])
            keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_panel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
        
        text = "📱 QUẢN LÝ GÓI SPAM SMS KHÁCH HÀNG:\n----------------------------------------\n"
        keyboard = []
        for uid, sms_list in SMS_DB.items():
            for i, s in enumerate(sms_list):
                if s["expire_time"] > time.time():
                    text += f"• ID: `{uid}` | SĐT: `{s['phone']}` | Gói: {s['package']}\n"
                    keyboard.append([
                        InlineKeyboardButton(f"➕ Gia hạn (ID {uid})", callback_data=f"admin_sms_renew:{uid}:{i}"),
                        InlineKeyboardButton(f"❌ Hủy (ID {uid})", callback_data=f"admin_sms_cancel:{uid}:{i}")
                    ])
        keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_panel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
        
        text = "📱 QUẢN LÝ GÓI SPAM SMS KHÁCH HÀNG:\n----------------------------------------\n"
        keyboard = []
        for uid, sms_list in SMS_DB.items():
            for i, s in enumerate(sms_list):
                if s["expire_time"] > time.time():
                    text += f"• ID: `{uid}` | SĐT: `{s['phone']}` | Gói: {s['package']}\n"
                    keyboard.append([
                        InlineKeyboardButton(f"➕ Gia hạn (ID {uid})", callback_data=f"admin_sms_renew:{uid}:{i}"),
                        InlineKeyboardButton(f"❌ Hủy (ID {uid})", callback_data=f"admin_sms_cancel:{uid}:{i}")
                    ])
        keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_panel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "menu_main":
        text, reply_markup = main_menu_keyboard(user.id, user.username, user.first_name)
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(text, reply_markup=reply_markup)
        else:
            await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "cat_fb":
        text, reply_markup = fb_menu_keyboard()
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "cat_tt":
        text, reply_markup = tiktok_menu_keyboard()
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "cat_yt":
        text, reply_markup = youtube_menu_keyboard()
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "cat_ig":
        text, reply_markup = instagram_menu_keyboard()
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data.startswith("subcat_fb_") or data.startswith("subcat_tt_") or data.startswith("subcat_yt_") or data.startswith("subcat_ig_"):
        cat_key = data.replace("subcat_", "")
        context.user_data["current_cat_key"] = cat_key
        if cat_key in SERVICES:
            text, reply_markup = service_items_keyboard(cat_key)
            await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "menu_gitcode":
        text = (
            f"🎁 NHẬP MÃ GITCODE KHUYẾN MÃI\n"
            f"----------------------------------------\n"
            f"👇 Vui lòng gửi mã Gitcode của bạn vào đây để nhận thưởng số dư trực tiếp:"
        )
        keyboard = [[InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
        msg = await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        context.user_data["prompt_msg_id"] = msg.message_id
        return INPUT_GITCODE

    elif data == "admin_list_users":
        if not is_admin(user.id, user.username):
            return
        
        if not USERS_DB:
            text = "ℹ️ Hiện chưa có khách hàng nào sử dụng bot."
        else:
            text = "👥 DANH SÁCH KHÁCH HÀNG Đang SỬ DỤNG BOT:\n----------------------------------------\n"
            for uid, info in USERS_DB.items():
                text += f"• 🆔 ID: `{uid}` | 💰 Số dư: {info.get('balance', 0):,.0f}đ\n"
            text += "\n👇 Bấm nút bên dưới để chỉnh sửa hoặc xóa số dư khách hàng:"

        keyboard = [
            [InlineKeyboardButton("✏️ Sửa / Xóa số dư khách", callback_data="admin_prompt_edit_balance")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_prompt_edit_balance":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"✏️ CHỈNH SỬA / XÓA SỐ DƯ KHÁCH HÀNG\n"
            f"----------------------------------------\n"
            f"💬 Gửi tin nhắn theo cú pháp: `<ID_KHÁCH> <SỐ_TIỀN_MỚI>`\n"
            f"*(Ví dụ muốn chỉnh số dư về 0 hoặc xóa số dư: `6900793565 0`)*\n"
            f"*(Ví dụ muốn set 500k: `6900793565 500000`)*"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_ADMIN_EDIT_USER

    elif data == "admin_gitcode_menu":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"🎁 QUẢN LÝ MÃ GITCODE KHUYẾN MÃI\n"
            f"----------------------------------------\n"
            f"👇 Chọn thao tác bạn muốn thực hiện:"
        )
        keyboard = [
            [InlineKeyboardButton("➕ Tạo Gitcode Mới", callback_data="admin_create_gc_sub")],
            [InlineKeyboardButton("📋 Xem danh sách & Xóa Gitcode", callback_data="admin_list_gitcodes")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_create_gc_sub":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"➕ TẠO MÃ GITCODE KHUYẾN MÃI\n"
            f"----------------------------------------\n"
            f"👇 Chọn nhanh mệnh giá hoặc tự viết mã và số tiền theo ý muốn:"
        )
        keyboard = [
            [InlineKeyboardButton("💵 10.000 đ", callback_data="create_gc:10000"), InlineKeyboardButton("💵 20.000 đ", callback_data="create_gc:20000"), InlineKeyboardButton("💵 50.000 đ", callback_data="create_gc:50000")],
            [InlineKeyboardButton("💵 100.000 đ", callback_data="create_gc:100000")],
            [InlineKeyboardButton("✍️ Tự viết Mã & Số tiền tùy ý", callback_data="create_gc_custom")],
            [InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_list_gitcodes":
        if not is_admin(user.id, user.username):
            return
        
        if not GITCODE_DB:
            text = "ℹ️ Hiện tại hệ thống chưa có mã Gitcode nào được tạo."
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")]]
        else:
            text = f"📋 DANH SÁCH MÃ GITCODE ĐÃ TẠO ({len(GITCODE_DB)} mã):\n----------------------------------------\n"
            keyboard = []
            for code, info in GITCODE_DB.items():
                used_count = len(info.get("used_by", []))
                text += f"• 🎁 Mã: `{code}` | 💵 Giá trị: {info.get('amount', 0):,.0f}đ | 👤 Đã dùng: {used_count} lần\n"
                keyboard.append([InlineKeyboardButton(f"🗑️ Xóa mã: {code}", callback_data=f"delete_gc:{code}")])
            
            keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")])

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("delete_gc:"):
        if not is_admin(user.id, user.username):
            return
        code_to_delete = data.split(":")[1]
        if code_to_delete in GITCODE_DB:
            del GITCODE_DB[code_to_delete]
            save_gitcode_db()
            await query.answer(f"✅ Đã xóa thành công mã {code_to_delete}!", show_alert=True)
        else:
            await query.answer("⚠️ Mã không tồn tại hoặc đã bị xóa trước đó!", show_alert=True)
        
        if not GITCODE_DB:
            text = "ℹ️ Hiện tại hệ thống chưa có mã Gitcode nào được tạo."
            keyboard = [[InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")]]
        else:
            text = f"📋 DANH SÁCH MÃ GITCODE ĐÃ TẠO ({len(GITCODE_DB)} mã):\n----------------------------------------\n"
            keyboard = []
            for code, info in GITCODE_DB.items():
                used_count = len(info.get("used_by", []))
                text += f"• 🎁 Mã: `{code}` | 💵 Giá trị: {info.get('amount', 0):,.0f}đ | 👤 Đã dùng: {used_count} lần\n"
                keyboard.append([InlineKeyboardButton(f"🗑️ Xóa mã: {code}", callback_data=f"delete_gc:{code}")])
            keyboard.append([InlineKeyboardButton("↩️ Trở về", callback_data="admin_gitcode_menu")])

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
            f"✅ ĐÃ TẠO VÀ LƯU GITCODE THÀNH CÔNG!\n\n"
            f"🎁 Mã Gitcode: `{code}`\n"
            f"💵 Mệnh giá: {amount:,.0f} VND\n\n"
            f"ℹ️ Mã đã được lưu tự động, bấm vào quản lý để xem danh sách."
        )
        keyboard = [
            [InlineKeyboardButton("📋 Xem danh sách Gitcode", callback_data="admin_list_gitcodes")],
            [InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "create_gc_custom":
        if not is_admin(user.id, user.username):
            return
        text = (
            f"✍️ TỰ VIẾT MÃ VÀ SỐ TIỀN CHO GITCODE\n"
            f"----------------------------------------\n"
            f"💬 Nhắn tin theo cú pháp: `<MÃ_CODE> <SỐ_TIỀN>`\n"
            f"*(Ví dụ: `TET2026 100000`)*"
        )
        keyboard = [[InlineKeyboardButton("↩️ Trở về Quản Lý", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_CREATE_CODE_CUSTOM

    elif data == "view_history":
        user_data = get_user_data(user.id)
        history = user_data.get("history", [])
        
        if not history:
            history_text = "ℹ️ Bạn chưa có lịch sử giao dịch hoặc sử dụng dịch vụ nào."
        else:
            history_text = "📜 LỊCH SỬ GIAO DỊCH & DỊCH VỤ ĐÃ DÙNG:\n----------------------------------------\n"
            for idx, item in enumerate(reversed(history[-15:]), 1):
                history_text += f"{idx}. {item}\n\n"

        keyboard = [[InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")]]
        await query.edit_message_text(history_text, reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

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
                f"📦 ĐÃ CHỌN: {selected_item['name']}\n"
                f"💵 GIÁ: {selected_item['price']}đ / đơn vị\n\n"
                f"🔗 GỬI LINK TĂNG TƯƠNG TÁC:\n"
                f"• Vui lòng gửi Link bài viết / trang cá nhân / video cần tăng tương tác.\n"
                f"• *Ví dụ:* `https://...`\n\n"
                f"💬 Nhắn link của bạn vào đây:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data["prompt_msg_id"] = msg.message_id
            return INPUT_LINK

    elif data == "nap_tien":
        keyboard = [
            [InlineKeyboardButton("💵 10.000 đ", callback_data="amount:10000"), InlineKeyboardButton("💵 50.000 đ", callback_data="amount:50000"), InlineKeyboardButton("💵 100.000 đ", callback_data="amount:100000")],
            [InlineKeyboardButton("💵 200.000 đ", callback_data="amount:200000"), InlineKeyboardButton("💵 500.000 đ", callback_data="amount:500000"), InlineKeyboardButton("💵 1.000.000 đ", callback_data="amount:1000000")],
            [InlineKeyboardButton("⌨️ Nhập số tiền khác", callback_data="custom_amount")],
            [InlineKeyboardButton("🏠 Trở về Menu", callback_data="menu_main")]
        ]
        text = "💳 CHỌN MỆNH GIÁ NẠP TIỀN\n\n👇 Chọn nhanh mệnh giá từ 10k đến 1tr hoặc nhập số tiền khác:"
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "custom_amount":
        await query.edit_message_text("⌨️ NHẬP SỐ TIỀN MUỐN NẠP\n\n💬 Nhắn số tiền bạn muốn nạp (Ví dụ: 150000):")
        return INPUT_TOPUP_AMOUNT

    elif data.startswith("amount:"):
        amount = int(data.split(":")[1])
        qr_url = f"https://img.vietqr.io/image/{BANK_INFO['bank_name']}-{BANK_INFO['account_no']}-compact2.png?amount={amount}&addInfo={user.id}&accountName={BANK_INFO['account_name'].replace(' ', '%20')}"
        text = (
            f"💳 THÔNG TIN CHUYỂN KHOẢN NẠP TIỀN\n"
            f"----------------------------------------\n"
            f"🏦 Ngân hàng: {BANK_INFO['bank_name']}\n"
            f"🔢 Số tài khoản: `{BANK_INFO['account_no']}`\n"
            f"👤 Chủ tài khoản: {BANK_INFO['account_name']}\n"
            f"💵 Số tiền: {amount:,.0f} VND\n"
            f"📝 Nội dung chuyển khoản (BẮT BUỘC): `{user.id}`\n\n"
            f"⚠️ LƯU Ý QUAN TRỌNG:\n"
            f"• Vui lòng kiểm tra kỹ Nội dung chuyển khoản phải chính xác là ID của bạn (`{user.id}`) để hệ thống tự động cộng tiền.\n"
            f"• Nếu chuyển sai nội dung, tiền sẽ không được cộng tự động và bạn cần liên hệ Admin hỗ trợ!\n"
            f"----------------------------------------\n"
            f"👇 Sau khi chuyển khoản xong, bấm nút [Đã chuyển khoản] bên dưới!"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Đã chuyển khoản", callback_data=f"confirm_trans:{amount}")],
            [InlineKeyboardButton("🔄 Chọn lại mệnh giá", callback_data="nap_tien")]
        ]
        await query.message.delete()
        await context.bot.send_photo(chat_id=user.id, photo=qr_url, caption=text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("confirm_trans:"):
        amount = float(data.split(":")[1])
        await query.edit_message_caption(
            caption=f"⏳ Đã gửi yêu cầu nạp {amount:,.0f} VND. Vui lòng đợi Admin duyệt!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Trở về Menu", callback_data="menu_main")]])
        )
        user_mention = get_user_mention(user)

        admin_notice = (
            f"🔔 YÊU CẦU NẠP TIỀN MỚI!\n"
            f"----------------------------------------\n"
            f"👤 Khách hàng: {user_mention} (ID: `{user.id}`)\n"
            f"💵 Số tiền: {amount:,.0f} VND\n"
            f"📝 Nội dung CK: `{user.id}`"
        )
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Duyệt cộng {amount:,.0f}đ", callback_data=f"admin_approve_topup:{user.id}:{amount}")],
            [InlineKeyboardButton("❌ Chưa nhận được tiền", callback_data=f"admin_reject_topup:{user.id}:{amount}")]
        ])
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notice, parse_mode="Markdown", reply_markup=btn)
        except Exception:
            pass

    elif data.startswith("admin_approve_topup:"):
        _, target_id_str, amount_str = data.split(":")
        target_id, amount = int(target_id_str), float(amount_str)
        user_data = get_user_data(target_id)
        user_data["balance"] += amount
        save_users_db() 
        
        new_bal = user_data["balance"]
        
        try:
            target_user = await context.bot.get_chat(target_id)
            user_tag = f"@{target_user.username}" if target_user.username else f"ID `{target_id}`"
        except Exception:
            user_tag = f"ID `{target_id}`"

        await query.edit_message_text(f"✅ Đã cộng {amount:,.0f}đ cho khách {user_tag}")
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🎉 BẠN ĐÃ ĐƯỢC CỘNG TIỀN THÀNH CÔNG!\n\n💰 Số tiền nạp: +{amount:,.0f} VND\n💳 Số dư hiện tại: {new_bal:,.0f} VND"
            )
        except Exception:
            pass

    elif data.startswith("admin_reject_topup:"):
        _, target_id_str, amount_str = data.split(":")
        target_id, amount = int(target_id_str), float(amount_str)
        
        try:
            target_user = await context.bot.get_chat(target_id)
            user_link_str = get_user_mention(target_user)
        except Exception:
            user_link_str = f"ID `{target_id}`"

        await query.edit_message_text(f"❌ Đã từ chối/báo chưa nhận được tiền cho giao dịch {amount:,.0f}đ của khách {user_link_str} (ID: `{target_id}`).", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_id, text=f"⚠️ Giao dịch nạp {amount:,.0f} VND của bạn chưa được xác nhận tiền về tài khoản. Vui lòng liên hệ Admin {ADMIN_USERNAME} để được hỗ trợ!")
        except Exception:
            pass

    elif data.startswith("admin_accept_order:"):
        new_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Đã nhận đơn", callback_data="none")]
        ])
        try:
            current_text = query.message.text
            await query.edit_message_text(text=current_text + "\n\n🟢 STATUS: ĐÃ NHẬN ĐƠN", parse_mode="Markdown", reply_markup=new_keyboard)
        except Exception:
            pass

    elif data.startswith("admin_reject_order:"):
        try:
            current_text = query.message.text
            await query.edit_message_text(text=current_text + "\n\n🔴 STATUS: ĐÃ TỪ CHỐI ĐƠN", parse_mode="Markdown")
        except Exception:
            pass

    elif data == "products_p1":
        text, reply_markup = products_menu_keyboard(page=1)
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "products_p2":
        text, reply_markup = products_menu_keyboard(page=2)
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "item_cat_groups":
        text, reply_markup = groups_menu_keyboard(page=1)
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "groups_p1":
        text, reply_markup = groups_menu_keyboard(page=1)
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data == "groups_p2":
        text, reply_markup = groups_menu_keyboard(page=2)
        await query.edit_message_text(text, reply_markup=reply_markup)

    elif data.startswith("item_") and data != "item_cat_groups":
        cat_id = data.replace("item_", "")
        stock = get_stock_count(cat_id)
        text = (
            f"📦 CHI TIẾT CHUYÊN MỤC SẢN PHẨM\n"
            f"----------------------------------------\n"
            f"📊 Số lượng hàng trong kho: {stock}\n\n"
            f"ℹ️ Hiện tại hệ thống đang cập nhật tài khoản tự động cho mục này. Vui lòng liên hệ Admin nếu cần mua gấp!"
        )
        keyboard = [
            [InlineKeyboardButton("📞 Liên hệ Admin", url=f"https://t.me/{ADMIN_USERNAME.replace('@','')}")],
            [
                InlineKeyboardButton("↩️ Trở về", callback_data="products_p1"),
                InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
            ]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("group_detail_"):
        group_id = data.replace("group_detail_", "")
        all_groups = GROUPS_PAGE_1 + GROUPS_PAGE_2
        selected_group = next((g for g in all_groups if g["id"] == group_id), None)
        
        if not selected_group:
            await query.edit_message_text("❌ Không tìm thấy thông tin nhóm!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu_main")]]))
            return

        mem_count = selected_group['mem']
        total_price = mem_count * 20
        
        mem_formatted = f"{mem_count:,}"
        price_formatted = f"{total_price:,.0f}"

        text = (
            f"📋 XÁC NHẬN MUA NHÓM\n"
            f"----------------------------------------\n"
            f"👥 Tên Group: {selected_group['name']}\n"
            f"📊 Số thành viên: {mem_formatted} mem\n"
            f"💵 Thành tiền: {price_formatted} VNĐ\n"
            f"----------------------------------------\n"
            f"👇 Bấm nút Thanh toán bên dưới để hoàn tất đơn hàng."
        )
        
        is_page_1 = any(g['id'] == group_id for g in GROUPS_PAGE_1)
        keyboard = [
            [InlineKeyboardButton("💳 Thanh toán", callback_data=f"paygroup_{group_id}")],
            [
                InlineKeyboardButton("↩️ Trở về", callback_data="groups_p1" if is_page_1 else "groups_p2"),
                InlineKeyboardButton("🏠 Menu Chính", callback_data="menu_main")
            ]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

    elif data.startswith("paygroup_"):
        group_id = data.replace("paygroup_", "")
        all_groups = GROUPS_PAGE_1 + GROUPS_PAGE_2
        selected_group = next((g for g in all_groups if g["id"] == group_id), None)
        
        if not selected_group:
            await query.edit_message_text("❌ Không tìm thấy thông tin nhóm!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu_main")]]))
            return

        mem_count = selected_group['mem']
        total_price = mem_count * 20
        user_data = get_user_data(user.id)
        
        if user_data["balance"] < total_price:
            msg_text = (
                f"❌ SỐ DƯ KHÔNG ĐỦ!\n\n"
                f"💳 Số dư của bạn: {user_data['balance']:,.0f}đ\n"
                f"💵 Giá nhóm: {total_price:,.0f}đ\n\n"
                f"⚠️ Vui lòng nạp thêm tiền để mua nhóm!"
            )
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Nạp tiền ngay", callback_data="nap_tien"), InlineKeyboardButton("🏠 Menu", callback_data="menu_main")]])
            await query.edit_message_text(msg_text, reply_markup=keyboard)
            return

        user_data["balance"] -= total_price
        user_data["history"].append(f"Mua Nhóm: {selected_group['name']} | Giá: {total_price:,.0f}đ")
