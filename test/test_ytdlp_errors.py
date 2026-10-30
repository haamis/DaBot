import unittest
from unittest.mock import patch

import music_bot
from music_bot import STALE_COOKIE_MARKER, extract_info_sync, is_age_restricted_error


class TestAgeRestrictedDetection(unittest.TestCase):
    def test_age_gate_messages(self):
        self.assertTrue(is_age_restricted_error(Exception(
            "ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate for some users.")))
        self.assertTrue(is_age_restricted_error(
            Exception('This video is age-restricted; some formats may be missing without authentication.')))

    def test_other_failures_are_not_age_restricted(self):
        # Bot check: a cookie problem, not an age gate.
        self.assertFalse(is_age_restricted_error(Exception(
            "Sign in to confirm you're not a bot. This helps protect our community.")))
        self.assertFalse(is_age_restricted_error(Exception('Unable to download webpage: HTTP Error 429')))
        self.assertFalse(is_age_restricted_error(Exception('Unable to extract page config')))


class TestStaleCookieFallback(unittest.TestCase):
    def _run(self, warn_on_cookie_use):
        calls = []

        class FakeYDL:
            def __init__(self, options):
                self.options = options
                calls.append(options)

            def extract_info(self, url, download=False):
                if self.options.get('cookiefile') and warn_on_cookie_use:
                    self.options['logger'].warning(
                        f"WARNING: [youtube] The provided YouTube account {STALE_COOKIE_MARKER}.")
                return {'url': f"stream-{self.options.get('cookiefile')}"}

        with patch.object(music_bot.yt_dlp, 'YoutubeDL', FakeYDL), \
                patch.dict(music_bot.ytdl_format_options, {'cookiefile': './cookies.txt'}):
            info = extract_info_sync('https://example.com/watch?v=x')
        return calls, info

    def test_retries_anonymously_when_cookies_rejected(self):
        calls, info = self._run(warn_on_cookie_use=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['cookiefile'], './cookies.txt')
        self.assertNotIn('cookiefile', calls[1])
        # The returned stream URL must come from the cookieless retry.
        self.assertEqual(info['url'], 'stream-None')

    def test_keeps_first_result_when_retry_fails(self):
        calls = []

        class FakeYDL:
            def __init__(self, options):
                self.options = options
                calls.append(options)

            def extract_info(self, url, download=False):
                if self.options.get('cookiefile'):
                    # Both pinned clients warn; only one line should be printed.
                    self.options['logger'].warning(f"WARNING: {STALE_COOKIE_MARKER}")
                    self.options['logger'].warning(f"WARNING: {STALE_COOKIE_MARKER}")
                    return {'url': 'stream-cookies'}
                raise RuntimeError('retry boom')

        with patch.object(music_bot.yt_dlp, 'YoutubeDL', FakeYDL), \
                patch.dict(music_bot.ytdl_format_options, {'cookiefile': './cookies.txt'}), \
                patch('builtins.print') as printed:
            info = extract_info_sync('https://example.com/watch?v=x')

        self.assertEqual(len(calls), 2)
        self.assertEqual(info['url'], 'stream-cookies')
        lines = [str(call.args[0]) for call in printed.call_args_list if call.args]
        self.assertEqual(sum(STALE_COOKIE_MARKER in line for line in lines), 1)
        self.assertFalse(any('extraction error' in line for line in lines))

    def test_no_retry_when_cookies_accepted(self):
        calls, info = self._run(warn_on_cookie_use=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(info['url'], 'stream-./cookies.txt')

    def test_no_retry_without_cookie_file(self):
        calls = []

        class FakeYDL:
            def __init__(self, options):
                self.options = options
                calls.append(options)

            def extract_info(self, url, download=False):
                self.options['logger'].warning(f"WARNING: {STALE_COOKIE_MARKER}")
                return {'url': 'stream'}

        with patch.object(music_bot.yt_dlp, 'YoutubeDL', FakeYDL), \
                patch.dict(music_bot.ytdl_format_options, {}, clear=True):
            extract_info_sync('https://example.com/watch?v=x')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
