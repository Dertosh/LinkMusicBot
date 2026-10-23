import unittest
from unittest.mock import AsyncMock, MagicMock, Mock
from threading import BoundedSemaphore
from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.models import Song
from linkmusicbot.spotify_account import NotConnected


class CurrentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot=LinkMusicBot.__new__(LinkMusicBot)
        self.bot._work_slots=BoundedSemaphore(2)
        self.bot.spotify_account=Mock()
        self.update=MagicMock()
        self.update.inline_query.from_user.id=42
        self.update.effective_user.id=42
        self.update.effective_user.language_code='ru'
        self.update.inline_query.answer=AsyncMock()
        self.update.effective_message.reply_text=AsyncMock()

    async def test_inline_uses_requesting_user_and_never_shared_cache(self):
        song=Song('Enemy','Imagine Dragons & JID','');song.service_links={'Spotify':'https://open.spotify.com/track/1r9xUipOqoNwggBpENDsvJ'}
        self.bot.spotify_account.current.return_value=song
        result=Mock();self.bot.make_iqr=Mock(return_value=result)
        self.bot._guard=Mock();self.bot._library=Mock()
        await self.bot.current_inline(self.update,Mock())
        self.bot.spotify_account.current.assert_called_once_with(42)
        self.bot._guard.get.assert_not_called();self.bot._library.get.assert_not_called()
        self.update.inline_query.answer.assert_awaited_once_with([result],cache_time=0,is_personal=True)

    async def test_connect_button_and_no_playback(self):
        self.bot.spotify_account.current.side_effect=NotConnected()
        await self.bot.current_inline(self.update,Mock())
        answer=self.update.inline_query.answer.call_args.kwargs
        self.assertEqual(answer['cache_time'],0);self.assertTrue(answer['is_personal'])
        self.assertEqual(answer['button'].start_parameter,'spotify')
        self.bot.spotify_account.current.side_effect=None
        self.bot.spotify_account.current.return_value=None
        self.update.inline_query.answer.reset_mock()
        await self.bot.current_inline(self.update,Mock())
        self.assertEqual(self.update.inline_query.answer.call_args.args[0][0].id,'current-empty')

    async def test_group_cannot_publish_authorization_link(self):
        self.update.effective_chat.type='group'
        await self.bot.connect_spotify(self.update,Mock())
        self.bot.spotify_account.begin.assert_not_called()

    async def test_command_offers_inline_share_button(self):
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton, InputTextMessageContent
        result=Mock()
        result.reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Spotify',url='https://open.spotify.com/track/1r9xUipOqoNwggBpENDsvJ')]])
        result.input_message_content=InputTextMessageContent('Enemy')
        self.bot._current_result=Mock(return_value=result)
        await self.bot.current_command(self.update,Mock())
        markup=self.update.effective_message.reply_text.call_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[-1][0].switch_inline_query,'current')
