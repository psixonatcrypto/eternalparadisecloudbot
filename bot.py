# -*- coding: utf-8 -*-
import os
import logging
import sqlite3
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- Переменные окружения ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DB_NAME = "files.db"

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("BOT_TOKEN и CHANNEL_ID должны быть заданы")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- База данных ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS files (
        key TEXT PRIMARY KEY,
        file_id TEXT NOT NULL,
        filename TEXT,
        chat_id TEXT,
        message_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def save_file_info(key, file_id, filename, chat_id, message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO files (key, file_id, filename, chat_id, message_id) VALUES (?, ?, ?, ?, ?)',
              (key, file_id, filename, chat_id, message_id))
    conn.commit()
    conn.close()

def get_file_info(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT file_id, filename FROM files WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return {"file_id": row[0], "filename": row[1]} if row else None

def delete_file_info(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM files WHERE key = ?', (key,))
    conn.commit()
    conn.close()

# --- Клавиатуры ---
def main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 Загрузить файл", callback_data="upload")],
        [InlineKeyboardButton("🔍 Получить по ключу", callback_data="get_prompt")],
        [InlineKeyboardButton("❌ Удалить по ключу", callback_data="delete_prompt")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def file_actions_keyboard(key, file_link):
    keyboard = [
        [InlineKeyboardButton("📥 Скачать", url=file_link)],
        [InlineKeyboardButton("📋 Копировать ключ", callback_data=f"copy_{key}")],
        [InlineKeyboardButton("🔁 Получить файл сюда", callback_data=f"get_{key}")],
        [InlineKeyboardButton("❌ Удалить ссылку", callback_data=f"delete_{key}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Команды и обработчики ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот-файлообменник.\n"
        "Отправь мне любой файл – я сохраню его в канале и дам ссылку.\n"
        "Используй кнопки ниже:",
        reply_markup=main_keyboard()
    )

async def help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 *Как пользоваться:*\n"
        "1. Отправьте файл – получу ссылку и ключ.\n"
        "2. По ссылке файл может скачать кто угодно.\n"
        "3. Команды: /get <ключ>, /delete <ключ> – или кнопки.\n\n"
        "Канал для хранения: " + CHANNEL_ID,
        parse_mode="Markdown"
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if message.document:
        file_id = message.document.file_id
        filename = message.document.file_name
    elif message.photo:
        file_id = message.photo[-1].file_id
        filename = f"photo_{file_id[:10]}.jpg"
    elif message.video:
        file_id = message.video.file_id
        filename = message.video.file_name or f"video_{file_id[:10]}.mp4"
    elif message.audio:
        file_id = message.audio.file_id
        filename = message.audio.file_name or f"audio_{file_id[:10]}.mp3"
    elif message.voice:
        file_id = message.voice.file_id
        filename = f"voice_{file_id[:10]}.ogg"
    else:
        await update.message.reply_text("❌ Неподдерживаемый тип файла.")
        return

    try:
        sent = await context.bot.send_document(
            chat_id=CHANNEL_ID,
            document=file_id,
            caption=f"📁 Файл от {user.first_name}"
        )
        key = str(uuid4())[:8]
        save_file_info(key, file_id, filename, CHANNEL_ID, sent.message_id)
        link = f"https://t.me/{CHANNEL_ID.lstrip('@')}/{sent.message_id}"
        await update.message.reply_text(
            f"✅ Файл *{filename}* сохранён!\n\n🔗 Ссылка: {link}\n📌 Ключ: `{key}`",
            parse_mode="Markdown",
            reply_markup=file_actions_keyboard(key, link)
        )
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Ошибка. Проверьте, что бот – администратор канала.")

async def get_file_by_key(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    info = get_file_info(key)
    if not info:
        await update.callback_query.answer("❌ Файл не найден", show_alert=True)
        return
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=info["file_id"],
        filename=info["filename"],
        caption=f"📎 Ваш файл по ключу `{key}`"
    )
    await update.callback_query.answer()

async def delete_file_by_key(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    if get_file_info(key):
        delete_file_info(key)
        await update.callback_query.answer("✅ Файл удалён", show_alert=True)
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    else:
        await update.callback_query.answer("❌ Ключ не найден", show_alert=True)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "upload":
        await query.answer("Просто отправьте мне любой файл")
    elif data == "get_prompt":
        await query.message.reply_text("Введите ключ командой: `/get ключ`", parse_mode="Markdown")
        await query.answer()
    elif data == "delete_prompt":
        await query.message.reply_text("Введите ключ командой: `/delete ключ`", parse_mode="Markdown")
        await query.answer()
    elif data == "help":
        await query.message.reply_text(
            "📌 *Справка*\n\n"
            "Отправьте файл – получу ссылку.\n"
            "/get ключ – получить файл\n"
            "/delete ключ – удалить ссылку\n\n"
            "Кнопки под файлом позволяют скачать, скопировать ключ, получить или удалить.",
            parse_mode="Markdown"
        )
        await query.answer()
    elif data.startswith("copy_"):
        key = data[5:]
        await query.answer(f"Ключ: {key}", show_alert=True)
    elif data.startswith("get_"):
        key = data[4:]
        await get_file_by_key(update, context, key)
    elif data.startswith("delete_"):
        key = data[7:]
        await delete_file_by_key(update, context, key)
    else:
        await query.answer()

# --- Команды /get и /delete (текстовые) ---
async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите ключ: `/get ключ`", parse_mode="Markdown")
        return
    key = context.args[0]
    info = get_file_info(key)
    if not info:
        await update.message.reply_text("❌ Файл не найден.")
        return
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=info["file_id"],
        filename=info["filename"],
        caption=f"📎 Ваш файл по ключу `{key}`"
    )

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите ключ: `/delete ключ`", parse_mode="Markdown")
        return
    key = context.args[0]
    if get_file_info(key):
        delete_file_info(key)
        await update.message.reply_text(f"✅ Ключ `{key}` удалён.")
    else:
        await update.message.reply_text("❌ Ключ не найден.")

# --- Запуск ---
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_text))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_file
    ))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот с кнопками запущен")
    app.run_polling()

if __name__ == "__main__":
    main()