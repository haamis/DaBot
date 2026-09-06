import asyncio
import collections
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from music_bot import (
    AudioTrack,
    ChannelMusicPlayer,
    MultiChannelMusicManager,
    manager,
    on_voice_state_update,
)


class TestMusicQueue(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_bot = MagicMock()
        self.mock_bot.loop = asyncio.get_event_loop()
        self.player = ChannelMusicPlayer(guild_id=123, channel_id=456, bot_client=self.mock_bot)

    def test_audio_track_duration(self):
        track1 = AudioTrack(title="Song 1", webpage_url="http://test.com/1", duration=90)
        self.assertEqual(track1.get_duration_str(), "0:01:30")

        track2 = AudioTrack(title="Song 2", webpage_url="http://test.com/2", duration=3665)
        self.assertEqual(track2.get_duration_str(), "1:01:05")

        track3 = AudioTrack(title="Live Stream", webpage_url="http://test.com/3", duration=0)
        self.assertEqual(track3.get_duration_str(), "Unknown")

    def test_effective_duration_scales_with_modifier(self):
        track = AudioTrack(title="Nightcore Song", webpage_url="u", duration=100, modifier="nightcore")
        self.assertEqual(track.get_effective_duration(), 80)
        self.assertEqual(track.get_effective_duration_str(), "0:01:20")

        track.modifier = "vaporwave"
        self.assertEqual(track.get_effective_duration(), 125)

        track.modifier = ""
        self.assertEqual(track.get_effective_duration(), 100)
        self.assertEqual(track.get_effective_duration_str(), "0:01:40")

        track.duration = 0
        self.assertEqual(track.get_effective_duration_str(), "Unknown")

    async def test_queue_fifo_order(self):
        mock_ctx = MagicMock()
        track1 = AudioTrack(title="Track 1", webpage_url="http://test.com/1")
        track2 = AudioTrack(title="Track 2", webpage_url="http://test.com/2")
        track3 = AudioTrack(title="Track 3", webpage_url="http://test.com/3")

        self.player.get_voice_client = MagicMock(return_value=None)

        await self.player.add_tracks(mock_ctx, [track1, track2, track3])
        self.assertEqual(len(self.player.queue), 3)
        self.assertEqual(self.player.queue[0].title, "Track 1")
        self.assertEqual(self.player.queue[1].title, "Track 2")
        self.assertEqual(self.player.queue[2].title, "Track 3")

    async def test_clear_queue(self):
        track1 = AudioTrack(title="Track 1", webpage_url="http://test.com/1")
        self.player.queue.append(track1)
        self.assertEqual(len(self.player.queue), 1)

        await self.player.clear()
        self.assertEqual(len(self.player.queue), 0)

    async def test_disconnects_after_one_hour_of_inactivity(self):
        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = False
        mock_vc.disconnect = AsyncMock()
        self.player.get_voice_client = MagicMock(return_value=mock_vc)
        self.player.idle_since = 100.0

        with patch("music_bot.time.monotonic", return_value=3700.0):
            disconnected = await self.player.disconnect_if_inactive()

        self.assertTrue(disconnected)
        mock_vc.disconnect.assert_awaited_once()

    async def test_paused_audio_is_exempt_from_inactivity_disconnect(self):
        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = True
        self.player.get_voice_client = MagicMock(return_value=mock_vc)
        self.player.idle_since = 100.0

        with patch("music_bot.time.monotonic", return_value=3700.0):
            disconnected = await self.player.disconnect_if_inactive()

        self.assertFalse(disconnected)
        mock_vc.disconnect.assert_not_called()

    async def test_alone_empty_idle_channel_disconnects_immediately(self):
        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = False
        mock_vc.channel.members = [MagicMock()]
        mock_vc.disconnect = AsyncMock()
        self.player.get_voice_client = MagicMock(return_value=mock_vc)

        disconnected = await self.player.disconnect_if_inactive()

        self.assertTrue(disconnected)
        mock_vc.disconnect.assert_awaited_once()

    async def test_active_audio_prevents_inactivity_disconnect(self):
        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = True
        mock_vc.is_paused.return_value = False
        self.player.get_voice_client = MagicMock(return_value=mock_vc)
        self.player.idle_since = 100.0

        with patch("music_bot.time.monotonic", return_value=3700.0):
            disconnected = await self.player.disconnect_if_inactive()

        self.assertFalse(disconnected)
        self.assertIsNone(self.player.idle_since)
        mock_vc.disconnect.assert_not_called()

    async def test_alone_channel_with_queued_audio_waits_for_timeout(self):
        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = False
        mock_vc.channel.members = [MagicMock()]
        mock_vc.disconnect = AsyncMock()
        self.player.queue.append(AudioTrack(title="Queued", webpage_url="url"))
        self.player.get_voice_client = MagicMock(return_value=mock_vc)
        self.player.idle_since = 100.0

        with patch("music_bot.time.monotonic", return_value=101.0):
            disconnected = await self.player.disconnect_if_inactive()

        self.assertFalse(disconnected)
        mock_vc.disconnect.assert_not_awaited()

    async def test_one_hour_timeout_preserves_queue(self):
        """If the 1-hour timeout fires but tracks remain queued, reset idle timer instead of disconnecting."""
        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = False
        mock_vc.channel.members = [MagicMock(), MagicMock()]
        mock_vc.disconnect = AsyncMock()
        self.player.get_voice_client = MagicMock(return_value=mock_vc)
        self.player.idle_since = 100.0
        self.player.queue.append(AudioTrack(title="Pending", webpage_url="url"))

        with patch("music_bot.time.monotonic", return_value=3700.0):
            disconnected = await self.player.disconnect_if_inactive()

        self.assertFalse(disconnected)
        self.assertEqual(len(self.player.queue), 1)
        mock_vc.disconnect.assert_not_awaited()

    async def test_handle_playback_finished_when_queue_empty(self):
        """When playback ends and the queue is empty, mark_idle and attempt cleanup."""
        self.player.queue = collections.deque()
        self.player.current = None
        ctx = MagicMock()
        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = False
        self.player.get_voice_client = MagicMock(return_value=mock_vc)

        with patch.object(self.player, "mark_idle") as mark_idle, \
             patch.object(self.player, "play_next", new=AsyncMock()) as play_next, \
             patch.object(self.player, "disconnect_if_inactive", new=AsyncMock()) as disconnect:
            await self.player.handle_playback_finished(ctx)

        mark_idle.assert_called_once()
        play_next.assert_awaited_once_with(ctx)
        disconnect.assert_awaited_once()

    async def test_watchdog_does_not_create_duplicate_task(self):
        blocker = asyncio.Event()

        async def wait_for_release():
            await blocker.wait()

        with patch.object(self.player, "_inactivity_watchdog", side_effect=wait_for_release) as watchdog:
            self.player.start_inactivity_watchdog()
            first_task = self.player.inactivity_task
            self.player.start_inactivity_watchdog()

            self.assertIs(self.player.inactivity_task, first_task)
            self.assertEqual(watchdog.call_count, 1)
            blocker.set()
            await first_task

    async def test_ensure_voice_connection_starts_watchdog_after_move(self):
        test_manager = MultiChannelMusicManager(self.mock_bot)
        target_channel = MagicMock(id=456)
        existing_voice_client = MagicMock()
        existing_voice_client.channel.id = 100
        existing_voice_client.move_to = AsyncMock()
        guild = MagicMock(id=123, voice_client=existing_voice_client)
        ctx = MagicMock()
        ctx.author.voice.channel = target_channel
        ctx.guild = guild
        ctx.bot = self.mock_bot

        with patch.object(ChannelMusicPlayer, "start_inactivity_watchdog") as start_watchdog:
            voice_client, player = await test_manager.ensure_voice_connection(ctx)

        self.assertIs(voice_client, existing_voice_client)
        self.assertIs(player.voice_client, existing_voice_client)
        existing_voice_client.move_to.assert_awaited_once_with(target_channel)
        start_watchdog.assert_called_once_with()

    async def test_voice_state_departure_checks_matching_player(self):
        departing_member = MagicMock(bot=False)
        departing_member.guild.id = 123
        before = MagicMock()
        before.channel.id = 456
        after = MagicMock()
        after.channel = None
        matching_player = MagicMock(guild_id=123, channel_id=456)
        matching_player.disconnect_if_inactive = AsyncMock()
        other_player = MagicMock(guild_id=123, channel_id=999)
        other_player.disconnect_if_inactive = AsyncMock()

        with patch.object(manager, "players", {(123, 456, 1): matching_player, (123, 999, 1): other_player}):
            await on_voice_state_update(departing_member, before, after)

        matching_player.disconnect_if_inactive.assert_awaited_once()
        other_player.disconnect_if_inactive.assert_not_awaited()

    async def test_voice_state_ignores_bot_departures(self):
        bot_member = MagicMock(bot=True)
        before = MagicMock()
        before.channel.id = 456
        after = MagicMock()
        after.channel = None
        player = MagicMock(guild_id=123, channel_id=456)
        player.disconnect_if_inactive = AsyncMock()

        with patch.object(manager, "players", {(123, 456, 1): player}):
            await on_voice_state_update(bot_member, before, after)

        player.disconnect_if_inactive.assert_not_awaited()

    async def test_seek_to_front_injection(self):
        mock_ctx = MagicMock()
        mock_vc = MagicMock()
        self.player.get_voice_client = MagicMock(return_value=mock_vc)

        current_track = AudioTrack(title="Playing Track", webpage_url="http://test.com/curr", duration=300)
        self.player.current = current_track

        waiting_track = AudioTrack(title="Waiting Track", webpage_url="http://test.com/wait")
        self.player.queue.append(waiting_track)

        success = await self.player.seek_to(mock_ctx, 120, "2:00")
        self.assertTrue(success)
        mock_vc.stop.assert_called_once()

        self.assertEqual(len(self.player.queue), 2)
        seeked = self.player.queue[0]
        self.assertEqual(seeked.title, "Playing Track")
        self.assertEqual(seeked.timestamp, 120)
        self.assertIsNone(seeked.stream_url)
        self.assertEqual(self.player.queue[1].title, "Waiting Track")

    def test_multi_channel_isolation(self):
        mgr = MultiChannelMusicManager(self.mock_bot)
        p1 = mgr.get_player(guild_id=1, channel_id=100)
        p2 = mgr.get_player(guild_id=1, channel_id=200)
        p3 = mgr.get_player(guild_id=2, channel_id=100)

        self.assertIsNot(p1, p2)
        self.assertIsNot(p1, p3)

        p1.queue.append(AudioTrack(title="G1C100 Song", webpage_url="url"))
        self.assertEqual(len(p1.queue), 1)
        self.assertEqual(len(p2.queue), 0)
        self.assertEqual(len(p3.queue), 0)

    def test_players_are_isolated_per_bot(self):
        mgr = MultiChannelMusicManager(self.mock_bot)
        worker_bot = MagicMock()

        main_player = mgr.get_player(guild_id=1, channel_id=100, bot_client=self.mock_bot)
        worker_player = mgr.get_player(guild_id=1, channel_id=100, bot_client=worker_bot)

        self.assertIsNot(main_player, worker_player)
        self.assertIs(main_player.bot, self.mock_bot)
        self.assertIs(worker_player.bot, worker_bot)

    def test_progress_uses_modifier_playback_speed(self):
        self.player.current = AudioTrack(
            title="Nightcore Track", webpage_url="url", duration=100, modifier="nightcore"
        )
        self.player.playback_started_at = 100.0

        with patch("music_bot.time.monotonic", return_value=110.0):
            self.assertEqual(self.player.get_playback_position(), 12)

        self.player.current.modifier = "vaporwave"
        with patch("music_bot.time.monotonic", return_value=110.0):
            self.assertEqual(self.player.get_playback_position(), 8)

    def test_wall_clock_position_uses_effective_duration(self):
        self.player.current = AudioTrack(
            title="Nightcore Track", webpage_url="url", duration=100, modifier="nightcore"
        )
        self.player.playback_started_at = 100.0

        with patch("music_bot.time.monotonic", return_value=108.0):
            wall = self.player.get_wall_clock_position()
            self.assertEqual(wall, 8)

        self.player.current.modifier = ""
        self.player.playback_started_at = 100.0
        with patch("music_bot.time.monotonic", return_value=110.0):
            self.assertEqual(self.player.get_wall_clock_position(), 10)

    def test_wall_clock_position_clamps_to_effective_duration(self):
        self.player.current = AudioTrack(
            title="Long Nightcore", webpage_url="url", duration=100, modifier="nightcore"
        )
        self.player.playback_started_at = 100.0

        with patch("music_bot.time.monotonic", return_value=200.0):
            self.assertEqual(self.player.get_wall_clock_position(), 80)


if __name__ == '__main__':
    unittest.main()