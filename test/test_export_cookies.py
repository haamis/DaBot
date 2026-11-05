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

    def test_filters_accumulated_st_cookies_but_keeps_login_cookies(self):
        cookies = [
            FakeCookie('.youtube.com', name=f'ST-{i}', value='x' * 3800)
            for i in range(59)
        ]
        cookies.extend([
            FakeCookie('.youtube.com', name='SID', value='login'),
            FakeCookie('.youtube.com', name='__Secure-3PAPISID', value='secure-login'),
            FakeCookie('www.youtube.com', name='ST-host', value='x' * 3800),
            FakeCookie('.youtube.com', name='PREF', value='preferences'),
        ])
        module = load_script(cookies)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cookies.txt'
            self.assertEqual(module.export_cookies(out), 3)
            lines = [l.split('\t') for l in out.read_text().splitlines()
                     if not l.startswith('#')]

        self.assertEqual([(l[5], l[6]) for l in lines], [
            ('SID', 'login'),
            ('__Secure-3PAPISID', 'secure-login'),
            ('PREF', 'preferences'),
        ])

    def test_only_st_cookies_preserves_existing_output(self):
        module = load_script([FakeCookie('.youtube.com', name='ST-only')])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cookies.txt'
            out.write_text('existing working cookies\n')
            self.assertEqual(module.export_cookies(out), 0)
            self.assertEqual(out.read_text(), 'existing working cookies\n')

    def test_only_st_cookies_does_not_create_output(self):
        module = load_script([FakeCookie('.youtube.com', name='ST-only')])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cookies.txt'
            self.assertEqual(module.export_cookies(out), 0)
            self.assertFalse(out.exists())

    def test_failed_replacement_preserves_output_and_cleans_temporary_file(self):
        module = load_script([FakeCookie('.youtube.com')])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cookies.txt'
            out.write_text('existing cookies\n')
            with patch.object(Path, 'replace', side_effect=PermissionError('locked')):
                self.assertEqual(module.export_cookies(out), 0)
            self.assertEqual(out.read_text(), 'existing cookies\n')
            self.assertEqual(list(Path(tmp).iterdir()), [out])


if __name__ == '__main__':
    unittest.main()
