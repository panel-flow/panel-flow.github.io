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
    for file in check_site.LANDING.values():
        if file != "index.html":
            (root / file).write_text(f'<html><head><link rel="canonical" href="{base}{file}"></head><body>l</body></html>', encoding="utf-8")
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
        return check_site.check_offline(self.root, BASE, landing=False)  # the synthetic site has no landing sources

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


class LandingCheckTests(unittest.TestCase):
    """check_offline with the landing checks, on a copy of the real site: it must pass, and each defect must be named."""

    def setUp(self):
        import shutil
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        repo = Path(__file__).resolve().parent.parent
        shutil.copytree(repo, self.root, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "_drafts"))
        self.base = check_site.DEFAULT_BASE

    def problems(self):
        return check_site.check_offline(self.root, self.base)

    def edit(self, name, old, new, count=1):
        path = self.root / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, count), encoding="utf-8")

    def has(self, fragment):
        problems = self.problems()
        self.assertTrue(any(fragment in p for p in problems), problems)

    def test_the_real_site_passes(self):
        self.assertEqual(self.problems(), [])

    GOOD_VIDEO = ('<video controls muted playsinline preload="none" poster="img/og-card.png" width="640" height="1390" aria-label="x">'
                  '<source src="video/release/demo.mp4" type="video/mp4"></video>')

    def with_video(self, video=None, files=True):
        (self.root / "video" / "release").mkdir(parents=True, exist_ok=True)
        if files:
            (self.root / "video" / "release" / "demo.mp4").write_bytes(b"mp4")
        self.edit("index.html", "<body>", "<body>" + (video or self.GOOD_VIDEO))

    def video_problems(self):
        return [p for p in self.problems() if "<video>" in p or "video" in p.lower() and "poster" in p or "the video" in p or "<source>" in p]

    def test_a_demo_video_as_the_builder_writes_it_passes(self):
        self.with_video()
        self.assertEqual(self.video_problems(), [])

    def test_a_video_must_be_silent_paused_preloaded_nothing_and_have_a_poster_and_a_name(self):
        for old, new, message in (
                ("controls ", "", "lacks controls"), ("muted ", "", "lacks muted"), ("playsinline ", "", "lacks playsinline"),
                ('preload="none"', 'preload="auto"', 'lacks preload="none"'), (" aria-label=\"x\"", "", "no aria-label"),
                (' width="640" height="1390"', "", "no width and height"), (' poster="img/og-card.png"', "", "has no poster"),
                ("controls ", "controls autoplay ", "has autoplay"), ("controls ", "controls loop ", "has loop")):
            self.setUp()
            self.with_video(self.GOOD_VIDEO.replace(old, new, 1))
            self.assertTrue(any(message in p for p in self.problems()), (message, self.problems()))

    def test_a_video_whose_files_do_not_exist_is_named(self):
        self.with_video(self.GOOD_VIDEO.replace("img/og-card.png", "img/nope.png"))
        self.has("the poster img/nope.png does not exist")
        self.setUp()
        self.with_video(files=False)
        self.has("the video video/release/demo.mp4 does not exist")

    def test_the_source_must_be_one_mp4_under_video(self):
        self.with_video(self.GOOD_VIDEO.replace("video/release/demo.mp4", "elsewhere/demo.mp4"))
        self.has("a <source> must be an mp4 under video/")
        self.setUp()
        self.with_video(self.GOOD_VIDEO.replace("</video>", '<source src="video/release/demo.mp4" type="video/mp4"></video>'))
        self.has("needs exactly one <source>")

    def test_at_most_two_videos_a_page(self):
        self.with_video(self.GOOD_VIDEO * 3)
        self.has("3 <video> elements on the page")

    def test_art_behind_a_section_must_exist(self):
        self.edit("index.html", '<section class="hero">', '<section class="hero" data-art style="--art:url(img/release/missing.webp)">')
        self.has("index.html: url(img/release/missing.webp) points to a file that does not exist")
        self.edit("index.html", "url(img/release/missing.webp)", "url(img/og-card.png)")  # a file that is there
        self.assertFalse([p for p in self.problems() if "points to a file that does not exist" in p])

    def test_a_remote_or_data_url_in_the_css_is_not_checked_as_a_local_file(self):
        self.edit("index.html", "</body>", '<p style="background:url(https://example.com/x.png)"></p><p style="background:url(data:image/png;base64,AAAA)"></p></body>')
        self.assertFalse([p for p in self.problems() if "points to a file that does not exist" in p])

    def test_the_landing_pages_are_checked_against_the_build(self):
        self.edit("index.html", "</body>", "<!-- by hand --></body>")
        self.has("index.html: differs from what _src/ builds")

    def test_each_page_defect_is_named(self):
        # the page is edited by hand, so the build check also fires; each message must still be there
        cases = [
            ("index-pt-BR.html", '<html lang="pt-BR"', '<html lang="en"', "html lang should be pt-BR"),
            ("index-pt-BR.html", '<link rel="canonical" href="https://panel-flow.github.io/index-pt-BR.html">',
             '<link rel="canonical" href="https://panel-flow.github.io/">', "canonical link should be"),
            ("index.html", 'hreflang="x-default" href="https://panel-flow.github.io/"', 'hreflang="x-default" href="https://panel-flow.github.io/index.html"',
             "hreflang x-default is missing or wrong"),
            ("index-es-MX.html", 'hreflang="pt-BR" href="https://panel-flow.github.io/index-pt-BR.html"', 'hreflang="pt-BR" href="x"',
             "hreflang pt-BR is missing or wrong"),
            ("index.html", "<h1 ", "<h1 ></h1><h1 ", "exactly one h1"),
            ("index.html", "<body>", '<body><p data-i18n="x">x</p>', "leftover client-side translation"),
            ("index.html", "<body>", "<body><video></video>", "a <video> lacks controls"),
            ("index.html", "<body>", '<body><nav aria-label="Legal"></nav>', "exactly one <nav> element"),
            ("index.html", "<body>", '<body><img src="img/og-card.png" width="1" height="1">', "an <img> has no alt text"),
            ("index.html", "<body>", '<body><img src="img/og-card.png" alt="x">', "has no width and height"),
            ("index.html", '<meta property="og:url" content="https://panel-flow.github.io/">', "", "og:url should be"),
            ("index.html", '"inLanguage": "en-US"', '"inLanguage": "pt-BR"', "structured data inLanguage should be en-US"),
            ("index.html", '"url": "https://panel-flow.github.io/"', '"url": "https://x/"', "structured data url should be"),
            ("index.html", "https://apps.apple.com/app/id6755895197", "https://example.com/", "the App Store link is missing", 99),
            ("index.html", "<title>", "<tit>", "no <title>"),
        ]
        for name, old, new, message, *count in cases:
            with self.subTest(message=message):
                backup = (self.root / name).read_text(encoding="utf-8")
                self.edit(name, old, new, *(count or [1]))
                self.has(message)
                (self.root / name).write_text(backup, encoding="utf-8")

    def test_a_missing_landing_page_is_named(self):
        (self.root / "index-es-MX.html").unlink()
        self.has("index-es-MX.html: missing")

    def test_the_sitemap_must_list_each_landing_page_with_its_alternates(self):
        self.edit("sitemap.xml", "<loc>https://panel-flow.github.io/index-pt-BR.html</loc>", "<loc>https://panel-flow.github.io/index-pt-BR.htm</loc>")
        self.has("does not list the landing page https://panel-flow.github.io/index-pt-BR.html")
        self.edit("sitemap.xml", "<loc>https://panel-flow.github.io/index-pt-BR.htm</loc>", "<loc>https://panel-flow.github.io/index-pt-BR.html</loc>")
        self.edit("sitemap.xml", '<xhtml:link rel="alternate" hreflang="es-MX" href="https://panel-flow.github.io/index-es-MX.html"/>', "", count=1)
        self.has("lacks the alternate es-MX")

    def test_the_sitemap_entry_needs_x_default(self):
        self.edit("sitemap.xml", '<xhtml:link rel="alternate" hreflang="x-default" href="https://panel-flow.github.io/"/>', "", count=1)
        self.has("lacks x-default")

    def test_the_landing_is_still_checked_by_the_generic_rules(self):
        self.edit("index.html", "</body>", '<a href="https://sciasxp.github.io/x">old</a></body>')
        self.has("index.html: still references the old address")


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

    def test_the_landing_pages_must_be_served_with_their_own_canonical(self):
        (self.root / "index-pt-BR.html").unlink()
        self.assertTrue(any("index-pt-BR.html" in p and "404" in p for p in check_site.check_live(self.base)))
        (self.root / "index-pt-BR.html").write_text(f'<html><head><link rel="canonical" href="{self.base}">x</head></html>', encoding="utf-8")
        self.assertTrue(any("index-pt-BR.html: the served page has a different canonical link" in p for p in check_site.check_live(self.base)))
        (self.root / "index.html").write_text('<html><head><link rel="canonical" href="https://x/"></head></html>', encoding="utf-8")
        self.assertIn(f"{self.base}: the served page has a different canonical link", check_site.check_live(self.base))

    def test_a_served_support_page_without_the_email_is_reported(self):
        path = self.root / "support-en.html"
        path.write_text(path.read_text(encoding="utf-8").replace(f"mailto:{check_site.EMAIL}", "mailto:x@y.z"), encoding="utf-8")
        self.assertTrue(any("contact email is missing" in p for p in check_site.check_live(self.base)))


if __name__ == "__main__":
    unittest.main()
