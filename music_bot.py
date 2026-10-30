import asyncio
import collections
import concurrent.futures
import dataclasses
import datetime
import os
import random
import re
import time
from typing import Dict, List, Optional, Tuple, Union

import discord
from discord.ext import commands
import yt_dlp

# --- Intents and Bot Initialization ---
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

MAX_PLAYLIST_LENGTH = 300
PLAYBACK_SPEEDS = {'nightcore': 1.25, 'vaporwave': 0.8}
INACTIVITY_CHECK_INTERVAL_SECONDS = 60

# --- Global Executor for Parallel Blocking Tasks ---
executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

# --- yt-dlp Options ---
# bgutil PO-token provider; Docker Compose points this at the pot-provider service.
POT_PROVIDER_URL = os.environ.get('POT_PROVIDER_URL', 'http://127.0.0.1:4416')

ytdl_format_options = {
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': False,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    # Pin clients: the default 'tv' client's HLS URLs 403 here, with or without
    # cookies. web/android hand out plain googlevideo URLs that play.
    'extractor_args': {
        'youtube': {'player_client': ['web', 'android']},
        'youtubepot-bgutilhttp': {'base_url': [POT_PROVIDER_URL]},
    },
}

# Ignore a missing or empty cookie file: Docker creates an empty directory for a
# missing bind-mount source, and yt-dlp then fails every extraction on it.
COOKIE_FILE = './cookies.txt'
if os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
    ytdl_format_options['cookiefile'] = COOKIE_FILE
elif os.path.exists(COOKIE_FILE):
    print(f"[WARNING] Ignoring unusable cookie file '{COOKIE_FILE}'; videos that need login may fail to load.")

# --- FFmpeg Audio Filter Options ---
ffmpeg_options = {
    'before_options': '-hide_banner -loglevel error -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-loglevel fatal -vn -filter:a loudnorm=i=-24:tp=-2:lra=7'
}

ffmpeg_nightcore_options = {
    'before_options': '-hide_banner -loglevel error -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-loglevel fatal -vn -filter:a asetrate=44100*1.25,aresample=44100,loudnorm=i=-24:tp=-2:lra=7'
}

ffmpeg_vaporwave_options = {
    'before_options': '-hide_banner -loglevel error -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-loglevel fatal -vn -filter:a asetrate=44100*0.8,aresample=44100,loudnorm=i=-24:tp=-2:lra=7'
}


# --- Data Structures ---
@dataclasses.dataclass
class AudioTrack:
    title: str
    webpage_url: str
    stream_url: Optional[str] = None
    duration: int = 0
    modifier: str = ''
    timestamp: int = 0
    requester_name: str = 'Unknown'
    requester_id: Optional[int] = None
    channel_id: Optional[int] = None

    def get_duration_str(self) -> str:
        if not self.duration:
            return "Unknown"
        return str(datetime.timedelta(seconds=int(self.duration)))

    def get_effective_duration(self) -> int:
        """Returns the track duration scaled by its playback-speed modifier."""
        if not self.duration:
            return 0
        speed = PLAYBACK_SPEEDS.get(self.modifier, 1.0)
        return int(self.duration / speed)

    def get_effective_duration_str(self) -> str:
        if not self.duration:
            return "Unknown"
        return str(datetime.timedelta(seconds=int(self.get_effective_duration())))


# --- Helper Functions ---
def parse_time_str(time_str: str) -> int:
    """Parses HH:MM:SS, MM:SS, or SS string into total seconds."""
    try:
        parts = list(map(int, reversed(time_str.strip().split(':'))))
        seconds = 0
        for i, part in enumerate(parts):
            seconds += part * (60 ** i)
        return max(0, seconds)
    except (ValueError, TypeError):
        return 0


def parse_timestamp(args: Union[Tuple, List, str]) -> int:
    """Extracts timestamp in seconds from URL parameters or arguments (e.g. t=1h20m30s, t=90s, t=120)."""
    full_text = " ".join(args) if isinstance(args, (list, tuple)) else str(args)

    # 1. Match compound h/m/s format: e.g. 1h20m30s, 2m15s, 45s, 1h5s, 2h5m, 30m
    match_hms = re.search(r'[?&](?:t|start)=(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', full_text)
    if match_hms:
        hours = int(match_hms.group(1) or 0)
        minutes = int(match_hms.group(2) or 0)
        seconds = int(match_hms.group(3) or 0)
        total = hours * 3600 + minutes * 60 + seconds
        if total > 0:
            return total

    # 2. Match pure seconds format: e.g. ?t=90, &start=120, ?t=120s
    match_sec = re.search(r'[?&](?:t|start)=(\d+)s?', full_text)
    if match_sec:
        return int(match_sec.group(1))

    return 0



