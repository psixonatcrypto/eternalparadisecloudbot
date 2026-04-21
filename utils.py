# -*- coding: utf-8 -*-
import datetime
import logging
import traceback
from config import TIMEZONE_OFFSET, ADMIN_ID

logger = logging.getLogger(__name__)

bot_instance = None

def set_bot_instance(bot):
    global bot_instance
    bot_instance = bot

async def send_error_to_admin(error_text):
    global bot_instance
    if bot_instance and ADMIN_ID:
        try:
            await bot_instance.send_message(chat_id=ADMIN_ID, text=f"⚠️ *Ошибка в боте:*\n\n```\n{error_text[:3000]}\n```", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Не удалось отправить ошибку админу: {e}")

def format_datetime_for_user(dt_utc):
    if dt_utc:
        local_dt = dt_utc + datetime.timedelta(hours=TIMEZONE_OFFSET)
        return local_dt.strftime("%d.%m.%Y %H:%M")
    return None

def hash_password(password):
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()

def check_password(password, password_hash):
    return hash_password(password) == password_hash
