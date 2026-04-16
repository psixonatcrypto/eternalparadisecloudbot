# -*- coding: utf-8 -*-
import os
import logging
import sqlite3
from uuid import uuid4
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("8696097579:AAFd9g6SSRXJHucfq_bqL0cyU4dlirybg_A")
CHANNEL_ID = os.getenv("@eternalparadisecloudbot")   # например, "@my_files_channel"
DB_NAME = "files.db"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Отправь мне любой файл – я сохраню его в канале и дам ссылку.\n"
        "/get <ключ> – получить файл\n"
        "/delete <ключ> – удалить ссылку"
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
            f"✅ Файл *{filename}* сохранён!\n\n🔗 {link}\n\n📌 Ключ: `{key}`\n/get {key}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Ошибка. Проверьте, что бот – администратор канала и канал публичный.")

async def get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите ключ: `/get ключ`", parse_mode="Markdown")
        return
    key = context.args[0]
    info = get_file_info(key)
    if not info:
        await update.message.reply_text("❌ Файл не найден.")
        return
    await context.bot.send_document(chat_id=update.effective_chat.id, document=info["file_id"], filename=info["filename"])

async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите ключ: `/delete ключ`", parse_mode="Markdown")
        return
    key = context.args[0]
    if get_file_info(key):
        delete_file_info(key)
        await update.message.reply_text(f"✅ Ключ `{key}` удалён.")
    else:
        await update.message.reply_text("❌ Ключ не найден.")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("get", get_file))
    app.add_handler(CommandHandler("delete", delete_file))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_file
    ))
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()