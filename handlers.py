# -*- coding: utf-8 -*-
import asyncio
import datetime
import logging
import traceback
import sqlite3
from uuid import uuid4
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import ADMIN_ID, CHANNEL_ID, BOT_USERNAME, ABOUT_TEXT, COMPLAINT_TEXT, HELP_TEXT, DB_NAME
from db import *
from keyboards import *
from utils import send_error_to_admin, format_datetime_for_user, hash_password, check_password

logger = logging.getLogger(__name__)

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return
        user = update.effective_user
        if user:
            save_user(user.id, user.first_name, user.username)
        
        if context.args and len(context.args) > 0:
            key = context.args[0]
            info = get_file_info(key)
            if info:
                if is_file_blocked(key):
                    await update.message.reply_text("⛔ Доступ к файлу заблокирован на 1 час из-за частых неверных попыток ввода пароля.")
                    return
                
                if info.get("password_hash"):
                    context.user_data['pending_file_key'] = key
                    await update.message.reply_text("🔒 Файл защищён паролем. Введите пароль:")
                    return
                else:
                    increment_downloads(key)
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
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        await send_error_to_admin(f"Ошибка в start:\n{traceback.format_exc()}")

async def help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка в help_text: {e}")
        await send_error_to_admin(f"Ошибка в help_text:\n{traceback.format_exc()}")

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        await query.message.reply_text(ABOUT_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка в about: {e}")
        await send_error_to_admin(f"Ошибка в about:\n{traceback.format_exc()}")

async def complaint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        await query.message.reply_text(COMPLAINT_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка в complaint: {e}")
        await send_error_to_admin(f"Ошибка в complaint:\n{traceback.format_exc()}")

async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id=0, files_page=0):
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        
        text = "📁 *Ваши файлы и папки:*"
        keyboard = folder_keyboard(user_id, parent_id, files_page)
        if query:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
            await query.answer()
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка в my_files: {e}")
        await send_error_to_admin(f"Ошибка в my_files:\n{traceback.format_exc()}")

async def favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        
        text = "⭐️ *Ваши избранные файлы:*"
        keyboard = favorites_keyboard(user_id, page)
        if query:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
            await query.answer()
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка в favorites: {e}")
        await send_error_to_admin(f"Ошибка в favorites:\n{traceback.format_exc()}")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return
        if not context.args:
            await update.message.reply_text("🔎 Укажите текст для поиска: `/search текст`", parse_mode="Markdown")
            return
        
        query = " ".join(context.args)
        user_id = update.effective_user.id
        results = search_files(user_id, query)
        
        if not results:
            await update.message.reply_text(f"❌ По запросу «{query}» ничего не найдено.\n\nПопробуйте поискать по названию файла или по ключу.")
            return
        
        context.user_data['search_results'] = results
        text = f"🔎 *Результаты поиска по запросу «{query}»:*\nНайдено {len(results)} файлов."
        await update.message.reply_text(text, parse_mode="Markdown")
        await update.message.reply_text("📋 Список найденных файлов:", reply_markup=search_results_keyboard(results, 0))
    except Exception as e:
        logger.error(f"Ошибка в search_command: {e}")
        await send_error_to_admin(f"Ошибка в search_command:\n{traceback.format_exc()}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Ошибка в stats: {e}")
        await send_error_to_admin(f"Ошибка в stats:\n{traceback.format_exc()}")

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
            increment_downloads(key)
            await send_file_by_info(update.effective_chat.id, info, key, context.bot)
    except Exception as e:
        logger.error(f"Ошибка в get_command: {e}")
        await send_error_to_admin(f"Ошибка в get_command:\n{traceback.format_exc()}")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Ошибка в delete_command: {e}")
        await send_error_to_admin(f"Ошибка в delete_command:\n{traceback.format_exc()}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Ошибка в broadcast: {e}")
        await send_error_to_admin(f"Ошибка в broadcast:\n{traceback.format_exc()}")

async def delkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Ошибка в delkey_command: {e}")
        await send_error_to_admin(f"Ошибка в delkey_command:\n{traceback.format_exc()}")

async def check_expired_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только администратор.")
        return
    
    expired = get_expired_files()
    if not expired:
        await update.message.reply_text("📭 Просроченных файлов не найдено.")
        return
    
    await update.message.reply_text(f"🔍 Найдено {len(expired)} просроченных файлов. Удаляю...")
    
    deleted = 0
    failed = 0
    for key, message_id, chat_id, filename, expires_at in expired:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            delete_file_info(key)
            deleted += 1
            logger.info(f"Принудительно удалён {filename} (ключ {key})")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка удаления {key}: {e}")
            failed += 1
    
    await update.message.reply_text(f"✅ Удалено {deleted} файлов.\n❌ Ошибок: {failed}")

async def check_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только администратор.")
        return
    
    now_utc = datetime.datetime.now()
    now_local = now_utc + datetime.timedelta(hours=3)
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT key, filename, expires_at FROM files WHERE expires_at IS NOT NULL ORDER BY created_at DESC LIMIT 5')
    rows = c.fetchall()
    conn.close()
    
    text = f"🕐 *Серверное время (UTC):* `{now_utc.strftime('%Y-%m-%d %H:%M:%S')}`\n"
    text += f"🕐 *Московское время:* `{now_local.strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
    text += "📁 *Последние 5 файлов с expires_at:*\n"
    for key, filename, expires_at in rows:
        text += f"• `{filename}` | expires: `{expires_at}`\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def send_file_by_info(chat_id, info, key, bot):
    if info["media_type"] == "photo":
        await bot.send_photo(chat_id=chat_id, photo=info["file_id"], caption=f"📸 Ваше фото\n👁 Скачиваний: {info['downloads_count']}")
    elif info["media_type"] == "video":
        await bot.send_video(chat_id=chat_id, video=info["file_id"], caption=f"🎬 Ваше видео\n👁 Скачиваний: {info['downloads_count']}")
    elif info["media_type"] == "audio":
        await bot.send_audio(chat_id=chat_id, audio=info["file_id"], caption=f"🎵 Ваш аудиофайл\n👁 Скачиваний: {info['downloads_count']}")
    elif info["media_type"] == "voice":
        await bot.send_voice(chat_id=chat_id, voice=info["file_id"], caption=f"🎙️ Ваше голосовое\n👁 Скачиваний: {info['downloads_count']}")
    else:
        await bot.send_document(chat_id=chat_id, document=info["file_id"], filename=info["filename"], caption=f"👁 Скачиваний: {info['downloads_count']}")

# --- Обработчики файлов и текста ---
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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

        current_folder = context.user_data.get('current_folder', 0)
        
        context.user_data['temp_file'] = {
            'file_id': file_id,
            'filename': filename,
            'media_type': media_type,
            'user_id': user.id,
            'user_first_name': user.first_name,
            'folder_id': current_folder
        }
        
        await update.message.reply_text(
            f"📁 Файл *{filename}*\n\nВыберите срок хранения:",
            parse_mode="Markdown",
            reply_markup=storage_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка в handle_file: {e}")
        await send_error_to_admin(f"Ошибка в handle_file:\n{traceback.format_exc()}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return
        text = update.message.text.strip()
        
        if context.user_data.get('new_folder_parent') is not None:
            await process_folder_creation(update, context)
            return
        
        if context.user_data.get('rename_file_key') is not None:
            await rename_file_process(update, context)
            return
        
        if context.user_data.get('waiting_for') == 'search_query':
            context.user_data['waiting_for'] = None
            query = text
            user_id = update.effective_user.id
            results = search_files(user_id, query)
            
            if not results:
                await update.message.reply_text(f"❌ По запросу «{query}» ничего не найдено.\n\nПопробуйте поискать по названию файла или по ключу.")
                return
            
            context.user_data['search_results'] = results
            text_msg = f"🔎 *Результаты поиска по запросу «{query}»:*\nНайдено {len(results)} файлов."
            await update.message.reply_text(text_msg, parse_mode="Markdown")
            await update.message.reply_text("📋 Список найденных файлов:", reply_markup=search_results_keyboard(results, 0))
            return
        
        if context.user_data.get('pending_file_key'):
            key = context.user_data.pop('pending_file_key')
            info = get_file_info(key)
            if info and info.get("password_hash"):
                if is_file_blocked(key):
                    await update.message.reply_text("⛔ Доступ к файлу заблокирован на 1 час из-за частых неверных попыток ввода пароля.")
                    return
                
                if check_password(text, info["password_hash"]):
                    conn = sqlite3.connect(DB_NAME)
                    c = conn.cursor()
                    c.execute('UPDATE files SET failed_attempts = 0, blocked_until = NULL WHERE key = ?', (key,))
                    conn.commit()
                    conn.close()
                    increment_downloads(key)
                    await send_file_by_info(update.effective_chat.id, info, key, context.bot)
                else:
                    attempts = increment_failed_attempts(key)
                    if attempts >= 5:
                        block_file_access(key)
                        await update.message.reply_text("⛔ Вы превысили лимит неверных попыток (5). Доступ к файлу заблокирован на 1 час.")
                    else:
                        await update.message.reply_text(f"❌ Неверный пароль. Осталось попыток: {5 - attempts}")
            else:
                await update.message.reply_text("❌ Файл не найден или пароль не установлен.")
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
                increment_downloads(text)
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
    except Exception as e:
        logger.error(f"Ошибка в handle_text: {e}")
        await send_error_to_admin(f"Ошибка в handle_text:\n{traceback.format_exc()}")

async def save_file_with_options(update: Update, context: ContextTypes.DEFAULT_TYPE, period):
    try:
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
        folder_id = temp.get('folder_id', 0)
        
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
        
        expires_at_str = expires_at.strftime("%Y-%m-%d %H:%M:%S") if expires_at else None
        
        context.user_data['temp_file_data'] = {
            'file_id': file_id,
            'filename': filename,
            'media_type': media_type,
            'user_id': user_id,
            'user_first_name': user_first_name,
            'expires_at': expires_at_str,
            'period_text': period_text,
            'folder_id': folder_id
        }
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒 Да, установить пароль", callback_data="final_with_pwd")],
            [InlineKeyboardButton("📁 Нет, без пароля", callback_data="final_no_pwd")]
        ])
        await query.message.edit_text(f"Срок хранения: {period_text}\n\nУстановить пароль на файл?", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка в save_file_with_options: {e}")
        await send_error_to_admin(f"Ошибка в save_file_with_options:\n{traceback.format_exc()}")

async def final_save_file_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, password=None):
    try:
        query = update.callback_query
        await query.answer()
        
        temp = context.user_data.get('temp_file_data')
        if not temp:
            await query.message.reply_text("❌ Ошибка: данные файла не найдены.")
            return
        
        await _save_file(query.message, context, temp, password)
    except Exception as e:
        logger.error(f"Ошибка в final_save_file_from_callback: {e}")
        await send_error_to_admin(f"Ошибка в final_save_file_from_callback:\n{traceback.format_exc()}")

async def final_save_file_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE, password=None):
    try:
        message = update.message
        temp = context.user_data.get('temp_file_data')
        if not temp:
            await message.reply_text("❌ Ошибка: данные файла не найдены.")
            return
        
        await _save_file(message, context, temp, password)
    except Exception as e:
        logger.error(f"Ошибка в final_save_file_from_text: {e}")
        await send_error_to_admin(f"Ошибка в final_save_file_from_text:\n{traceback.format_exc()}")

