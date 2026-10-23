import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import unittest
from telegram import InlineKeyboardButton
from linkmusicbot.cover_photos import CoverStore, as_photo, as_text
from linkmusicbot.presentation import build_result
from linkmusicbot.models import Song


class CoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_photo_automatically_retries_text_without_duplicate_card(self):
        from telegram.error import BadRequest
        from linkmusicbot.bot import LinkMusicBot
        song = Song('Song', 'Artist', '')
        song.cover_art = {'url': 'https://i.scdn.co/image/test'}
        card = build_result(song, [])
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot._guard = Mock();bot._guard.get.return_value = [card]
        bot._music_services = []
        bot._covers = Mock();bot._covers.get.return_value = 'old-file-id'
        bot.application = SimpleNamespace(bot=SimpleNamespace(id=1))
        bot._schedule_refresh = Mock()
        inline = SimpleNamespace(query='Song',from_user=SimpleNamespace(id=1),offset='',
                                 answer=AsyncMock(side_effect=[BadRequest('WEBPAGE_CURL_FAILED'),BadRequest('PHOTO_INVALID'),None]))
        await bot.inline_query_handler(SimpleNamespace(inline_query=inline),None)
        first, photo, second = inline.answer.await_args_list
        self.assertEqual(len(first.args[0]),1)
        self.assertEqual(first.args[0][0].type,'article')
        self.assertEqual(photo.args[0][0].type,'photo')
        self.assertEqual(len(second.args[0]),1)
        self.assertEqual(second.args[0][0].type,'article')
        self.assertEqual(second.args[0][0].title,'Song')
        self.assertTrue(second.args[0][0].input_message_content.link_preview_options.is_disabled)
        bot._covers.forget.assert_called_once()

    async def test_upload_once_and_reuse_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'covers.sqlite3')
            bot = SimpleNamespace(id=123, send_photo=AsyncMock(return_value=SimpleNamespace(
                photo=[SimpleNamespace(file_id='telegram-photo-id')])))
            store = CoverStore(path)
            try:
                ids = await asyncio.gather(store.upload(bot, -100123, 'https://i.scdn.co/image/test'),
                                           store.upload(bot, -100123, 'https://i.scdn.co/image/test'))
                self.assertEqual(ids, ['telegram-photo-id'] * 2)
                bot.send_photo.assert_awaited_once()
            finally:
                store.close()
            store = CoverStore(path)
            try:
                self.assertEqual(await store.upload(bot, -100123, 'https://i.scdn.co/image/test'), 'telegram-photo-id')
                bot.send_photo.assert_awaited_once()
                self.assertIsNone(store.get(456, 'https://i.scdn.co/image/test'))
            finally:
                store.close()

    async def test_failed_upload_is_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CoverStore(str(Path(folder) / 'covers.sqlite3'))
            bot = SimpleNamespace(id=1, send_photo=AsyncMock(side_effect=ValueError('no permission')))
            try:
                with self.assertRaises(ValueError):
                    await store.upload(bot, -100123, 'https://i.scdn.co/image/test')
                self.assertIsNone(store.get(1, 'https://i.scdn.co/image/test'))
            finally:
                store.close()

    def test_photo_is_media_not_web_preview_and_has_text_alternative(self):
        song = Song('Song', 'Artist', '')
        song.cover_art = {'url': 'https://i.scdn.co/image/test'}
        result = build_result(song, [[InlineKeyboardButton('Loading', callback_data='music_loading:p-123')]])
        photo = as_photo(result)
        self.assertEqual(photo.type, 'photo')
        self.assertNotIn('input_message_content', photo.to_dict())
        self.assertIn('Song', photo.caption)
        self.assertEqual(photo.reply_markup.inline_keyboard[0][0].callback_data, 'music_loading:ph-p-123')
        cached = as_photo(result, 'telegram-photo-id')
        self.assertEqual(cached.photo_file_id, 'telegram-photo-id')
        self.assertNotIn('photo_url', cached.to_dict())
        self.assertTrue(as_text(result).input_message_content.link_preview_options.is_disabled)
