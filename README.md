# DaBot

A Discord music bot built on [discord.py](https://github.com/Rapptz/discord.py) and
[yt-dlp](https://github.com/yt-dlp/yt-dlp). It streams YouTube audio into voice channels,
keeps a queue per channel, and adds a few playback gimmicks (nightcore, vaporwave, gachi,
YTP/STP search). Everything runs in one file, `music_bot.py`, inside Docker Compose.

## Features

- Play/search YouTube tracks and playlists by URL or query.
- Per-voice-channel queues: several channels (and several bot tokens) can play at once.
- Nightcore (1.25x) and vaporwave (0.8x) speed modes via ffmpeg filter chains.
- Interactive search picker (top 5 results) and playlist confirmation for large playlists.
- Now Playing and queue views with a live progress bar.
- Seek to a timestamp, pause/resume, skip, shuffle, clear.
- Leaves automatically when the channel has no humans left and nothing is playing or queued.

## Commands

Prefix: `!` (`!help` lists commands in Discord).

| Command | Aliases | What it does |
| --- | --- | --- |
| `!join` | `!j` | Join your voice channel (or move to it). |
| `!leave` | `!dc`, `!disconnect` | Clear the queue and disconnect. |
| `!play <query/url>` | `!p` | Queue a track, search result, or playlist. |
| `!search <query>` | | Show the top 5 results and queue the one you pick. |
| `!nightcore <query/url>` | `!nc` | Play at 1.25x speed. |
| `!vaporwave <query/url>` | `!vw` | Play at 0.8x speed. |
| `!gachi <query/url>` | `!g` | Search with the "gachi right version" prefix. |
| `!gachinightcore <query/url>` | `!gnc` | Gachi search + nightcore. |
| `!gachivaporwave <query/url>` | `!gvw` | Gachi search + vaporwave. |
| `!ytp <query/url>` | | Search with the "ytp" prefix. |
| `!stp <query/url>` | | Search with the "stp" prefix. |
| `!pause` / `!resume` | | Pause or resume playback. |
| `!skip` | `!s` | Skip the current track. |
| `!clear` | | Empty the queue (current track keeps playing). |
| `!queue` | `!q` | Show Now Playing and the upcoming queue. |
| `!shuffle` | `!sh` | Shuffle the upcoming queue. |
| `!nowplaying` | `!np` | Show the current track and progress. |
| `!seekto <time>` | `!st`, `!seek` | Seek to `SS`, `MM:SS`, or `HH:MM:SS`. |

Notes:

- Playlist detection needs a direct URL containing `?list=` / `&list=`. Playlists are capped
  at 300 tracks; above 50 you get a confirm button.
- A YouTube URL with `?t=` / `&start=` starts that single track at the timestamp
  (`1h2m3s`, `2m15s`, `90`, `90s`). Playlist entries always start at 0.
- The `gachi`/`ytp`/`stp` prefixes only apply to text searches, not to direct URLs.

## Quick start

Prerequisites: Docker with Compose, a Discord application/bot token, and network access on
first `up` (the PO-token provider image is pulled).

1. Create `.env` in the repository root:

   ```sh
   DISCORD_TOKEN=your-bot-token
   ```

2. Export YouTube cookies (optional but recommended) to `./cookies.txt` in Netscape format.
   Create the file (even empty) **before** `up`, or Docker creates a root-owned directory at
   that path. Empty/missing cookies are ignored; age-gated videos then just fail to load.

3. Start the bot:

   ```sh
   docker compose up -d --build
   docker compose logs -f music-bot
   ```

   You should see `Logged in as ...`. `docker compose ps` shows whether the container is up.

4. Invite the bot with the `bot` and `applications.commands` scopes and the **Message
   Content** privileged intent enabled in the Discord developer portal. It needs permission
   to view channels, send messages, and connect/speak in voice.

Code changes require a rebuild (`--build`); the image copies `music_bot.py` at build time.

### Updating

The container refreshes yt-dlp to the latest pre-release on every start, because YouTube
breaks stable releases often. A nightly host cron job keeps it fully fresh:

```sh
cd /path/to/DaBot && docker compose build --pull && docker compose up -d --force-recreate
```

`--force-recreate` is what triggers the start-up yt-dlp upgrade; the build alone is not
enough if the image did not change.

## Configuration

Set through `.env` (Compose passes it to the bot) or the environment:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DISCORD_TOKEN` | yes | Main bot token. |
| `DISCORD_TOKENS` | no | Comma-separated extra tokens for simultaneous playback in several channels. |
| `DISCORD_TOKEN_2` … `_9` | no | Alternative way to pass extra worker tokens. |
| `POT_PROVIDER_URL` | no | PO-token provider URL. Compose sets it to `http://pot-provider:4416`. |

`docker-compose.yml` starts two services: `music-bot` and `pot-provider`
(`brainicism/bgutil-ytdlp-pot-provider`), which supplies YouTube PO tokens. The bot waits for
the provider's healthcheck, so `up` needs registry access; an already-running bot keeps
working if the provider is unavailable.

## Tests

```sh
./venv/bin/python -m unittest
```

Tests live under `test/` and are pure unit tests (mocked voice clients and yt-dlp). Queue
tests use `test.com` URLs on purpose, so yt-dlp DNS errors in the output do not mean failure.

## Layout

```
music_bot.py          the whole bot: commands, players, yt-dlp/ffmpeg wiring
Dockerfile            image with ffmpeg, deno, discord.py, yt-dlp, bgutil plugin
docker-compose.yml    bot + PO-token provider
test/                 unittest suite
AGENTS.md             maintenance notes: deployment, ffmpeg options, design decisions
```

## Troubleshooting

- **Track cuts off early / no audio**: reconnect flags must stay in ffmpeg `before_options`;
  see `AGENTS.md`. Also check `docker compose logs music-bot` for extraction errors.
- **403 / age-restriction errors**: refresh `cookies.txt`. If yt-dlp says cookies are no
  longer valid, the bot retries without them, but auth-gated videos will fail.
- **No startup output**: the image runs `python -u` with `PYTHONUNBUFFERED=1`; keep both.
- **yt-dlp / provider version warnings**: the bgutil plugin and provider image both float;
  update them together.

### Automated cookie updates (Windows → server)

Age-gated videos need fresh cookies. The bot reloads `cookies.txt` on every
extraction, so you only need to push an updated file — no container restart.

Both scripts run **only on the Windows desktop** that has Firefox. The server
has no browser and never runs the exporter; it just receives `cookies.txt`.

**scripts/export-cookies.py** reads Firefox cookies and writes Netscape format.
**scripts/push-cookies.bat** runs it and `scp`s the file to the server.

1. On Windows, install deps once:
   ```cmd
   pip install browser-cookie3
   ```

2. Test manually (adjust server/path):
   ```cmd
   scripts\push-cookies.bat haama@boksi.local /home/haama/DaBot/cookies.txt
   ```

   The SSH key defaults to `~/.ssh/id_local`; pass another path as the fourth
   argument to override. The `.bat` expands `~` to `%USERPROFILE%` because
   Windows `scp` does not do that itself.

3. Schedule it (Task Scheduler → Create Basic Task):
   - Trigger: Daily / every 6 hours / whatever you prefer.
   - Action: Start a program → `cmd.exe`
   - Arguments:
     ```
     /c "C:\path\to\DaBot\scripts\push-cookies.bat" haama@boksi.local /home/haama/DaBot/cookies.txt
     ```
   - Run only when the user is logged on (needs the Firefox profile).

The script aborts without touching the server copy if Firefox has no YouTube
cookies, so a browser logout cannot wipe a working file.
