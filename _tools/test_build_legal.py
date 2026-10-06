"""Tests for build-legal.py: the nine legal pages built from _src/legal.json. They run on a copy of the real sources.
Run: python3 -m unittest discover -s _tools -p "test_*.py" -q"""
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
SPEC = importlib.util.spec_from_file_location("build_legal", TOOLS / "build-legal.py")
bl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bl)
NINE = sorted(f"{p}-{s}.html" for p in ("privacy-policy", "terms", "support") for s in ("en", "es-MX", "pt-BR"))


class LegalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "_src").mkdir()
        for name in ("legal.json", "legal.html"):
            shutil.copyfile(REPO / "_src" / name, self.root / "_src" / name)
        self.doc = json.loads((REPO / "_src" / "legal.json").read_text(encoding="utf-8"))

    def write(self, doc):
        (self.root / "_src" / "legal.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def problems(self, doc):
        return bl.validate(doc)

    def has(self, doc, fragment):
        problems = self.problems(doc)
        self.assertTrue(any(fragment in p for p in problems), problems)

    def test_the_pages_on_disk_are_what_the_sources_build(self):
        self.assertEqual(bl.check(REPO), [])

    def test_the_nine_file_names_are_the_apps_contract(self):
        self.assertEqual(sorted(bl.build(self.root)), NINE)

    def test_the_build_is_deterministic(self):
        self.assertEqual(bl.build(self.root), bl.build(self.root))

    def test_the_date_is_one_per_page_and_written_in_each_language(self):
        self.doc["effective"]["terms"] = "2027-03-05"
        self.write(self.doc)
        pages = bl.build(self.root)
        self.assertIn('<time class="effective" datetime="2027-03-05">Effective March 5, 2027</time>', pages["terms-en.html"])
        self.assertIn(">Vigente desde 5 de marzo de 2027</time>", pages["terms-es-MX.html"])
        self.assertIn(">Em vigor desde 5 de março de 2027</time>", pages["terms-pt-BR.html"])
        self.assertNotIn('class="effective"', pages["support-en.html"])

    def test_a_text_change_reaches_only_its_page(self):
        before = bl.build(self.root)
        self.doc["locales"]["pt-BR"]["pages"]["support"]["intro"] = "Outra frase."
        self.write(self.doc)
        after = bl.build(self.root)
        self.assertEqual([n for n in NINE if before[n] != after[n]], ["support-pt-BR.html"])
        self.assertIn('<p class="intro">Outra frase.</p>', after["support-pt-BR.html"])

    def test_text_is_escaped_and_the_footer_names_each_page_by_its_title(self):
        self.doc["locales"]["en-US"]["pages"]["terms"]["description"] = 'Say "hi" & <go>'
        self.write(self.doc)
        page = bl.build(self.root)["terms-en.html"]
        self.assertIn('content="Say &quot;hi&quot; &amp; &lt;go&gt;"', page)
        self.assertIn('<a href="privacy-policy-en.html">Privacy Policy</a><a href="terms-en.html">Terms of Use</a>', page)

    def test_check_names_a_hand_edit_and_a_missing_page(self):
        for name, text in bl.build(self.root).items():
            (self.root / name).write_text(text, encoding="utf-8")
        self.assertEqual(bl.check(self.root), [])
        (self.root / "terms-en.html").write_text("edited by hand", encoding="utf-8")
        (self.root / "support-es-MX.html").unlink()
        problems = bl.check(self.root)
        self.assertTrue(any(p.startswith("terms-en.html: differs") for p in problems), problems)
        self.assertTrue(any(p.startswith("support-es-MX.html: missing") for p in problems), problems)

    def test_the_command_line(self):
        out = subprocess.run([sys.executable, str(TOOLS / "build-legal.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(subprocess.run([sys.executable, str(TOOLS / "build-legal.py"), "--nope"], capture_output=True).returncode, 2)

    # --- what the sources may say ---

    def test_the_real_sources_are_valid(self):
        self.assertEqual(self.problems(self.doc), [])

    def test_the_locales_and_pages_are_exactly_the_contracts(self):
        doc = copy.deepcopy(self.doc)
        del doc["locales"]["es-MX"]
        self.has(doc, "locales must be exactly")
        doc = copy.deepcopy(self.doc)
        doc["locales"]["en-US"]["pages"]["cookies"] = doc["locales"]["en-US"]["pages"]["support"]
        self.has(doc, "en-US.pages must be exactly")

    def test_the_effective_dates(self):
        doc = copy.deepcopy(self.doc)
        doc["effective"]["terms"] = "1 October 2026"
        self.has(doc, "effective.terms must be a date")
        doc = copy.deepcopy(self.doc)
        doc["locales"]["es-MX"]["pages"]["privacy-policy"]["effective"] = "Vigente"
        self.has(doc, "es-MX.privacy-policy.effective must hold {date} once")
        doc = copy.deepcopy(self.doc)
        doc["locales"]["en-US"]["pages"]["support"]["effective"] = "Effective {date}"
        self.has(doc, "en-US.support must have exactly")

    def test_the_sections_match_across_languages(self):
        doc = copy.deepcopy(self.doc)
        doc["locales"]["pt-BR"]["pages"]["terms"]["sections"].pop()
        self.has(doc, "pt-BR.terms: the sections are not the ones of en-US")
        doc = copy.deepcopy(self.doc)
        sections = doc["locales"]["en-US"]["pages"]["support"]["sections"]
        sections[1]["id"] = sections[0]["id"]
        self.has(doc, "two sections share an id")

    def test_the_body_of_a_section_is_a_small_subset_of_html(self):
        cases = {
            '<p>x</p><script>alert(1)</script>': "<script> is not allowed",
            '<p onclick="x()">x</p>': "attributes other than href",
            '<p><a href="http://example.com">x</a></p>': "is not one of the pages",
            '<p><a href="cookies-en.html">x</a></p>': "is not one of the pages",
            '<p><a href="mailto:someone@else.com">x</a></p>': "is not one of the pages",
            '<p>x': "unclosed <p>",
            '<p>x</ul>': "does not close",
            '<p>[[EMAIL]]</p>': "leftover placeholder",
        }
        for body, fragment in cases.items():
            with self.subTest(body=body):
                doc = copy.deepcopy(self.doc)
                doc["locales"]["en-US"]["pages"]["terms"]["sections"][0]["html"] = body
                self.has(doc, fragment)
        doc = copy.deepcopy(self.doc)
        doc["locales"]["en-US"]["pages"]["terms"]["sections"][0]["html"] = (
            '<p><strong>a</strong><br><em>b</em> <a href="support-en.html">s</a> <a href="https://www.apple.com/legal/">l</a></p>'
            '<ul><li><a href="mailto:sciasxp@gmail.com">m</a></li></ul>')
        self.assertEqual(self.problems(doc), [])

    def test_a_broken_source_refuses_the_build(self):
        self.doc["contact"] = "nobody"
        self.write(self.doc)
        with self.assertRaises(bl.BuildError):
            bl.build(self.root)
        self.assertTrue(bl.check(self.root)[0].startswith("the legal pages cannot be built"))


if __name__ == "__main__":
    unittest.main()
