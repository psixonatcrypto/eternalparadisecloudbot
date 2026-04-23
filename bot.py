# -*- coding: utf-8 -*-
import asyncio
import logging
import threading
import os
import sys
import fcntl
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from config import BOT_TOKEN
from db import init_db, get_expired_files, delete_file_info, Database
from handlers import (
    start, help_text, get_command, delete_command, delkey_command,
    broadcast, stats, search_command, check_expired_now, check_time,
    handle_file, handle_text, button_handler
)
from utils import set_bot_instance

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Проверка на двойной запуск ---
lock_file = "/tmp/bot.lock"
try:
    lock_fd = open(lock_file, 'w')
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    logger.info("✅ Блокировка получена, бот запущен единственный раз")
except IOError:
    logger.error("❌ Бот уже запущен! Завершаем работу.")
    sys.exit(1)

# --- Веб-сервер для бодрствования ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Бот работает", 200

def run_web():
    flask_app.run(host='0.0.0.0', port=8080)

threading.Thread(target=run_web, daemon=True).start()

# --- Фоновая задача для автоудаления ---
async def check_expired_files(app):
    while True:
        try:
            with Database() as c:
                c.execute('SELECT datetime("now")')
                now_sqlite = c.fetchone()[0]
                logger.info(f"Проверка просрочки | SQLite время: {now_sqlite}")
            
            expired = get_expired_files()
            if expired:
                logger.info(f"Найдено {len(expired)} просроченных файлов")
                for key, message_id, chat_id, filename, expires_at in expired:
                    try:
                        await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
                        logger.info(f"✅ Удалено сообщение {message_id} из канала для файла {filename}")
                        delete_file_info(key)
                        logger.info(f"✅ Автоудаление: {filename} (ключ {key}) удалён из БД")
                    except Exception as e:
                        logger.error(f"❌ Не удалось удалить {filename}: {e}")
            else:
                logger.info("Просроченных файлов не найдено")
        except Exception as e:
            logger.error(f"Ошибка при проверке просроченных файлов: {e}")
        await asyncio.sleep(60)

# --- Запуск ---
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    set_bot_instance(app.bot)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(check_expired_files(app))
    
    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_text))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("delkey", delkey_command))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("checkexpired", check_expired_now))
    app.add_handler(CommandHandler("checktime", check_time))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_file
    ))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Бот запущен (модульная версия)")
    
    try:
        app.run_polling()
    except Exception as e:
        logger.error(f"Ошибка при запуске polling: {e}")
    finally:
        # Освобождаем блокировку при завершении
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

if __name__ == "__main__":
    main()
