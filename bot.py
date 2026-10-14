import asyncio
import json
import os
import re
import time

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# ===== الإعدادات =====
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ضع_التوكن_هنا")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # معرّفك الرقمي في تليكرام
DATA_FILE = os.environ.get("DATA_FILE", "link.json")  # على Railway اجعله /data/link.json (Volume)


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("link", None)
    data.setdefault("users", [])
    data.setdefault("ttl", None)         # مدة الحذف التلقائي بالثواني (None = معطّل)
    data.setdefault("expires_at", None)  # وقت انتهاء الرابط الحالي
    if data["link"] and data["expires_at"] and time.time() >= data["expires_at"]:
        data["link"] = None
        data["expires_at"] = None
        save_data(data)
    return data


def parse_duration(text: str):
    """يحوّل 30m / 2h / 1d إلى ثوانٍ. بدون وحدة = دقائق."""
    m = re.fullmatch(r"(\d+)\s*([mhd]?)", text.strip().lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2) or "m"
    seconds = n * {"m": 60, "h": 3600, "d": 86400}[unit]
    return seconds if seconds > 0 else None


def fmt_duration(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400} يوم"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} ساعة"
    return f"{max(seconds // 60, 1)} دقيقة"


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == ADMIN_ID


def subscribe(user_id: int):
    """تسجيل العميل ليصله إشعار عند تغيير الرابط."""
    data = load_data()
    if user_id not in data["users"]:
        data["users"].append(user_id)
        save_data(data)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_text(
            "أهلاً بك أيها المشرف.\n\n"
            "• أرسل أي رابط لحفظه (يستبدل القديم ويُخطر العملاء)\n"
            "• /delete لحذف الرابط الحالي\n"
            "• /deploy لعرض الرابط الحالي\n"
            "• /users لعرض عدد المشتركين\n"
            "• /expire لضبط الحذف التلقائي بعد مدة (مثال: /expire 2h)"
        )
    else:
        subscribe(update.effective_user.id)
        await update.message.reply_text(
            "أهلاً بك! اكتب /deploy للحصول على الرابط.\n"
            "ستصلك رسالة تلقائية عند نشر رابط جديد. لإيقاف الإشعارات اكتب /stop"
        )


async def deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        subscribe(update.effective_user.id)
    link = load_data()["link"]
    if link:
        await update.message.reply_text(link)
    else:
        await update.message.reply_text("لا يوجد في الوقت الحالي")


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = update.effective_user.id
    if uid in data["users"]:
        data["users"].remove(uid)
        save_data(data)
    await update.message.reply_text("تم إيقاف الإشعارات. اكتب /start لتفعيلها من جديد.")


async def users_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(f"عدد المشتركين: {len(load_data()['users'])}")


async def delete_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    data = load_data()
    if data["link"]:
        data["link"] = None
        data["expires_at"] = None
        save_data(data)
        await update.message.reply_text("تم حذف الرابط ✅")
    else:
        await update.message.reply_text("لا يوجد رابط محفوظ لحذفه.")


async def expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    data = load_data()
    arg = context.args[0] if context.args else ""

    if not arg:
        if data["ttl"]:
            msg = f"الحذف التلقائي مفعّل: {fmt_duration(data['ttl'])} لكل رابط."
            if data["link"] and data["expires_at"]:
                left = max(int(data["expires_at"] - time.time()), 0)
                msg += f"\nالمتبقي للرابط الحالي: {max(left // 60, 1)} دقيقة تقريباً."
        else:
            msg = "الحذف التلقائي معطّل."
        await update.message.reply_text(
            msg + "\n\nالاستخدام:\n/expire 30m (دقائق)\n/expire 2h (ساعات)\n/expire 1d (أيام)\n/expire off (إيقاف)"
        )
        return

    if arg.lower() in ("off", "0", "ايقاف", "إيقاف"):
        data["ttl"] = None
        data["expires_at"] = None
        save_data(data)
        await update.message.reply_text("تم إيقاف الحذف التلقائي ✅")
        return

    seconds = parse_duration(arg)
    if not seconds:
        await update.message.reply_text("صيغة غير صحيحة. مثال: /expire 30m أو /expire 2h أو /expire 1d")
        return

    data["ttl"] = seconds
    if data["link"]:
        data["expires_at"] = time.time() + seconds  # يبدأ العدّ من الآن للرابط الحالي
    save_data(data)
    await update.message.reply_text(
        f"تم تفعيل الحذف التلقائي بعد {fmt_duration(seconds)} ✅\n"
        "ينطبق على الرابط الحالي (من الآن) وعلى كل رابط جديد."
    )


async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("أرسل الرابط كنص.")
        return

    data = load_data()
    data["link"] = text  # يُحفظ كما أرسلته (مع أو بدون http/https) ويستبدل القديم
    data["expires_at"] = time.time() + data["ttl"] if data["ttl"] else None
    save_data(data)
    await update.message.reply_text("تم حفظ الرابط الجديد ✅ (وحُذف القديم)\nجارٍ إخطار العملاء...")

    sent, failed = 0, 0
    blocked = []
    for uid in data["users"]:
        try:
            await context.bot.send_message(uid, f"🔔 تم نشر رابط جديد:\n{data['link']}")
            sent += 1
        except TelegramError:
            failed += 1
            blocked.append(uid)  # العميل حظر البوت أو حذف المحادثة
        await asyncio.sleep(0.05)  # تجنّب حدود تليكرام

    if blocked:
        data = load_data()
        data["users"] = [u for u in data["users"] if u not in blocked]
        save_data(data)

    await update.message.reply_text(f"تم الإرسال إلى {sent} عميل. فشل: {failed}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("deploy", deploy))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("users", users_count))
    app.add_handler(CommandHandler("delete", delete_link))
    app.add_handler(CommandHandler("expire", expire))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link))
    app.run_polling()


if __name__ == "__main__":
    main()
