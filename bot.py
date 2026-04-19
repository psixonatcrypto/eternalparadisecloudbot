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

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DB_NAME = "files.db"

ADMIN_ID = 483977434
BOT_USERNAME = "eternalparadisecloudbot"
# =================================

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("BOT_TOKEN и CHANNEL_ID должны быть заданы")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Веб-сервер ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Бот работает", 200

def run_web():
    flask_app.run(host='0.0.0.0', port=8080)

threading.Thread(target=run_web, daemon=True).start()

# --- Инициализация БД ---
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

def check_password(password, password_hash):
    return hash_password(password) == password_hash

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

def get_user_files_in_folder(user_id, folder_id=0, limit=10, offset=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT key, filename, created_at FROM files WHERE user_id = ? AND folder_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?',
              (user_id, folder_id, limit, offset))
    rows = c.fetchall()
    c.execute('SELECT COUNT(*) FROM files WHERE user_id = ? AND folder_id = ?', (user_id, folder_id))
    total = c.fetchone()[0]
    conn.close()
    return rows, total

def save_user(user_id, first_name, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (user_id, first_name, username, last_seen) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
              (user_id, first_name, username))
    conn.commit()
    conn.close()

def get_total_files():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM files')
    total = c.fetchone()[0]
    conn.close()
    return total

def get_new_users_count(days=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if days > 0:
        c.execute('SELECT COUNT(*) FROM users WHERE last_seen >= datetime("now", ?)', (f"-{days} days",))
    else:
        c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()[0]
    conn.close()
    return count

# --- Клавиатуры ---
def main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 Загрузить файл", callback_data="upload")],
        [InlineKeyboardButton("🔍 Получить по ключу", callback_data="get_prompt")],
        [InlineKeyboardButton("❌ Удалить по ключу", callback_data="delete_prompt")],
        [InlineKeyboardButton("📁 Мои файлы", callback_data="my_files_root")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def folder_keyboard(user_id, parent_id=0, files_page=0):
    folders = get_user_folders(user_id, parent_id)
    files, total_files = get_user_files_in_folder(user_id, parent_id, limit=10, offset=files_page * 10)
    
    keyboard = []
    for folder_id, folder_name, pwd_hash in folders:
        if pwd_hash:
            display_name = f"🔒 {folder_name}"
        else:
            display_name = f"📁 {folder_name}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"open_folder_{folder_id}_{files_page}")])
    
    for key, filename, created_at in files:
        deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
        keyboard.append([InlineKeyboardButton(f"📄 {filename[:30]}", url=deep_link)])
    
    nav_buttons = []
    if files_page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"files_page_{parent_id}_{files_page-1}"))
    if (files_page + 1) * 10 < total_files:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"files_page_{parent_id}_{files_page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    action_buttons = []
    action_buttons.append(InlineKeyboardButton("➕ Новая папка", callback_data=f"new_folder_{parent_id}_{files_page}"))
    action_buttons.append(InlineKeyboardButton("📤 Добавить файл", callback_data="upload"))
    keyboard.append(action_buttons)
    
    if parent_id != 0:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"my_files_{parent_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(keyboard)

async def send_file_by_info(chat_id, info, key, bot):
    if info["media_type"] == "photo":
        await bot.send_photo(chat_id=chat_id, photo=info["file_id"], caption=f"📸 Ваше фото")
    elif info["media_type"] == "video":
        await bot.send_video(chat_id=chat_id, video=info["file_id"], caption=f"🎬 Ваше видео")
    elif info["media_type"] == "audio":
        await bot.send_audio(chat_id=chat_id, audio=info["file_id"], caption=f"🎵 Ваш аудиофайл")
    elif info["media_type"] == "voice":
        await bot.send_voice(chat_id=chat_id, voice=info["file_id"], caption=f"🎙️ Ваше голосовое")
    else:
        await bot.send_document(chat_id=chat_id, document=info["file_id"], filename=info["filename"])

# --- Обработчики ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    if user:
        save_user(user.id, user.first_name, user.username)
    
    if context.args and len(context.args) > 0:
        key = context.args[0]
        # обработка глубокой ссылки
        pass
    
    await update.message.reply_text(
        "👋 Привет! Я бот-файлообменник.\n"
        "Отправь мне любой файл – я сохраню его в облаке.\n"
        "Используй кнопки ниже:",
        reply_markup=main_keyboard()
    )

async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id=0, files_page=0):
    query = update.callback_query
    user_id = update.effective_user.id
    
    text = "📁 *Ваши файлы и папки:*"
    keyboard = folder_keyboard(user_id, parent_id, files_page)
    if query:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
        await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только администратор.")
        return
    
    total_users = get_new_users_count()
    today_users = get_new_users_count(1)
    week_users = get_new_users_count(7)
    month_users = get_new_users_count(30)
    total_files = get_total_files()
    
    text = f"📊 *Статистика бота*\n\n"
    text += f"👥 *Пользователи:*\n"
    text += f"• Всего: {total_users}\n"
    text += f"• За сегодня: {today_users}\n"
    text += f"• За неделю: {week_users}\n"
    text += f"• За месяц: {month_users}\n\n"
    text += f"📁 *Файлы:*\n"
    text += f"• Всего загружено: {total_files}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# --- Создание папок (исправленная версия) ---
