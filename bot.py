# -*- coding: utf-8 -*-
import os
import logging
import sqlite3
import asyncio
import threading
import datetime
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

# --- Функции для паролей ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def check_password(password, password_hash):
    return hash_password(password) == password_hash

def get_file_password_hash(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT password_hash FROM files WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_folder_password_hash(folder_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT password_hash FROM folders WHERE id = ?', (folder_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# --- Функции БД ---
def save_file_info(key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id=0, password_hash=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO files (key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id, password_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
              (key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id, password_hash))
    conn.commit()
    conn.close()

def get_file_info(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT file_id, filename, media_type, message_id, password_hash FROM files WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"file_id": row[0], "filename": row[1], "media_type": row[2], "message_id": row[3], "password_hash": row[4]}
    return None

def delete_file_info(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM files WHERE key = ?', (key,))
    conn.commit()
    conn.close()

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

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT user_id FROM users')
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

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

def file_actions_keyboard(key):
    deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
    keyboard = [
        [InlineKeyboardButton("📥 Скачать", url=deep_link)],
        [InlineKeyboardButton("🔐 Снять пароль", callback_data=f"unlock_{key}")],
        [InlineKeyboardButton("📋 Ключ", callback_data=f"copy_{key}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{key}")]
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
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('SELECT parent_id FROM folders WHERE id = ? AND user_id = ?', (parent_id, user_id))
        row = c.fetchone()
        conn.close()
        back_parent = row[0] if row else 0
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"my_files_{back_parent}")])
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
        info = get_file_info(key)
        if info:
            if info.get("password_hash"):
                context.user_data['pending_file_key'] = key
                await update.message.reply_text("🔒 Файл защищён паролем. Введите пароль:")
                return
            else:
                await send_file_by_info(update.effective_chat.id, info, key, context.bot)
                return
        else:
            await update.message.reply_text("❌ Файл по этой ссылке не найден.")
            return
    
    await update.message.reply_text(
        "👋 Привет! Я бот-файлообменник.\n"
        "Отправь мне любой файл – я сохраню его в облаке.\n"
        "Используй кнопки ниже:",
        reply_markup=main_keyboard()
    )

async def help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📌 *Как пользоваться:*\n"
        "1. Отправьте файл – можно установить пароль.\n"
        "2. Нажмите «Мои файлы» – увидите папки и файлы.\n"
        "3. Нажмите на файл – скачается.\n"
        "4. У файла есть кнопки: «Снять пароль», «Ключ», «Удалить».\n\n"
        "Команды: /get <ключ>, /delete <ключ>\n\n"
        "Если обнаружили баг: @Eternal_paradise_supbot",
        parse_mode="Markdown"
    )

async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id=0, files_page=0):
    query = update.callback_query
    user_id = update.effective_user.id
    
    if parent_id != 0:
        pwd_hash = get_folder_password_hash(parent_id)
        if pwd_hash:
            context.user_data['pending_folder_id'] = parent_id
            context.user_data['pending_folder_files_page'] = files_page
            if query:
                await query.message.reply_text("🔒 Папка защищена паролем. Введите пароль:")
                await query.answer()
            else:
                await update.message.reply_text("🔒 Папка защищена паролем. Введите пароль:")
            return
    
    text = "📁 *Ваши файлы и папки:*"
    if query:
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=folder_keyboard(user_id, parent_id, files_page))
        await query.answer()
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=folder_keyboard(user_id, parent_id, files_page))

async def new_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id, files_page):
    query = update.callback_query
    context.user_data['new_folder_parent'] = parent_id
    context.user_data['new_folder_files_page'] = files_page
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Да, установить пароль", callback_data="new_folder_with_pwd")],
        [InlineKeyboardButton("📁 Нет, без пароля", callback_data="new_folder_no_pwd")]
    ])
    await query.message.reply_text("Создать папку с паролем?", reply_markup=keyboard)
    await query.answer()

async def handle_folder_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    folder_name = update.message.text
    parent_id = context.user_data.get('new_folder_parent', 0)
    files_page = context.user_data.get('new_folder_files_page', 0)
    with_password = context.user_data.get('new_folder_with_password', False)
    password = context.user_data.get('new_folder_password', None)
    
    user_id = update.effective_user.id
    password_hash = hash_password(password) if with_password and password else None
    create_folder(user_id, folder_name, parent_id, password_hash)
    
    # Очищаем временные данные
    context.user_data.pop('new_folder_parent', None)
    context.user_data.pop('new_folder_files_page', None)
    context.user_data.pop('new_folder_with_password', None)
    context.user_data.pop('new_folder_password', None)
    
    await update.message.reply_text(f"✅ Папка «{folder_name}» создана!")
    await my_files(update, context, parent_id, files_page)

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

    context.user_data['temp_file'] = {
        'file_id': file_id,
        'filename': filename,
        'media_type': media_type,
        'user_id': user.id,
        'user_first_name': user.first_name
    }
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Да, установить пароль", callback_data="file_with_pwd")],
        [InlineKeyboardButton("📁 Нет, без пароля", callback_data="file_no_pwd")]
    ])
    await update.message.reply_text("Установить пароль на этот файл?", reply_markup=keyboard)

