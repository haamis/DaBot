import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from music_bot import is_watch_url, play_handler


class TestWatchUrlDetection(unittest.TestCase):
    def test_watch_url_with_list(self):
        self.assertTrue(is_watch_url("https://www.youtube.com/watch?v=abc&list=PL123"))
        self.assertTrue(is_watch_url("https://www.youtube.com/watch?list=PL123&v=abc"))
        self.assertTrue(is_watch_url("https://youtu.be/abc?list=PL123"))

    def test_not_a_watch_url(self):
        self.assertFalse(is_watch_url("https://www.youtube.com/playlist?list=PL123"))
        self.assertFalse(is_watch_url("https://youtu.be/"))
        self.assertFalse(is_watch_url("watch v=abc"))


class TestPlayHandlerFallbacks(unittest.IsolatedAsyncioTestCase):
    async def _run(self, args, fake_extract):
        ctx = MagicMock()
        ctx.author.display_name = "tester"
        ctx.author.id = 1
        ctx.author.voice.channel.id = 2
        ctx.send = AsyncMock()
        typing_cm = MagicMock()
        typing_cm.__aenter__ = AsyncMock()
        typing_cm.__aexit__ = AsyncMock(return_value=False)
        ctx.typing.return_value = typing_cm

        player = MagicMock()
        player.add_tracks = AsyncMock()

        with patch('music_bot.manager.ensure_voice_connection',
                   AsyncMock(return_value=(MagicMock(), player))), \
                patch('music_bot.safe_extract_info', side_effect=fake_extract):
            await play_handler(ctx, args)
        return ctx, player

    async def test_unresolvable_list_plays_the_video(self):
        flat_result = {'_type': 'url', 'id': 'hxvTUyf-rw8'}  # yt-dlp fell back to the video
        video = {
            'title': "Running In The 90's",
            'webpage_url': 'https://www.youtube.com/watch?v=hxvTUyf-rw8',
            'duration': 146,
        }

        async def fake_extract(url, download=False, flat=False):
            return flat_result if flat else video

        ctx, player = await self._run(
            ("https://www.youtube.com/watch?v=hxvTUyf-rw8&list=RDhxvTUyf-rw",), fake_extract)

        player.add_tracks.assert_awaited_once()
        tracks = player.add_tracks.await_args.args[1]
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Running In The 90's")
        sent = [call.args[0] for call in ctx.send.await_args_list]
        self.assertTrue(any("`list=`" in message for message in sent))

    async def test_unresolvable_list_on_short_url_plays_the_video(self):
        # youtu.be/<id>?list=... is a watch URL too; a bad list must not hide it.
        flat_result = {'_type': 'url', 'id': 'PL0000000000000000000000000000000000'}
        video = {
            'title': 'Running In The 90\'s',
            'webpage_url': 'https://www.youtube.com/watch?v=hxvTUyf-rw8',
            'duration': 146,
        }

        async def fake_extract(url, download=False, flat=False):
            return flat_result if flat else video

        ctx, player = await self._run(
            ("https://youtu.be/hxvTUyf-rw8?list=PL0000000000000000000000000000000000",),
            fake_extract)

        player.add_tracks.assert_awaited_once()
        tracks = player.add_tracks.await_args.args[1]
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Running In The 90's")

    async def test_bare_id_like_search_falls_back_to_search(self):
        video = {
            'title': 'Scooter - How Much Is The Fish',
            'webpage_url': 'https://www.youtube.com/watch?v=KdPzPJwoRcw',
            'duration': 227,
        }

        async def fake_extract(url, download=False, flat=False):
            # "gachivision" matches YouTube's bare video-ID pattern but is not a video.
            return None if url == "gachivision" else video

        _, player = await self._run(("gachivision",), fake_extract)

        player.add_tracks.assert_awaited_once()
        tracks = player.add_tracks.await_args.args[1]
        self.assertEqual(tracks[0].title, 'Scooter - How Much Is The Fish')


if __name__ == '__main__':
    unittest.main()
