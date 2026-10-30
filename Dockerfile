FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# yt-dlp's JS runtime: yt-dlp-ejs needs one to solve YouTube's nsig, otherwise
# yt-dlp warns that extraction is deprecated and some formats go missing.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY music_bot.py .

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

# App deps matching the working host. discord.py[voice] pulls aiohttp, PyNaCl and
# davey (Discord's DAVE/E2EE voice, required or voice connections get dropped);
# yt-dlp[default] pulls its own stack.
RUN uv pip install --system \
    "discord.py[voice]==2.7.1" \
    "yt-dlp[default]" \
    bgutil-ytdlp-pot-provider

# yt-dlp rots fast and YouTube breaks with it; refresh on start (`|| true`) so a bad
# release or an offline start only warns and the bot runs on the baked-in version.
CMD ["sh", "-c", "uv pip install --system -U --pre 'yt-dlp[default]' bgutil-ytdlp-pot-provider || true; exec python -u music_bot.py"]
