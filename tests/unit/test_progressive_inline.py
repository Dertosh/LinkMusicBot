import asyncio
from threading import BoundedSemaphore, Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, AsyncMock

from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.models import Song
from linkmusicbot.security import QueryGuard


class ProgressiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_edits_coalesce_and_send_latest_complete_state(self):
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        job = self.bot._link_jobs[cards[0].id]
        await job['task']
        job['done'] = False
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_edit(**kwargs):
            if not entered.is_set():
                entered.set()
                await release.wait()

        edit = self.bot.application.bot.edit_message_text
        edit.side_effect = slow_edit
        writer = asyncio.create_task(self.bot._edit_progressive(job, 'message'))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            for index in range(10):
                job['links']['Apple Music'] = 'https://music.apple.com/us/song/' + str(index)
                await self.bot._edit_progressive(job, 'message')
            job['done'] = True
            await self.bot._edit_progressive(job, 'message')
            self.assertEqual(edit.await_count, 1)
            # A different message is not blocked by this one's pending request.
            await self.bot._edit_progressive(job, 'other-message')
            self.assertEqual(edit.await_count, 2)
        finally:
            release.set()
            await writer
        self.assertEqual(edit.await_count, 3)
        final = edit.call_args.kwargs
        self.assertEqual(final['inline_message_id'], 'message')
        self.assertNotIn('⏳', final['text'])
        self.assertEqual(final['reply_markup'].inline_keyboard[1][0].url,
                         'https://music.apple.com/us/song/9')
        self.assertFalse(job['pending_edits'])

    async def test_rejected_intermediate_edit_does_not_unsubscribe_final_update(self):
        from telegram.error import BadRequest
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        job = self.bot._link_jobs[cards[0].id]
        await job['task']
        job['messages'].add('message')
        self.bot.application.bot.edit_message_text.side_effect = [BadRequest('temporary rejection'), None]
        await self.bot._publish_progressive(job)
        self.assertIn('message', job['messages'])
        await self.bot._publish_progressive(job)
        self.assertEqual(self.bot.application.bot.edit_message_text.await_count, 2)
        self.assertNotIn('⏳', self.bot.application.bot.edit_message_text.call_args.kwargs['text'])

    async def test_photo_message_without_format_marker_recovers_caption(self):
        from telegram.error import BadRequest
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        job = self.bot._link_jobs[cards[0].id]
        await job['task']
        self.bot.application.bot.edit_message_text.side_effect = BadRequest('There is no text in the message to edit')
        self.bot.application.bot.edit_message_caption = AsyncMock()
        await self.bot._edit_progressive(job, 'message')
        self.bot.application.bot.edit_message_caption.assert_awaited_once()
        self.assertNotIn('⏳', self.bot.application.bot.edit_message_caption.call_args.kwargs['caption'])

    async def test_preview_error_retries_photo_then_text(self):
        from telegram.error import BadRequest
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        job = self.bot._link_jobs[cards[0].id]
        await job['task']
        job['song'].cover_art = {'url': 'https://i.scdn.co/image/test'}
        job['preview_messages'] = {'message'}
        self.bot.application.bot.edit_message_text.side_effect = [BadRequest('WEBPAGE_FORBIDDEN'), None]
        self.bot.application.bot.edit_message_media = AsyncMock(side_effect=BadRequest('PHOTO_FORBIDDEN'))
        await self.bot._edit_progressive(job, 'message')
        self.bot.application.bot.edit_message_media.assert_awaited_once()
        self.assertEqual(self.bot.application.bot.edit_message_text.await_count, 2)
        self.assertTrue(self.bot.application.bot.edit_message_text.call_args.kwargs['link_preview_options'].is_disabled)

    async def test_chosen_photo_updates_caption_instead_of_text(self):
        self.bot.application.bot.edit_message_caption = AsyncMock()
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        job = self.bot._link_jobs[cards[0].id]
        await job['task']
        chosen = SimpleNamespace(result_id='ph-' + job['id'], inline_message_id='photo-message',
                                 from_user=SimpleNamespace(id=1), query=job['query'])
        await self.bot.chosen_inline_handler(SimpleNamespace(chosen_inline_result=chosen), None)
        self.bot.application.bot.edit_message_caption.assert_awaited_once()
        self.bot.application.bot.edit_message_text.assert_not_awaited()

    async def test_loading_button_recovers_missing_chosen_event(self):
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        job = self.bot._link_jobs[cards[0].id]
        await job['task']
        callback = SimpleNamespace(data='music_loading:' + job['id'], from_user=SimpleNamespace(id=1),
            inline_message_id='recovered', answer=AsyncMock())
        await self.bot.loading_callback(SimpleNamespace(callback_query=callback), None)
        self.assertIn('recovered', job['messages'])
        self.assertNotIn('⏳', self.bot.application.bot.edit_message_text.call_args.kwargs['text'])

    def setUp(self):
        self.bot = LinkMusicBot.__new__(LinkMusicBot)
        self.bot._guard = QueryGuard()
        self.bot._library = Mock()
        self.bot._work_slots = BoundedSemaphore(2)
        self.bot.application = SimpleNamespace(bot=SimpleNamespace(edit_message_text=AsyncMock()))
        self.source = Mock()
        self.source.service_name.return_value = 'Spotify'
        self.source.can_handle_link.return_value = True
        self.source.link_is_song.return_value = True
        song = Song('Song', 'Artist', '')
        song.service_links = {'Spotify': 'https://open.spotify.com/track/source'}
        self.source.link_to_song.return_value = song
        self.other = Mock()
        self.other.service_name.return_value = 'Apple Music'
        self.other.can_handle_link.return_value = True
        self.other.song_to_link.return_value = 'https://music.apple.com/us/song/123'
        self.bot._music_services = [self.source, self.other]

    async def test_source_preview_precedes_other_provider_and_chosen_message_is_completed(self):
        release = Event()
        self.other.song_to_link.side_effect = lambda item: (release.wait(3), 'https://music.apple.com/us/song/123')[1]
        try:
            cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
            self.assertIn('⏳', cards[0].input_message_content.message_text)
            self.assertEqual(len(cards[0].reply_markup.inline_keyboard), 2)
            self.bot._library.put.assert_not_called()
            update = SimpleNamespace(chosen_inline_result=SimpleNamespace(result_id=cards[0].id,
                inline_message_id='message-1', from_user=SimpleNamespace(id=1), query='unused'))
            await self.bot.chosen_inline_handler(update, None)
            release.set()
            await self.bot._link_jobs[cards[0].id]['task']
        finally:
            release.set()
        call = self.bot.application.bot.edit_message_text.call_args.kwargs
        self.assertNotIn('⏳', call['text'])
        self.assertEqual([r[0].text for r in call['reply_markup'].inline_keyboard], ['Spotify', 'Apple Music'])
        self.bot._library.put.assert_called_once()

    async def test_completed_before_selection_and_repeated_preview_reuses_job(self):
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        await self.bot._link_jobs[cards[0].id]['task']
        repeated = await self.bot._progressive_results('https://open.spotify.com/track/source', 2)
        self.assertEqual(repeated[0].id, cards[0].id)
        self.source.link_to_song.assert_called_once()
        self.other.song_to_link.assert_called_once()
        update = SimpleNamespace(chosen_inline_result=SimpleNamespace(result_id=cards[0].id,
            inline_message_id='message-2', from_user=SimpleNamespace(id=2), query='unused'))
        await self.bot.chosen_inline_handler(update, None)
        self.assertNotIn('⏳', self.bot.application.bot.edit_message_text.call_args.kwargs['text'])

    async def test_provider_failure_removes_spinner_and_keeps_search_button(self):
        self.other.song_to_link.side_effect = ValueError('unavailable')
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        job = self.bot._link_jobs[cards[0].id]
        await job['task']
        result = self.bot._progressive_card(job)
        self.assertNotIn('⏳', result.input_message_content.message_text)
        self.assertIn('/search?', result.reply_markup.inline_keyboard[1][0].url)

    async def test_other_user_cannot_subscribe_to_preview(self):
        cards = await self.bot._progressive_results('https://open.spotify.com/track/source', 1)
        await self.bot._link_jobs[cards[0].id]['task']
        update = SimpleNamespace(chosen_inline_result=SimpleNamespace(result_id=cards[0].id,
            inline_message_id='message-2', from_user=SimpleNamespace(id=2), query='unused'))
        await self.bot.chosen_inline_handler(update, None)
        self.bot.application.bot.edit_message_text.assert_not_awaited()
