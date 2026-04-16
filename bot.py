# -*- coding: utf-8 -*-
import os
import logging
import sqlite3
import asyncio
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ========== НАСТРОЙКИ (измените под себя) ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DB_NAME = "files.db"

# Ваш Telegram ID (узнайте у @userinfobot)
ADMIN_ID = 483977434          # ВСТАВЬТЕ СВОЙ ID (число)
BOT_USERNAME = "eternalparadisecloudbot"   # username вашего бота (без @)
# ===================================================

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("BOT_TOKEN и CHANNEL_ID должны быть заданы")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- База данных (файлы и пользователи) ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS files (
        key TEXT PRIMARY KEY,
        file_id TEXT NOT NULL,
        filename TEXT,
        chat_id TEXT,
        message_id INTEGER,
        media_type TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def save_file_info(key, file_id, filename, chat_id, message_id, media_type):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO files (key, file_id, filename, chat_id, message_id, media_type) VALUES (?, ?, ?, ?, ?, ?)',
              (key, file_id, filename, chat_id, message_id, media_type))
    conn.commit()
    conn.close()

def get_file_info(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT file_id, filename, media_type, message_id FROM files WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"file_id": row[0], "filename": row[1], "media_type": row[2], "message_id": row[3]}
    return None

def delete_file_info(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM files WHERE key = ?', (key,))
    conn.commit()
    conn.close()

def save_user(user_id, first_name, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (user_id, first_name, username, last_seen) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
              (user_id, first_name, username))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT user_id FROM users')
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

# --- Клавиатуры ---
def main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 Загрузить файл", callback_data="upload")],
        [InlineKeyboardButton("🔍 Получить по ключу", callback_data="get_prompt")],
        [InlineKeyboardButton("❌ Удалить по ключу", callback_data="delete_prompt")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def file_actions_keyboard(key):
    deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
    keyboard = [
        [InlineKeyboardButton("📥 Скачать файл", callback_data=f"download_{key}")],
        [InlineKeyboardButton("🔗 Поделиться ссылкой", callback_data=f"share_{key}")],
        [InlineKeyboardButton("📋 Копировать ключ", callback_data=f"copy_{key}")],
        [InlineKeyboardButton("❌ Удалить файл", callback_data=f"delete_{key}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Вспомогательная отправка файла ---
async def send_file_by_info(chat_id, info, key, bot):
    if info["media_type"] == "photo":
        await bot.send_photo(chat_id=chat_id, photo=info["file_id"], caption=f"📸 Ваше фото по ключу `{key}`")
    elif info["media_type"] == "video":
        await bot.send_video(chat_id=chat_id, video=info["file_id"], caption=f"🎬 Ваше видео по ключу `{key}`")
    elif info["media_type"] == "audio":
        await bot.send_audio(chat_id=chat_id, audio=info["file_id"], caption=f"🎵 Ваш аудиофайл по ключу `{key}`")
    elif info["media_type"] == "voice":
        await bot.send_voice(chat_id=chat_id, voice=info["file_id"], caption=f"🎙️ Ваше голосовое по ключу `{key}`")
    else:
        await bot.send_document(chat_id=chat_id, document=info["file_id"], filename=info["filename"])

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    if user:
        save_user(user.id, user.first_name, user.username)
    
    if context.args and len(context.args) > 0:
        key = context.args[0]
        info = get_file_info(key)
        if info:
            await send_file_by_info(update.effective_chat.id, info, key, context.bot)
            return
        else:
            await update.message.reply_text("❌ Файл по этой ссылке не найден.")
            return
    
    await update.message.reply_text(
        "👋 Привет! Я бот-файлообменник.\n"
        "Отправь мне любой файл – я сохраню его в облаке и дам ссылку.\n"
        "Используй кнопки ниже:",
        reply_markup=main_keyboard()
    )

async def help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📌 *Как пользоваться:*\n"
        "1. Отправьте файл – получу ключ и кнопки.\n"
        "2. Нажмите «Скачать файл» – бот пришлёт файл сюда.\n"
        "3. Нажмите «Поделиться ссылкой» – получите ссылку для отправки другим.\n"
        "4. Нажмите «Удалить файл» – удалит файл из канала и ссылку.\n\n"
        "Команды: /get <ключ>, /delete <ключ>, /broadcast (только админ)\n\n"
        "Если вы обнаружили баг, сообщите нам: @Eternal_paradise_supbot",
        parse_mode="Markdown"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только администратор может использовать эту команду.")
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Укажите текст рассылки после /broadcast")
        return
    users = get_all_users()
    if not users:
        await update.message.reply_text("Нет пользователей в базе.")
        return
    sent = 0
    failed = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            sent += 1
        except Exception as e:
            logger.error(f"Не удалось отправить {uid}: {e}")
            failed += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"📨 Рассылка завершена.\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    if user:
        save_user(user.id, user.first_name, user.username)

    message = update.effective_message
    if message.document:
        file_id = message.document.file_id
        filename = message.document.file_name
        media_type = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        filename = f"photo_{file_id[:10]}.jpg"
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        filename = message.video.file_name or f"video_{file_id[:10]}.mp4"
        media_type = "video"
    elif message.audio:
        file_id = message.audio.file_id
        filename = message.audio.file_name or f"audio_{file_id[:10]}.mp3"
        media_type = "audio"
    elif message.voice:
        file_id = message.voice.file_id
        filename = f"voice_{file_id[:10]}.ogg"
        media_type = "voice"
    else:
        await update.message.reply_text("❌ Неподдерживаемый тип файла.")
        return

    try:
        if media_type == "photo":
            sent = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=file_id, caption=f"📸 Фото от {user.first_name}")
        elif media_type == "video":
            sent = await context.bot.send_video(chat_id=CHANNEL_ID, video=file_id, caption=f"🎬 Видео от {user.first_name}")
        elif media_type == "audio":
            sent = await context.bot.send_audio(chat_id=CHANNEL_ID, audio=file_id, caption=f"🎵 Аудио от {user.first_name}")
        elif media_type == "voice":
            sent = await context.bot.send_voice(chat_id=CHANNEL_ID, voice=file_id, caption=f"🎙️ Голосовое от {user.first_name}")
        else:
            sent = await context.bot.send_document(chat_id=CHANNEL_ID, document=file_id, caption=f"📁 Файл от {user.first_name}")

        key = str(uuid4())[:8]
        save_file_info(key, file_id, filename, CHANNEL_ID, sent.message_id, media_type)
        link = f"https://t.me/{CHANNEL_ID.lstrip('@')}/{sent.message_id}"
        await update.message.reply_text(
            f"✅ Файл *{filename}* сохранён!\n\n"
            f"🔗 Ссылка (для других): {link}\n"
            f"📌 Ключ: `{key}`\n\n"
            f"Нажмите кнопку ниже, чтобы скачать файл сюда:",
            parse_mode="Markdown",
            reply_markup=file_actions_keyboard(key)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке в канал: {e}")
        await update.message.reply_text("❌ Ошибка. Проверьте, что бот – администратор канала и канал публичный.")

async def share_link(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    if not update.callback_query:
        return
    info = get_file_info(key)
    if not info:
        await update.callback_query.answer("❌ Файл не найден", show_alert=True)
        return
    
    deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
    
    await update.callback_query.message.reply_text(
        f"🔗 *Ссылка, чтобы поделиться файлом:*\n{deep_link}\n\n"
        f"Кто угодно может перейти по ссылке и сразу получить файл.",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await update.callback_query.answer()

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    if not update.callback_query:
        return
    info = get_file_info(key)
    if not info:
        await update.callback_query.answer("❌ Файл не найден", show_alert=True)
        return
    try:
        await send_file_by_info(update.effective_chat.id, info, key, context.bot)
        await update.callback_query.answer("✅ Файл отправлен!")
    except Exception as e:
        logger.error(f"Ошибка отправки файла: {e}")
        await update.callback_query.answer("❌ Не удалось отправить файл", show_alert=True)

async def delete_file_completely(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    if not update.callback_query:
        return
    info = get_file_info(key)
    if not info:
        await update.callback_query.answer("❌ Файл не найден", show_alert=True)
        return
    try:
        await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=info["message_id"])
        logger.info(f"Сообщение {info['message_id']} удалено из канала")
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение из канала: {e}")
    delete_file_info(key)
    await update.callback_query.answer("✅ Файл удалён из канала и базы", show_alert=True)
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except:
        pass

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
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
            "Отправьте файл – получу ключ.\n"
            "Нажмите «Скачать файл» – бот пришлёт файл сюда.\n"
            "Нажмите «Поделиться ссылкой» – получите ссылку для отправки другим.\n"
            "Нажмите «Удалить файл» – удалит файл из канала и ссылку.\n\n"
            "Команды: /get ключ, /delete ключ",
            parse_mode="Markdown"
        )
        await query.answer()
    elif data.startswith("copy_"):
        key = data[5:]
        await query.answer(f"Ключ: {key}", show_alert=True)
    elif data.startswith("share_"):
        key = data[6:]
        await share_link(update, context, key)
    elif data.startswith("download_"):
        key = data[9:]
        await download_file(update, context, key)
    elif data.startswith("delete_"):
        key = data[7:]
        await delete_file_completely(update, context, key)
    else:
        await query.answer()

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Укажите ключ: `/get ключ`", parse_mode="Markdown")
        return
    key = context.args[0]
    info = get_file_info(key)
    if not info:
        await update.message.reply_text("❌ Файл не найден.")
        return
    await send_file_by_info(update.effective_chat.id, info, key, context.bot)

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Укажите ключ: `/delete ключ`", parse_mode="Markdown")
        return
    key = context.args[0]
    info = get_file_info(key)
    if not info:
        await update.message.reply_text("❌ Ключ не найден.")
        return
    try:
        await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=info["message_id"])
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение из канала: {e}")
    delete_file_info(key)
    await update.message.reply_text(f"✅ Ключ `{key}` и файл в канале удалены.")

# --- Запуск ---
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_text))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_file
    ))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()