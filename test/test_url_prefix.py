import unittest

from music_bot import is_direct_url, is_playlist_url


class TestUrlPrefix(unittest.TestCase):
    def test_is_direct_url(self):
        self.assertTrue(is_direct_url("http://example.com"))
        self.assertTrue(is_direct_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(is_direct_url("https://youtu.be/dQw4w9WgXcQ"))
        self.assertTrue(is_direct_url("  https://soundcloud.com/artist/track  "))

        self.assertFalse(is_direct_url("rick astley never gonna give you up"))
        self.assertFalse(is_direct_url("gachi right version"))
        self.assertFalse(is_direct_url("ytsearch:hello"))
        self.assertFalse(is_direct_url("ftp://not-supported.com"))

    def test_prefix_query_builder_logic(self):
        prefix = "gachi right version"

        direct_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        query_from_url = direct_url if is_direct_url(direct_url) else f"{prefix} {direct_url}"
        self.assertEqual(query_from_url, direct_url)

        search_term = "turn around"
        query_from_search = search_term if is_direct_url(search_term) else f"{prefix} {search_term}"
        self.assertEqual(query_from_search, "gachi right version turn around")


class TestPlaylistDetection(unittest.TestCase):
    """Playlist detection should trigger only for direct URLs with actual `?list=` / `&list=` parameters, not the substring `playlist`."""

    def _is_playlist(self, query: str) -> bool:
        return is_playlist_url(query)

    def test_youtube_playlist_url(self):
        self.assertTrue(self._is_playlist("https://www.youtube.com/watch?v=abc&list=PL123"))
        self.assertTrue(self._is_playlist("https://www.youtube.com/playlist?list=PL123"))

    def test_search_query_with_playlist_word(self):
        self.assertFalse(self._is_playlist("rick astley playlist mix"))
        self.assertFalse(self._is_playlist("best songs playlist 2024"))

    def test_search_query_without_list(self):
        self.assertFalse(self._is_playlist("https://www.youtube.com/watch?v=abc"))
        self.assertFalse(self._is_playlist("turn around flashdance"))

    def test_search_query_with_list_param_looking_text(self):
        self.assertFalse(self._is_playlist("songs ?list=abc"))
        self.assertFalse(self._is_playlist("tracks &list=xyz_123"))


if __name__ == '__main__':
    unittest.main()