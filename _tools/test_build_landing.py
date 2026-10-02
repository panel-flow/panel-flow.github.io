"""Tests for build-landing.py: the three landing pages built from _src/. They run on a copy of the real sources and images.
Run: python3 -m unittest discover -s _tools -p "test_*.py" -q"""
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
SPEC = importlib.util.spec_from_file_location("build_landing", TOOLS / "build-landing.py")
bl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bl)


def copy_site(dest):
    shutil.copytree(REPO / "_src", dest / "_src")
    shutil.copytree(REPO / "img", dest / "img")


class BuildCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        copy_site(self.root)

    def content(self, tag, **override):
        path = self.root / "_src" / "content" / f"{tag}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(override)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def facts(self, **override):
        path = self.root / "_src" / "facts.json"
        data = json.loads(path.read_text())
        data.update(override)
        path.write_text(json.dumps(data))

    def pages(self):
        return bl.build(self.root)


class OutputTests(BuildCase):
    def test_three_pages_are_built_with_their_own_language(self):
        pages = self.pages()
        self.assertEqual(sorted(pages), ["index-es-MX.html", "index-pt-BR.html", "index.html"])
        self.assertIn('<html lang="en-US">', pages["index.html"])
        self.assertIn('<html lang="pt-BR">', pages["index-pt-BR.html"])
        self.assertIn('<html lang="es-MX">', pages["index-es-MX.html"])
        self.assertIn("Read comics", pages["index.html"])
        self.assertIn("Leia quadrinhos", pages["index-pt-BR.html"])
        self.assertIn("Lee cómics", pages["index-es-MX.html"])

    def test_the_build_is_deterministic_and_the_committed_pages_are_up_to_date(self):
        self.assertEqual(self.pages(), self.pages())
        for name, text in bl.build(REPO).items():
            self.assertEqual((REPO / name).read_text(encoding="utf-8"), text, name)

    def test_the_url_contract_of_the_root_and_the_alternates(self):
        pages = self.pages()
        root = pages["index.html"]
        self.assertIn('<link rel="canonical" href="https://panel-flow.github.io/">', root)
        for page in pages.values():
            self.assertIn('hreflang="en-US" href="https://panel-flow.github.io/"', page)
            self.assertIn('hreflang="x-default" href="https://panel-flow.github.io/"', page)
            self.assertIn('hreflang="pt-BR" href="https://panel-flow.github.io/index-pt-BR.html"', page)
            self.assertIn('hreflang="es-MX" href="https://panel-flow.github.io/index-es-MX.html"', page)
        self.assertIn('<link rel="canonical" href="https://panel-flow.github.io/index-pt-BR.html">', pages["index-pt-BR.html"])
        self.assertIn('<meta property="og:locale" content="es_MX">', pages["index-es-MX.html"])
        self.assertIn('<meta property="og:locale:alternate" content="pt_BR">', pages["index-es-MX.html"])
        self.assertNotIn('<meta property="og:locale:alternate" content="es_MX">', pages["index-es-MX.html"])

    def test_the_switcher_marks_only_the_current_page_and_never_redirects(self):
        pages = self.pages()
        for name, tag in (("index.html", "en-US"), ("index-pt-BR.html", "pt-BR"), ("index-es-MX.html", "es-MX")):
            page = pages[name]
            self.assertEqual(page.count('aria-current="page"'), 1)
            self.assertIn(f'class="lang-btn active" href="{bl.PAGES[tag]["href"]}" hreflang="{tag}" lang="{tag}" aria-current="page"', page)
            self.assertNotIn("navigator.language", page)
            self.assertNotIn("location.replace", page)
            self.assertNotIn("location.href", page)

    def test_the_legal_links_follow_the_language_of_the_page(self):
        pages = self.pages()
        for name, suffix in (("index.html", "en"), ("index-pt-BR.html", "pt-BR"), ("index-es-MX.html", "es-MX")):
            for group in ("privacy-policy", "terms", "support"):
                self.assertIn(f'href="{group}-{suffix}.html"', pages[name])

    def test_only_the_main_navigation_is_a_nav_element(self):
        for name, page in self.pages().items():
            self.assertEqual(page.count("<nav"), 1, name)  # the CSS fixes every <nav> to the top of the window
            self.assertIn('<div role="navigation" aria-label="Legal"', page)

    def test_images_are_static_with_alt_and_size(self):
        page = self.pages()["index-pt-BR.html"]
        self.assertIn('src="img/screenshot_1-ptbr.webp" width="640" height="1384" alt="Panel Flow mostrando uma página de quadrinhos"', page)
        self.assertNotIn("<video", page)
        self.assertNotIn("mp4", page)
        self.assertIn('fetchpriority="high"', page)

    def test_the_text_comes_escaped_and_the_facts_flow_in(self):
        page = self.pages()["index.html"]
        amp = [v for v in json.loads((self.root / "_src/content/en-US.json").read_text()).values() if isinstance(v, str) and "&" in v][0]
        self.assertIn(amp.replace("&", "&amp;"), page)  # an ampersand in a text is escaped
        self.assertIn("iOS 26+", page)
        self.assertIn("&copy; 2026 Panel Flow.", page)
        self.facts(min_ios="27", year="2027")
        page = self.pages()["index.html"]
        self.assertIn("iOS 27+", page)
        self.assertNotIn("iOS 26+", page)
        self.assertIn("&copy; 2027 Panel Flow.", page)

    def test_the_numbers_of_the_stats_bar_come_from_the_content_not_the_template(self):
        template = (self.root / "_src" / "landing.html").read_text(encoding="utf-8")
        self.assertNotRegex(template, r'stat-number gradient-text">[^{]')  # no literal number in the template
        page = self.pages()["index.html"]
        for n, value in ((1, "6+"), (2, "3"), (3, "2"), (4, "100%")):
            self.assertIn(f'<div class="stat-number gradient-text">{value}</div>', page)
        self.content("pt-BR", stat4_value="98 %")
        self.assertIn('<div class="stat-number gradient-text">98 %</div>', self.pages()["index-pt-BR.html"])
        self.assertIn('<div class="stat-number gradient-text">100%</div>', self.pages()["index.html"])  # per language

    def test_a_stat_number_missing_in_one_language_is_named(self):
        path = self.root / "_src" / "content" / "es-MX.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["stat2_value"]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("es-MX: missing the key 'stat2_value'", str(ctx.exception))

    def art(self, tags=("en-US", "pt-BR", "es-MX"), name="release/art-hero.webp", key="art_hero"):
        (self.root / "img" / "release").mkdir(exist_ok=True)
        shutil.copyfile(self.root / "img" / "poster_guided.webp", self.root / "img" / name)
        for tag in tags:
            path = self.root / "_src" / "content" / f"{tag}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["images"] = {**data["images"], key: name}
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        bl.write_assets(self.root)

    def test_a_page_without_art_has_no_art_attribute_and_the_css_rule_is_inert(self):
        for page in self.pages().values():
            self.assertNotIn("data-art", page.replace(".hero[data-art]", "").replace(".cta-section[data-art]", ""))
            self.assertIn('<section class="hero">', page)
            self.assertIn('<section class="section cta-section">', page)

    def test_art_puts_a_background_behind_its_section_only(self):
        self.art()
        page = self.pages()["index.html"]
        self.assertIn('<section class="hero" data-art style="--art:url(img/release/art-hero.webp)">', page)
        self.assertIn('<section class="section cta-section">', page)  # no art_cta: that section is as before
        self.assertIn("rgba(10,10,12,0.82)", page)  # the dark overlay the text contrast relies on
        self.assertNotIn("<img src=\"img/release/art-hero", page)  # decorative: a CSS background, not an <img> without alt

    def test_the_art_file_is_in_the_asset_manifest(self):
        self.art()
        self.assertIn("release/art-hero.webp", json.loads((self.root / "_src" / "assets.json").read_text()))

    def test_art_must_be_in_every_language_or_none(self):
        self.art(tags=("en-US",))
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("the art slots differ between the languages", str(ctx.exception))

    def test_an_unknown_image_key_is_refused(self):
        self.art(key="art_footer")
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("'art_footer' is not an image slot or an art slot", str(ctx.exception))

    def test_an_art_name_cannot_break_out_of_the_attribute_or_the_folder(self):
        self.art()
        for bad in ('x".webp', "../_src/facts.json", "release/a b.webp", "x.webp);color:red", "a/../b.webp"):
            for tag in ("en-US", "pt-BR", "es-MX"):
                path = self.root / "_src" / "content" / f"{tag}.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                data["images"]["art_hero"] = bad
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(bl.BuildError) as ctx:
                self.pages()
            self.assertIn("is not a plain image path", str(ctx.exception), bad)

    def test_art_that_is_missing_or_not_in_the_manifest_is_named(self):
        self.art()
        (self.root / "img" / "release" / "art-hero.webp").unlink()
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("img/release/art-hero.webp does not exist", str(ctx.exception))
        self.art()
        path = self.root / "_src" / "assets.json"
        sizes = json.loads(path.read_text())
        del sizes["release/art-hero.webp"]  # every other image is still listed: only the art is missing
        path.write_text(json.dumps(sizes))
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("art_hero: img/release/art-hero.webp is not in _src/assets.json", str(ctx.exception))

    def test_quotes_in_a_text_cannot_break_an_attribute(self):
        self.content("en-US", meta_description='A "quoted" <b>description</b> & more')
        page = self.pages()["index.html"]
        self.assertIn('content="A &quot;quoted&quot; &lt;b&gt;description&lt;/b&gt; &amp; more"', page)

    def test_the_structured_data_is_json_for_each_page(self):
        import re
        for name, tag in (("index.html", "en-US"), ("index-pt-BR.html", "pt-BR"), ("index-es-MX.html", "es-MX")):
            page = self.pages()[name]
            data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
            self.assertEqual((data["inLanguage"], data["url"]), (tag, bl.PAGES[tag]["url"]))
            self.assertEqual(data["downloadUrl"], "https://apps.apple.com/app/id6755895197")

    def test_a_closing_script_tag_in_a_text_cannot_end_the_structured_data(self):
        self.content("en-US", meta_description="</script><script>alert(1)</script>")
        page = self.pages()["index.html"]
        ld = page.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0]
        self.assertIn("<\\/script>", ld)


