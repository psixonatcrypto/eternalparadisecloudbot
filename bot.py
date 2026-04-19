# -*- coding: utf-8 -*-
import os
import logging
import sqlite3
import asyncio
import threading
import hashlib
import datetime
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
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        parent_id INTEGER DEFAULT 0,
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
    logger.info("База данных инициализирована")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def check_password(password, password_hash):
    return hash_password(password) == password_hash

# --- Функции БД ---
def save_file_info(key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id=0, password_hash=None, expires_at=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO files (key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id, password_hash, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
              (key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id, password_hash, expires_at))
    conn.commit()
    conn.close()

def get_file_info(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT file_id, filename, media_type, message_id, password_hash, expires_at FROM files WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"file_id": row[0], "filename": row[1], "media_type": row[2], "message_id": row[3], "password_hash": row[4], "expires_at": row[5]}
    return None

def delete_file_info(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM files WHERE key = ?', (key,))
    conn.commit()
    conn.close()

def remove_file_password(key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE files SET password_hash = NULL WHERE key = ?', (key,))
    conn.commit()
    conn.close()

def get_expired_files():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT key, message_id, chat_id, filename FROM files WHERE expires_at IS NOT NULL AND expires_at <= datetime("now")')
    rows = c.fetchall()
    conn.close()
    return rows

def create_folder(user_id, name, parent_id=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO folders (name, user_id, parent_id) VALUES (?, ?, ?)', (name, user_id, parent_id))
    folder_id = c.lastrowid
    conn.commit()
    conn.close()
    return folder_id

def get_user_folders(user_id, parent_id=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, name FROM folders WHERE user_id = ? AND parent_id = ? ORDER BY name', (user_id, parent_id))
    rows = c.fetchall()
    conn.close()
    return rows

def get_user_files_in_folder(user_id, folder_id=0, limit=10, offset=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT key, filename, created_at, expires_at FROM files WHERE user_id = ? AND folder_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?',
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

def file_actions_keyboard(key, has_password=False):
    deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
    keyboard = []
    if has_password:
        keyboard.append([InlineKeyboardButton("🔓 Снять пароль", callback_data=f"unlock_{key}")])
    keyboard.append([InlineKeyboardButton("📥 Скачать", url=deep_link)])
    keyboard.append([InlineKeyboardButton("📋 Ключ", callback_data=f"copy_{key}")])
    keyboard.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{key}")])
    return InlineKeyboardMarkup(keyboard)

def folder_keyboard(user_id, parent_id=0, files_page=0):
    folders = get_user_folders(user_id, parent_id)
    files, total_files = get_user_files_in_folder(user_id, parent_id, limit=10, offset=files_page * 10)
    
    keyboard = []
    for folder_id, folder_name in folders:
        keyboard.append([InlineKeyboardButton(f"📁 {folder_name}", callback_data=f"open_folder_{folder_id}_{files_page}")])
    
    for key, filename, created_at, expires_at in files:
        deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
        if expires_at:
            try:
                expires_str = datetime.datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")
                display_name = f"📄 {filename[:20]} (до {expires_str})"
            except:
                display_name = f"📄 {filename[:30]}"
        else:
            display_name = f"📄 {filename[:30]}"
        keyboard.append([InlineKeyboardButton(display_name, url=deep_link)])
    
    nav_buttons = []
    if files_page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"files_page_{parent_id}_{files_page-1}"))
    if (files_page + 1) * 10 < total_files:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"files_page_{parent_id}_{files_page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    if parent_id == 0:
        keyboard.append([InlineKeyboardButton("➕ Новая папка", callback_data=f"new_folder_{parent_id}_{files_page}")])
    else:
        # Кнопка удаления папки (только если не в корне)
        keyboard.append([InlineKeyboardButton("🗑 Удалить эту папку", callback_data=f"delete_folder_{parent_id}_{files_page}")])
    
    keyboard.append([InlineKeyboardButton("📤 Добавить файл", callback_data="upload")])
    
    if parent_id != 0:
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"my_files_back_{parent_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(keyboard)

def storage_keyboard():
    keyboard = [
        [InlineKeyboardButton("⏰ 1 час", callback_data="period_1h")],
        [InlineKeyboardButton("📅 1 день", callback_data="period_1d")],
        [InlineKeyboardButton("📆 1 неделя", callback_data="period_1w")],
        [InlineKeyboardButton("🗓 1 месяц", callback_data="period_1m")],
        [InlineKeyboardButton("♾ Навсегда", callback_data="period_forever")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_upload")]
    ]
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

# --- Автоматическое удаление просроченных файлов ---
async def check_expired_files(app):
    while True:
        try:
            expired = get_expired_files()
            if expired:
                logger.info(f"Найдено {len(expired)} просроченных файлов")
                for key, message_id, chat_id, filename in expired:
                    try:
                        await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
                        delete_file_info(key)
                        logger.info(f"Автоудаление: {filename} (ключ {key}) удалён")
                    except Exception as e:
                        logger.error(f"Не удалось удалить {filename}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при проверке просроченных файлов: {e}")
        await asyncio.sleep(3600)

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
        "1. Отправьте файл – выберите срок хранения.\n"
        "2. При желании установите пароль.\n"
        "3. Нажмите «Мои файлы» – увидите папки и файлы.\n"
        "4. Нажмите на файл – скачается.\n"
        "5. Чтобы удалить папку, откройте её и нажмите «🗑 Удалить эту папку».\n\n"
        "Команды: /get <ключ>, /delete <ключ>\n\n"
        "Если обнаружили баг: @Eternal_paradise_supbot",
        parse_mode="Markdown"
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
    
    await update.message.reply_text(
        f"📁 Файл *{filename}*\n\nВыберите срок хранения:",
        parse_mode="Markdown",
        reply_markup=storage_keyboard()
    )

async def save_file_with_options(update: Update, context: ContextTypes.DEFAULT_TYPE, period):
    query = update.callback_query
    await query.answer()
    
    temp = context.user_data.get('temp_file')
    if not temp:
        await query.message.reply_text("❌ Ошибка: файл не найден. Попробуйте загрузить заново.")
        return
    
    file_id = temp['file_id']
    filename = temp['filename']
    media_type = temp['media_type']
    user_id = temp['user_id']
    user_first_name = temp['user_first_name']
    
    expires_at = None
    period_text = ""
    if period == "1h":
        expires_at = datetime.datetime.now() + datetime.timedelta(hours=1)
        period_text = "1 час"
    elif period == "1d":
        expires_at = datetime.datetime.now() + datetime.timedelta(days=1)
        period_text = "1 день"
    elif period == "1w":
        expires_at = datetime.datetime.now() + datetime.timedelta(weeks=1)
        period_text = "1 неделя"
    elif period == "1m":
        expires_at = datetime.datetime.now() + datetime.timedelta(days=30)
        period_text = "1 месяц"
    elif period == "forever":
        period_text = "навсегда"
    
    context.user_data['temp_file_data'] = {
        'file_id': file_id,
        'filename': filename,
        'media_type': media_type,
        'user_id': user_id,
        'user_first_name': user_first_name,
        'expires_at': expires_at.isoformat() if expires_at else None,
        'period_text': period_text
    }
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Да, установить пароль", callback_data="final_with_pwd")],
        [InlineKeyboardButton("📁 Нет, без пароля", callback_data="final_no_pwd")]
    ])
    await query.message.edit_text(f"Срок хранения: {period_text}\n\nУстановить пароль на файл?", reply_markup=keyboard)

async def final_save_file_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, password=None):
    """Сохранение файла при нажатии кнопки (есть callback_query)"""
    query = update.callback_query
    await query.answer()
    
    temp = context.user_data.get('temp_file_data')
    if not temp:
        await query.message.reply_text("❌ Ошибка: данные файла не найдены.")
        return
    
    await _save_file(query.message, context, temp, password)

async def final_save_file_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE, password=None):
    """Сохранение файла при вводе пароля текстом (нет callback_query)"""
    message = update.message
    temp = context.user_data.get('temp_file_data')
    if not temp:
        await message.reply_text("❌ Ошибка: данные файла не найдены.")
        return
    
    await _save_file(message, context, temp, password)

async def _save_file(message, context, temp, password=None):
    """Общая функция сохранения файла"""
    file_id = temp['file_id']
    filename = temp['filename']
    media_type = temp['media_type']
    user_id = temp['user_id']
    user_first_name = temp['user_first_name']
    expires_at = temp['expires_at']
    period_text = temp['period_text']
    
    password_hash = hash_password(password) if password else None
    
    try:
        key = str(uuid4())[:8]
        caption = f"📁 Файл от {user_first_name} | Ключ: {key}"
        if expires_at:
            expires_str = datetime.datetime.fromisoformat(expires_at).strftime("%d.%m.%Y %H:%M")
            caption += f"\n⏰ Удалить: {expires_str}"
        
        if media_type == "photo":
            sent = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=file_id, caption=caption)
        elif media_type == "video":
            sent = await context.bot.send_video(chat_id=CHANNEL_ID, video=file_id, caption=caption)
        elif media_type == "audio":
            sent = await context.bot.send_audio(chat_id=CHANNEL_ID, audio=file_id, caption=caption)
        elif media_type == "voice":
            sent = await context.bot.send_voice(chat_id=CHANNEL_ID, voice=file_id, caption=caption)
        else:
            sent = await context.bot.send_document(chat_id=CHANNEL_ID, document=file_id, caption=caption)

        save_file_info(key, file_id, filename, CHANNEL_ID, sent.message_id, media_type, user_id, folder_id=0, password_hash=password_hash, expires_at=expires_at)
        deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
        
        result_text = f"✅ Файл *{filename}* сохранён!\n\n"
        result_text += f"🔗 *Ссылка:* {deep_link}\n"
        result_text += f"📌 Ключ: `{key}`\n"
        result_text += f"⏰ Срок хранения: {period_text}\n"
        if password:
            result_text += f"🔒 Пароль: `{password}` (запомните его!)\n"
        
        await message.reply_text(
            result_text,
            parse_mode="Markdown",
            reply_markup=file_actions_keyboard(key, has_password=bool(password))
        )
        
        # Очищаем временные данные
        context.user_data.pop('temp_file', None)
        context.user_data.pop('temp_file_data', None)
        context.user_data.pop('temp_file_needs_pwd', None)
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении: {e}")
        import traceback
        traceback.print_exc()
        await message.reply_text("❌ Ошибка при сохранении файла. Попробуйте ещё раз.")