def format_playback_progress(position: float, duration: int, width: int = 18) -> str:
    """Formats a playback position as a compact Discord-friendly progress bar."""
    if duration <= 0:
        return "`Live / unknown duration`"

    position = max(0, min(int(position), duration))
    completed = min(width - 1, int((position / duration) * width))
    bar = "━" * completed + "🔘" + "━" * (width - 1 - completed)
    return (
        f"`{datetime.timedelta(seconds=position)}` {bar} "
        f"`{datetime.timedelta(seconds=duration)}`"
    )

def is_direct_url(text: str) -> bool:
    """Checks if a string is a direct HTTP/HTTPS URL."""
    return bool(re.match(r'^https?://', text.strip()))


def is_playlist_url(text: str) -> bool:
    """Checks if a direct URL points at a playlist via its list= parameter."""
    return is_direct_url(text) and bool(re.search(r'[?&]list=[\w-]+', text.strip()))


AGE_RESTRICTED_MARKERS = (
    'confirm your age',
    'age-restricted',
    'age restricted',
    'age-verification',
    'age_verification',
    'inappropriate for some users',
)


def is_age_restricted_error(err: BaseException) -> bool:
    """Return True when a yt-dlp exception is an age-gate failure.

    Matches the phrases YouTube/yt-dlp actually use; a bare 'age' substring
    would also hit 'page' and the "confirm you're not a bot" cookie error.
    """
    msg = str(err).lower()
    return any(marker in msg for marker in AGE_RESTRICTED_MARKERS)


class AgeRestrictedError(Exception):
    """Raised when yt-dlp refuses extraction because the video is age-restricted."""
    pass


STALE_COOKIE_MARKER = 'cookies are no longer valid'


class _YtdlpLogger:
    """yt-dlp logger: re-emits warnings/errors and flags rejected cookie files.

    Supplying a logger stops yt-dlp printing its own warnings, so they are
    printed here to keep stale-cookie and provider problems visible in logs.
    debug/info stay silent: quiet=True already suppresses that output, and
    yt-dlp routes its screen output through debug once a logger is set.
    """

    def __init__(self):
        self.cookies_rejected = False
        self._seen = set()

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        # yt-dlp ignores only_once when a logger is set, so dedupe per attempt.
        if msg not in self._seen:
            self._seen.add(msg)
            print(f"[yt-dlp] {msg}")
        if STALE_COOKIE_MARKER in msg:
            self.cookies_rejected = True

    def error(self, msg):
        print(f"[yt-dlp] {msg}")


def _extract_once(
    url: str, options: dict, download: bool
) -> Tuple[Optional[dict], bool, Optional[BaseException]]:
    """One extraction attempt; returns (info, cookies_rejected, error)."""
    logger = _YtdlpLogger()
    client = yt_dlp.YoutubeDL({**options, 'logger': logger})
    try:
        return client.extract_info(url, download=download), logger.cookies_rejected, None
    except Exception as e:
        if is_age_restricted_error(e):
            print(f"[ERROR] yt-dlp extraction error for '{url}': {e}")
            raise AgeRestrictedError(str(e)) from e
        return None, logger.cookies_rejected, e


def extract_info_sync(url: str, download: bool = False, flat: bool = False) -> Optional[dict]:
    """Blocking extraction executed inside the ThreadPoolExecutor.

    Builds a fresh YoutubeDL and a fresh options dict per call: yt-dlp
    instances are not thread-safe and its constructor mutates the options
    dict it is given, and this runs on a shared executor pool.

    When YouTube rejects the cookie file, retries anonymously: stale cookies
    still extract, but the stream URLs they hand out 403 in ffmpeg.
    """
    options = {**ytdl_format_options}
    if flat:
        options.update(extract_flat=True, noplaylist=False)
    data, cookies_rejected, error = _extract_once(url, options, download)
    if cookies_rejected and 'cookiefile' in options:
        print("[WARNING] YouTube rejected the cookie file; retrying without cookies.")
        options.pop('cookiefile')
        retried, _, error = _extract_once(url, options, download)
        data = retried or data
    if error and not data:
        print(f"[ERROR] yt-dlp extraction error for '{url}': {error}")
    return data


# Strong references to fire-and-forget tasks so they are never garbage-collected mid-run
_background_tasks: set = set()