async def save_file_with_password(update: Update, context: ContextTypes.DEFAULT_TYPE, password=None):
    query = update.callback_query
    temp = context.user_data.get('temp_file')
    if not temp:
        await query.message.reply_text("❌ Ошибка: файл не найден. Попробуйте загрузить заново.")
        return
    
    file_id = temp['file_id']
    filename = temp['filename']
    media_type = temp['media_type']
    user_id = temp['user_id']
    user_first_name = temp['user_first_name']
    
    password_hash = hash_password(password) if password else None
    
    try:
        key = str(uuid4())[:8]
        if media_type == "photo":
            sent = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=file_id, caption=f"📸 Фото от {user_first_name} | Ключ: {key}")
        elif media_type == "video":
            sent = await context.bot.send_video(chat_id=CHANNEL_ID, video=file_id, caption=f"🎬 Видео от {user_first_name} | Ключ: {key}")
        elif media_type == "audio":
            sent = await context.bot.send_audio(chat_id=CHANNEL_ID, audio=file_id, caption=f"🎵 Аудио от {user_first_name} | Ключ: {key}")
        elif media_type == "voice":
            sent = await context.bot.send_voice(chat_id=CHANNEL_ID, voice=file_id, caption=f"🎙️ Голосовое от {user_first_name} | Ключ: {key}")
        else:
            sent = await context.bot.send_document(chat_id=CHANNEL_ID, document=file_id, caption=f"📁 Файл от {user_first_name} | Ключ: {key}")

        save_file_info(key, file_id, filename, CHANNEL_ID, sent.message_id, media_type, user_id, folder_id=0, password_hash=password_hash)
        deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
        
        if password:
            await query.message.edit_text(
                f"✅ Файл *{filename}* сохранён с паролем!\n\n"
                f"🔗 *Ссылка:* {deep_link}\n"
                f"📌 Ключ: `{key}`\n"
                f"🔒 Пароль: `{password}` (запомните его!)\n\n"
                f"Вы можете найти файл в разделе «Мои файлы».",
                parse_mode="Markdown",
                reply_markup=file_actions_keyboard(key)
            )
        else:
            await query.message.edit_text(
                f"✅ Файл *{filename}* сохранён!\n\n"
                f"🔗 *Ссылка:* {deep_link}\n"
                f"📌 Ключ: `{key}`\n\n"
                f"Вы можете найти файл в разделе «Мои файлы».",
                parse_mode="Markdown",
                reply_markup=file_actions_keyboard(key)
            )
        del context.user_data['temp_file']
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка при сохранении: {e}")
        await query.message.edit_text("❌ Ошибка при сохранении файла.")
        await query.answer()

