import unittest

from music_bot import is_age_restricted_error


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


if __name__ == '__main__':
    unittest.main()
