"""Fast source previews and progressive edits of chosen inline messages."""
import asyncio
from copy import deepcopy
import logging
import time
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent, LinkPreviewOptions, InputMediaPhoto
from telegram.error import BadRequest, RetryAfter

from .models import Song
from .presentation import build_result
from .security import normalize_query, request_budget, http_session_scope
from .services.base import search_links
from .cover_photos import message_text


class ProgressiveInlineMixin:
    def _progressive_state(self):
        """Initialize job indexes and expire completed jobs after their retention period."""
        if not hasattr(self, '_link_jobs'):
            self._link_jobs = {}
            self._link_queries = {}
        now = time.monotonic()
        for identifier, job in list(self._link_jobs.items()):
            if job['done'] and now - job['created'] > 1800:
                self._link_jobs.pop(identifier)
                if self._link_queries.get(job['query']) == identifier:
                    self._link_queries.pop(job['query'], None)

    def _progressive_card(self, job):
        """Build a current snapshot of source links, resolved platforms, and loading state."""
        rows = [[self.service_button(s.service_name(), job['links'][s.service_name()])]
                for s in self._music_services if s.service_name() in job['links']]
        result = build_result(job['song'], rows)
        content = result.input_message_content
        description = result.description
        if not job['done']:
            rows.append([InlineKeyboardButton('⏳ Поиск площадок…', callback_data='music_loading:' + job['id'])])
            result = build_result(job['song'], rows)
            content = InputTextMessageContent(
                content.message_text + '\n\n⏳ Ищу ссылки на других площадках…',
                link_preview_options=content.link_preview_options)
            description = (job['song'].artist + ' · ⏳ Поиск площадок…')[:256]
        return InlineQueryResultArticle(id=job['id'], title=result.title,
            description=description, thumbnail_url=result.thumbnail_url,
            input_message_content=content, reply_markup=result.reply_markup)

    async def _progressive_results(self, query, user):
        """Read a supported source URL and start or reuse a background resolution job."""
        self._progressive_state()
        query = normalize_query(query)
        identifier = self._link_queries.get(query)
        if identifier in self._link_jobs:
            job = self._link_jobs[identifier]
            job['users'].add(user)
            return [self._progressive_card(job)]
        service = next((s for s in self._music_services if s.can_handle_link(query)
                        and s.link_is_song(query)), None)
        if service is None:
            return None
        # Bound memory and background work even if clients submit many URLs.
        if len(self._link_jobs) >= 256 or not self._work_slots.acquire(blocking=False):
            return []
        try:
            def source():
                with request_budget(15), http_session_scope():
                    return service.link_to_song(query)
            worker = asyncio.create_task(asyncio.to_thread(source))
            try:
                song = await asyncio.shield(worker)
            except asyncio.CancelledError:
                await worker
                raise
        finally:
            self._work_slots.release()
        if not isinstance(song, Song):
            return None
        # Another request may have finished reading this same source meanwhile.
        identifier = self._link_queries.get(query)
        if identifier in self._link_jobs:
            job = self._link_jobs[identifier]
            job['users'].add(user)
            return [self._progressive_card(job)]
        identifier = 'p-' + uuid4().hex
        job = {'id': identifier, 'query': query, 'song': song,
               'links': {service.service_name(): song.service_links[service.service_name()]},
               'users': {user}, 'messages': set(), 'done': False, 'created': time.monotonic()}
        self._link_jobs[identifier] = job
        self._link_queries[query] = identifier
        job['task'] = asyncio.create_task(self._complete_progressive(job))
        return [self._progressive_card(job)]

    async def _edit_progressive(self, job, message_id, retried=False):
        # Keep only a dirty flag, rather than queueing every intermediate edit.
        # The active writer drains the newest state after its current request.
        """Coalesce concurrent edits for one message and drain the newest pending state."""
        lock = job.setdefault('edit_locks', {}).setdefault(message_id, asyncio.Lock())
        pending = job.setdefault('pending_edits', set())
        pending.add(message_id)
        if lock.locked():
            return
        async with lock:
            while message_id in pending:
                # Clear before awaiting: arrivals during the HTTP request set
                # the flag again and are collapsed into the next snapshot.
                pending.discard(message_id)
                await self._edit_progressive_locked(job, message_id, retried)

    async def _edit_progressive_locked(self, job, message_id, retried=False):
        """Send a serialized snapshot with rate-limit and media-format recovery."""
        result = self._progressive_card(job)
        content = result.input_message_content
        try:
            if message_id in job.get('photo_messages', set()):
                await self.application.bot.edit_message_caption(
                    inline_message_id=message_id, caption=content.message_text[:1024], reply_markup=result.reply_markup)
            else:
                preview = content.link_preview_options
                if message_id in job.get('preview_messages', set()) and result.thumbnail_url:
                    preview = LinkPreviewOptions(url=result.thumbnail_url, prefer_large_media=True, show_above_text=True)
                await self.application.bot.edit_message_text(
                    inline_message_id=message_id, text=content.message_text,
                    reply_markup=result.reply_markup, link_preview_options=preview)
        except RetryAfter as error:
            if not retried:
                delay = error.retry_after
                await asyncio.sleep(delay.total_seconds() if hasattr(delay, 'total_seconds') else float(delay))
                await self._edit_progressive_locked(job, message_id, retried=True)
        except BadRequest as error:
            detail = str(error).lower()
            if 'there is no text in the message' in detail and message_id not in job.get('photo_messages', set()):
                job.setdefault('photo_messages', set()).add(message_id)
                await self._edit_progressive_locked(job, message_id, retried=True)
                return
            if ('webpage' in str(error).lower() or 'embed' in str(error).lower()) and result.thumbnail_url:
                try:
                    store = getattr(self, '_covers', None)
                    file_id = store.get(self.application.bot.id, result.thumbnail_url) if store else None
                    await self.application.bot.edit_message_media(inline_message_id=message_id,
                        media=InputMediaPhoto(file_id or result.thumbnail_url, caption=content.message_text[:1024]),
                        reply_markup=result.reply_markup)
                    job.setdefault('photo_messages', set()).add(message_id)
                    return
                except BadRequest:
                    job.get('preview_messages', set()).discard(message_id)
                    await self.application.bot.edit_message_text(inline_message_id=message_id,
                        text=content.message_text, reply_markup=result.reply_markup,
                        link_preview_options=LinkPreviewOptions(is_disabled=True))
                    return
            if 'message is not modified' not in str(error).lower():
                if any(reason in detail for reason in ('message to edit not found', 'message_id_invalid', "message can't be edited")):
                    job['messages'].discard(message_id)
                logging.warning('Progressive edit failed: %s', str(error)[:200])
        except Exception as error:
            logging.warning('Progressive edit failed: %s', type(error).__name__)

    async def _publish_progressive(self, job):
        """Update the messages subscribed to this lookup job."""
        for message_id in tuple(job['messages']):
            await self._edit_progressive(job, message_id)

    async def _complete_progressive(self, job):
        """Resolve remaining providers in parallel, cache the final card, and publish it."""
        acquired = self._work_slots.acquire(blocking=False)
        tasks = []
        try:
            missing = [s for s in self._music_services if s.service_name() not in job['links']]
            if acquired:
                def resolve(service):
                    with request_budget(25), http_session_scope():
                        item = deepcopy(job['song'])
                        try:
                            return service.service_name(), service.song_to_link(item)
                        except Exception:
                            fallback = search_links(item, '', '')
                            return service.service_name(), fallback.service_links[service.service_name()]
                tasks = [asyncio.create_task(asyncio.to_thread(resolve, s)) for s in missing]
                for task in asyncio.as_completed(tasks):
                    name, link = await task
                    service = next(s for s in missing if s.service_name() == name)
                    if service.can_handle_link(link):
                        job['links'][name] = link
                    await self._publish_progressive(job)
            else:
                fallback = search_links(deepcopy(job['song']), '', '')
                job['links'].update({s.service_name(): fallback.service_links[s.service_name()] for s in missing})
        except Exception as error:
            logging.warning('Progressive lookup failed: %s', type(error).__name__)
        finally:
            # Never free a slot while synchronous request threads still run.
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if acquired:
                self._work_slots.release()
            job['done'] = True
            final = self._progressive_card(job)
            # Cache only complete cards, never the loading placeholder.
            try:
                self._guard.put(job['query'], [final])
                self._library.put(job['query'], [final])
            except Exception as error:
                logging.warning('Progressive cache failed: %s', type(error).__name__)
            await self._publish_progressive(job)

    async def chosen_inline_handler(self, update, context):
        """Subscribe the selected inline message to its job and warm the cover cache."""
        chosen = update.chosen_inline_result
        is_photo = chosen.result_id.startswith('ph-')
        identifier = chosen.result_id[3:] if chosen.result_id.startswith(('ph-', 'tx-')) else chosen.result_id
        if not chosen.result_id.startswith('tx-'):
            task = asyncio.create_task(self._cache_chosen_cover(identifier, chosen.query))
            if not hasattr(self, '_cover_tasks'):
                self._cover_tasks = set()
            self._cover_tasks.add(task)
            task.add_done_callback(self._cover_tasks.discard)
        logging.warning('Inline choice received: progressive=%s editable=%s format=%s',
                        identifier.startswith('p-'), bool(chosen.inline_message_id),
                        'photo' if is_photo else 'text' if chosen.result_id.startswith('tx-') else 'preview')
        if not identifier.startswith('p-') or not chosen.inline_message_id:
            return
        self._progressive_state()
        job = self._link_jobs.get(identifier)
        if job is None:
            # A user may choose a preview retained by Telegram after a restart.
            results = await self._progressive_results(chosen.query, chosen.from_user.id)
            if not results:
                return
            job = self._link_jobs.get(results[0].id)
        if job is None or chosen.from_user.id not in job['users']:
            logging.warning('Progressive choice has no matching user job')
            return
        job['messages'].add(chosen.inline_message_id)
        if is_photo:
            job.setdefault('photo_messages', set()).add(chosen.inline_message_id)
        elif not chosen.result_id.startswith('tx-'):
            job.setdefault('preview_messages', set()).add(chosen.inline_message_id)
        await self._edit_progressive(job, chosen.inline_message_id)

    async def _cache_chosen_cover(self, identifier, query):
        """Upload a selected cover to storage only when its reusable file ID is missing."""
        from .settings import secrets
        storage = secrets.get('cover_storage_chat_id')
        store = getattr(self, '_covers', None)
        if not storage or store is None:
            return
        self._progressive_state()
        job = self._link_jobs.get(identifier)
        url = job['song'].cover_art.get('url') if job and job['song'].cover_art else None
        if url is None:
            for card in self._library.get(normalize_query(query)) or []:
                if card.id == identifier:
                    url = card.thumbnail_url
                    break
        if url:
            try:
                await store.upload(self.application.bot, storage, url)
            except Exception as error:
                logging.warning('Cover upload failed: %s', type(error).__name__)

    async def loading_callback(self, update, context):
        """Refresh a subscribed card when selection feedback was missed."""
        callback = update.callback_query
        self._progressive_state()
        identifier = (callback.data or '').partition(':')[2]
        is_photo = identifier.startswith('ph-')
        if is_photo:
            identifier = identifier[3:]
        job = self._link_jobs.get(identifier)
        if job is not None and callback.from_user.id in job['users'] and callback.inline_message_id:
            job['messages'].add(callback.inline_message_id)
            if is_photo:
                job.setdefault('photo_messages', set()).add(callback.inline_message_id)
            await callback.answer('Готово.' if job['done'] else 'Поиск продолжается…')
            await self._edit_progressive(job, callback.inline_message_id)
        else:
            await callback.answer('Повторно вставьте исходную ссылку в inline-поиск, чтобы обновить карточку.')