# --- Снятие пароля с файла ---
async def unlock_file(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    query = update.callback_query
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE files SET password_hash = NULL WHERE key = ?', (key,))
    conn.commit()
    conn.close()
    await query.answer("✅ Пароль с файла снят!", show_alert=True)
    
    # Обновляем сообщение с кнопками
    deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
    keyboard = [
        [InlineKeyboardButton("📥 Скачать", url=deep_link)],
        [InlineKeyboardButton("📋 Ключ", callback_data=f"copy_{key}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{key}")]
    ]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

# --- Обработчики кнопок и текста ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
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
            "3. Нажмите на файл – скачается.\n"
            "4. У файла есть кнопки: «Снять пароль», «Ключ», «Удалить».\n\n"
            "Команды: /get <ключ>, /delete <ключ>\n\n"
            "Если обнаружили баг: @Eternal_paradise_supbot",
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
        except (IndexError, ValueError):
            await query.answer("Ошибка формата", show_alert=True)
    elif data.startswith("open_folder_"):
        try:
            parts = data.split("_")
            folder_id = int(parts[2])
            files_page = int(parts[3]) if len(parts) > 3 else 0
            await my_files(update, context, folder_id, files_page)
        except (IndexError, ValueError):
            await query.answer("Ошибка формата", show_alert=True)
    elif data.startswith("files_page_"):
        try:
            parts = data.split("_")
            parent_id = int(parts[2])
            files_page = int(parts[3]) if len(parts) > 3 else 0
            user_id = update.effective_user.id
            keyboard = folder_keyboard(user_id, parent_id, files_page)
            await query.message.edit_reply_markup(reply_markup=keyboard)
            await query.answer()
        except (IndexError, ValueError):
            await query.answer("Ошибка формата", show_alert=True)
    elif data.startswith("new_folder_"):
        try:
            parts = data.split("_")
            parent_id = int(parts[2])
            files_page = int(parts[3]) if len(parts) > 3 else 0
            await new_folder(update, context, parent_id, files_page)
        except (IndexError, ValueError):
            await query.answer("Ошибка формата", show_alert=True)
    elif data == "new_folder_with_pwd":
        context.user_data['new_folder_with_password'] = True
        context.user_data['new_folder_password'] = None
        await query.message.reply_text("Введите пароль для папки:")
        await query.answer()
    elif data == "new_folder_no_pwd":
        context.user_data['new_folder_with_password'] = False
        context.user_data['new_folder_password'] = None
        await query.message.reply_text("Введите название папки:")
        await query.answer()
    elif data == "file_with_pwd":
        context.user_data['temp_file_with_pwd'] = True
        await query.message.reply_text("Введите пароль для файла:")
        await query.answer()
    elif data == "file_no_pwd":
        context.user_data['temp_file_with_pwd'] = False
        await save_file_with_password(update, context, password=None)
    elif data.startswith("unlock_"):
        key = data[7:]
        await unlock_file(update, context, key)
    elif data.startswith("copy_"):
        key = data[5:]
        await query.answer(f"Ключ: {key}", show_alert=True)
    elif data.startswith("delete_"):
        key = data[7:]
        info = get_file_info(key)
        if info:
            try:
                await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=info["message_id"])
            except:
                pass
            delete_file_info(key)
            await query.answer("✅ Файл удалён", show_alert=True)
            await query.message.edit_text("Файл удалён", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="my_files_root")]]))
    else:
        await query.answer()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    text = update.message.text.strip()
    
    waiting_for = context.user_data.get('waiting_for')
    if waiting_for == 'get_key':
        context.user_data['waiting_for'] = None
        info = get_file_info(text)
        if not info:
            await update.message.reply_text("❌ Файл не найден.")
            return
        if info.get("password_hash"):
            context.user_data['pending_file_key'] = text
            await update.message.reply_text("🔒 Файл защищён паролем. Введите пароль:")
        else:
            await send_file_by_info(update.effective_chat.id, info, text, context.bot)
        return
    elif waiting_for == 'delete_key':
        context.user_data['waiting_for'] = None
        info = get_file_info(text)
        if not info:
            await update.message.reply_text("❌ Файл не найден.")
            return
        try:
            await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=info["message_id"])
        except:
            pass
        delete_file_info(text)
        await update.message.reply_text(f"✅ Файл с ключом `{text}` удалён.")
        return
    
    if context.user_data.get('pending_file_key'):
        key = context.user_data.pop('pending_file_key')
        info = get_file_info(key)
        if info and info.get("password_hash"):
            if check_password(text, info["password_hash"]):
                await send_file_by_info(update.effective_chat.id, info, key, context.bot)
            else:
                await update.message.reply_text("❌ Неверный пароль. Доступ запрещён.")
        else:
            await update.message.reply_text("❌ Файл не найден или пароль не установлен.")
        return
    
    if context.user_data.get('pending_folder_id'):
        folder_id = context.user_data.pop('pending_folder_id')
        files_page = context.user_data.pop('pending_folder_files_page', 0)
        pwd_hash = get_folder_password_hash(folder_id)
        if pwd_hash and check_password(text, pwd_hash):
            await my_files(update, context, folder_id, files_page)
        else:
            await update.message.reply_text("❌ Неверный пароль. Доступ к папке запрещён.")
        return
    
    if context.user_data.get('new_folder_with_password') is True and context.user_data.get('new_folder_password') is None:
        context.user_data['new_folder_password'] = text
        await update.message.reply_text("Введите название папки:")
        return
    
    if context.user_data.get('new_folder_parent') is not None and context.user_data.get('new_folder_password') is not None:
        await handle_folder_name(update, context)
        return
    
    if context.user_data.get('temp_file_with_pwd') is True and context.user_data.get('temp_file') is not None:
        password = text
        context.user_data['temp_file_with_pwd'] = False
        await save_file_with_password(update, context, password)
        return
    
    await update.message.reply_text("❓ Неизвестная команда. Используйте /start")

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
    if info.get("password_hash"):
        context.user_data['pending_file_key'] = key
        await update.message.reply_text("🔒 Файл защищён паролем. Введите пароль:")
    else:
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

# --- Запуск ---
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_text))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_file
    ))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Бот запущен (полная версия с паролями и управлением файлами)")
    app.run_polling()

if __name__ == "__main__":
    main()