def spawn_background_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def safe_extract_info(url: str, download: bool = False, flat: bool = False) -> Optional[dict]:
    """Non-blocking extraction wrapper.

    Returns None when extraction fails, except for age-restricted videos
    which raise AgeRestrictedError so callers can report a specific message.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, extract_info_sync, url, download, flat)


async def resolve_stream_url(track: AudioTrack) -> Optional[str]:
    """Resolves a direct playable stream URL right before playback.

    Always performs a fresh yt-dlp extraction so the signed stream URL
    is never stale (YouTube invalidates signatures before their nominal expiry).

    Raises AgeRestrictedError when the video fails to load due to age-restriction.
    """
    query = track.webpage_url or track.title
    info = await safe_extract_info(query, download=False, flat=False)
    if not info:
        return None

    if 'entries' in info:
        entries = [e for e in info['entries'] if e]
        if not entries:
            return None
        info = entries[0]

    track.stream_url = info.get('url')
    if not track.title or track.title == 'Unknown Title':
        track.title = info.get('title', track.title)
    if not track.duration:
        track.duration = int(info.get('duration') or 0)
    return track.stream_url


# --- Modern Interactive UI Components ---
class PlaylistConfirmView(discord.ui.View):
    def __init__(self, author_id: int, num_entries: int, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.num_entries = num_entries
        self.confirmed: Optional[bool] = None

    @discord.ui.button(label="Queue All", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command author can confirm this.", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command author can cancel this.", ephemeral=True)
            return
        self.confirmed = False
        await interaction.response.defer()
        self.stop()


class SearchSelect(discord.ui.Select):
    def __init__(self, entries: List[dict]):
        options = []
        for i, entry in enumerate(entries[:5]):
            title = (entry.get('title') or 'Unknown')[:80]
            dur = str(datetime.timedelta(seconds=int(entry.get('duration') or 0)))
            options.append(discord.SelectOption(
                label=f"{i+1}. {title}",
                value=str(i),
                description=f"Duration: {dur}"
            ))
        super().__init__(placeholder="Select a video to play...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        view: 'SearchResultsView' = self.view
        if interaction.user.id != view.author_id:
            await interaction.response.send_message("Only the user who initiated the search can select a track.", ephemeral=True)
            return
        view.selected_index = int(self.values[0])
        await interaction.response.defer()
        view.stop()


class SearchResultsView(discord.ui.View):
    def __init__(self, author_id: int, entries: List[dict], timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.entries = entries
        self.selected_index: Optional[int] = None
        self.add_item(SearchSelect(entries))


# --- Channel & Multi-Voice Music Player ---
class ChannelMusicPlayer:
    """Manages audio playback and queue for a specific voice channel in a guild."""
    def __init__(self, guild_id: int, channel_id: int, bot_client: commands.Bot):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.bot = bot_client
        self.queue: collections.deque[AudioTrack] = collections.deque()
        self.current: Optional[AudioTrack] = None
        self.queue_lock = asyncio.Lock()      # Guards queue operations (add, pop, clear, shuffle, seek)
        self.playback_lock = asyncio.Lock()   # Guards track transitions & FFmpeg startup to avoid overlapping plays
        self.voice_client: Optional[discord.VoiceClient] = None
        self.playback_started_at: Optional[float] = None
        self.paused_at: Optional[float] = None
        self.total_paused_time: float = 0.0
        self.inactivity_task: Optional[asyncio.Task] = None

    def get_voice_client(self) -> Optional[discord.VoiceClient]:
        guild = self.bot.get_guild(self.guild_id)
        if guild and guild.voice_client and guild.voice_client.channel and guild.voice_client.channel.id == self.channel_id:
            self.voice_client = guild.voice_client
            return self.voice_client
        return None

    def start_inactivity_watchdog(self) -> None:
        """Disconnect when the channel is left with no listeners and no audio."""
        if self.inactivity_task and not self.inactivity_task.done():
            return
        self.inactivity_task = asyncio.create_task(self._inactivity_watchdog())

    async def _inactivity_watchdog(self) -> None:
        try:
            while True:
                await asyncio.sleep(INACTIVITY_CHECK_INTERVAL_SECONDS)
                vc = self.get_voice_client()
                if not vc or not vc.is_connected():
                    return
                if await self.disconnect_if_inactive():
                    return
        except asyncio.CancelledError:
            raise
        finally:
            self.inactivity_task = None

    async def should_disconnect_when_alone(self, vc: discord.VoiceClient) -> bool:
        """Return whether an idle player has no human listeners and no pending audio."""
        members = getattr(vc.channel, "members", ())
        human_count = sum(1 for m in members if not m.bot)
        if human_count > 0:
            return False
        async with self.queue_lock:
            return not self.queue

    async def disconnect_if_inactive(self) -> bool:
        """Disconnect once every human user has left and nothing is playing, paused, or pending."""
        vc = self.get_voice_client()
        if not vc or not vc.is_connected():
            return False
        if vc.is_playing() or vc.is_paused():
            return False
        if not await self.should_disconnect_when_alone(vc):
            return False

        await self.clear()
        self.current = None
        await vc.disconnect()
        return True

    async def add_tracks(self, ctx: commands.Context, tracks: List[AudioTrack]) -> None:
        async with self.queue_lock:
            for track in tracks:
                self.queue.append(track)

        # Trigger playback if idle
        vc = self.get_voice_client()
        if vc and not vc.is_playing() and not vc.is_paused():
            spawn_background_task(self.play_next(ctx))

    async def play_next(self, ctx: commands.Context) -> None:
        """Pops the next track and starts playback."""
        async with self.playback_lock:
            vc = self.get_voice_client()
            if not vc or not vc.is_connected():
                self.current = None
                return

            if vc.is_playing() or vc.is_paused():
                return

            while True:
                async with self.queue_lock:
                    if not self.queue:
                        self.current = None
                        return
                    track = self.queue.popleft()
                    self.current = track
                    self.playback_started_at = None
                    self.paused_at = None
                    self.total_paused_time = 0.0

                # Stream URL resolution (fresh fetch each time)
                try:
                    stream_url = await resolve_stream_url(track)
                except AgeRestrictedError:
                    await ctx.send(f"🔞 Failed to load **{track.title}** due to age-restriction. Skipping...")
                    continue
                if not stream_url:
                    await ctx.send(f"⚠️ Failed to resolve stream for: **{track.title}**. Skipping...")
                    continue

                # Select audio filter
                if track.modifier == "nightcore":
                    ffmpeg_opts = ffmpeg_nightcore_options.copy()
                elif track.modifier == "vaporwave":
                    ffmpeg_opts = ffmpeg_vaporwave_options.copy()
                else:
                    ffmpeg_opts = ffmpeg_options.copy()

                if track.timestamp > 0:
                    ffmpeg_opts["before_options"] = f"-ss {track.timestamp} " + ffmpeg_opts["before_options"]

                try:
                    audio_source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_opts)
                except Exception as e:
                    print(f"[ERROR] FFmpeg initialization error: {e}")
                    await ctx.send(f"⚠️ Error preparing audio stream: {e}")
                    continue

                def after_callback(error):
                    if error:
                        print(f"[ERROR] Playback error on channel {self.channel_id}: {error}")

                    if self.bot.loop.is_running():
                        asyncio.run_coroutine_threadsafe(self.handle_playback_finished(ctx), self.bot.loop)

                try:
                    vc.play(audio_source, after=after_callback)
                    self.playback_started_at = time.monotonic()
                    break
                except discord.ClientException as e:
                    print(f"[WARNING] ClientException during play: {e}")
                    async with self.queue_lock:
                        self.queue.appendleft(track)
                    self.current = None
                    return
                except Exception as e:
                    print(f"[ERROR] Unexpected play error: {e}")
                    await ctx.send(f"⚠️ Playback error: {e}")
                    continue

            ts_str = f" (Seeked to {datetime.timedelta(seconds=track.timestamp)})" if track.timestamp > 0 else ""
            mod_str = f" [{track.modifier.upper()}]" if track.modifier else ""
            await ctx.send(f"🎶 **Now playing**: {track.title} `[{track.get_effective_duration_str()}]`{ts_str}{mod_str}")

    async def handle_playback_finished(self, ctx: commands.Context) -> None:
        await self.play_next(ctx)
        await self.disconnect_if_inactive()

    def get_playback_position(self) -> int:
        """Returns the current source position, including any seek offset."""
        if not self.current:
            return 0
        if self.playback_started_at is None:
            return self.current.timestamp

        end_time = self.paused_at if self.paused_at is not None else time.monotonic()
        elapsed = max(0.0, end_time - self.playback_started_at - self.total_paused_time)
        elapsed *= PLAYBACK_SPEEDS.get(self.current.modifier, 1.0)
        position = int(self.current.timestamp + elapsed)
        return min(position, self.current.duration) if self.current.duration else position

    def get_wall_clock_position(self) -> int:
        """Returns the perceived playback position scaled to the effective duration."""
        if not self.current:
            return 0
        speed = PLAYBACK_SPEEDS.get(self.current.modifier, 1.0)
        wall = int(self.get_playback_position() / speed)
        effective = self.current.get_effective_duration()
        return min(wall, effective) if effective else wall

    def get_progress_bar(self) -> str:
        """Returns the current track's position as a display-ready progress bar."""
        if not self.current:
            return ""
        return format_playback_progress(self.get_wall_clock_position(), self.current.get_effective_duration())

    def pause(self) -> bool:
        vc = self.get_voice_client()
        if not vc or not vc.is_playing():
            return False
        vc.pause()
        self.paused_at = time.monotonic()
        return True

    def resume(self) -> bool:
        vc = self.get_voice_client()
        if not vc or not vc.is_paused():
            return False
        vc.resume()
        if self.paused_at is not None:
            self.total_paused_time += time.monotonic() - self.paused_at
            self.paused_at = None
        return True

    async def skip(self, ctx: commands.Context) -> bool:
        vc = self.get_voice_client()
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            return True
        return False

    async def clear(self) -> None:
        async with self.queue_lock:
            self.queue.clear()

    async def shuffle(self) -> None:
        async with self.queue_lock:
            temp = list(self.queue)
            random.shuffle(temp)
            self.queue = collections.deque(temp)

    async def seek_to(self, seconds: int) -> bool:
        vc = self.get_voice_client()
        if not self.current or not vc:
            return False

        # Duplicate current track with updated timestamp and clear stream_url
        # so resolve_stream_url fetches a fresh URL for the new seek position
        new_track = dataclasses.replace(self.current, timestamp=seconds, stream_url=None)
        async with self.queue_lock:
            self.queue.appendleft(new_track)

        # Stopping will trigger after_callback which pops new_track
        vc.stop()
        return True