async def unlock_file(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    query = update.callback_query
    remove_file_password(key)
    await query.answer("✅ Пароль снят!", show_alert=True)
    
    deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Скачать", url=deep_link)],
        [InlineKeyboardButton("📋 Ключ", callback_data=f"copy_{key}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{key}")]
    ])
    await query.message.edit_reply_markup(reply_markup=keyboard)

# --- Создание папок ---
async def new_folder_start(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id, files_page):
    query = update.callback_query
    context.user_data['new_folder_parent'] = parent_id
    context.user_data['new_folder_files_page'] = files_page
    await query.message.reply_text("Введите название папки:")
    await query.answer()

async def process_folder_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parent_id = context.user_data.pop('new_folder_parent', 0)
    files_page = context.user_data.pop('new_folder_files_page', 0)
    
    user_id = update.effective_user.id
    create_folder(user_id, text, parent_id)
    
    await update.message.reply_text(f"✅ Папка «{text}» создана!")
    await my_files(update, context, parent_id, files_page)

# --- Удаление папки ---
async def delete_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, folder_id, files_page):
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Получаем информацию о папке
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT name, parent_id FROM folders WHERE id = ? AND user_id = ?', (folder_id, user_id))
    row = c.fetchone()
    conn.close()
    
    if not row:
        await query.answer("❌ Папка не найдена", show_alert=True)
        return
    
    folder_name, parent_id = row
    
    # Удаляем все файлы в папке
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Получаем все файлы в папке для удаления из канала
    c.execute('SELECT key, message_id FROM files WHERE folder_id = ? AND user_id = ?', (folder_id, user_id))
    files_in_folder = c.fetchall()
    
    # Удаляем файлы из канала
    for key, message_id in files_in_folder:
        try:
            await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
            logger.info(f"Удалён файл {key} из канала")
        except Exception as e:
            logger.error(f"Не удалось удалить файл {key}: {e}")
    
    # Удаляем файлы из БД
    c.execute('DELETE FROM files WHERE folder_id = ? AND user_id = ?', (folder_id, user_id))
    
    # Удаляем все подпапки (рекурсивно)
    c.execute('SELECT id FROM folders WHERE parent_id = ? AND user_id = ?', (folder_id, user_id))
    subfolders = c.fetchall()
    for sub_id, in subfolders:
        # Удаляем файлы в подпапках
        c.execute('SELECT key, message_id FROM files WHERE folder_id = ? AND user_id = ?', (sub_id, user_id))
        sub_files = c.fetchall()
        for key, message_id in sub_files:
            try:
                await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
            except:
                pass
        c.execute('DELETE FROM files WHERE folder_id = ? AND user_id = ?', (sub_id, user_id))
        c.execute('DELETE FROM folders WHERE id = ? AND user_id = ?', (sub_id, user_id))
    
    # Удаляем саму папку
    c.execute('DELETE FROM folders WHERE id = ? AND user_id = ?', (folder_id, user_id))
    conn.commit()
    conn.close()
    
    await query.answer(f"✅ Папка «{folder_name}» и всё её содержимое удалены!", show_alert=True)
    await my_files(update, context, parent_id, 0)

