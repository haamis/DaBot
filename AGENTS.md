# Repository notes

- Run Python checks and tests with the repository virtual environment: `./venv/bin/python -m unittest`.
- Run the full suite from the repository root; it discovers tests under `test/`.
- Some queue tests deliberately use `test.com` URLs, so yt-dlp DNS errors may appear even when the suite passes.
- Voice-channel logic is asynchronous: test it with mocked voice clients and `AsyncMock` for `disconnect()`.