async def _save_file(message, context, temp, password=None):
    file_id = temp['file_id']
    filename = temp['filename']
    media_type = temp['media_type']
    user_id = temp['user_id']
    user_first_name = temp['user_first_name']
    expires_at = temp['expires_at']
    period_text = temp['period_text']
    folder_id = temp.get('folder_id', 0)
    
    password_hash = hash_password(password) if password else None
    
    try:
        key = str(uuid4())[:8]
        
        caption = f"📁 Файл от {user_first_name}\n🔑 Ключ: {key}"
        if expires_at:
            expires_utc = datetime.datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
            expires_local = format_datetime_for_user(expires_utc)
            caption += f"\n⏰ Удалить: {expires_local} (МСК)"
        
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

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🔑 *Ключ для этого файла:* `{key}`\n\nНажмите на ключ, чтобы скопировать.",
            parse_mode="Markdown"
        )

        save_file_info(key, file_id, filename, CHANNEL_ID, sent.message_id, media_type, user_id, folder_id, password_hash=password_hash, expires_at=expires_at)
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
            reply_markup=owner_file_actions_keyboard(key, has_password=bool(password), folder_id=folder_id)
        )
        
        context.user_data.pop('temp_file', None)
        context.user_data.pop('temp_file_data', None)
        context.user_data.pop('temp_file_needs_pwd', None)
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении: {e}")
        await send_error_to_admin(f"Ошибка при сохранении файла {filename}:\n{traceback.format_exc()}")
        await message.reply_text("❌ Ошибка при сохранении файла. Попробуйте ещё раз.")

