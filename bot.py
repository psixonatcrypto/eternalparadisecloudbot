# -*- coding: utf-8 -*-
import os
import logging
import sqlite3
import asyncio
import threading
import hashlib
from uuid import uuid4
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DB_NAME = "files.db"
ADMIN_ID = 483977434
BOT_USERNAME = "eternalparadisecloudbot"

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("BOT_TOKEN и CHANNEL_ID должны быть заданы")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Бот работает", 200

def run_web():
    flask_app.run(host='0.0.0.0', port=8080)

threading.Thread(target=run_web, daemon=True).start()

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
        user_id INTEGER,
        folder_id INTEGER DEFAULT 0,
        password_hash TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        parent_id INTEGER DEFAULT 0,
        password_hash TEXT,
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

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_folder(user_id, name, parent_id=0, password_hash=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO folders (name, user_id, parent_id, password_hash) VALUES (?, ?, ?, ?)', (name, user_id, parent_id, password_hash))
    folder_id = c.lastrowid
    conn.commit()
    conn.close()
    return folder_id

def get_user_folders(user_id, parent_id=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, name, password_hash FROM folders WHERE user_id = ? AND parent_id = ? ORDER BY name', (user_id, parent_id))
    rows = c.fetchall()
    conn.close()
    return rows

def save_user(user_id, first_name, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (user_id, first_name, username, last_seen) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
              (user_id, first_name, username))
    conn.commit()
    conn.close()

def main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 Загрузить файл", callback_data="upload")],
        [InlineKeyboardButton("📁 Мои файлы", callback_data="my_files_root")],
    ]
    return InlineKeyboardMarkup(keyboard)

def folder_keyboard(user_id, parent_id=0):
    folders = get_user_folders(user_id, parent_id)
    keyboard = []
    for folder_id, folder_name, pwd_hash in folders:
        if pwd_hash:
            display_name = f"🔒 {folder_name}"
        else:
            display_name = f"📁 {folder_name}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"open_folder_{folder_id}")])
    
    keyboard.append([InlineKeyboardButton("➕ Новая папка", callback_data=f"new_folder_{parent_id}")])
    if parent_id != 0:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"my_files_{parent_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    if user:
        save_user(user.id, user.first_name, user.username)
    await update.message.reply_text("👋 Привет!", reply_markup=main_keyboard())

async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id=0):
    query = update.callback_query
    user_id = update.effective_user.id
    text = "📁 *Ваши папки:*"
    keyboard = folder_keyboard(user_id, parent_id)
    if query:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
        await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def new_folder_start(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id):
    query = update.callback_query
    context.user_data['new_folder_parent'] = parent_id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Да", callback_data="new_folder_with_pwd")],
        [InlineKeyboardButton("📁 Нет", callback_data="new_folder_without_pwd")]
    ])
    await query.message.reply_text("Установить пароль на папку?", reply_markup=keyboard)
    await query.answer()

async def new_folder_with_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['new_folder_needs_pwd'] = True
    await query.message.reply_text("Введите пароль для папки:")
    await query.answer()

async def new_folder_without_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['new_folder_needs_pwd'] = False
    await query.message.reply_text("Введите название папки:")
    await query.answer()

async def process_folder_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parent_id = context.user_data.get('new_folder_parent', 0)
    needs_pwd = context.user_data.get('new_folder_needs_pwd', False)
    pwd = context.user_data.get('new_folder_pwd', None)
    
    if needs_pwd and pwd is None:
        context.user_data['new_folder_pwd'] = text
        await update.message.reply_text("Введите название папки:")
        return
    
    user_id = update.effective_user.id
    password_hash = hash_password(context.user_data.get('new_folder_pwd')) if needs_pwd else None
    create_folder(user_id, text, parent_id, password_hash)
    
    context.user_data.pop('new_folder_parent', None)
    context.user_data.pop('new_folder_needs_pwd', None)
    context.user_data.pop('new_folder_pwd', None)
    
    await update.message.reply_text(f"✅ Папка «{text}» создана!")
    await my_files(update, context, parent_id)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "upload":
        await query.answer("Просто отправьте мне любой файл")
    elif data == "main_menu":
        await query.message.edit_text("👋 Главное меню", reply_markup=main_keyboard())
        await query.answer()
    elif data == "my_files_root":
        await my_files(update, context, 0)
    elif data.startswith("my_files_"):
        parent_id = int(data.split("_")[2])
        await my_files(update, context, parent_id)
    elif data.startswith("open_folder_"):
        folder_id = int(data.split("_")[2])
        await my_files(update, context, folder_id)
    elif data.startswith("new_folder_"):
        parent_id = int(data.split("_")[2])
        await new_folder_start(update, context, parent_id)
    elif data == "new_folder_with_pwd":
        await new_folder_with_pwd(update, context)
    elif data == "new_folder_without_pwd":
        await new_folder_without_pwd(update, context)
    else:
        await query.answer()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('new_folder_parent') is not None:
        await process_folder_creation(update, context)
    else:
        await update.message.reply_text("Используйте кнопки")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
