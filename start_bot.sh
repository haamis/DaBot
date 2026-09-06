#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [[ ! -f ./.env ]]; then
    echo "Missing .env; add DISCORD_TOKEN=..." >&2
    exit 1
fi

set -a
source ./.env
set +a

: "${DISCORD_TOKEN:?DISCORD_TOKEN must be set in .env}"
exec "$DIR/venv/bin/python" "$DIR/music_bot.py"
