# -*- coding: utf-8 -*-
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import BOT_USERNAME
from db import get_user_folders, get_user_files_in_folder
from utils import format_datetime_for_user
import datetime

def main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 Загрузить файл", callback_data="upload")],
        [InlineKeyboardButton("📁 Мои файлы", callback_data="my_files_root")],
        [InlineKeyboardButton("⭐️ Избранное", callback_data="favorites")],
        [InlineKeyboardButton("🔎 Поиск", callback_data="search_prompt")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
        [InlineKeyboardButton("🌐 О проекте", callback_data="about")],
        [InlineKeyboardButton("⚠️ Жалоба", callback_data="complaint")]
    ]
    return InlineKeyboardMarkup(keyboard)

def owner_file_actions_keyboard(key, has_password=False, folder_id=0, is_favorite=False):
    deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
    keyboard = []
    if has_password:
        keyboard.append([InlineKeyboardButton("🔓 Снять пароль", callback_data=f"unlock_{key}")])
    keyboard.append([InlineKeyboardButton("📥 Скачать", url=deep_link)])
    keyboard.append([InlineKeyboardButton("🔗 Ссылка для друга", callback_data=f"share_link_{key}")])
    keyboard.append([InlineKeyboardButton("📋 Ключ", callback_data=f"copy_{key}")])
    keyboard.append([InlineKeyboardButton("✏️ Переименовать", callback_data=f"rename_{key}")])
    if is_favorite:
        keyboard.append([InlineKeyboardButton("🗑 Из избранного", callback_data=f"unfavorite_{key}")])
    else:
        keyboard.append([InlineKeyboardButton("⭐️ В избранное", callback_data=f"favorite_{key}")])
    keyboard.append([InlineKeyboardButton("📁 Перенести в папку", callback_data=f"move_file_{key}_{folder_id}")])
    keyboard.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{key}")])
    return InlineKeyboardMarkup(keyboard)

def folder_keyboard(user_id, parent_id=0, files_page=0):
    folders = get_user_folders(user_id, parent_id)
    files, total_files = get_user_files_in_folder(user_id, parent_id, limit=10, offset=files_page * 10)
    
    keyboard = []
    for folder_id, folder_name in folders:
        keyboard.append([InlineKeyboardButton(f"📁 {folder_name}", callback_data=f"open_folder_{folder_id}_{files_page}")])
    
    for key, filename, created_at, expires_at, downloads_count, is_favorite in files:
        star = "⭐️ " if is_favorite else ""
        if expires_at:
            try:
                expires_dt = datetime.datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                expires_str = format_datetime_for_user(expires_dt)
                display_name = f"{star}📄 {filename[:15]} (до {expires_str}) 👁 {downloads_count}"
            except:
                display_name = f"{star}📄 {filename[:20]} 👁 {downloads_count}"
        else:
            display_name = f"{star}📄 {filename[:20]} 👁 {downloads_count}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"open_file_{key}_{parent_id}_{files_page}")])
    
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

def favorites_keyboard(user_id, page=0, limit=10):
    from db import get_user_folders  # local import to avoid circular
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT key, filename, created_at, expires_at, downloads_count FROM files WHERE user_id = ? AND is_favorite = 1 ORDER BY created_at DESC LIMIT ? OFFSET ?',
              (user_id, limit, page * limit))
    files = c.fetchall()
    c.execute('SELECT COUNT(*) FROM files WHERE user_id = ? AND is_favorite = 1', (user_id,))
    total = c.fetchone()[0]
    conn.close()
    
    keyboard = []
    for key, filename, created_at, expires_at, downloads_count in files:
        if expires_at:
            try:
                expires_dt = datetime.datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                expires_str = format_datetime_for_user(expires_dt)
                display_name = f"📄 {filename[:20]} (до {expires_str}) 👁 {downloads_count}"
            except:
                display_name = f"📄 {filename[:25]}"
        else:
            display_name = f"📄 {filename[:25]}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"open_file_{key}_0_0")])
    
    total_pages = (total + limit - 1) // limit
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"favorites_page_{page-1}"))
    if page + 1 < total_pages:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"favorites_page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def search_results_keyboard(files, page=0, limit=10):
    keyboard = []
    start = page * limit
    end = start + limit
    for key, filename, created_at, expires_at, downloads_count, is_favorite in files[start:end]:
        star = "⭐️ " if is_favorite else ""
        if expires_at:
            try:
                expires_dt = datetime.datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                expires_str = format_datetime_for_user(expires_dt)
                display_name = f"{star}📄 {filename[:20]} (до {expires_str}) 👁 {downloads_count}"
            except:
                display_name = f"{star}📄 {filename[:25]}"
        else:
            display_name = f"{star}📄 {filename[:25]}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"open_file_{key}_0_0")])
    
    total_pages = (len(files) + limit - 1) // limit
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"search_page_{page-1}"))
    if page + 1 < total_pages:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"search_page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)