# --- Админ-команда ---
async def delkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только администратор.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите ключ: `/delkey ключ`")
        return
    
    key = context.args[0]
    info = get_file_info(key)
    if not info:
        await update.message.reply_text(f"❌ Ключ `{key}` не найден.")
        return
    
    try:
        await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=info["message_id"])
        await update.message.reply_text(f"✅ Файл с ключом `{key}` удалён из канала.")
    except Exception as e:
        logger.error(f"Не удалось удалить из канала: {e}")
        await update.message.reply_text(f"⚠ Не удалось удалить файл из канала.")
    
    delete_file_info(key)
    await update.message.reply_text(f"✅ Запись с ключом `{key}` удалена из базы данных.")

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
            "1. Отправьте файл – выберите срок хранения.\n"
            "2. При желании установите пароль.\n"
            "3. Нажмите «Мои файлы» – увидите папки и файлы.\n"
            "4. Нажмите на файл – скачается.\n"
            "5. Чтобы удалить папку, откройте её и нажмите «🗑 Удалить эту папку».\n\n"
            "Команды: /get <ключ>, /delete <ключ>",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
        )
        await query.answer()
    elif data == "my_files_root":
        await my_files(update, context, 0, 0)
    elif data.startswith("my_files_back_"):
        try:
            current_parent = int(data.split("_")[3])
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute('SELECT parent_id FROM folders WHERE id = ? AND user_id = ?', (current_parent, update.effective_user.id))
            row = c.fetchone()
            conn.close()
            parent_id = row[0] if row else 0
            await my_files(update, context, parent_id, 0)
        except:
            await query.answer("Ошибка", show_alert=True)
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
    elif data.startswith("new_folder_"):
        try:
            parts = data.split("_")
            parent_id = int(parts[2])
            files_page = int(parts[3])
            await new_folder_start(update, context, parent_id, files_page)
        except:
            await query.answer("Ошибка", show_alert=True)
    elif data.startswith("delete_folder_"):
        try:
            parts = data.split("_")
            folder_id = int(parts[2])
            files_page = int(parts[3]) if len(parts) > 3 else 0
            await delete_folder(update, context, folder_id, files_page)
        except:
            await query.answer("Ошибка", show_alert=True)
    elif data.startswith("period_"):
        try:
            period = data.split("_")[1]
            if context.user_data.get('temp_file'):
                await save_file_with_options(update, context, period)
            else:
                await query.answer("❌ Ошибка: файл не найден. Попробуйте заново.", show_alert=True)
        except:
            await query.answer("Ошибка", show_alert=True)
    elif data == "cancel_upload":
        context.user_data.pop('temp_file', None)
        await query.message.edit_text("❌ Загрузка отменена.")
        await query.answer()
    elif data == "final_with_pwd":
        context.user_data['temp_file_needs_pwd'] = True
        await query.message.reply_text("Введите пароль для файла:")
        await query.answer()
    elif data == "final_no_pwd":
        await final_save_file_from_callback(update, context, password=None)
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
    
    if context.user_data.get('new_folder_parent') is not None:
        await process_folder_creation(update, context)
        return
    
    if context.user_data.get('pending_file_key'):
        key = context.user_data.pop('pending_file_key')
        info = get_file_info(key)
        if info and info.get("password_hash"):
            if check_password(text, info["password_hash"]):
                await send_file_by_info(update.effective_chat.id, info, key, context.bot)
            else:
                await update.message.reply_text("❌ Неверный пароль. Доступ запрещён.")
        return
    
    if context.user_data.get('waiting_for') == 'get_key':
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
    
    if context.user_data.get('waiting_for') == 'delete_key':
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
    
    if context.user_data.get('temp_file_needs_pwd') is True and context.user_data.get('temp_file_data') is not None:
        password = text
        context.user_data['temp_file_needs_pwd'] = False
        await final_save_file_from_text(update, context, password)
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
        await update.message.reply_text("Укажите ключ: `/delete ключ`")
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
    await update.message.reply_text(f"✅ Ключ `{key}` и файл удалены.")

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
        except:
            failed += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"📨 Рассылка завершена.\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Запускаем фоновую задачу для удаления просроченных файлов
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(check_expired_files(app))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_text))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("delkey", delkey_command))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_file
    ))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Бот запущен (полная версия с удалением папок)")
    app.run_polling()

if __name__ == "__main__":
    main()
