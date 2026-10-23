import unittest
from unittest.mock import Mock, AsyncMock, patch
from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.security import QueryGuard


class InlineLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_retry_waits_one_second_instead_of_five(self):
        bot=LinkMusicBot.__new__(LinkMusicBot);bot._guard=Mock()
        bot._guard.get.return_value=None;bot._guard.allow.side_effect=[False,True]
        bot._build_results=Mock(return_value=[])
        update=Mock();update.inline_query.query='a new track';update.inline_query.from_user.id=1
        update.inline_query.offset='';update.inline_query.answer=AsyncMock()
        with patch('linkmusicbot.bot.asyncio.sleep',new_callable=AsyncMock) as sleep:
            await bot.inline_query_handler(update,Mock())
        self.assertIn(1,[c.args[0] for c in sleep.call_args_list])
        self.assertNotIn(5,[c.args[0] for c in sleep.call_args_list])
        update.inline_query.answer.assert_awaited_once()

    def test_interactive_interval_does_not_remove_global_limit(self):
        guard=QueryGuard()
        with patch('linkmusicbot.security.time.monotonic',return_value=100):
            self.assertTrue(guard.allow(1,min_interval=1))
        with patch('linkmusicbot.security.time.monotonic',return_value=101):
            self.assertTrue(guard.allow(1,min_interval=1))

    def test_polling_retries_temporary_startup_failure(self):
        bot=LinkMusicBot.__new__(LinkMusicBot);bot.spotify_account=None;bot.application=Mock()
        bot.run()
        self.assertEqual(bot.application.run_polling.call_args.kwargs['bootstrap_retries'],10)
