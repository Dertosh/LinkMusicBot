import asyncio
import logging
import re
import os
from threading import BoundedSemaphore
from uuid import uuid4
from collections import OrderedDict

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup,
                      InlineQueryResultArticle, LinkPreviewOptions,
                      InputTextMessageContent)
from telegram.ext import Application, CommandHandler, InlineQueryHandler, MessageHandler, filters
from telegram.error import BadRequest

from .settings import secrets
from .library import LocalLibrary
from .services import AppleMusic, Spotify, YouTube
from .security import QueryGuard, check_budget, request_budget, valid_url, normalize_query


class LinkMusicBot:
    @staticmethod
    def service_button(name, link):
        return InlineKeyboardButton(name, url=link)

    def __init__(self, token):
        self._music_services = [AppleMusic(), YouTube(), Spotify()]
        self.search_service = self._music_services[0]
        self._guard = QueryGuard()
        self._library = LocalLibrary(os.environ.get("MUSIC_CACHE_PATH", "data/music.sqlite3"))
        self._work_slots = BoundedSemaphore(2)
        self._pending_queries = OrderedDict()
        self.application = Application.builder().token(token).concurrent_updates(4).build()
        self.application.add_handler(InlineQueryHandler(self.inline_query_handler))
        self.application.add_handler(CommandHandler("start", self.message_handler))
        self.application.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND, self.message_handler,
        ))
        self.application.add_error_handler(self.error_handler)

    def make_iqr(self, item):
        rows = []
        for service in self._music_services:
            check_budget()
            try:
                link = getattr(item, "service_links", {}).get(service.service_name())
                if link is None:
                    link = service.object_to_link(item)
                if service.can_handle_link(link):
                    rows.append([self.service_button(service.service_name(), link)])
            except Exception:
                continue
        markup = InlineKeyboardMarkup(rows)
        title = item.title[:256]
        description = item.artist[:256]
        message = f"🎵 {title}\n👤 {description}\n\n🎧 Слушать на платформах ↓"
        thumbnail = None
        if item.cover_art is not None and valid_url(
            item.cover_art["url"], {"i.scdn.co", "image-cdn-ak.spotifycdn.com"}
            | {f"is{i}-ssl.mzstatic.com" for i in range(1, 6)}
        ):
            thumbnail = item.cover_art["url"]
        return InlineQueryResultArticle(
            id=uuid4().hex, title=title,
            description=description, thumbnail_url=thumbnail,
            input_message_content=InputTextMessageContent(
                message, link_preview_options=LinkPreviewOptions(
                    url=thumbnail, prefer_large_media=True, show_above_text=True,
                ) if thumbnail else LinkPreviewOptions(is_disabled=True),
            ), reply_markup=markup,
        )

    def handle_link(self, link):
        for service in self._music_services:
            if service.can_handle_link(link):
                return self.make_iqr(service.link_to_object(link))
        return None

    def handle_search(self, query):
        services = [self.search_service] + [
            service for name in ("Spotify", "YouTube")
            for service in self._music_services
            if service is not self.search_service and service.service_name() == name
        ]
        for service in services:
            check_budget()
            try:
                items = list(service.search(query, n=2))
            except Exception as error:
                logging.warning("%s search failed: %s", service.service_name(), type(error).__name__)
                continue
            if items:
                for item in items:
                    # Keep the source track; resolve other platforms to their first match.
                    if hasattr(item, "service_links"):
                        source = service.service_name()
                        item.service_links = {
                            name: link for name, link in item.service_links.items()
                            if name == source
                        }
                return [self.make_iqr(item) for item in items]
        return []

    def _build_results(self, query):
        query = normalize_query(query)
        cached = self._guard.get(query)
        if cached is not None:
            return cached
        library = getattr(self, "_library", None)
        if library is not None:
            cached = library.get(query)
            if cached is not None:
                self._guard.put(query, cached)
                return cached
        # Cancellation must not release a slot while its worker still runs.
        if not self._work_slots.acquire(blocking=False):
            return []
        try:
            with self._guard.query_lock(query):
                return self._convert_and_cache(query)
        finally:
            self._work_slots.release()

    def _convert_and_cache(self, query):
        cached = self._guard.get(query)
        if cached is not None:
            return cached
        with request_budget():
            item = self.handle_link(query)
            results = [item] if item is not None else (
                [] if "://" in query else self.handle_search(query)
            )
        self._guard.put(query, results)
        library = getattr(self, "_library", None)
        if library is not None:
            library.put(query, results)
        return results

    async def inline_query_handler(self, update, context):
        inline_query = update.inline_query
        query = inline_query.query.strip()
        results = []
        if query and len(query) <= 512:
            user = inline_query.from_user.id
            if not hasattr(self, "_pending_queries"):
                self._pending_queries = OrderedDict()
            marker = object()
            self._pending_queries[user] = marker
            self._pending_queries.move_to_end(user)
            if len(self._pending_queries) > 4096:
                self._pending_queries.popitem(last=False)
            await asyncio.sleep(0.4)
            if self._pending_queries.get(user) is not marker:
                return
            cached = self._guard.get(normalize_query(query))
            if cached is None and getattr(self, "_library", None) is not None:
                cached = self._library.get(normalize_query(query))
            if cached is not None:
                results = cached
            elif not self._guard.allow(user):
                await asyncio.sleep(5)
                if self._pending_queries.get(user) is not marker:
                    return
                if not self._guard.allow(user):
                    await inline_query.answer([], cache_time=0, is_personal=True)
                    return
            try:
                if cached is None:
                    results = await asyncio.to_thread(self._build_results, query)
            except Exception as error:
                logging.warning("Inline query processing failed: %s", type(error).__name__)
            if self._pending_queries.get(user) is not marker:
                return
            self._pending_queries.pop(user, None)
        await inline_query.answer(results, cache_time=60 if results else 0, is_personal=True)

    async def message_handler(self, update, context):
        language = (getattr(update.effective_user, "language_code", None) or "en").lower()
        username = context.bot.username
        if language.split("-")[0] == "ru":
            text = (
                "🎵 Я помогаю искать музыку в inline-режиме чата.\n\n"
                f"В любом чате введи @{username}, затем название песни или ссылку "
                "на трек. Выбери результат, чтобы отправить обложку и кнопки сервисов."
            )
        else:
            text = (
                "🎵 I help you find music in inline mode.\n\n"
                f"In any chat, type @{username} followed by a song title or track link. "
                "Choose a result to send its cover and music service buttons."
            )
        await update.effective_message.reply_text(text)

    async def error_handler(self, update, context):
        error = context.error
        detail = str(error) if isinstance(error, BadRequest) else ""
        for value in secrets.values():
            if isinstance(value, str) and value:
                detail = detail.replace(value, "[hidden]")
        detail = re.sub(r"https?://\S+", "[URL hidden]", detail)
        logging.warning("Telegram update failed: %s %s", type(error).__name__, detail[:200])

    def run(self):
        self.application.run_polling(allowed_updates=["inline_query", "message"])


def main():
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("telegram").setLevel(logging.CRITICAL)
    LinkMusicBot(secrets["telegram_token"]).run()
