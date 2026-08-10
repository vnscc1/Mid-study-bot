"""
بوت المساعد الدراسي الطبي - Telegram Bot
يلخص المحاضرات الطبية، يولّد أسئلة مراجعة، ويشرح المصطلحات
"""

import os
import logging
import asyncio
from datetime import datetime, date
from io import BytesIO

import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from db import Database
from file_extract import extract_text_from_file

# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

FREE_DAILY_LIMIT = 5
MODEL = "claude-sonnet-4-5"  # عدّل لأي موديل تفضله

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
db = Database("bot_data.db")

# نخزن آخر محتوى رفعه كل مستخدم عشان نولّد منه أسئلة لاحقًا
last_content_cache: dict[int, str] = {}

MEDICAL_SYSTEM_PROMPT = """أنت مساعد دراسي متخصص في المواد الطبية (تشريح، علم أمراض النطق واللغة SLP، فسيولوجي، وما شابه).
مهمتك تلخيص المحتوى الطبي بدقة علمية وبأسلوب واضح بالعربية الفصحى المبسطة، مع الحفاظ على المصطلحات الطبية الدقيقة (تقدر تكتب المصطلح بالإنجليزي بين قوسين إذا يفيد الطالب).
لا تختصر بشكل يفقد المعلومة العلمية أهميتها. رتب التلخيص بنقاط واضحة وعناوين فرعية إذا كان المحتوى طويل."""


# ---------------------------------------------------------------------------
# دوال مساعدة
# ---------------------------------------------------------------------------

async def check_and_increment_usage(user_id: int) -> tuple[bool, int]:
    """يرجع (مسموح؟, عدد الطلبات المتبقية اليوم). يزيد العداد إذا مسموح."""
    is_premium = db.is_premium(user_id)
    if is_premium:
        return True, -1  # غير محدود

    today = date.today().isoformat()
    count = db.get_usage_count(user_id, today)
    if count >= FREE_DAILY_LIMIT:
        return False, 0

    db.increment_usage(user_id, today)
    remaining = FREE_DAILY_LIMIT - (count + 1)
    return True, remaining


def call_claude(user_message: str, system: str = MEDICAL_SYSTEM_PROMPT, max_tokens: int = 2000) -> str:
    response = claude_client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# أوامر البوت
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.ensure_user(update.effective_user.id)
    text = (
        "أهلًا فيك! 👋\n\n"
        "أنا مساعدك الدراسي للمواد الطبية. أقدر أساعدك في:\n\n"
        "📄 *تلخيص محاضرة* — أرسل ملف PDF أو صورة أو نص المحاضرة\n"
        "❓ *أسئلة مراجعة* — اكتب /quiz بعد ما ترسل محتوى\n"
        "📖 *شرح مصطلح* — اكتب /explain متبوع بالمصطلح\n\n"
        f"النسخة المجانية: {FREE_DAILY_LIMIT} طلبات يوميًا\n"
        "للترقية اكتب /upgrade"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def explain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)

    if not context.args:
        await update.message.reply_text("اكتب المصطلح بعد الأمر، مثال:\n`/explain Broca's Area`", parse_mode="Markdown")
        return

    allowed, remaining = await check_and_increment_usage(user_id)
    if not allowed:
        await send_limit_reached(update)
        return

    term = " ".join(context.args)
    await update.message.reply_chat_action("typing")

    prompt = f"اشرح المصطلح الطبي التالي بشكل واضح ومختصر لطالب طب/علوم صحية: {term}"
    try:
        explanation = call_claude(prompt, max_tokens=800)
        await update.message.reply_text(explanation)
        await maybe_notify_remaining(update, remaining)
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        await update.message.reply_text("صار خطأ أثناء المعالجة، حاول مرة ثانية.")


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)

    content = last_content_cache.get(user_id)
    if not content:
        await update.message.reply_text("لازم ترسل محاضرة أو نص أول (ملف أو رسالة نصية) قبل ما أقدر أسوي لك أسئلة.")
        return

    allowed, remaining = await check_and_increment_usage(user_id)
    if not allowed:
        await send_limit_reached(update)
        return

    await update.message.reply_chat_action("typing")
    prompt = (
        "بناءً على المحتوى التالي، سوّ لي 5 أسئلة مراجعة (اختيار من متعدد، كل سؤال له 4 خيارات وحدد الإجابة الصحيحة في النهاية):\n\n"
        f"{content}"
    )
    try:
        questions = call_claude(prompt, max_tokens=1500)
        await update.message.reply_text(questions)
        await maybe_notify_remaining(update, remaining)
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        await update.message.reply_text("صار خطأ أثناء المعالجة، حاول مرة ثانية.")


