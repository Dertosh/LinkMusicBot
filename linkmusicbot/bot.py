import asyncio
import logging
import re
import os
import time
from contextvars import ContextVar, copy_context
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import BoundedSemaphore
from collections import OrderedDict

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle,
                      InlineQueryResultsButton, InputTextMessageContent)
from telegram.ext import Application, CommandHandler, InlineQueryHandler, MessageHandler, filters, ChosenInlineResultHandler, CallbackQueryHandler
from telegram.error import BadRequest
from telegram.request import HTTPXRequest

from .settings import secrets
from .library import LocalLibrary
from .presentation import build_result
from .services import AppleMusic, Spotify, YouTube, YandexMusic
from .services.base import search_links, query_variants, same_recording, recording_identity
from .models import Song
from .search_ranking import rank_results, query_matches
from .about import ATTRIBUTION
from .spotify_account import SpotifyAccount, AccountError, NotConnected
from .usage import UsageStats
from .progressive_inline import ProgressiveInlineMixin
from .cover_photos import CoverStore, as_photo, as_text, as_preview
from .security import QueryGuard, check_budget, request_budget, normalize_query, youtube_music_url, http_session_scope

_RECHECKING_CACHE = ContextVar('rechecking_music_cache', default=False)


class LinkMusicBot(ProgressiveInlineMixin):
    @staticmethod
    def _parallel_services(services, operation):
        # Copy the caller's absolute deadline and cache-refresh context into
        # every worker. Gather in provider order, independent of completion.
        if not services:
            return []
        def run(service):
            started = time.monotonic()
            try:
                with http_session_scope():
                    return operation(service)
            finally:
                elapsed = time.monotonic() - started
                name = service.service_name() if hasattr(service, 'service_name') else type(service).__name__
                logging.info('Provider job: %s %.3fs', name, elapsed)
                if elapsed > 3:
                    logging.warning('Slow provider job: %s %.3fs', name, elapsed)
        with ThreadPoolExecutor(max_workers=min(4, len(services))) as pool:
            futures = [pool.submit(copy_context().run, run, service) for service in services]
            return [future.result() for future in futures]

    @staticmethod
    def service_button(name, link):
        if name == "YouTube":
            link = youtube_music_url(link)
        return InlineKeyboardButton(name, url=link)

    def __init__(self, token):
        self._music_services = [AppleMusic(), YouTube(), Spotify(), YandexMusic()]
        self.search_service = self._music_services[0]
        self._guard = QueryGuard()
        self._library = LocalLibrary(os.environ.get("MUSIC_CACHE_PATH", "data/music.sqlite3"))
        self._covers = CoverStore(str(Path(os.environ.get('MUSIC_CACHE_PATH', 'data/music.sqlite3')).parent / 'covers.sqlite3'))
        self._work_slots = BoundedSemaphore(2)
        self._pending_queries = OrderedDict()
        self._refreshing = set()
        self._refresh_tasks = set()
        self._usage = UsageStats(str(Path(os.environ.get('MUSIC_CACHE_PATH', 'data/music.sqlite3')).parent / 'usage.sqlite3'))
        self.spotify_account = None
        if secrets.get('spotify_redirect_uri'):
            key = secrets.get('spotify_token_key', '')
            if secrets.get('spotify_token_key_file'):
                key = Path(secrets['spotify_token_key_file']).read_text().strip()
            self.spotify_account = SpotifyAccount(secrets.get('spotify_client_id'), secrets['spotify_redirect_uri'],
                                                  key, str(Path(os.environ.get('MUSIC_CACHE_PATH', 'data/music.sqlite3')).parent / 'spotify-accounts.sqlite3'))
        self.application = (Application.builder().token(token).concurrent_updates(4)
            .request(HTTPXRequest(connect_timeout=10, read_timeout=10, httpx_kwargs={'trust_env': False}))
            .get_updates_request(HTTPXRequest(connect_timeout=10, read_timeout=40, httpx_kwargs={'trust_env': False}))
            .build())
        self.application.add_handler(InlineQueryHandler(self.inline_query_handler))
        self.application.add_handler(ChosenInlineResultHandler(self.chosen_inline_handler))
        self.application.add_handler(CallbackQueryHandler(self.loading_callback, pattern='^music_loading(?:$|:)'))
        self.application.add_handler(CommandHandler("start", self.message_handler))
        self.application.add_handler(CommandHandler('chatid', self.chat_id_command))
        self.application.add_handler(CommandHandler('connect_spotify', self.connect_spotify))
        self.application.add_handler(CommandHandler('disconnect_spotify', self.disconnect_spotify))
        self.application.add_handler(CommandHandler('current', self.current_command))
        self.application.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND, self.message_handler,
        ))
        self.application.add_error_handler(self.error_handler)

    def make_iqr(self, item):
        rows = []
        known_links = {}
        library = getattr(self, '_library', None)
        if isinstance(library, LocalLibrary) and not _RECHECKING_CACHE.get():
            from .services.base import recording_query
            for cached in library.get_local(recording_query(item)) or []:
                if same_recording(item, cached.title, cached.description or ''):
                    for row in cached.reply_markup.inline_keyboard:
                        for button in row:
                            if button.url and not re.search(r'/(?:search|results)(?:/|\?|$)', button.url):
                                known_links[button.text] = button.url
        def resolve(service):
            candidate = deepcopy(item)
            try:
                check_budget()
                link = getattr(candidate, "service_links", {}).get(service.service_name())
                if link is None or re.search(r'/(?:search|results)(?:/|\?|$)', link):
                    link = known_links.get(service.service_name(), link)
                if link is None:
                    link = service.object_to_link(candidate)
                if service.can_handle_link(link):
                    return service, link, candidate.cover_art
            except Exception:
                fallback = Song(item.title, item.artist, "")
                search_links(fallback, "", "")
                link = fallback.service_links.get(service.service_name())
                if link and service.can_handle_link(link):
                    return service, link, None
            return None
        # Most title-search cards already contain all their links. Rendering
        # those cards requires no network and must not spawn a pool per card.
        resolved_links = {}
        pending = []
        for service in self._music_services:
            link = getattr(item, 'service_links', {}).get(service.service_name())
            if link is None or re.search(r'/(?:search|results)(?:/|\?|$)', link):
                link = known_links.get(service.service_name(), link)
            if link is not None:
                resolved_links[id(service)] = (service, link, None) if service.can_handle_link(link) else None
            else:
                pending.append(service)
        for resolved, service in zip(self._parallel_services(pending, resolve), pending):
            resolved_links[id(service)] = resolved
        for service in self._music_services:
            resolved = resolved_links[id(service)]
            if resolved is not None:
                service, link, cover = resolved
                rows.append([self.service_button(service.service_name(), link)])
                if item.cover_art is None and cover is not None:
                    item.cover_art = cover
        return build_result(item, rows)

    def handle_link(self, link):
        for service in self._music_services:
            if service.can_handle_link(link):
                return self.make_iqr(service.link_to_object(link))
        return None

    def _retain_direct_links(self, result, cached):
        data = result.to_dict()
        old_links = {b.text: b.url for row in cached.reply_markup.inline_keyboard for b in row}
        for row in data.get("reply_markup", {}).get("inline_keyboard", []):
            for button in row:
                name = button.get("text")
                old = old_links.get(name, "")
                service = next((s for s in self._music_services if s.service_name() == name), None)
                search = r"https://[^/]+/(?:[^/]+/)?(?:search(?:/|\?|$)|results(?:\?|$))"
                if service and re.match(search, button.get("url", "")) and old and not re.match(search, old) and service.can_handle_link(old):
                    button["url"] = old
        data["reply_markup"] = InlineKeyboardMarkup.de_json(data.get("reply_markup") or {"inline_keyboard": []}, None)
        return InlineQueryResultArticle.de_json(data, None)

    def _link_results(self, query):
        result = self.handle_link(query)
        if result is None:
            return []
        results = [result]
        if isinstance(result, InlineQueryResultArticle) and re.search(r'\(Cover(?: Remix)? by ', result.title):
            selected = Song(result.title, result.description or "", "")
            title, _ = recording_identity(selected.title, selected.artist)
            title = re.sub(r'\s*\((?:Russian|English|Japanese)\s+(?:Ver\.?|Version)\)', '', title, flags=re.I).strip()
            # The selected cover stays first; alternative performers/versions
            # remain separate cards with their own verified service links.
            for alternative in self.handle_search(title):
                if not same_recording(selected, alternative.title, alternative.description or ""):
                    results.append(alternative)
        return results[:50]

    def handle_search(self, query):
        query = normalize_query(query)
        services = [self.search_service] + [
            service for name in ("Spotify", "Яндекс Музыка", "YouTube")
            for service in self._music_services
            if service is not self.search_service and service.service_name() == name
        ]
        def search_provider(service):
            found = []
            for variant in query_variants(query):
                try:
                    check_budget()
                    items = list(service.search(variant, n=10))
                except Exception as error:
                    logging.warning("%s search failed: %s", service.service_name(), type(error).__name__)
                    continue
                found.extend(items)
            return service, found
        found = []
        for service, items in self._parallel_services(services, search_provider):
            source = service.service_name()
            for item in items:
                if not query_matches(item.title, item.artist, query):
                    continue
                source_link = getattr(item, "service_links", {}).get(source)
                existing = next((s for s in found if same_recording(s, item.title, item.artist,
                    duration_ms=getattr(item, 'duration_ms', None), isrc=getattr(item, 'isrc', None))), None)
                if existing is not None:
                    if source_link:
                        existing.service_links[source] = source_link
                    if existing.cover_art is None:
                        existing.cover_art = item.cover_art
                    continue
                search_links(item, source, source_link or search_links(
                    Song(item.title, item.artist, ""), "", "").service_links.get(source, ""))
                found.append(item)
        ranked = rank_results(found, query)[:50]
        # Yandex's track index can omit a release present in its artist
        # catalogue. Enrich only the first three cards, not every result.
        yandex = next((s for s in self._music_services if isinstance(s, YandexMusic)), None)
        if yandex is not None:
            def enrich(service):
                for item in ranked[:3]:
                    link = item.service_links.get(service.service_name(), '')
                    if link and '/search?' not in link:
                        continue
                    try:
                        check_budget()
                        item.service_links[service.service_name()] = service.song_to_link(deepcopy(item))
                    except Exception:
                        # Keep the source card and explicit search on failure.
                        pass
            self._parallel_services([yandex], enrich)
        # Other buttons use proven merged links or explicit searches instead
        # of multiplying provider requests for every inline candidate.
        results = [self.make_iqr(item) for item in ranked]
        library = getattr(self, "_library", None)
        if isinstance(library, LocalLibrary) and not _RECHECKING_CACHE.get():
            for candidate in library.get_local(query) or []:
                if not query_matches(candidate.title, candidate.description or "", query):
                    continue
                if re.search(r"\bOfficial\s+(?:MV|Video|Music Video)\b", candidate.title, re.I):
                    # Legacy YouTube search stored the uploader as the artist.
                    # Do not reintroduce those raw previews as verified songs.
                    continue
                expected = Song(candidate.title, candidate.description or "", "")
                index = next((i for i, r in enumerate(results) if same_recording(expected, r.title, r.description or "")), None)
                if index is not None:
                    results[index] = self._retain_direct_links(results[index], candidate)
                else:
                    results.append(candidate)
        return rank_results(results, query)[:50]

    def _schedule_refresh(self, query):
        library = getattr(self, "_library", None)
        if not isinstance(library, LocalLibrary) or not library.needs_refresh(query):
            return
        if not hasattr(self, "_refreshing"):
            self._refreshing, self._refresh_tasks = set(), set()
        # Keep one of the two worker slots available for interactive misses.
        if self._refreshing or not self._work_slots.acquire(blocking=False):
            return
        if not hasattr(self, '_refresh_guard'):
            self._refresh_guard = QueryGuard()
        if not self._refresh_guard.allow(-1):
            self._work_slots.release()
            return
        self._refreshing.add(query)
        try:
            library.mark_refresh(query)
        except Exception:
            self._refreshing.discard(query)
            self._work_slots.release()
            raise
        async def refresh():
            try:
                worker = asyncio.create_task(asyncio.to_thread(self._refresh_query, query))
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    # A cancelled asyncio task must not release a worker slot
                    # while the underlying request thread is still running.
                    await asyncio.shield(worker)
                    raise
            except Exception as error:
                logging.warning("Cache refresh failed: %s", type(error).__name__)
            finally:
                self._refreshing.discard(query)
                self._work_slots.release()
        task = asyncio.create_task(refresh())
        self._refresh_tasks.add(task)
        task.add_done_callback(self._refresh_tasks.discard)

    def _refresh_query(self, query):
        token = _RECHECKING_CACHE.set(True)
        try:
            with self._guard.query_lock(query), request_budget():
                if "://" in query:
                    results = self._link_results(query)
                else:
                    results = self.handle_search(query)
        finally:
            _RECHECKING_CACHE.reset(token)
        # Service failures must not erase a previously useful snapshot.
        if results:
            self._library.put(query, results)
            self._guard.put(query, results)

    def _build_results(self, query):
        query = normalize_query(query)
        cached = self._guard.get(query)
        if cached is not None and not self._needs_yandex(cached):
            return cached
        library = getattr(self, "_library", None)
        if library is not None:
            cached = library.get(query)
            if cached is not None:
                self._guard.put(query, cached)
                if not self._needs_yandex(cached):
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
            if not self._needs_yandex(cached):
                return cached
            service = next(s for s in self._music_services if isinstance(s, YandexMusic))
            results = []
            with request_budget():
                for result in cached:
                    if not isinstance(result, InlineQueryResultArticle):
                        results.append(result)
                        continue
                    rows = list(result.reply_markup.inline_keyboard)
                    if not any(button.text == service.service_name() for row in rows for button in row):
                        link = service.song_to_link(Song(result.title, result.description or "", ""))
                        rows.append([self.service_button(service.service_name(), link)])
                    data = result.to_dict()
                    data["reply_markup"] = InlineKeyboardMarkup(rows)
                    results.append(type(result).de_json(data, None))
            self._guard.put(query, results)
            library = getattr(self, "_library", None)
            if library is not None:
                library.put(query, results)
            return results
        with request_budget():
            results = self._link_results(query)
            if not results and "://" not in query:
                results = self.handle_search(query)
        self._guard.put(query, results)
        library = getattr(self, "_library", None)
        if library is not None:
            library.put(query, results)
        return results

    def _needs_yandex(self, results):
        if not any(isinstance(service, YandexMusic) for service in getattr(self, "_music_services", [])):
            return False
        return any(isinstance(result, InlineQueryResultArticle) and
                   not any(button.text == "Яндекс Музыка" for row in result.reply_markup.inline_keyboard for button in row)
                   for result in results)

    async def inline_query_handler(self, update, context):
        started = time.monotonic()
        inline_query = update.inline_query
        query = inline_query.query.strip()
        if query.casefold() in {'current', '/current'}:
            self._record_usage(inline_query.from_user, 'inline')
            await self.current_inline(update, context)
            return
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
            await asyncio.sleep(0.1 if '://' in query else secrets.get("inline_debounce_ms", 600) / 1000)
            if self._pending_queries.get(user) is not marker:
                return
            self._record_usage(inline_query.from_user, 'inline')
            cached = self._guard.get(normalize_query(query))
            if cached is None and getattr(self, "_library", None) is not None:
                cached = self._library.get(normalize_query(query))
            if cached is not None and self._needs_yandex(cached):
                cached = None
            if cached is not None:
                results = cached
                self._schedule_refresh(normalize_query(query))
            elif not self._guard.allow(user, min_interval=1):
                await asyncio.sleep(1)
                if self._pending_queries.get(user) is not marker:
                    return
                if not self._guard.allow(user, min_interval=1):
                    await inline_query.answer([], cache_time=0, is_personal=True)
                    return
            try:
                if cached is None:
                    progressive = await self._progressive_results(query, user) if '://' in query else None
                    if progressive is None:
                        results = await asyncio.to_thread(self._build_results, query)
                    else:
                        results = progressive
            except Exception as error:
                logging.warning("Inline query processing failed: %s", type(error).__name__)
            if self._pending_queries.get(user) is not marker:
                return
            self._pending_queries.pop(user, None)
        offset = getattr(inline_query, "offset", "")
        offset = int(offset) if isinstance(offset, str) and offset.isdigit() else 0
        size = secrets.get("inline_result_limit", 10)
        page = results[offset:offset + size]
        # One visible card. Retry formats only when Bot API reports a media error.
        media_page = []
        for result in page:
            if isinstance(result, InlineQueryResultArticle) and result.thumbnail_url:
                media_page.append(as_preview(result))
            else:
                media_page.append(result)
        next_offset = str(offset + size) if offset + size < len(results) else ""
        kwargs = {"next_offset": next_offset} if next_offset else {}
        elapsed = time.monotonic()-started
        if elapsed > 3:
            logging.warning('Slow inline response: %.2fs, results=%d', elapsed, len(page))
        loading = any(getattr(result, 'id', '').startswith('p-') for result in page)
        try:
            await inline_query.answer(media_page, cache_time=0 if loading or not page else 60, is_personal=True, **kwargs)
        except BadRequest as error:
            detail = str(error).lower()
            if not any(word in detail for word in ('photo', 'file_id', 'file identifier', 'webpage', 'embed')):
                raise
            photos = []
            for result in page:
                if isinstance(result, InlineQueryResultArticle) and result.thumbnail_url:
                    file_id = self._covers.get(self.application.bot.id, result.thumbnail_url) if getattr(self, '_covers', None) else None
                    photos.append(as_photo(result, file_id))
                else:
                    photos.append(result)
            try:
                await inline_query.answer(photos, cache_time=0, is_personal=True, **kwargs)
                return
            except BadRequest as photo_error:
                detail = str(photo_error).lower()
                if not any(word in detail for word in ('photo', 'file_id', 'file identifier', 'webpage', 'media')):
                    raise
                for result in page:
                    if getattr(result, 'thumbnail_url', None) and getattr(self, '_covers', None):
                        self._covers.forget(self.application.bot.id, result.thumbnail_url)
            text_page = [as_text(r) if isinstance(r, InlineQueryResultArticle) else r for r in page]
            await inline_query.answer(text_page, cache_time=0, is_personal=True, **kwargs)

    async def chat_id_command(self, update, context):
        await update.effective_message.reply_text('ID чата: ' + str(update.effective_chat.id))

    async def message_handler(self, update, context):
        if getattr(context, 'args', None) == ['spotify']:
            await self.connect_spotify(update, context)
            return
        self._record_usage(update.effective_user, 'start')
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
        text += "\n\n" + ATTRIBUTION["ru" if language.split("-")[0] == "ru" else "en"]
        text += ('\n\n/connect_spotify — подключить Spotify\n/current — текущая песня\n'
                 'В чате: @' + username + ' current\n/disconnect_spotify — отключить аккаунт'
                 if language.split('-')[0] == 'ru' else
                 '\n\n/connect_spotify — connect Spotify\n/current — current track\n'
                 'In a chat: @' + username + ' current\n/disconnect_spotify — disconnect account')
        await update.effective_message.reply_text(text)

    @staticmethod
    def _account_text(update, ru, en):
        return ru if (getattr(update.effective_user, 'language_code', '') or '').lower().startswith('ru') else en

    def _record_usage(self, user, kind):
        usage = getattr(self, '_usage', None)
        if usage is not None:
            try:
                usage.record(user, kind)
            except Exception:
                logging.warning('Usage counter unavailable')

    async def connect_spotify(self, update, context):
        self._record_usage(update.effective_user, 'connect')
        if update.effective_chat.type != 'private':
            await update.effective_message.reply_text(self._account_text(update, 'Подключайте Spotify в личном чате бота.', 'Connect Spotify in a private chat with the bot.'))
            return
        if not self.spotify_account:
            await update.effective_message.reply_text(self._account_text(update, 'Авторизация Spotify пока не настроена на сервере.', 'Spotify authorization is not configured on this server yet.'))
            return
        url = await asyncio.to_thread(self.spotify_account.begin, update.effective_user.id)
        await update.effective_message.reply_text(self._account_text(update, 'Подключите Spotify. Ссылка действует 10 минут; не пересылайте её.', 'Connect Spotify. This link expires in 10 minutes; do not forward it.'),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Spotify', url=url)]]))

    async def disconnect_spotify(self, update, context):
        self._record_usage(update.effective_user, 'disconnect')
        if update.effective_chat.type != 'private':
            await update.effective_message.reply_text(self._account_text(update, 'Отключайте аккаунт в личном чате бота.', 'Disconnect in a private chat with the bot.'))
            return
        if self.spotify_account:
            await asyncio.to_thread(self.spotify_account.disconnect, update.effective_user.id)
        await update.effective_message.reply_text(self._account_text(update, 'Аккаунт отключён, сохранённые токены удалены.', 'Account disconnected; stored tokens deleted.'))

    def _current_result(self, user):
        if not self.spotify_account:
            raise NotConnected('Spotify authorization is not configured.')
        if not self._work_slots.acquire(blocking=False):
            raise AccountError('Please try again shortly.')
        try:
            song = self.spotify_account.current(user)
            if song is None:
                return None
            # Only public song metadata can enter the catalogue. Never cache a
            # user/current association, access token or playback response there.
            source = song.service_links['Spotify']
            search_links(song, 'Spotify', source)
            with request_budget(8):
                return self.make_iqr(song)
        finally:
            self._work_slots.release()

    async def current_command(self, update, context):
        self._record_usage(update.effective_user, 'current')
        try:
            result = await asyncio.to_thread(self._current_result, update.effective_user.id)
        except NotConnected:
            await update.effective_message.reply_text(self._account_text(update, 'Сначала подключите аккаунт: /connect_spotify в личном чате бота.', 'First use /connect_spotify in a private chat with the bot.'))
            return
        except AccountError:
            await update.effective_message.reply_text(self._account_text(update, 'Spotify временно недоступен. Повторите позже.', 'Spotify is temporarily unavailable. Try again later.'))
            return
        if result is None:
            await update.effective_message.reply_text(self._account_text(update, 'Сейчас музыка не играет. Включите трек в Spotify.', 'Nothing is playing. Start a track in Spotify.'))
            return
        content = result.input_message_content
        rows = list(result.reply_markup.inline_keyboard)
        rows.append([InlineKeyboardButton(self._account_text(update, 'Отправить в чат', 'Send to a chat'), switch_inline_query='current')])
        await update.effective_message.reply_text(content.message_text, reply_markup=InlineKeyboardMarkup(rows),
                                                 link_preview_options=content.link_preview_options)

    async def current_inline(self, update, context):
        inline = update.inline_query
        try:
            result = await asyncio.to_thread(self._current_result, inline.from_user.id)
        except NotConnected:
            await inline.answer([], cache_time=0, is_personal=True,
                button=InlineQueryResultsButton(text=self._account_text(update, 'Подключить Spotify', 'Connect Spotify'), start_parameter='spotify'))
            return
        except AccountError:
            text = self._account_text(update, 'Spotify временно недоступен. Повторите позже.', 'Spotify is temporarily unavailable. Try again later.')
            result = InlineQueryResultArticle(id='current-unavailable', title=text, input_message_content=InputTextMessageContent(text))
        if result is None:
            text = self._account_text(update, 'Сейчас музыка не играет. Включите трек в Spotify.', 'Nothing is playing. Start a track in Spotify.')
            result = InlineQueryResultArticle(id='current-empty', title=text, input_message_content=InputTextMessageContent(text))
        await inline.answer([result], cache_time=0, is_personal=True)

    async def error_handler(self, update, context):
        error = context.error
        detail = str(error) if isinstance(error, BadRequest) else ""
        for value in secrets.values():
            if isinstance(value, str) and value:
                detail = detail.replace(value, "[hidden]")
        detail = re.sub(r"https?://\S+", "[URL hidden]", detail)
        logging.warning("Telegram update failed: %s %s", type(error).__name__, detail[:200])

    def run(self):
        server = None
        if self.spotify_account:
            from .spotify_callback import start_callback
            server = start_callback(self.spotify_account, port=secrets.get('spotify_callback_port', 8080))
        try:
            self.application.run_polling(allowed_updates=["inline_query", "message", "chosen_inline_result", "callback_query"], bootstrap_retries=10)
        finally:
            if server:
                server.shutdown()
                server.server_close()
            if self.spotify_account:
                self.spotify_account.close()
            if getattr(self, '_usage', None) is not None:
                self._usage.close()
            if getattr(self, '_covers', None) is not None:
                self._covers.close()


def main():
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("telegram").setLevel(logging.CRITICAL)
    LinkMusicBot(secrets["telegram_token"]).run()
