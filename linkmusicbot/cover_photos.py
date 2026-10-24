"""Photo inline cards and persistent Telegram file IDs for cover reuse."""
import asyncio
import sqlite3
import time
from pathlib import Path
from threading import Lock

from telegram import InlineQueryResultArticle, InlineQueryResultPhoto, InlineQueryResultCachedPhoto, InlineKeyboardButton, InlineKeyboardMarkup, InputTextMessageContent, LinkPreviewOptions


def message_text(result):
    """Read message text from either an SDK content object or a cached dictionary."""
    content = result.input_message_content
    return content.get('message_text', '') if isinstance(content, dict) else content.message_text


def as_photo(result, file_id=None):
    """Build a URL or cached photo result and preserve loading callback identity."""
    rows = []
    for row in result.reply_markup.inline_keyboard:
        buttons = []
        for button in row:
            if button.callback_data and button.callback_data.startswith('music_loading:'):
                data = button.to_dict()
                data['callback_data'] = 'music_loading:ph-' + button.callback_data.partition(':')[2]
                button = InlineKeyboardButton.de_json(data, None)
            buttons.append(button)
        rows.append(buttons)
    common = dict(id='ph-' + result.id, title=result.title, description=result.description,
                  caption=message_text(result)[:1024], reply_markup=InlineKeyboardMarkup(rows))
    if file_id:
        return InlineQueryResultCachedPhoto(photo_file_id=file_id, **common)
    return InlineQueryResultPhoto(photo_url=result.thumbnail_url,
                                  thumbnail_url=result.thumbnail_url, **common)


def as_text(result):
    """Build a text-only fallback with webpage previews explicitly disabled."""
    return InlineQueryResultArticle(id='tx-' + result.id, title=result.title,
        description=result.description, input_message_content=InputTextMessageContent(
            message_text(result), link_preview_options=LinkPreviewOptions(is_disabled=True)),
        reply_markup=result.reply_markup)


def as_preview(result):
    """Build an article with the cover URL used as a large webpage preview."""
    return InlineQueryResultArticle(id=result.id, title=result.title,
        description=result.description, thumbnail_url=result.thumbnail_url,
        input_message_content=InputTextMessageContent(message_text(result),
            link_preview_options=LinkPreviewOptions(url=result.thumbnail_url,
                prefer_large_media=True, show_above_text=True)), reply_markup=result.reply_markup)


class CoverStore:
    def __init__(self, path):
        """Open the persistent, per-bot mapping from cover URLs to Telegram file IDs."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS covers '
                        '(bot_id TEXT, url TEXT, file_id TEXT, updated REAL, PRIMARY KEY(bot_id,url))')
        self._uploads = {}

    def get(self, bot_id, url):
        """Return the cached Telegram file ID for this bot and cover URL, if present."""
        with self.lock:
            row = self.db.execute('SELECT file_id FROM covers WHERE bot_id=? AND url=?',
                                  (str(bot_id), url)).fetchone()
        return row[0] if row else None

    def put(self, bot_id, url, file_id):
        """Persist a reusable cover file ID scoped to the bot that uploaded it."""
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO covers VALUES (?,?,?,?)',
                            (str(bot_id), url, file_id, time.time()))

    def forget(self, bot_id, url):
        """Remove a rejected file ID so a later request can upload the cover again."""
        with self.lock, self.db:
            self.db.execute('DELETE FROM covers WHERE bot_id=? AND url=?', (str(bot_id), url))

    async def upload(self, bot, chat_id, url):
        """Reuse a saved file ID or coalesce concurrent uploads of the same cover."""
        existing = self.get(bot.id, url)
        if existing:
            return existing
        key = (bot.id, url)
        # File IDs belong to a bot; sharing the same URL does not make them
        # transferable to another bot using this database.
        if key in self._uploads:
            return await asyncio.shield(self._uploads[key])
        async def send():
            photo = await bot.send_photo(chat_id=chat_id, photo=url, disable_notification=True)
            file_id = photo.photo[-1].file_id
            self.put(bot.id, url, file_id)
            return file_id
        task = asyncio.create_task(send())
        self._uploads[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._uploads.pop(key, None)

    def close(self):
        """Close the cover metadata database."""
        self.db.close()