class SourceProblemTests(BuildCase):
    def test_a_key_missing_in_one_language_is_named(self):
        path = self.root / "_src" / "content" / "pt-BR.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["hero_desc"]
        path.write_text(json.dumps(data, ensure_ascii=False))
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("pt-BR: missing the key 'hero_desc'", str(ctx.exception))

    def test_an_extra_key_an_empty_text_and_a_missing_slot_are_named(self):
        self.content("es-MX", surprise="x", hero_cta=" ")
        path = self.root / "_src" / "content" / "es-MX.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["images"]["hero"]
        path.write_text(json.dumps(data, ensure_ascii=False))
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        message = str(ctx.exception)
        self.assertIn("has the key 'surprise'", message)
        self.assertIn("'hero_cta' is empty", message)
        self.assertIn("the slot 'hero' has no image", message)

    def test_an_unknown_fact_and_a_missing_fact_are_errors(self):
        self.content("en-US", cta_desc="iOS {nope}+")
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("unknown fact {nope}", str(ctx.exception))
        self.content("en-US", cta_desc="iOS {min_ios}+")
        (self.root / "_src" / "facts.json").write_text('{"min_ios": "26"}')
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("no 'year'", str(ctx.exception))

    def test_an_image_that_is_missing_or_not_in_the_manifest_is_an_error(self):
        (self.root / "img" / "screenshot_2-en.webp").unlink()
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("img/screenshot_2-en.webp does not exist", str(ctx.exception))
        shutil.copyfile(REPO / "img" / "screenshot_2-en.webp", self.root / "img" / "screenshot_2-en.webp")
        assets = json.loads((self.root / "_src" / "assets.json").read_text())
        del assets["screenshot_2-en.webp"]
        (self.root / "_src" / "assets.json").write_text(json.dumps(assets))
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("is not in _src/assets.json", str(ctx.exception))

    def test_a_placeholder_the_content_does_not_have_is_an_error(self):
        path = self.root / "_src" / "landing.html"
        path.write_text(path.read_text(encoding="utf-8").replace("{{hero_cta}}", "{{no_such_key}}", 1), encoding="utf-8")
        with self.assertRaises(bl.BuildError) as ctx:
            self.pages()
        self.assertIn("'no_such_key'", str(ctx.exception))


