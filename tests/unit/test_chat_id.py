import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from linkmusicbot.bot import LinkMusicBot


class ChatIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_id_is_returned_as_exact_integer(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=-1001234567890),
                                 effective_message=SimpleNamespace(reply_text=AsyncMock()))
        await bot.chat_id_command(update, None)
        update.effective_message.reply_text.assert_awaited_once_with('ID чата: -1001234567890')
