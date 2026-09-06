import asyncio
import collections
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from music_bot import AudioTrack, ChannelMusicPlayer


def _make_player():
    bot = MagicMock()
    bot.loop = asyncio.get_event_loop()
    return bot, ChannelMusicPlayer(guild_id=1, channel_id=1, bot_client=bot)


def _idle_vc():
    vc = MagicMock()
    vc.is_connected.return_value = True
    vc.is_playing.return_value = False
    vc.is_paused.return_value = False
    vc.channel.members = [MagicMock(), MagicMock()]
    vc.disconnect = AsyncMock()
    vc.stop = MagicMock()
    return vc


def _ready_track(title="Track", duration=180):
    return AudioTrack(
        title=title,
        webpage_url=f"http://test.com/{title}",
        stream_url=f"http://stream.test.com/{title}",
        duration=duration,
    )


class TestPlayNext(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_bot, self.player = _make_player()
        self.ctx = MagicMock()
        self.ctx.send = AsyncMock()

    def _wire_idle_vc(self):
        vc = _idle_vc()
        self.player.get_voice_client = MagicMock(return_value=vc)
        return vc

    @patch("music_bot.resolve_stream_url", new=AsyncMock(return_value="http://stream.test.com/t"))
    @patch("music_bot.discord.FFmpegPCMAudio")
    async def test_starts_track_and_sends_now_playing(self, mock_ffmpeg):
        vc = self._wire_idle_vc()
        track = _ready_track()
        self.player.queue.append(track)

        await self.player.play_next(self.ctx)

        vc.play.assert_called_once()
        self.assertIs(self.player.current, track)
        self.assertEqual(self.player.queue, collections.deque())
        self.ctx.send.assert_awaited_once()
        sent = self.ctx.send.await_args.args[0]
        self.assertIn("Now playing", sent)
        self.assertIn(track.title, sent)

    @patch("music_bot.resolve_stream_url")
    async def test_skips_track_with_unresolvable_stream(self, mock_resolve):
        """When only one track's stream fails, the next valid track should still be played."""
        vc = self._wire_idle_vc()
        bad = AudioTrack(title="Bad", webpage_url="u")
        good = _ready_track(title="Good")

        async def resolve(track, *_args, **_kwargs):
            return None if track.title == "Bad" else f"http://stream.test.com/{track.title}"

        mock_resolve.side_effect = resolve
        self.player.queue.extend([bad, good])

        with patch("music_bot.discord.FFmpegPCMAudio"):
            await self.player.play_next(self.ctx)

        vc.play.assert_called_once()
        self.assertEqual(self.player.queue, collections.deque())
        self.assertEqual(self.player.current.title, "Good")
        sent = " ".join(call.args[0] for call in self.ctx.send.await_args_list)
        self.assertIn("Bad", sent)
        self.assertIn("Good", sent)

    async def test_returns_when_no_voice_client(self):
        self.player.get_voice_client = MagicMock(return_value=None)
        self.player.current = _ready_track()

        await self.player.play_next(self.ctx)

        self.assertIsNone(self.player.current)
        self.ctx.send.assert_not_called()

    async def test_returns_when_already_playing(self):
        vc = _idle_vc()
        vc.is_playing.return_value = True
        self.player.get_voice_client = MagicMock(return_value=vc)
        self.player.queue.append(_ready_track())

        await self.player.play_next(self.ctx)

        vc.play.assert_not_called()
        self.assertEqual(len(self.player.queue), 1)
        self.ctx.send.assert_not_called()

    @patch("music_bot.resolve_stream_url", new=AsyncMock(return_value="http://stream.test.com/t"))
    @patch("music_bot.discord.FFmpegPCMAudio")
    async def test_client_exception_requeues_to_front(self, mock_ffmpeg):
        vc = self._wire_idle_vc()
        vc.play.side_effect = discord.ClientException()
        track = _ready_track()
        self.player.queue.append(track)

        await self.player.play_next(self.ctx)

        self.assertEqual(len(self.player.queue), 1)
        self.assertIs(self.player.queue[0], track)
        self.assertIsNone(self.player.current)
        self.ctx.send.assert_not_called()

    @patch("music_bot.resolve_stream_url", new=AsyncMock(return_value=None))
    async def test_sends_skip_messages_outside_lock(self):
        """Skip messages should be sent for each unresolvable track, even if the queue ends empty."""
        self._wire_idle_vc()
        for title in ["A", "B", "C"]:
            self.player.queue.append(AudioTrack(title=title, webpage_url=f"u/{title}"))

        await self.player.play_next(self.ctx)

        sent = " ".join(call.args[0] for call in self.ctx.send.await_args_list)
        self.assertIn("A", sent)
        self.assertIn("B", sent)
        self.assertIn("C", sent)

    @patch("music_bot.resolve_stream_url", new=AsyncMock(return_value="http://stream.test.com/t"))
    @patch("music_bot.discord.FFmpegPCMAudio")
    async def test_now_playing_message_uses_effective_duration(self, mock_ffmpeg):
        self._wire_idle_vc()
        track = AudioTrack(
            title="Fast Song",
            webpage_url="u",
            stream_url="s",
            duration=200,
            modifier="nightcore",
        )
        self.player.queue.append(track)

        await self.player.play_next(self.ctx)

        sent = self.ctx.send.await_args.args[0]
        self.assertIn("0:02:40", sent)

    @patch("music_bot.resolve_stream_url", new=AsyncMock(return_value="http://stream.test.com/t"))
    @patch("music_bot.discord.FFmpegPCMAudio")
    async def test_seek_offset_is_applied_to_ffmpeg(self, mock_ffmpeg):
        self._wire_idle_vc()
        track = AudioTrack(
            title="Seeked",
            webpage_url="u",
            stream_url="s",
            duration=300,
            timestamp=60,
        )
        self.player.queue.append(track)

        await self.player.play_next(self.ctx)

        ffmpeg_kwargs = mock_ffmpeg.call_args.kwargs
        self.assertIn("-ss 60", ffmpeg_kwargs["before_options"])


if __name__ == '__main__':
    unittest.main()