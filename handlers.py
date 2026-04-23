async def backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создаёт бэкап БД и отправляет админу"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только администратор.")
        return
    
    import os
    import datetime
    import shutil
    from config import DB_NAME
    
    if not os.path.exists(DB_NAME):
        await update.message.reply_text("❌ База данных не найдена!")
        return
    
    # Получаем количество файлов
    total_files = get_total_files()
    
    backup_name = f"files_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    
    try:
        # Копируем файл
        shutil.copy(DB_NAME, backup_name)
        
        # Отправляем админу
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=open(backup_name, 'rb'),
            filename=backup_name,
            caption=f"📦 *Бэкап базы данных*\n\n"
                   f"📅 Дата: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                   f"📄 Файлов в БД: {total_files}\n"
                   f"💾 Размер: {os.path.getsize(backup_name) / 1024:.1f} KB\n\n"
                   f"🔐 Храните файл в надёжном месте!",
            parse_mode="Markdown"
        )
        
        # Удаляем временный файл
        os.remove(backup_name)
        
        await update.message.reply_text(f"✅ Бэкап создан! Файл отправлен в чат.\n📄 Всего файлов: {total_files}")
    except Exception as e:
        logger.error(f"Ошибка при создании бэкапа: {e}")
        await update.message.reply_text(f"❌ Ошибка при создании бэкапа: {e}")

async def restore_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Восстанавливает БД из присланного файла"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только администратор.")
        return
    
    if not update.message or not update.message.document:
        await update.message.reply_text(
            "❌ *Как восстановить БД:*\n\n"
            "1. Отправьте файл бэкапа (.db)\n"
            "2. В подписи к файлу напишите `/restore`\n\n"
            "Или отправьте команду `/restore` и сразу файл.",
            parse_mode="Markdown"
        )
        return
    
    import os
    import shutil
    import sqlite3
    from config import DB_NAME
    
    # Отправляем сообщение о начале восстановления
    status_msg = await update.message.reply_text("🔄 Восстановление базы данных...")
    
    try:
        # Скачиваем файл
        file = await context.bot.get_file(update.message.document.file_id)
        temp_file = "restore_temp.db"
        await file.download_to_drive(temp_file)
        
        # Проверяем, что это валидная БД
        try:
            conn = sqlite3.connect(temp_file)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM files")
            files_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users")
            users_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM folders")
            folders_count = c.fetchone()[0]
            conn.close()
        except Exception as e:
            os.remove(temp_file)
            await status_msg.edit_text("❌ Присланный файл не является валидной базой данных!")
            return
        
        # Делаем бэкап текущей БД (если существует)
        if os.path.exists(DB_NAME):
            backup_name = f"old_db_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy(DB_NAME, backup_name)
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=open(backup_name, 'rb'),
                filename=backup_name,
                caption="📦 Старая БД (создана автоматически перед восстановлением)"
            )
            os.remove(backup_name)
        
        # Восстанавливаем БД
        shutil.copy(temp_file, DB_NAME)
        os.remove(temp_file)
        
        # Проверяем, что восстановление прошло успешно
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM files")
        new_files_count = c.fetchone()[0]
        conn.close()
        
        await status_msg.edit_text(
            f"✅ *База данных восстановлена!*\n\n"
            f"📄 Файлов: {files_count}\n"
            f"👥 Пользователей: {users_count}\n"
            f"📂 Папок: {folders_count}\n\n"
            f"🔐 Проверьте командой /stats",
            parse_mode="Markdown"
        )
        
        logger.info(f"БД восстановлена админом. Файлов: {files_count}, Пользователей: {users_count}")
        
    except Exception as e:
        logger.error(f"Ошибка при восстановлении БД: {e}")
        await status_msg.edit_text(f"❌ Ошибка при восстановлении: {e}")