class CheckTests(BuildCase):
    def write_pages(self):
        for name, text in self.pages().items():
            (self.root / name).write_text(text, encoding="utf-8")

    def test_fresh_pages_pass_and_a_hand_edit_or_a_missing_page_does_not(self):
        self.write_pages()
        self.assertEqual(bl.check(self.root), [])
        page = self.root / "index-pt-BR.html"
        page.write_text(page.read_text(encoding="utf-8").replace("Leia quadrinhos", "Leia gibis"), encoding="utf-8")
        self.assertTrue(any("index-pt-BR.html: differs from what _src/ builds" in p for p in bl.check(self.root)))
        page.unlink()
        self.assertTrue(any("index-pt-BR.html: missing" in p for p in bl.check(self.root)))

    def test_a_source_edit_without_a_rebuild_is_stale(self):
        self.write_pages()
        self.content("en-US", hero_cta="Get it now")
        self.assertTrue(any("index.html: differs" in p for p in bl.check(self.root)))

    def test_a_wrong_size_in_the_manifest_is_named(self):
        self.write_pages()
        assets = json.loads((self.root / "_src" / "assets.json").read_text())
        assets["screenshot_1-en.webp"] = [1, 1]
        (self.root / "_src" / "assets.json").write_text(json.dumps(assets))
        self.assertTrue(any("assets.json has [1, 1] for img/screenshot_1-en.webp" in p for p in bl.check(self.root)))

    def test_a_source_that_cannot_be_built_is_reported_not_raised(self):
        self.write_pages()
        (self.root / "_src" / "facts.json").write_text("{}")
        self.assertTrue(any(p.startswith("the landing cannot be built") for p in bl.check(self.root)))

    def test_the_assets_manifest_is_rewritten_from_the_real_images(self):
        (self.root / "_src" / "assets.json").write_text("{}")
        sizes = bl.write_assets(self.root)
        self.assertEqual(sizes["screenshot_1-en.webp"], [640, 1384])
        self.assertEqual(json.loads((self.root / "_src" / "assets.json").read_text()), sizes)


