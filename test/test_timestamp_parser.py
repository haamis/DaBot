import unittest

from music_bot import parse_time_str, parse_timestamp


class TestTimestampParser(unittest.TestCase):
    def test_parse_time_str(self):
        self.assertEqual(parse_time_str("45"), 45)
        self.assertEqual(parse_time_str("0"), 0)

        self.assertEqual(parse_time_str("1:30"), 90)
        self.assertEqual(parse_time_str("03:15"), 195)
        self.assertEqual(parse_time_str("00:00"), 0)

        self.assertEqual(parse_time_str("1:00:00"), 3600)
        self.assertEqual(parse_time_str("01:20:30"), 4830)

        self.assertEqual(parse_time_str("abc"), 0)
        self.assertEqual(parse_time_str(""), 0)

    def test_parse_timestamp_url_numeric(self):
        self.assertEqual(parse_timestamp("https://www.youtube.com/watch?v=xyz?t=90"), 90)
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=120"), 120)
        self.assertEqual(parse_timestamp("https://youtu.be/xyz&start=75"), 75)

    def test_parse_timestamp_url_compound(self):
        """Any combination of h/m/s suffixes is accepted; `s` is no longer mandatory."""
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=1h20m30s"), 4830)
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=2m15s"), 135)
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=45s"), 45)
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=1h5s"), 3605)
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=2h5m"), 7500)

    def test_parse_timestamp_url_hours_only(self):
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=2h"), 7200)

    def test_parse_timestamp_url_minutes_only(self):
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=30m"), 1800)

    def test_parse_timestamp_compound_with_hours_only_units(self):
        """Reaffirms that mixed-unit timestamps work as long as any suffix is present."""
        self.assertEqual(parse_timestamp("https://youtu.be/xyz?t=2h0m30s"), 7230)

    def test_parse_timestamp_args_list(self):
        self.assertEqual(parse_timestamp(("https://youtu.be/xyz?t=50s", "extra", "text")), 50)
        self.assertEqual(parse_timestamp(["https://www.youtube.com/watch?v=abc&t=60"]), 60)

    def test_parse_timestamp_no_timestamp(self):
        self.assertEqual(parse_timestamp("https://www.youtube.com/watch?v=abc"), 0)
        self.assertEqual(parse_timestamp(["just", "a", "search", "query"]), 0)


if __name__ == '__main__':
    unittest.main()