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
        media_type TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    c.execute('SELECT file_id, filename, media_type FROM files WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"file_id": row[0], "filename": row[1], "media_type": row[2]}
    return None

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

def file_actions_keyboard(key):
    keyboard = [
        [InlineKeyboardButton("📥 Скачать файл", callback_data=f"download_{key}")],
        [InlineKeyboardButton("📋 Копировать ключ", callback_data=f"copy_{key}")],
        [InlineKeyboardButton("❌ Удалить файл", callback_data=f"delete_{key}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Команды и обработчики ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот-файлообменник.\n"
        "Отправь мне любой файл – я сохраню его в канале и дам ключ.\n"
        "Используй кнопки ниже:",
        reply_markup=main_keyboard()
    )

async def help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 *Как пользоваться:*\n"
        "1. Отправьте файл – получу ключ и кнопки.\n"
        "2. Нажмите «Скачать файл» – бот пришлёт файл сюда.\n"
        "3. Нажмите «Удалить файл» – удалит файл из канала и ссылку.\n\n"
        "Команды: /get <ключ>, /delete <ключ>\n"
        "Канал для хранения: " + CHANNEL_ID,
        parse_mode="Markdown"
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    # Определяем тип и соответствующий метод отправки в канал
    if message.document:
        file_id = message.document.file_id
        filename = message.document.file_name
        media_type = "document"
        send_method = context.bot.send_document
    elif message.photo:
        file_id = message.photo[-1].file_id
        filename = f"photo_{file_id[:10]}.jpg"
        media_type = "photo"
        send_method = context.bot.send_photo
    elif message.video:
        file_id = message.video.file_id
        filename = message.video.file_name or f"video_{file_id[:10]}.mp4"
        media_type = "video"
        send_method = context.bot.send_video
    elif message.audio:
        file_id = message.audio.file_id
        filename = message.audio.file_name or f"audio_{file_id[:10]}.mp3"
        media_type = "audio"
        send_method = context.bot.send_audio
    elif message.voice:
        file_id = message.voice.file_id
        filename = f"voice_{file_id[:10]}.ogg"
        media_type = "voice"
        send_method = context.bot.send_voice
    else:
        await update.message.reply_text("❌ Неподдерживаемый тип файла.")
        return

    try:
        # Отправляем в канал соответствующим методом
        if media_type == "photo":
            sent = await send_method(chat_id=CHANNEL_ID, photo=file_id, caption=f"📸 Фото от {user.first_name}")
        elif media_type == "video":
            sent = await send_method(chat_id=CHANNEL_ID, video=file_id, caption=f"🎬 Видео от {user.first_name}")
        elif media_type == "audio":
            sent = await send_method(chat_id=CHANNEL_ID, audio=file_id, caption=f"🎵 Аудио от {user.first_name}")
        elif media_type == "voice":
            sent = await send_method(chat_id=CHANNEL_ID, voice=file_id, caption=f"🎙️ Голосовое от {user.first_name}")
        else:
            sent = await send_method(chat_id=CHANNEL_ID, document=file_id, caption=f"📁 Файл от {user.first_name}")

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
        await update.message.reply_text("❌ Ошибка. Проверьте, что бот – администратор канала.")

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    info = get_file_info(key)
    if not info:
        await update.callback_query.answer("❌ Файл не найден", show_alert=True)
        return
    try:
        # Отправляем файл пользователю в зависимости от типа
        if info["media_type"] == "photo":
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=info["file_id"],
                caption=f"📸 Ваше фото по ключу `{key}`"
            )
        elif info["media_type"] == "video":
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=info["file_id"],
                caption=f"🎬 Ваше видео по ключу `{key}`"
            )
        elif info["media_type"] == "audio":
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=info["file_id"],
                caption=f"🎵 Ваш аудиофайл по ключу `{key}`"
            )
        elif info["media_type"] == "voice":
            await context.bot.send_voice(
                chat_id=update.effective_chat.id,
                voice=info["file_id"],
                caption=f"🎙️ Ваше голосовое по ключу `{key}`"
            )
        else:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=info["file_id"],
                filename=info["filename"],
                caption=f"📎 Ваш файл по ключу `{key}`"
            )
        await update.callback_query.answer("✅ Файл отправлен!")
    except Exception as e:
        logger.error(f"Ошибка отправки файла: {e}")
        await update.callback_query.answer("❌ Не удалось отправить файл", show_alert=True)

async def delete_file_completely(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    info = get_file_info(key)
    if not info:
        await update.callback_query.answer("❌ Файл не найден", show_alert=True)
        return

    # Удаляем сообщение из канала
    try:
        await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=info["message_id"])
        logger.info(f"Сообщение {info['message_id']} удалено из канала")
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение из канала: {e}")

    # Удаляем запись из БД
    delete_file_info(key)
    await update.callback_query.answer("✅ Файл удалён из канала и базы", show_alert=True)
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except:
        pass

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
            "Отправьте файл – получу ключ.\n"
            "Нажмите «Скачать файл» – бот пришлёт файл сюда.\n"
            "Нажмите «Удалить файл» – удалит файл из канала и ссылку.\n\n"
            "Команды: /get ключ, /delete ключ",
            parse_mode="Markdown"
        )
        await query.answer()
    elif data.startswith("copy_"):
        key = data[5:]
        await query.answer(f"Ключ: {key}", show_alert=True)
    elif data.startswith("download_"):
        key = data[9:]
        await download_file(update, context, key)
    elif data.startswith("delete_"):
        key = data[7:]
        await delete_file_completely(update, context, key)
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
    try:
        if info["media_type"] == "photo":
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=info["file_id"], caption=f"📸 Ваше фото по ключу `{key}`")
        elif info["media_type"] == "video":
            await context.bot.send_video(chat_id=update.effective_chat.id, video=info["file_id"], caption=f"🎬 Ваше видео по ключу `{key}`")
        elif info["media_type"] == "audio":
            await context.bot.send_audio(chat_id=update.effective_chat.id, audio=info["file_id"], caption=f"🎵 Ваш аудиофайл по ключу `{key}`")
        elif info["media_type"] == "voice":
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=info["file_id"], caption=f"🎙️ Ваше голосовое по ключу `{key}`")
        else:
            await context.bot.send_document(chat_id=update.effective_chat.id, document=info["file_id"], filename=info["filename"])
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Не удалось отправить файл.")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    except:
        pass
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
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_file
    ))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен (исправленная версия с корректной отправкой медиа)")
    app.run_polling()

if __name__ == "__main__":
    main()