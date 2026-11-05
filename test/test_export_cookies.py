import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'export-cookies.py'


class FakeCookie:
    def __init__(self, domain, name='SID', value='abc', path='/', secure=True, expires=1700000000):
        self.domain = domain
        self.name = name
        self.value = value
        self.path = path
        self.secure = secure
        self.expires = expires


def load_script(cookies):
    """Load export-cookies.py with a fake browser_cookie3 module."""
    fake = types.ModuleType('browser_cookie3')
    fake.BrowserCookieError = type('BrowserCookieError', (Exception,), {})
    fake.firefox = lambda **kwargs: cookies
    with patch.dict(sys.modules, {'browser_cookie3': fake}):
        spec = importlib.util.spec_from_file_location('export_cookies', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class TestExportCookies(unittest.TestCase):
    def test_writes_netscape_columns(self):
        module = load_script([FakeCookie('.youtube.com')])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cookies.txt'
            self.assertEqual(module.export_cookies(out), 1)
            lines = [line for line in out.read_text().splitlines() if not line.startswith('#')]

        # domain, include-subdomains, path, secure, expires, name, value
        self.assertEqual(lines, ['.youtube.com\tTRUE\t/\tTRUE\t1700000000\tSID\tabc'])

    def test_host_only_cookie_is_not_marked_for_subdomains(self):
        module = load_script([FakeCookie('www.youtube.com')])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cookies.txt'
            module.export_cookies(out)
            line = [l for l in out.read_text().splitlines() if not l.startswith('#')][0]

        self.assertEqual(line.split('\t')[1], 'FALSE')

    def test_filters_lookalike_domains(self):
        module = load_script([FakeCookie('.youtube.com'), FakeCookie('notyoutube.com')])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cookies.txt'
            self.assertEqual(module.export_cookies(out), 1)
            lines = [l for l in out.read_text().splitlines() if not l.startswith('#')]

        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('.youtube.com\t'))

    def test_no_cookies_writes_nothing(self):
        module = load_script([])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cookies.txt'
            self.assertEqual(module.export_cookies(out), 0)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
