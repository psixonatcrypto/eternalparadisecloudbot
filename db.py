# -*- coding: utf-8 -*-
import sqlite3
import logging
import datetime
from config import DB_NAME

logger = logging.getLogger(__name__)

# --- Контекстный менеджер для БД ---
class Database:
    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name
    
    def __enter__(self):
        self.conn = sqlite3.connect(self.db_name)
        return self.conn.cursor()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        self.conn.close()

# --- Инициализация БД ---
def init_db():
    with Database() as c:
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
            downloads_count INTEGER DEFAULT 0,
            failed_attempts INTEGER DEFAULT 0,
            blocked_until TIMESTAMP,
            is_favorite INTEGER DEFAULT 0,
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
        # Индексы для ускорения запросов
        c.execute('CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_files_folder_id ON files(folder_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_files_expires_at ON files(expires_at)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_files_user_folder ON files(user_id, folder_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_files_is_favorite ON files(is_favorite)')
    logger.info("База данных инициализирована")

# --- Функции работы с файлами ---
def save_file_info(key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id=0, password_hash=None, expires_at=None, is_favorite=0):
    with Database() as c:
        c.execute('INSERT INTO files (key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id, password_hash, expires_at, is_favorite) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                  (key, file_id, filename, chat_id, message_id, media_type, user_id, folder_id, password_hash, expires_at, is_favorite))

def get_file_info(key):
    with Database() as c:
        # Выбираем только нужные поля
        c.execute('SELECT file_id, filename, media_type, message_id, password_hash, expires_at, downloads_count, failed_attempts, blocked_until, folder_id, user_id, is_favorite FROM files WHERE key = ?', (key,))
        row = c.fetchone()
    if row:
        return {
            "file_id": row[0], "filename": row[1], "media_type": row[2],
            "message_id": row[3], "password_hash": row[4], "expires_at": row[5],
            "downloads_count": row[6] or 0, "failed_attempts": row[7] or 0,
            "blocked_until": row[8], "folder_id": row[9] or 0, "user_id": row[10],
            "is_favorite": row[11] or 0
        }
    return None

def delete_file_info(key):
    with Database() as c:
        c.execute('DELETE FROM files WHERE key = ?', (key,))

def remove_file_password(key):
    with Database() as c:
        c.execute('UPDATE files SET password_hash = NULL, failed_attempts = 0, blocked_until = NULL WHERE key = ?', (key,))

def increment_downloads(key):
    with Database() as c:
        c.execute('UPDATE files SET downloads_count = downloads_count + 1 WHERE key = ?', (key,))

def increment_failed_attempts(key):
    with Database() as c:
        c.execute('UPDATE files SET failed_attempts = failed_attempts + 1 WHERE key = ?', (key,))
        c.execute('SELECT failed_attempts FROM files WHERE key = ?', (key,))
        row = c.fetchone()
        return row[0] if row else 0

def block_file_access(key, minutes=60):
    blocked_until = (datetime.datetime.now() + datetime.timedelta(minutes=minutes)).isoformat()
    with Database() as c:
        c.execute('UPDATE files SET blocked_until = ? WHERE key = ?', (blocked_until, key))

def is_file_blocked(key):
    with Database() as c:
        # Используем SELECT 1 вместо загрузки всего поля
        c.execute('SELECT 1 FROM files WHERE key = ? AND blocked_until > datetime("now") LIMIT 1', (key,))
        row = c.fetchone()
        return row is not None

def get_expired_files(batch_size=100):
    """Возвращает просроченные файлы порциями (по умолчанию 100 за раз)"""
    now_utc = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with Database() as c:
        c.execute('SELECT key, message_id, chat_id, filename, expires_at FROM files WHERE expires_at IS NOT NULL AND expires_at <= ? LIMIT ?', (now_utc, batch_size))
        rows = c.fetchall()
    if rows:
        logger.info(f"Найдено просроченных файлов: {len(rows)} (проверка в {now_utc} UTC)")
        for row in rows:
            logger.info(f"Просрочен: {row[3]} | expires_at: {row[4]}")
    return rows

def update_file_folder(key, target_folder_id, user_id):
    with Database() as c:
        c.execute('UPDATE files SET folder_id = ? WHERE key = ? AND user_id = ?', (target_folder_id, key, user_id))

def rename_file(key, new_filename, user_id):
    with Database() as c:
        c.execute('UPDATE files SET filename = ? WHERE key = ? AND user_id = ?', (new_filename, key, user_id))

def toggle_favorite(key, user_id):
    with Database() as c:
        # Используем RETURNING для получения нового значения (SQLite 3.35+)
        try:
            c.execute('''
                UPDATE files SET is_favorite = CASE WHEN is_favorite = 1 THEN 0 ELSE 1 END 
                WHERE key = ? AND user_id = ? 
                RETURNING is_favorite
            ''', (key, user_id))
            row = c.fetchone()
            is_favorite = row[0] if row else 0
        except sqlite3.OperationalError:
            # Если RETURNING не поддерживается (старая версия SQLite), делаем два запроса
            c.execute('UPDATE files SET is_favorite = CASE WHEN is_favorite = 1 THEN 0 ELSE 1 END WHERE key = ? AND user_id = ?', (key, user_id))
            c.execute('SELECT is_favorite FROM files WHERE key = ?', (key,))
            row = c.fetchone()
            is_favorite = row[0] if row else 0
        return is_favorite

def search_files(user_id, query, limit=20):
    with Database() as c:
        c.execute('''SELECT key, filename, created_at, expires_at, downloads_count, is_favorite 
                     FROM files 
                     WHERE user_id = ? AND (LOWER(filename) LIKE LOWER(?) OR LOWER(key) LIKE LOWER(?))
                     ORDER BY is_favorite DESC, created_at DESC 
                     LIMIT ?''',
                  (user_id, f'%{query}%', f'%{query}%', limit))
        return c.fetchall()

# --- Функции работы с папками ---
def create_folder(user_id, name, parent_id=0):
    with Database() as c:
        c.execute('INSERT INTO folders (name, user_id, parent_id) VALUES (?, ?, ?)', (name, user_id, parent_id))
        return c.lastrowid

def get_user_folders(user_id, parent_id=0):
    with Database() as c:
        c.execute('SELECT id, name FROM folders WHERE user_id = ? AND parent_id = ? ORDER BY name', (user_id, parent_id))
        return c.fetchall()

def get_user_files_in_folder(user_id, folder_id=0, limit=10, offset=0):
    with Database() as c:
        # Используем оконную функцию COUNT(*) OVER() для получения общего количества за один запрос
        c.execute('''
            SELECT key, filename, created_at, expires_at, downloads_count, is_favorite, COUNT(*) OVER() as total_count
            FROM files 
            WHERE user_id = ? AND folder_id = ? 
            ORDER BY is_favorite DESC, created_at DESC 
            LIMIT ? OFFSET ?
        ''', (user_id, folder_id, limit, offset))
        rows = c.fetchall()
        total = rows[0][6] if rows else 0
        # Убираем total_count из результатов
        rows = [row[:6] for row in rows]
        return rows, total

def delete_folder_and_files(folder_id, user_id):
    """Удаляет папку и все файлы внутри неё. Возвращает список файлов для удаления из канала"""
    files_to_delete = []
    with Database() as c:
        # Получаем файлы в папке
        c.execute('SELECT key, message_id FROM files WHERE folder_id = ? AND user_id = ?', (folder_id, user_id))
        files_to_delete.extend(c.fetchall())
        # Удаляем файлы из БД
        c.execute('DELETE FROM files WHERE folder_id = ? AND user_id = ?', (folder_id, user_id))
        # Получаем подпапки
        c.execute('SELECT id FROM folders WHERE parent_id = ? AND user_id = ?', (folder_id, user_id))
        subfolders = c.fetchall()
        for sub_id, in subfolders:
            # Рекурсивно собираем файлы из подпапок
            c.execute('SELECT key, message_id FROM files WHERE folder_id = ? AND user_id = ?', (sub_id, user_id))
            files_to_delete.extend(c.fetchall())
            c.execute('DELETE FROM files WHERE folder_id = ? AND user_id = ?', (sub_id, user_id))
            c.execute('DELETE FROM folders WHERE id = ? AND user_id = ?', (sub_id, user_id))
        # Удаляем саму папку
        c.execute('DELETE FROM folders WHERE id = ? AND user_id = ?', (folder_id, user_id))
        return files_to_delete

# --- Функции работы с пользователями ---
def save_user(user_id, first_name, username):
    with Database() as c:
        c.execute('INSERT OR REPLACE INTO users (user_id, first_name, username, last_seen) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
                  (user_id, first_name, username))

def get_all_users():
    with Database() as c:
        c.execute('SELECT user_id FROM users')
        return [row[0] for row in c.fetchall()]

def get_total_files():
    with Database() as c:
        c.execute('SELECT COUNT(*) FROM files')
        return c.fetchone()[0]

def get_new_users_count(days=0):
    with Database() as c:
        if days > 0:
            c.execute('SELECT COUNT(*) FROM users WHERE last_seen >= datetime("now", ?)', (f"-{days} days",))
        else:
            c.execute('SELECT COUNT(*) FROM users')
        return c.fetchone()[0]