async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🌟 *النسخة المدفوعة*\n\n"
        "- طلبات غير محدودة يوميًا\n"
        "- رفع ملفات أكبر\n"
        "- حفظ سجل الملخصات\n\n"
        "للاشتراك تواصل مع الدعم: @vncsc_username\n"
        "(اربط هنا بوابة الدفع اللي تفضلها لاحقًا)"
    )
    await update.message.reply_text(text)


async def send_limit_reached(update: Update):
    await update.message.reply_text(
        f"وصلت الحد اليومي المجاني ({FREE_DAILY_LIMIT} طلبات). "
        "جرّب بكرة أو اترقّى للنسخة المدفوعة عبر /upgrade"
    )


async def maybe_notify_remaining(update: Update, remaining: int):
    if remaining >= 0 and remaining <= 2:
        await update.message.reply_text(f"⚠️ باقي لك {remaining} طلبات مجانية اليوم.")


# ---------------------------------------------------------------------------
# استقبال الملفات والنصوص
# ---------------------------------------------------------------------------

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)

    allowed, remaining = await check_and_increment_usage(user_id)
    if not allowed:
        await send_limit_reached(update)
        return

    await update.message.reply_chat_action("typing")
    status_msg = await update.message.reply_text("جاري استخراج النص من الملف...")

    try:
        file = await update.message.document.get_file()
        file_bytes = await file.download_as_bytearray()
        filename = update.message.document.file_name or "file"

        extracted_text = extract_text_from_file(bytes(file_bytes), filename)
        if not extracted_text.strip():
            await status_msg.edit_text("ما قدرت أستخرج نص من الملف. جرب ملف ثاني أو انسخ النص مباشرة.")
            return

        last_content_cache[user_id] = extracted_text[:15000]  # حد أقصى تحسبًا لطول النص

        await status_msg.edit_text("جاري التلخيص...")
        summary_prompt = f"لخّص المحتوى الطبي التالي:\n\n{extracted_text[:15000]}"
        summary = call_claude(summary_prompt)

        await status_msg.delete()
        await update.message.reply_text(summary)
        await update.message.reply_text("تقدر تكتب /quiz عشان أسوي لك أسئلة مراجعة من نفس المحتوى.")
        await maybe_notify_remaining(update, remaining)

    except Exception as e:
        logger.error(f"File handling error: {e}")
        await status_msg.edit_text("صار خطأ أثناء معالجة الملف، حاول مرة ثانية.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    text = update.message.text

    if len(text) < 50:
        await update.message.reply_text(
            "ارسل لي محاضرة أطول أو ملف عشان ألخصها، أو استخدم /explain لشرح مصطلح معين."
        )
        return

    allowed, remaining = await check_and_increment_usage(user_id)
    if not allowed:
        await send_limit_reached(update)
        return

    last_content_cache[user_id] = text[:15000]

    await update.message.reply_chat_action("typing")
    try:
        summary = call_claude(f"لخّص المحتوى الطبي التالي:\n\n{text[:15000]}")
        await update.message.reply_text(summary)
        await update.message.reply_text("تقدر تكتب /quiz عشان أسوي لك أسئلة مراجعة من نفس المحتوى.")
        await maybe_notify_remaining(update, remaining)
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        await update.message.reply_text("صار خطأ أثناء المعالجة، حاول مرة ثانية.")


# ---------------------------------------------------------------------------
# التشغيل
# ---------------------------------------------------------------------------

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("ضع TELEGRAM_BOT_TOKEN في متغيرات البيئة")
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ضع ANTHROPIC_API_KEY في متغيرات البيئة")

    db.init()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("explain", explain))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("upgrade", upgrade))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
