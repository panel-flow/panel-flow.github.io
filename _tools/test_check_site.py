"""Tests for check-site.py, using a minimal valid site built in a temporary folder.
Run: python3 -m unittest discover -s _tools -p "test_*.py" -q"""
import functools
import http.server
import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("check_site", Path(__file__).resolve().parent / "check-site.py")
check_site = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_site)

BASE = "http://127.0.0.1:1/"  # offline tests never fetch it


def page_html(base, group, key, body=""):
    links = "".join(f'<link rel="alternate" hreflang="{h}" href="{base}{group}-{k}.html">'
                    for k, h in check_site.LOCALES.items())
    links += f'<link rel="alternate" hreflang="x-default" href="{base}{group}-en.html">'
    return (f'<!doctype html><html lang="{check_site.LOCALES[key]}"><head><title>T</title>'
            f'<link rel="canonical" href="{base}{group}-{key}.html">{links}'
            '<meta property="og:title" content="T"><meta property="og:description" content="D">'
            f'<meta property="og:url" content="{base}{group}-{key}.html"><meta property="og:image" content="{base}img/o.png">'
            f'</head><body>{body}</body></html>')


def build_site(root, base=BASE):
    for group in check_site.GROUPS:
        for key in check_site.LOCALES:
            body = f'<a href="mailto:{check_site.EMAIL}">mail</a>' if group == "support" else ""
            (root / f"{group}-{key}.html").write_text(page_html(base, group, key, body), encoding="utf-8")
    (root / "index.html").write_text(
        f'<html><head><link rel="canonical" href="{base}"><script type="application/ld+json">{{}}</script></head>'
        '<body><a href="privacy-policy-en.html">p</a></body></html>', encoding="utf-8")
    entries = "".join(f"<url><loc>{base}{p}</loc></url>" for p in check_site.PAGES)
    (root / "sitemap.xml").write_text(f"<urlset>{entries}</urlset>", encoding="utf-8")
    (root / "robots.txt").write_text(f"User-agent: *\nSitemap: {base}sitemap.xml\n", encoding="utf-8")


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        build_site(self.root)

    def problems(self):
        return check_site.check_offline(self.root, BASE)

    def edit(self, name, old, new):
        path = self.root / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_a_complete_site_passes(self):
        self.assertEqual(self.problems(), [])

    def test_a_missing_page_is_reported(self):
        (self.root / "terms-pt-BR.html").unlink()
        self.assertTrue(any("terms-pt-BR.html: missing" in p for p in self.problems()))

    def test_leftover_placeholders_are_reported(self):
        self.edit("terms-en.html", "<body>", "<body>Effective [[EFFECTIVE_DATE]]")
        self.assertTrue(any("[[EFFECTIVE_DATE]]" in p for p in self.problems()))

    def test_the_old_address_is_reported(self):
        self.edit("privacy-policy-en.html", "<body>", '<body><a href="https://sciasxp.github.io/x/">x</a>')
        self.assertTrue(any("old address" in p for p in self.problems()))

    def test_a_wrong_canonical_is_reported(self):
        self.edit("support-en.html", f'rel="canonical" href="{BASE}support-en.html"', f'rel="canonical" href="{BASE}other.html"')
        self.assertTrue(any("canonical link should be" in p for p in self.problems()))

    def test_a_missing_hreflang_is_reported(self):
        self.edit("support-es-MX.html", f'<link rel="alternate" hreflang="x-default" href="{BASE}support-en.html">', "")
        self.assertTrue(any("x-default" in p for p in self.problems()))

    def test_a_wrong_html_lang_is_reported(self):
        self.edit("terms-es-MX.html", 'lang="es-MX"', 'lang="en-US"')
        self.assertTrue(any("html lang should be es-MX" in p for p in self.problems()))

    def test_support_pages_need_the_contact_email(self):
        self.edit("support-pt-BR.html", f"mailto:{check_site.EMAIL}", "mailto:someone@example.com")
        self.assertTrue(any("contact email" in p for p in self.problems()))

    def test_a_broken_local_link_is_reported(self):
        self.edit("index.html", 'href="privacy-policy-en.html"', 'href="gone.html"')
        self.assertTrue(any("gone.html" in p for p in self.problems()))

    def test_a_page_missing_from_the_sitemap_is_reported(self):
        self.edit("sitemap.xml", f"<url><loc>{BASE}terms-en.html</loc></url>", "")
        self.assertTrue(any("does not list terms-en.html" in p for p in self.problems()))

    def test_missing_open_graph_tags_are_reported(self):
        self.edit("support-en.html", '<meta property="og:image"', '<meta property="x:image"')
        self.assertTrue(any("og:image is missing" in p for p in self.problems()))


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        handler = functools.partial(Quiet, directory=str(self.root))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/"
        build_site(self.root, self.base)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_a_served_site_passes(self):
        self.assertEqual(check_site.check_live(self.base), [])

    def test_a_page_that_is_not_served_is_reported(self):
        (self.root / "support-en.html").unlink()
        self.assertTrue(any("support-en.html" in p and "404" in p for p in check_site.check_live(self.base)))

    def test_a_served_support_page_without_the_email_is_reported(self):
        path = self.root / "support-en.html"
        path.write_text(path.read_text(encoding="utf-8").replace(f"mailto:{check_site.EMAIL}", "mailto:x@y.z"), encoding="utf-8")
        self.assertTrue(any("contact email is missing" in p for p in check_site.check_live(self.base)))


if __name__ == "__main__":
    unittest.main()