class ImageSizeTests(unittest.TestCase):
    def write(self, data):
        f = tempfile.NamedTemporaryFile(delete=False)
        self.addCleanup(lambda: Path(f.name).unlink())
        f.write(data)
        f.close()
        return f.name

    def test_png(self):
        data = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1200, 630)
        self.assertEqual(bl.image_size(self.write(data)), (1200, 630))

    def test_webp_lossy_lossless_and_extended(self):
        lossy = b"RIFF" + bytes(4) + b"WEBPVP8 " + bytes(4) + bytes(3) + b"\x9d\x01\x2a" + struct.pack("<HH", 640, 1384)
        self.assertEqual(bl.image_size(self.write(lossy)), (640, 1384))
        w, h = 600 - 1, 1300 - 1
        bits = w | (h << 14)
        lossless = b"RIFF" + bytes(4) + b"WEBPVP8L" + bytes(4) + b"\x2f" + struct.pack("<I", bits)
        self.assertEqual(bl.image_size(self.write(lossless)), (600, 1300))
        ext = b"RIFF" + bytes(4) + b"WEBPVP8X" + bytes(4) + bytes(4) + (300 - 1).to_bytes(3, "little") + (500 - 1).to_bytes(3, "little")
        self.assertEqual(bl.image_size(self.write(ext)), (300, 500))

    def test_anything_else_is_an_error(self):
        with self.assertRaises(bl.BuildError):
            bl.image_size(self.write(b"GIF89a" + bytes(40)))


class CommandLineTests(BuildCase):
    def run_tool(self, *args):
        # run the real script against a copy: it works on its own folder, so the copy gets its own _tools
        shutil.copytree(TOOLS, self.root / "_tools", ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
        return subprocess.run([sys.executable, str(self.root / "_tools" / "build-landing.py"), *args], capture_output=True, text=True)

    def test_the_default_writes_the_pages_and_check_then_passes(self):
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "index-es-MX.html").is_file())
        self.assertEqual(self.run_tool("--check").returncode, 0)

    def test_check_fails_on_a_hand_edit(self):
        self.run_tool()
        page = self.root / "index.html"
        page.write_text(page.read_text(encoding="utf-8") + "<!-- by hand -->", encoding="utf-8")
        result = self.run_tool("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL index.html: differs", result.stdout)

    def test_assets_rewrites_the_manifest(self):
        result = self.run_tool("--assets")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("12 image(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
