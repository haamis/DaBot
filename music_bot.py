import asyncio, datetime, re
from functools import partial
import concurrent.futures

import discord
from discord.ext import commands
import yt_dlp

intents = discord.Intents.default()
intents.message_content = True  # Make sure this intent is enabled in your Discord developer portal

bot = commands.Bot(command_prefix='!', intents=intents)

# Suppress noise about console usage from errors
#yt_dlp.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,  # Allow playlists
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': True,
    'quiet': False,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # Bind to ipv4 since ipv6 addresses cause issues sometimes
    'cookiefile': './cookies.txt',
#    'username': 'oauth2',
#    'password': ''
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ffmpeg_nightcore_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter_complex "asetrate=44100*1.25,aresample=44100,atempo=1.25"'
}

ffmpeg_vaporwave_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter_complex "asetrate=44100*0.8,aresample=44100,atempo=0.8"'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

def parse_timestamp(url):
    if len(url) > 1:
        return 0
    match = re.search(r'[?&]t=(\d+)', url[0])
    if match:
        return int(match.group(1))
    return 0

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(self, url, ctx, *, loop=None, stream=True, modifier='', timestamp=0):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if not data:
            await ctx.send(f"Failed to load video, probably age-restricted.")
            return

        if 'entries' in data:
            # This is a playlist
            ret = []
            vid_unavailable_printed = False
            for entry in data['entries']:
                if entry:
                    entry['meme_modifier'] = modifier
                    entry['timestamp'] = timestamp
                    ret.append(entry)
                elif not vid_unavailable_printed:
                    await ctx.send(f"At least one video in the playlist was unavailable.")
                    vid_unavailable_printed = True
            return ret
        else:
            data['meme_modifier'] = modifier
            data['timestamp'] = timestamp
            return data

class MusicQueue:
    def __init__(self):
        self.queue = []
        self.current = None

    async def add_to_queue(self, ctx, source):
        self.queue.append((ctx, source))
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await self.play_next(ctx)

    async def play_next(self, ctx):
        if not self.queue:
            self.current = None
            await ctx.guild.voice_client.disconnect()
            return

        ctx, source = self.queue.pop(0)
        self.current = source
        if source["meme_modifier"] == 'nightcore':
            ffmpeg_opts = ffmpeg_nightcore_options.copy()
        elif source["meme_modifier"] == 'vaporwave':
            ffmpeg_opts = ffmpeg_vaporwave_options.copy()
        else:
            ffmpeg_opts = ffmpeg_options.copy()

        ffmpeg_opts['before_options'] += f' -ss {source["timestamp"]}' if source['timestamp'] else ''
        d_pcm = discord.FFmpegPCMAudio(source['url'], **ffmpeg_opts, )
        ytdl_source = YTDLSource(d_pcm, data=source)
        executor.submit(ctx.voice_client.play(ytdl_source, after=lambda e: self.play_next_in_queue(ctx)))
        dur_string = str(datetime.timedelta(seconds=source.get('duration')))
        await ctx.send(f'**Now playing**: {ytdl_source.title} **[{dur_string}]**')

    def play_next_in_queue(self, ctx):
        fut = asyncio.run_coroutine_threadsafe(self.play_next(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f'Error in play_next_in_queue: {e}')

    async def clear(self, ctx):
        self.queue = []

    async def shuffle(self, ctx):
        self.queue.shuffle()

music_queue = MusicQueue()

async def play_command(ctx, url, *, modifier='', prefix=''):
    if not ctx.voice_client:
        channel = ctx.message.author.voice.channel
        await channel.connect()
    async with ctx.typing():
        timestamp = parse_timestamp(url)
        sources = await YTDLSource.from_url(prefix + " ".join(url), ctx, loop=bot.loop, stream=True, modifier=modifier, timestamp=timestamp)
        if not sources:
            await ctx.send("No video found.")
            return

        if isinstance(sources, list):
            for source in sources:
                await music_queue.add_to_queue(ctx, source)
            if len(sources) > 1:
                await ctx.send(f'**Added to queue**: {len(sources)} videos')
            else:
                await ctx.send(f'**Added to queue**: {source.get("title")}')
        else:
            await music_queue.add_to_queue(ctx, sources)
            await ctx.send(f'**Added to queue**: {sources.get("title")}')

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

@bot.command(name='join', help='Tells the bot to join the voice channel', aliases=['j'])
async def join(ctx):
    if not ctx.message.author.voice:
        await ctx.send(f'{ctx.message.author.name} is not connected to a voice channel')
        return
    else:
        channel = ctx.message.author.voice.channel

    await channel.connect()

@bot.command(name='leave', help='To make the bot leave the voice channel')
async def leave(ctx):
    if ctx.voice_client:
        await ctx.guild.voice_client.disconnect()
        await ctx.send("I have left the voice channel")
    else:
        await ctx.send("I'm not in a voice channel")

@bot.command(name='play', help='To play song or playlist', aliases=['p'])
async def play(ctx, *url):
    await play_command(ctx, url)

@bot.command(name='nightcore', help='To play song or playlist in nightcore mode', aliases=['nc'])
async def nightcore(ctx, *url):
    await play_command(ctx, url, modifier='nightcore')

@bot.command(name='vaporwave', help='To play song or playlist in vaporwave mode', aliases=['vw'])
async def vaporwave(ctx, *url):
    await play_command(ctx, url, modifier='vaporwave')

@bot.command(name='gachi', help='To play song or playlist in gachi mode', aliases=['g'])
async def gachi(ctx, *url):
    await play_command(ctx, url, prefix="gachi right version ")

@bot.command(name='gachinightcore', help='To play song or playlist in gachi+nightcore mode', aliases=['gnc'])
async def gachi_nightcore(ctx, *url):
    await play_command(ctx, url, modifier='nightcore', prefix="gachi right version ")

@bot.command(name='gachivaporwave', help='To play song or playlist in gachi+vaporwave mode', aliases=['gvw'])
async def gachi_vaporwave(ctx, *url):
    await play_command(ctx, url, modifier='vaporwave', prefix="gachi right version ")

@bot.command(name='pause', help='This command pauses the song')
async def pause(ctx):
    ctx.voice_client.pause()
    await ctx.send("Paused the song")

@bot.command(name='resume', help='Resumes the song')
async def resume(ctx):
    ctx.voice_client.resume()
    await ctx.send("Resumed the song")

@bot.command(name='clear', help='Clear the queue')
async def clear(ctx):
    await music_queue.clear(ctx)
    await ctx.send("Queue cleared")

@bot.command(name='queue', help='Shows the current music queue', aliases=['q'])
async def queue(ctx):
    if music_queue.queue:
        titles = []
        for i, (_, source) in enumerate(music_queue.queue):
            if i < 20:
                titles.append("- " + source.get('title'))
            else:
                titles.append(f'... and {len(music_queue.queue) - 20} more.')
                break
        queue_list = '\n'.join(titles)
        await ctx.send(f'**Current queue**:\n{queue_list}')
    else:
        await ctx.send("The queue is empty")

@bot.command(name='shuffle', help='Shuffle the queue', aliases=['sh'])
async def shuffle(ctx):
    if music_queue.queue:
        await music_queue.shuffle(ctx)
        await ctx.send("Queue shuffled!")
    else:
        await ctx.send("The queue is empty")

@bot.command(name='skip', help='Skips the current song', aliases=['s'])
async def skip(ctx):
    ctx.voice_client.stop()

# asyncio.run(bot.start('REDACTED_DISCORD_TOKEN'), debug=True)
# handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
bot.run('REDACTED_DISCORD_TOKEN') #, log_handler=handler)
