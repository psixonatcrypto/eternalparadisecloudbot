# -*- coding: utf-8 -*-
import os

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID = 483977434
BOT_USERNAME = "eternalparadisecloudbot"

# База данных
DB_NAME = "files.db"

# Часовой пояс для отображения (Москва UTC+3)
TIMEZONE_OFFSET = 3

# Тексты сообщений
ABOUT_TEXT = """🌐 *О проекте Eternal Paradise*

Мы — игровое сообщество, объединяющее любителей разных игр.

📢 *Наши ресурсы:*
• Telegram канал: [Eternal Paradise](https://t.me/eternalparadise)
• Telegram чат: [Общий чат](https://t.me/eternalparadisechat)
• Discord: [Присоединиться](https://clck.ru/34QGq6)
• ВКонтакте: [Eternal Paradise](https://vk.com/eternal.paradise)

📁 *Бот-файлообменник* позволяет:
• Хранить файлы в облаке
• Устанавливать пароль на файлы
• Создавать папки для организации
• Выбирать срок хранения

По всем вопросам: [Eternal Paradise Support](https://t.me/Eternal_paradise_supbot)
С Ув. Eternal Paradise"""

COMPLAINT_TEXT = "⚠️ *Пожаловаться на проблему*\n\nЕсли у вас возникла проблема с ботом, файлом или вы нашли нарушение — напишите в нашу службу поддержки:\n\n👉 [Eternal Paradise Support](https://t.me/Eternal_paradise_supbot)\n\nМы рассмотрим вашу жалобу в ближайшее время."

HELP_TEXT = """📌 *Как пользоваться:*
1. Отправьте файл – выберите срок хранения.
2. При желании установите пароль.
3. Нажмите «Мои файлы» – увидите папки и файлы.
4. Нажмите на файл – откроется меню управления (для своих файлов).
5. Чтобы удалить папку, откройте её и нажмите «🗑 Удалить эту папку».
6. Нажмите «🔎 Поиск» – ищите файлы по названию или ключу.

Команды: /get <ключ>, /delete <ключ>

По всем вопросам: [Eternal Paradise Support](https://t.me/Eternal_paradise_supbot)"""