# --- Multi-Bot Worker Pool & Channel Manager ---
class MultiChannelMusicManager:
    """
    Manages channel players across multiple voice channels and servers.
    Supports single bot movement as well as secondary worker bot tokens
    for simultaneous multi-channel playback on the same server.
    """
    def __init__(self, main_bot: commands.Bot):
        self.main_bot = main_bot
        self.players: Dict[Tuple[int, int, int], ChannelMusicPlayer] = {}
        self.worker_bots: List[commands.Bot] = []

    def get_player(
        self,
        guild_id: int,
        channel_id: int,
        bot_client: Optional[commands.Bot] = None,
    ) -> ChannelMusicPlayer:
        bot_client = bot_client or self.main_bot
        key = (guild_id, channel_id, id(bot_client))
        if key not in self.players:
            self.players[key] = ChannelMusicPlayer(guild_id, channel_id, bot_client)
        return self.players[key]

    async def ensure_voice_connection(self, ctx: commands.Context) -> Optional[Tuple[discord.VoiceClient, ChannelMusicPlayer]]:
        """Ensures the bot is connected to the author's voice channel and returns the VoiceClient & player."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ You must be connected to a voice channel first.")
            return None

        channel = ctx.author.voice.channel
        guild = ctx.guild
        player = self.get_player(guild.id, channel.id, ctx.bot)

        # Check existing voice client in guild
        vc: Optional[discord.VoiceClient] = guild.voice_client

        if vc is None:
            try:
                vc = await channel.connect()
            except Exception as e:
                await ctx.send(f"❌ Could not connect to voice channel: {e}")
                return None
        elif vc.channel.id != channel.id:
            # Move to new channel seamlessly
            try:
                await vc.move_to(channel)
            except Exception as e:
                await ctx.send(f"❌ Could not move to voice channel: {e}")
                return None

        player.voice_client = vc
        player.start_inactivity_watchdog()
        return vc, player


manager = MultiChannelMusicManager(bot)


# --- Core Command Execution Helper ---
async def play_handler(ctx: commands.Context, args: Tuple[str, ...], *, modifier: str = '', prefix: str = ''):
    if not args:
        await ctx.send("⚠️ Please provide a song name, playlist, or URL.")
        return

    connection = await manager.ensure_voice_connection(ctx)
    if not connection:
        return

    vc, player = connection
    raw_query = " ".join(args).strip()
    timestamp = parse_timestamp(args)

    # Prefix logic: only prepend search keywords if not a direct URL
    if is_direct_url(raw_query):
        query = raw_query
    else:
        query = f"{prefix} {raw_query}".strip() if prefix else raw_query

    is_playlist = is_playlist_url(raw_query)
    tracks_to_add: List[AudioTrack] = []
    feedback_msg: Optional[str] = None

    entries: List[dict] = []
    async with ctx.typing():
        if is_playlist:
            try:
                flat_data = await safe_extract_info(query, download=False, flat=True)
            except AgeRestrictedError:
                await ctx.send("🔞 Failed to load playlist due to age-restriction.")
                return
            if not flat_data or 'entries' not in flat_data:
                await ctx.send("❌ Could not load playlist or playlist is empty.")
                return

            entries = [e for e in flat_data['entries'] if e]
            if len(entries) > MAX_PLAYLIST_LENGTH:
                await ctx.send(f"❌ Playlists are limited to **{MAX_PLAYLIST_LENGTH}** tracks.")
                return
            if not entries:
                await ctx.send("❌ No valid videos found in playlist.")
                return
        else:
            # Single video / search query
            try:
                data = await safe_extract_info(query, download=False, flat=False)
            except AgeRestrictedError:
                await ctx.send("🔞 Failed to load video due to age-restriction.")
                return
            if not data:
                await ctx.send("❌ No video found.")
                return

            if 'entries' in data:
                res_entries = [e for e in data['entries'] if e]
                if not res_entries:
                    await ctx.send("❌ No video found.")
                    return
                data = res_entries[0]

            track_url = data.get('webpage_url') or data.get('url') or query
            tracks_to_add.append(AudioTrack(
                title=data.get('title', 'Unknown Title'),
                webpage_url=track_url,
                stream_url=data.get('url'),
                duration=int(data.get('duration') or 0),
                modifier=modifier,
                timestamp=timestamp,
                requester_name=ctx.author.display_name,
                requester_id=ctx.author.id,
                channel_id=ctx.author.voice.channel.id
            ))
            t = tracks_to_add[0]
            feedback_msg = f"✅ **Added to queue**: {t.title} `[{t.get_duration_str()}]`"

    if is_playlist and entries:
        num_entries = len(entries)
        if num_entries > 50:
            view = PlaylistConfirmView(ctx.author.id, num_entries)
            confirm_msg = await ctx.send(
                f"⚠️ This playlist contains **{num_entries}** tracks. Queue all of them?",
                view=view
            )
            await view.wait()
            try:
                await confirm_msg.delete()
            except Exception:
                pass

            if not view.confirmed:
                await ctx.send("❌ Playlist queue cancelled.")
                return

        for entry in entries:
            track_url = entry.get('url') or entry.get('webpage_url') or entry.get('id')
            if track_url and not track_url.startswith('http'):
                track_url = f"https://www.youtube.com/watch?v={track_url}"
            tracks_to_add.append(AudioTrack(
                title=entry.get('title', 'Unknown Title'),
                webpage_url=track_url or query,
                duration=int(entry.get('duration') or 0),
                modifier=modifier,
                timestamp=0,
                requester_name=ctx.author.display_name,
                requester_id=ctx.author.id,
                channel_id=ctx.author.voice.channel.id
            ))
        feedback_msg = f"✅ **Added to queue**: {len(tracks_to_add)} tracks from playlist."

    if tracks_to_add:
        await player.add_tracks(ctx, tracks_to_add)
        if feedback_msg:
            await ctx.send(feedback_msg)


# --- Bot Events ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')


async def on_voice_state_update(member, before, after):
    """Immediately clean up an idle channel once its last human leaves."""
    if member.bot or before.channel == after.channel or before.channel is None:
        return
    for player in list(manager.players.values()):
        if player.guild_id == member.guild.id and player.channel_id == before.channel.id:
            await player.disconnect_if_inactive()


bot.event(on_voice_state_update)


# --- Bot Commands ---
@bot.command(name='join', help='Join the author\'s voice channel', aliases=['j'])
async def join(ctx: commands.Context):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You are not connected to a voice channel.")
        return

    channel = ctx.author.voice.channel
    if ctx.voice_client:
        if ctx.voice_client.channel.id == channel.id:
            await ctx.send(f"Already connected to **{channel.name}**.")
            return
        await ctx.voice_client.move_to(channel)
        player = manager.get_player(ctx.guild.id, channel.id, ctx.bot)
        player.voice_client = ctx.voice_client
        player.start_inactivity_watchdog()
        await ctx.send(f"Moved to **{channel.name}**.")
    else:
        vc = await channel.connect()
        player = manager.get_player(ctx.guild.id, channel.id, ctx.bot)
        player.voice_client = vc
        player.start_inactivity_watchdog()
        await ctx.send(f"Connected to **{channel.name}**.")


@bot.command(name='leave', help='Disconnect from voice channel', aliases=['dc', 'disconnect'])
async def leave(ctx: commands.Context):
    if ctx.voice_client:
        bot_channel = ctx.voice_client.channel
        channel_name = bot_channel.name if bot_channel else "the channel"
        if bot_channel:
            player = manager.get_player(ctx.guild.id, bot_channel.id, ctx.bot)
            await player.clear()
            player.current = None
        await ctx.voice_client.disconnect()
        await ctx.send(f"👋 Disconnected from **{channel_name}**.")
    else:
        await ctx.send("❌ I am not connected to any voice channel.")


@bot.command(name='play', help='Play a song or playlist', aliases=['p'])
async def play(ctx: commands.Context, *args: str):
    await play_handler(ctx, args)


@bot.command(name='nightcore', help='Play in nightcore mode', aliases=['nc'])
async def nightcore(ctx: commands.Context, *args: str):
    await play_handler(ctx, args, modifier='nightcore')


@bot.command(name='vaporwave', help='Play in vaporwave mode', aliases=['vw'])
async def vaporwave(ctx: commands.Context, *args: str):
    await play_handler(ctx, args, modifier='vaporwave')


@bot.command(name='gachi', help='Play in gachi mode', aliases=['g'])
async def gachi(ctx: commands.Context, *args: str):
    await play_handler(ctx, args, prefix="gachi right version")


@bot.command(name='gachinightcore', help='Play in gachi + nightcore mode', aliases=['gnc'])
async def gachi_nightcore(ctx: commands.Context, *args: str):
    await play_handler(ctx, args, modifier='nightcore', prefix="gachi right version")


@bot.command(name='gachivaporwave', help='Play in gachi + vaporwave mode', aliases=['gvw'])
async def gachi_vaporwave(ctx: commands.Context, *args: str):
    await play_handler(ctx, args, modifier='vaporwave', prefix="gachi right version")


@bot.command(name='ytp', help='Play in YTP mode')
async def ytp(ctx: commands.Context, *args: str):
    await play_handler(ctx, args, prefix="ytp")


@bot.command(name='stp', help='Play in STP mode')
async def stp(ctx: commands.Context, *args: str):
    await play_handler(ctx, args, prefix="stp")


@bot.command(name='search', help='Interactive YouTube search')
async def search(ctx: commands.Context, *, query: str):
    connection = await manager.ensure_voice_connection(ctx)
    if not connection:
        return

    vc, player = connection
    await ctx.send(f"🔍 Searching YouTube for: **{query}**...")

    try:
        results = await safe_extract_info(f"ytsearch5:{query}", download=False, flat=False)
    except AgeRestrictedError:
        await ctx.send("🔞 Failed to load video due to age-restriction.")
        return
    if not results or 'entries' not in results:
        await ctx.send("❌ No results found.")
        return

    entries = [e for e in results['entries'] if e][:5]
    if not entries:
        await ctx.send("❌ No results found.")
        return

    view = SearchResultsView(ctx.author.id, entries)

    lines = [f"**Search Results for '{query}'** (Select below within 60s):"]
    for i, e in enumerate(entries):
        dur = str(datetime.timedelta(seconds=int(e.get('duration') or 0)))
        lines.append(f"`{i+1}.` **{e.get('title', 'Unknown')}** `[{dur}]`")

    msg = await ctx.send("\n".join(lines), view=view)
    await view.wait()

    try:
        await msg.edit(view=None)
    except Exception:
        pass

    if view.selected_index is None:
        await ctx.send("⏱️ Search selection timed out.")
        return

    selected = entries[view.selected_index]
    track = AudioTrack(
        title=selected.get('title', 'Unknown Title'),
        webpage_url=selected.get('webpage_url') or selected.get('url'),
        stream_url=selected.get('url'),
        duration=int(selected.get('duration') or 0),
        requester_name=ctx.author.display_name,
        requester_id=ctx.author.id,
        channel_id=ctx.author.voice.channel.id
    )

    await player.add_tracks(ctx, [track])
    await ctx.send(f"✅ **Added to queue**: {track.title} `[{track.get_duration_str()}]`")


@bot.command(name='pause', help='Pause playback')
async def pause(ctx: commands.Context):
    if ctx.author.voice and ctx.author.voice.channel:
        player = manager.get_player(ctx.guild.id, ctx.author.voice.channel.id, ctx.bot)
        if player.pause():
            await ctx.send("⏸️ Paused playback.")
            return
    await ctx.send("❌ Nothing is currently playing.")


@bot.command(name='resume', help='Resume playback')
async def resume(ctx: commands.Context):
    if ctx.author.voice and ctx.author.voice.channel:
        player = manager.get_player(ctx.guild.id, ctx.author.voice.channel.id, ctx.bot)
        if player.resume():
            await ctx.send("▶️ Resumed playback.")
            return
    await ctx.send("❌ Playback is not paused.")

@bot.command(name='skip', help='Skip current song', aliases=['s'])
async def skip(ctx: commands.Context):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You are not connected to a voice channel.")
        return

    player = manager.get_player(ctx.guild.id, ctx.author.voice.channel.id, ctx.bot)
    if await player.skip(ctx):
        await ctx.send("⏭️ Skipped current track.")
    else:
        await ctx.send("❌ Nothing is currently playing to skip.")


@bot.command(name='clear', help='Clear the queue')
async def clear(ctx: commands.Context):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You are not connected to a voice channel.")
        return

    player = manager.get_player(ctx.guild.id, ctx.author.voice.channel.id, ctx.bot)
    await player.clear()
    await ctx.send("🗑️ Queue has been cleared.")


@bot.command(name='queue', help='Show current queue', aliases=['q'])
async def queue_cmd(ctx: commands.Context):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You are not connected to a voice channel.")
        return

    player = manager.get_player(ctx.guild.id, ctx.author.voice.channel.id, ctx.bot)
    async with player.queue_lock:
        current_track = player.current
        queued_tracks = list(player.queue)

    lines = []
    if current_track:
        lines.append(
            f"**Now Playing**: {current_track.title} `[{current_track.get_duration_str()}]`\n"
            f"{player.get_progress_bar()}\n"
        )

    if queued_tracks:
        lines.append("**Upcoming Queue:**")
        shown = 0
        for i, track in enumerate(queued_tracks):
            entry = f"`{i+1}.` {track.title} `[{track.get_duration_str()}]`"
            if i >= 15 or sum(len(line) + 1 for line in lines) + len(entry) > 1900:
                break
            lines.append(entry)
            shown += 1
        if shown < len(queued_tracks):
            lines.append(f"*... and {len(queued_tracks) - shown} more.*")
    elif not current_track:
        lines.append("The queue is currently empty.")

    await ctx.send("\n".join(lines))


@bot.command(name='shuffle', help='Shuffle upcoming queue', aliases=['sh'])
async def shuffle(ctx: commands.Context):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You are not connected to a voice channel.")
        return

    player = manager.get_player(ctx.guild.id, ctx.author.voice.channel.id, ctx.bot)
    if player.queue:
        await player.shuffle()
        await ctx.send("🔀 Queue shuffled!")
    else:
        await ctx.send("❌ Queue is empty.")


@bot.command(name='nowplaying', help='Display current playing track', aliases=['np'])
async def now_playing(ctx: commands.Context):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You are not connected to a voice channel.")
        return

    player = manager.get_player(ctx.guild.id, ctx.author.voice.channel.id, ctx.bot)
    if player.current:
        mod = f" ({player.current.modifier.upper()})" if player.current.modifier else ""
        await ctx.send(
            f"🎶 **Currently playing**: {player.current.title}{mod} `[{player.current.get_duration_str()}]` "
            f"(Requested by {player.current.requester_name})\n{player.get_progress_bar()}"
        )
    else:
        await ctx.send("❌ Nothing is currently playing.")


@bot.command(name='seekto', help='Seek to a timestamp (e.g. 1:30, 01:20:00, 90)', aliases=['st', 'seek'])
async def seek_to(ctx: commands.Context, *, timestamp: str):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ You are not connected to a voice channel.")
        return

    seconds = parse_time_str(timestamp)
    if seconds == 0 and timestamp.strip() not in ['0', '0:00', '00:00']:
        await ctx.send("❌ Invalid timestamp format. Please use `HH:MM:SS`, `MM:SS`, or `seconds`.")
        return

    player = manager.get_player(ctx.guild.id, ctx.author.voice.channel.id, ctx.bot)
    if not player.current:
        await ctx.send("❌ Nothing is currently playing.")
        return

    if player.current.duration > 0 and seconds >= player.current.duration:
        await ctx.send(f"❌ Timestamp exceeds song duration (`{player.current.get_duration_str()}`).")
        return

    success = await player.seek_to(seconds)

    if success:
        formatted = str(datetime.timedelta(seconds=seconds))
        await ctx.send(f"⏩ Seeking to `{formatted}`...")
    else:
        await ctx.send("❌ Failed to seek.")


# --- Multi-Token Launcher & Graceful Shutdown ---
async def start_all_bots():
    """Runs the main bot along with any secondary worker bots defined in env vars."""
    tokens = []
    main_token = os.environ.get('DISCORD_TOKEN')
    if main_token:
        tokens.append(main_token)

    # Support comma-separated DISCORD_TOKENS or DISCORD_TOKEN_2, DISCORD_TOKEN_3, etc.
    multi_tokens = os.environ.get('DISCORD_TOKENS')
    if multi_tokens:
        tokens.extend([t.strip() for t in multi_tokens.split(',') if t.strip() and t.strip() not in tokens])

    for i in range(2, 10):
        t = os.environ.get(f'DISCORD_TOKEN_{i}')
        if t and t not in tokens:
            tokens.append(t)

    if not tokens:
        print("Error: No DISCORD_TOKEN found in environment variables.")
        return

    try:
        if len(tokens) == 1:
            await bot.start(tokens[0])
        else:
            bot_tasks = [bot.start(tokens[0])]
            for idx, token in enumerate(tokens[1:], start=2):
                worker = commands.Bot(command_prefix='!', intents=intents)
                for command in bot.commands:
                    worker.add_command(command.copy())
                worker.event(on_voice_state_update)

                def make_worker_ready(worker_bot):
                    async def on_ready():
                        print(f'Logged in as {worker_bot.user} (ID: {worker_bot.user.id})')
                        print('------')
                    return on_ready

                worker.event(make_worker_ready(worker))
                manager.worker_bots.append(worker)
                bot_tasks.append(worker.start(token))
            await asyncio.gather(*bot_tasks)
    finally:
        print("Shutting down executor...")
        executor.shutdown(wait=False)


if __name__ == '__main__':
    try:
        asyncio.run(start_all_bots())
    except KeyboardInterrupt:
        print("\nBot process terminated by user.")
