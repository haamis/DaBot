# Repository notes

## Running / testing

- Single-file bot: `music_bot.py`, run by the Docker container (`Dockerfile`). Docker Compose
  is the only supported deployment.
- Run tests from the repository root with the venv: `./venv/bin/python -m unittest` (discovers tests under `test/`).
- Some queue tests deliberately use `test.com` URLs, so yt-dlp DNS errors may appear even when the suite passes.
- Voice-channel logic is asynchronous: test it with mocked voice clients and `AsyncMock` for `disconnect()`.
- Startup prints like `Logged in as ...` appear in `docker compose logs` (the image runs
  `python -u` with `PYTHONUNBUFFERED=1`); `docker compose ps` shows the container is up.
  Keep both unbuffered settings or startup output goes silent again (block-buffered until shutdown).

## Deployment (Docker)

- `docker compose up -d --build`. The image copies `music_bot.py` at build time, so code
  changes without `--build` keep running the old code. The image also refreshes yt-dlp on
  start (`|| true`), so an offline start still works.
- `.env` with `DISCORD_TOKEN` is required. Everything else runs in compose: the image ships
  `deno` (yt-dlp's JS runtime) and the `pot-provider` service supplies PO tokens, reached via
  `POT_PROVIDER_URL` (compose sets it to the service name).
- `up` pulls `pot-provider` (`pull_policy: always`) and waits for its healthcheck, so it needs
  registry access. A provider that fails to start blocks `up`; a bot that is already running
  keeps working without it.
- Nightly refresh is a host cron job, not a compose feature:
  `cd /home/haama/DaBot && docker compose build --pull && docker compose up -d --force-recreate`
  (log: `~/.cache/dabot-refresh.log`). `--force-recreate` is the part that updates yt-dlp: the
  `--pre` upgrade runs in the image entrypoint at container start, so an unchanged image would
  otherwise keep the old version. A failed build skips the `up`, leaving the running bot alone.
- The bgutil plugin and server must be on the same version; both float (`--pre` pip install,
  `:latest` image), so update them together if yt-dlp starts warning about a mismatch.
- `./cookies.txt` must exist on the host before `up`, otherwise Docker creates a root-owned
  directory at that path. The bot ignores a missing/empty cookie file, but remove the stray
  directory before putting real cookies there.

## ffmpeg options — do not regress

- Reconnect flags (`-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5`) MUST stay in
  `before_options` (pre-input). In post-input `options` they silently do nothing: mid-stream
  connection resets then truncate tracks early with exit=0 and no log trace.
- Bare boolean flags swallow the next token; always pass explicit values
  (`-reconnect 1`, never bare `-reconnect`).
- Reconnect options are HTTP-protocol options: they error ("Option not found") on file/lavfi
  inputs but are valid for the http(s) URLs the bot actually plays. Don't "verify" them with a
  local-file or lavfi dry-run.
- `-reconnect_on_http_error` takes a space-separated value form (`... 4xx,5xx`), not `=value`.
- discord.py appends `-loglevel warning` after the input; last `-loglevel` wins, so the
  `-loglevel fatal` in `options` suppresses recoverable TLS/demux error noise while fatal
  init errors still print.

## Design decisions

- No info cache or prefetch: user count is low, so `resolve_stream_url` always fetches fresh
  via yt-dlp. Do not re-add caching without asking.
- yt-dlp is installed with `--pre` on purpose (YouTube breaks stable releases often); keep the
  flag in the `Dockerfile`, and don't pin a stable version.
- yt-dlp warnings are not suppressed (`no_warnings: False`) so stale cookie files, provider
  version mismatches and extraction problems show up in `docker compose logs`. Do not re-add
  `no_warnings: True`; that hid every one of those.
- yt-dlp 403/age-restriction errors are stale-`cookies.txt` problems, not reconnect issues;
  the user maintains `cookies.txt` (gitignored). A missing or empty `cookies.txt` is ignored
  (no `cookiefile` set) so a fresh Docker bind mount can't break every extraction; auth-gated
  videos then just fail to load.
- Seek timestamps support compound `1h2m3s` forms with optional suffixes
  (`parse_timestamp` in `music_bot.py`); progress bar / Now Playing use
  `get_effective_duration` / `get_wall_clock_position`, not raw `FFmpegPCMAudio` duration.
- Nightcore/vaporwave speed comes from `asetrate` only (no `atempo`): `asetrate=44100*1.25`
  alone already plays 1.25x faster, so the values in `PLAYBACK_SPEEDS` must match the filter
  chain or all duration/progress math drifts. Do not re-add `atempo` without updating
  `PLAYBACK_SPEEDS` to the compounded rate.
- There is no idle-timeout disconnect. The bot leaves only when every human user has left
  the voice channel and nothing is playing, paused, or queued (watchdog re-checks every
  minute as a safety net). `ClientException` during playback clears only the current track.
- yt-dlp instances are created per extraction call (`extract_info_sync`); they are not
  thread-safe, so don't reintroduce module-level shared instances for the executor pool.
- Playlist detection (`is_playlist_url`) requires a direct URL with a real `?list=` /
  `&list=` parameter; search text containing the word "playlist" must stay a search.
  Seek timestamps (`t=`) apply only to single-track adds, never to playlist entries.