async def new_folder_start(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id, files_page):
    query = update.callback_query
    context.user_data['new_folder_parent'] = parent_id
    context.user_data['new_folder_files_page'] = files_page
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Да, с паролем", callback_data="new_folder_with_pwd")],
        [InlineKeyboardButton("📁 Нет, без пароля", callback_data="new_folder_without_pwd")]
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
    files_page = context.user_data.get('new_folder_files_page', 0)
    needs_pwd = context.user_data.get('new_folder_needs_pwd', False)
    pwd = context.user_data.get('new_folder_pwd', None)
    
    if needs_pwd and pwd is None:
        context.user_data['new_folder_pwd'] = text
        await update.message.reply_text("Введите название папки:")
        return
    
    user_id = update.effective_user.id
    password_hash = hash_password(context.user_data.get('new_folder_pwd')) if needs_pwd else None
    create_folder(user_id, text, parent_id, password_hash)
    
    # Очищаем временные данные
    context.user_data.pop('new_folder_parent', None)
    context.user_data.pop('new_folder_files_page', None)
    context.user_data.pop('new_folder_needs_pwd', None)
    context.user_data.pop('new_folder_pwd', None)
    
    await update.message.reply_text(f"✅ Папка «{text}» создана!")
    await my_files(update, context, parent_id, files_page)

# --- Обработчики кнопок ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "upload":
        await query.answer("Просто отправьте мне любой файл")
    elif data == "get_prompt":
        context.user_data['waiting_for'] = 'get_key'
        await query.message.reply_text("🔑 Введите ключ файла (только ключ):")
        await query.answer()
    elif data == "delete_prompt":
        context.user_data['waiting_for'] = 'delete_key'
        await query.message.reply_text("🗑 Введите ключ файла (только ключ):")
        await query.answer()
    elif data == "main_menu":
        await query.message.edit_text("👋 Главное меню\n\nИспользуйте кнопки ниже:", reply_markup=main_keyboard())
        await query.answer()
    elif data == "help":
        await query.message.edit_text(
            "📌 *Как пользоваться:*\n"
            "1. Отправьте файл – можно установить пароль.\n"
            "2. Нажмите «Мои файлы» – увидите папки и файлы.\n"
            "3. Нажмите на файл – скачается.\n\n"
            "Команды: /get <ключ>, /delete <ключ>",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
        )
        await query.answer()
    elif data == "my_files_root":
        await my_files(update, context, 0, 0)
    elif data.startswith("my_files_"):
        try:
            parent_id = int(data.split("_")[2])
            await my_files(update, context, parent_id, 0)
        except:
            await query.answer("Ошибка", show_alert=True)
    elif data.startswith("open_folder_"):
        try:
            parts = data.split("_")
            folder_id = int(parts[2])
            files_page = int(parts[3]) if len(parts) > 3 else 0
            await my_files(update, context, folder_id, files_page)
        except:
            await query.answer("Ошибка", show_alert=True)
    elif data.startswith("files_page_"):
        try:
            parts = data.split("_")
            parent_id = int(parts[2])
            files_page = int(parts[3])
            user_id = update.effective_user.id
            keyboard = folder_keyboard(user_id, parent_id, files_page)
            await query.message.edit_reply_markup(reply_markup=keyboard)
            await query.answer()
        except:
            await query.answer("Ошибка", show_alert=True)
    elif data.startswith("new_folder_") and data not in ["new_folder_with_pwd", "new_folder_without_pwd"]:
        try:
            parts = data.split("_")
            parent_id = int(parts[2])
            files_page = int(parts[3])
            await new_folder_start(update, context, parent_id, files_page)
        except:
            await query.answer("Ошибка", show_alert=True)
    elif data == "new_folder_with_pwd":
        await new_folder_with_pwd(update, context)
    elif data == "new_folder_without_pwd":
        await new_folder_without_pwd(update, context)
    else:
        await query.answer()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    text = update.message.text.strip()
    
    # Создание папки
    if context.user_data.get('new_folder_parent') is not None:
        await process_folder_creation(update, context)
        return
    
    # Обработка /get по ключу
    if context.user_data.get('waiting_for') == 'get_key':
        context.user_data['waiting_for'] = None
        # здесь будет логика получения файла
        await update.message.reply_text(f"Получение файла по ключу {text} (в разработке)")
        return
    
    # Обработка /delete по ключу
    if context.user_data.get('waiting_for') == 'delete_key':
        context.user_data['waiting_for'] = None
        await update.message.reply_text(f"Удаление файла по ключу {text} (в разработке)")
        return
    
    await update.message.reply_text("❓ Используйте кнопки меню")

# --- Команды ---
async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Укажите ключ: `/get ключ`")
        return
    key = context.args[0]
    await update.message.reply_text(f"Поиск файла с ключом {key} (в разработке)")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Укажите ключ: `/delete ключ`")
        return
    key = context.args[0]
    await update.message.reply_text(f"Удаление файла с ключом {key} (в разработке)")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только администратор.")
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Укажите текст рассылки после /broadcast")
        return
    await update.message.reply_text(f"Рассылка (в разработке)")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Бот запущен (полная версия с исправленными папками)")
    app.run_polling()

if __name__ == "__main__":
    main()
