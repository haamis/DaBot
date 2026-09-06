# Repository notes

## Running / testing

- Single-file bot: `music_bot.py`, launched via `start_bot.sh` (sources `.env` for `DISCORD_TOKEN`).
- Run tests from the repository root with the venv: `./venv/bin/python -m unittest` (discovers tests under `test/`).
- Some queue tests deliberately use `test.com` URLs, so yt-dlp DNS errors may appear even when the suite passes.
- Voice-channel logic is asynchronous: test it with mocked voice clients and `AsyncMock` for `disconnect()`.
- Restart the bot after code changes: `systemctl --user restart music-bot.service` (check `journalctl --user -u music-bot`).

## ffmpeg options (ffmpeg 6.1.1) — do not regress

- Reconnect flags (`-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5`) MUST stay in
  `before_options` (pre-input). In post-input `options` they silently do nothing: mid-stream
  connection resets then truncate tracks early with exit=0 and no log trace.
- Bare boolean flags in this ffmpeg build swallow the next token; always pass explicit values
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
- yt-dlp 403/age-restriction errors are stale-`cookies.txt` problems, not reconnect issues;
  the user maintains `cookies.txt` (gitignored).
- Seek timestamps support compound `1h2m3s` forms with optional suffixes
  (`parse_timestamp` in `music_bot.py`); progress bar / Now Playing use
  `get_effective_duration` / `get_wall_clock_position`, not raw `FFmpegPCMAudio` duration.
- The 1-hour inactivity disconnect preserves the queue; `ClientException` during playback
  clears only the current track.