async def open_file(update: Update, context: ContextTypes.DEFAULT_TYPE, key, parent_id, files_page):
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        
        info = get_file_info(key)
        if not info:
            await query.answer("❌ Файл не найден", show_alert=True)
            return
        
        if info.get('expires_at'):
            try:
                expires_dt = datetime.datetime.strptime(info['expires_at'], "%Y-%m-%d %H:%M:%S")
                expires_str = format_datetime_for_user(expires_dt)
            except:
                expires_str = info['expires_at']
        else:
            expires_str = "навсегда"
        
        is_owner = (info.get("user_id") == user_id)
        
        if is_owner:
            has_password = info.get("password_hash") is not None
            keyboard = owner_file_actions_keyboard(key, has_password, info.get("folder_id", 0), info.get("is_favorite", 0))
            await query.message.reply_text(
                f"📄 *{info['filename']}*\n\n"
                f"📌 Ключ: `{key}`\n"
                f"👁 Скачиваний: {info['downloads_count']}\n"
                f"⏰ Срок хранения: {expires_str}\n"
                f"⭐️ Избранное: {'Да' if info.get('is_favorite') else 'Нет'}\n\n"
                f"Выберите действие:",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            if is_file_blocked(key):
                await query.answer("⛔ Доступ к файлу заблокирован", show_alert=True)
                return
            if info.get("password_hash"):
                context.user_data['pending_file_key'] = key
                await query.message.reply_text("🔒 Файл защищён паролем. Введите пароль:")
            else:
                increment_downloads(key)
                await send_file_by_info(update.effective_chat.id, info, key, context.bot)
        
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка в open_file: {e}")
        await send_error_to_admin(f"Ошибка в open_file:\n{traceback.format_exc()}")

async def rename_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE, key):
    query = update.callback_query
    context.user_data['rename_file_key'] = key
    await query.message.reply_text("✏️ Введите новое название для файла:")
    await query.answer()

async def rename_file_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    key = context.user_data.get('rename_file_key')
    if not key:
        await update.message.reply_text("❌ Ошибка: файл не найден.")
        return
    
    user_id = update.effective_user.id
    rename_file(key, new_name, user_id)
    context.user_data.pop('rename_file_key', None)
    
    await update.message.reply_text(f"✅ Файл переименован в «{new_name}»")
    
    info = get_file_info(key)
    if info:
        if info.get('expires_at'):
            try:
                expires_dt = datetime.datetime.strptime(info['expires_at'], "%Y-%m-%d %H:%M:%S")
                expires_str = format_datetime_for_user(expires_dt)
            except:
                expires_str = info['expires_at']
        else:
            expires_str = "навсегда"
        
        has_password = info.get("password_hash") is not None
        keyboard = owner_file_actions_keyboard(key, has_password, info.get("folder_id", 0), info.get("is_favorite", 0))
        await update.message.reply_text(
            f"📄 *{new_name}*\n\n"
            f"📌 Ключ: `{key}`\n"
            f"👁 Скачиваний: {info['downloads_count']}\n"
            f"⏰ Срок хранения: {expires_str}\n"
            f"⭐️ Избранное: {'Да' if info.get('is_favorite') else 'Нет'}\n\n"
            f"Выберите действие:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

async def favorite_file(update: Update, context: ContextTypes.DEFAULT_TYPE, key):
    query = update.callback_query
    user_id = update.effective_user.id
    is_favorite = toggle_favorite(key, user_id)
    
    info = get_file_info(key)
    if info:
        has_password = info.get("password_hash") is not None
        keyboard = owner_file_actions_keyboard(key, has_password, info.get("folder_id", 0), is_favorite)
        await query.message.edit_reply_markup(reply_markup=keyboard)
    
    if is_favorite:
        await query.answer("⭐️ Файл добавлен в избранное!", show_alert=True)
    else:
        await query.answer("🗑 Файл удалён из избранного!", show_alert=True)

async def share_file_link(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    try:
        query = update.callback_query
        info = get_file_info(key)
        if not info:
            await query.answer("❌ Файл не найден", show_alert=True)
            return
        
        deep_link = f"https://t.me/{BOT_USERNAME}?start={key}"
        
        await query.message.reply_text(
            f"🔗 *Отправьте эту ссылку другу:*\n\n"
            f"`{deep_link}`\n\n"
            f"📌 *Ключ:* `{key}`\n\n"
            f"👤 *Получатель:* просто перейдёт по ссылке и файл скачается.\n"
            f"🔒 *Пароль:* {'установлен' if info.get('password_hash') else 'нет'}",
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад к файлу", callback_data=f"back_to_file_{key}_{info.get('folder_id', 0)}")]])
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка в share_file_link: {e}")
        await send_error_to_admin(f"Ошибка в share_file_link:\n{traceback.format_exc()}")

async def back_to_file(update: Update, context: ContextTypes.DEFAULT_TYPE, key, folder_id):
    try:
        query = update.callback_query
        info = get_file_info(key)
        if not info:
            await query.answer("❌ Файл не найден", show_alert=True)
            return
        
        if info.get('expires_at'):
            try:
                expires_dt = datetime.datetime.strptime(info['expires_at'], "%Y-%m-%d %H:%M:%S")
                expires_str = format_datetime_for_user(expires_dt)
            except:
                expires_str = info['expires_at']
        else:
            expires_str = "навсегда"
        
        has_password = info.get("password_hash") is not None
        keyboard = owner_file_actions_keyboard(key, has_password, folder_id, info.get("is_favorite", 0))
        
        await query.message.edit_text(
            f"📄 *{info['filename']}*\n\n"
            f"📌 Ключ: `{key}`\n"
            f"👁 Скачиваний: {info['downloads_count']}\n"
            f"⏰ Срок хранения: {expires_str}\n"
            f"⭐️ Избранное: {'Да' if info.get('is_favorite') else 'Нет'}\n\n"
            f"Выберите действие:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка в back_to_file: {e}")
        await send_error_to_admin(f"Ошибка в back_to_file:\n{traceback.format_exc()}")

async def move_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE, key, current_folder_id):
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        
        folders = get_user_folders(user_id, parent_id=0)
        
        if not folders:
            await query.answer("❌ У вас нет папок. Сначала создайте папку.", show_alert=True)
            return
        
        context.user_data['moving_file'] = {
            'key': key,
            'current_folder_id': current_folder_id
        }
        
        keyboard = []
        for folder_id, folder_name in folders:
            if folder_id != current_folder_id:
                keyboard.append([InlineKeyboardButton(f"📁 {folder_name}", callback_data=f"move_to_folder_{key}_{folder_id}")])
        keyboard.append([InlineKeyboardButton("🔙 Отмена", callback_data="cancel_move")])
        
        await query.message.reply_text("📁 Выберите папку для перемещения файла:", reply_markup=InlineKeyboardMarkup(keyboard))
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка в move_file_start: {e}")
        await send_error_to_admin(f"Ошибка в move_file_start:\n{traceback.format_exc()}")

async def move_file_to_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, key, target_folder_id):
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        
        update_file_folder(key, target_folder_id, user_id)
        
        context.user_data.pop('moving_file', None)
        
        await query.answer("✅ Файл перемещён!", show_alert=True)
        await query.message.edit_text("Файл перемещён в выбранную папку.")
    except Exception as e:
        logger.error(f"Ошибка в move_file_to_folder: {e}")
        await send_error_to_admin(f"Ошибка в move_file_to_folder:\n{traceback.format_exc()}")

async def unlock_file(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    try:
        query = update.callback_query
        remove_file_password(key)
        await query.answer("✅ Пароль снят!", show_alert=True)
        
        info = get_file_info(key)
        if info:
            has_password = info.get("password_hash") is not None
            keyboard = owner_file_actions_keyboard(key, has_password, info.get("folder_id", 0), info.get("is_favorite", 0))
            await query.message.edit_reply_markup(reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка в unlock_file: {e}")
        await send_error_to_admin(f"Ошибка в unlock_file:\n{traceback.format_exc()}")

async def new_folder_start(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id, files_page):
    try:
        query = update.callback_query
        context.user_data['new_folder_parent'] = parent_id
        context.user_data['new_folder_files_page'] = files_page
        await query.message.reply_text("Введите название папки:")
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка в new_folder_start: {e}")
        await send_error_to_admin(f"Ошибка в new_folder_start:\n{traceback.format_exc()}")

async def process_folder_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        parent_id = context.user_data.pop('new_folder_parent', 0)
        files_page = context.user_data.pop('new_folder_files_page', 0)
        
        user_id = update.effective_user.id
        create_folder(user_id, text, parent_id)
        
        await update.message.reply_text(f"✅ Папка «{text}» создана!")
        await my_files(update, context, parent_id, files_page)
    except Exception as e:
        logger.error(f"Ошибка в process_folder_creation: {e}")
        await send_error_to_admin(f"Ошибка в process_folder_creation:\n{traceback.format_exc()}")

async def delete_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, folder_id, files_page):
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('SELECT name, parent_id FROM folders WHERE id = ? AND user_id = ?', (folder_id, user_id))
        row = c.fetchone()
        conn.close()
        
        if not row:
            await query.answer("❌ Папка не найдена", show_alert=True)
            return
        
        folder_name, parent_id = row
        
        files_in_folder = delete_folder_and_files(folder_id, user_id)
        
        for key, message_id in files_in_folder:
            try:
                await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
                logger.info(f"Удалён файл {key} из канала")
            except Exception as e:
                logger.error(f"Не удалось удалить файл {key}: {e}")
        
        await query.answer(f"✅ Папка «{folder_name}» и всё её содержимое удалены!", show_alert=True)
        await my_files(update, context, parent_id, 0)
    except Exception as e:
        logger.error(f"Ошибка в delete_folder: {e}")
        await send_error_to_admin(f"Ошибка в delete_folder:\n{traceback.format_exc()}")

# --- Обработчик кнопок ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        data = query.data
        
        if data == "upload":
            await query.answer("Просто отправьте мне любой файл")
        elif data == "search_prompt":
            context.user_data['waiting_for'] = 'search_query'
            await query.message.reply_text("🔎 Введите текст для поиска (можно искать по названию файла или по ключу):")
            await query.answer()
        elif data == "favorites":
            await favorites(update, context, 0)
        elif data.startswith("favorites_page_"):
            page = int(data.split("_")[2])
            await favorites(update, context, page)
        elif data.startswith("search_page_"):
            page = int(data.split("_")[2])
            results = context.user_data.get('search_results', [])
            await query.message.edit_reply_markup(reply_markup=search_results_keyboard(results, page))
            await query.answer()
        elif data == "main_menu":
            context.user_data['current_folder'] = 0
            await query.message.edit_text("👋 Главное меню\n\nИспользуйте кнопки ниже:", reply_markup=main_keyboard())
            await query.answer()
        elif data == "about":
            await about(update, context)
        elif data == "complaint":
            await complaint(update, context)
        elif data == "help":
            await query.message.edit_text(HELP_TEXT, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            await query.answer()
        elif data == "my_files_root":
            context.user_data['current_folder'] = 0
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
                context.user_data['current_folder'] = parent_id
                await my_files(update, context, parent_id, 0)
            except:
                await query.answer("Ошибка", show_alert=True)
        elif data.startswith("my_files_"):
            try:
                parent_id = int(data.split("_")[2])
                context.user_data['current_folder'] = parent_id
                await my_files(update, context, parent_id, 0)
            except:
                await query.answer("Ошибка", show_alert=True)
        elif data.startswith("open_folder_"):
            try:
                parts = data.split("_")
                folder_id = int(parts[2])
                files_page = int(parts[3]) if len(parts) > 3 else 0
                context.user_data['current_folder'] = folder_id
                await my_files(update, context, folder_id, files_page)
            except:
                await query.answer("Ошибка", show_alert=True)
        elif data.startswith("open_file_"):
            try:
                parts = data.split("_")
                key = parts[2]
                parent_id = int(parts[3]) if len(parts) > 3 else 0
                files_page = int(parts[4]) if len(parts) > 4 else 0
                await open_file(update, context, key, parent_id, files_page)
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
        elif data.startswith("rename_"):
            key = data[7:]
            await rename_file_start(update, context, key)
        elif data.startswith("favorite_"):
            key = data[9:]
            await favorite_file(update, context, key)
        elif data.startswith("unfavorite_"):
            key = data[11:]
            await favorite_file(update, context, key)
        elif data.startswith("share_link_"):
            key = data[11:]
            await share_file_link(update, context, key)
        elif data.startswith("back_to_file_"):
            parts = data.split("_")
            key = parts[3]
            folder_id = int(parts[4]) if len(parts) > 4 else 0
            await back_to_file(update, context, key, folder_id)
        elif data.startswith("move_file_"):
            parts = data.split("_")
            key = parts[2]
            current_folder_id = int(parts[3]) if len(parts) > 3 else 0
            await move_file_start(update, context, key, current_folder_id)
        elif data.startswith("move_to_folder_"):
            parts = data.split("_")
            key = parts[3]
            target_folder_id = int(parts[4]) if len(parts) > 4 else 0
            await move_file_to_folder(update, context, key, target_folder_id)
        elif data == "cancel_move":
            context.user_data.pop('moving_file', None)
            await query.message.edit_text("❌ Перемещение отменено.")
            await query.answer()
        elif data.startswith("unlock_"):
            key = data[7:]
            await unlock_file(update, context, key)
        elif data.startswith("copy_"):
            key = data[5:]
            await query.message.reply_text(f"📌 *Ключ файла:*\n`{key}`\n\nНажмите на ключ, чтобы скопировать.", parse_mode="Markdown")
            await query.answer()
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
    except Exception as e:
        logger.error(f"Ошибка в button_handler: {e}")
        await send_error_to_admin(f"Ошибка в button_handler (data={data if 'data' in locals() else 'unknown'}):\n{traceback.format_exc()}")
