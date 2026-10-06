#!/usr/bin/env python3
"""Build the nine legal pages of the Panel Flow site (privacy policy, terms of use and support, in three languages) from _src/.

    python3 _tools/build-legal.py            # write privacy-policy-<lang>.html, terms-<lang>.html and support-<lang>.html
    python3 _tools/build-legal.py --check    # exit 1 if a page on disk differs from what the sources produce

Sources:  _src/legal.html   the page, with {{placeholders}}
          _src/legal.json   the texts: {"contact": email, "effective": {page: "YYYY-MM-DD"},
                            "locales": {tag: {"home", "language", "footer", "contact", "og_image_alt",
                                              "pages": {page: {"title", "description", "eyebrow", "intro", "effective",
                                                               "sections": [{"id", "title", "html"}]}}}}}

The file names are the app's contract (Panel Flow/Utilities/LegalLink.swift): <page>-<lang>.html with lang en, es-MX or pt-BR.
A page's `effective` text holds {date}; the date itself is one per page, in `effective`, and is written out in each language,
so the three languages cannot disagree on it. A page without a date (support) has no `effective` in either place.
The body of a section is a small subset of HTML (p, ul, ol, li, strong, em, br, a href): a link goes to one of the nine pages,
to the landing, to the contact address or to an https address. In the app repository this file is marketing/web/site.json's
`legal`, written here by the release flow (/pf-release, site-build.py); the pages are generated: do not edit them by hand.
Standard library only. The output is deterministic.
"""
import datetime
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://panel-flow.github.io/"
PAGES = ("privacy-policy", "terms", "support")
DATED = ("privacy-policy", "terms")
# tag -> file suffix (LegalLink.swift), the name of the language in its own language, og:locale
LOCALES = {
    "en-US": {"suffix": "en", "name": "English", "og": "en_US"},
    "es-MX": {"suffix": "es-MX", "name": "Español", "og": "es_MX"},
    "pt-BR": {"suffix": "pt-BR", "name": "Português", "og": "pt_BR"},
}
CHROME = ("home", "language", "footer", "contact", "og_image_alt")
PAGE_KEYS = {"title", "description", "eyebrow", "intro", "effective", "sections"}
MONTHS = {
    "en-US": "January February March April May June July August September October November December".split(),
    "es-MX": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
    "pt-BR": "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro".split(),
}
ALLOWED_TAGS = {"p", "ul", "ol", "li", "strong", "em", "br", "a"}
SECTION_ID = re.compile(r"[a-z][a-z0-9-]{0,30}")
EMAIL = re.compile(r"[^@\s\"<>]+@[^@\s\"<>]+\.[a-z]{2,}")


class BuildError(ValueError):
    pass


def file_name(page, tag):
    return f"{page}-{LOCALES[tag]['suffix']}.html"


def long_date(iso, tag):
    day = datetime.date.fromisoformat(iso)
    month = MONTHS[tag][day.month - 1]
    return f"{month} {day.day}, {day.year}" if tag == "en-US" else f"{day.day} de {month} de {day.year}"


class Fragment(HTMLParser):
    """Collects what a section body uses that the pages do not allow."""

    def __init__(self, local, contact):
        super().__init__(convert_charrefs=True)
        self.local, self.contact, self.problems, self.open = local, contact, [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.problems.append(f"<{tag}> is not allowed")
            return
        attrs = dict(attrs)
        if set(attrs) - ({"href"} if tag == "a" else set()):
            self.problems.append(f"<{tag}> has attributes other than href on a link: {sorted(attrs)}")
        if tag == "a":
            href = attrs.get("href") or ""
            if not (href in self.local or href == f"mailto:{self.contact}" or href.startswith("https://")):
                self.problems.append(f"the link '{href}' is not one of the pages, the contact address or an https address")
        if tag != "br":
            self.open.append(tag)

    def handle_endtag(self, tag):
        if tag == "br":
            return
        if not self.open or self.open[-1] != tag:
            self.problems.append(f"</{tag}> does not close the open element")
            return
        self.open.pop()

    def close(self):
        super().close()
        if self.open:
            self.problems.append("unclosed " + ", ".join(f"<{t}>" for t in self.open))


def text_problems(where, value):
    if not isinstance(value, str) or not value.strip():
        return [f"{where} must be a non-empty string"]
    if re.search(r"\[\[|\{\{|}}", value):
        return [f"{where} has a leftover placeholder"]
    return []


def validate(doc):
    """A list of problems; an empty list means the pages can be built."""
    if not isinstance(doc, dict) or set(doc) != {"contact", "effective", "locales"}:
        return ["legal.json must be {\"contact\", \"effective\", \"locales\"}"]
    problems = []
    contact = doc["contact"]
    if not isinstance(contact, str) or not EMAIL.fullmatch(contact):
        problems.append("contact must be an email address")
    effective = doc["effective"]
    if not isinstance(effective, dict) or set(effective) != set(DATED):
        problems.append(f"effective must give the date of exactly {', '.join(DATED)}")
        effective = {}
    for page, value in effective.items():
        try:
            datetime.date.fromisoformat(value)
        except (TypeError, ValueError):
            problems.append(f"effective.{page} must be a date, YYYY-MM-DD")
    locales = doc["locales"]
    if not isinstance(locales, dict) or set(locales) != set(LOCALES):
        return problems + [f"locales must be exactly {', '.join(LOCALES)}"]
    local = {file_name(p, t) for p in PAGES for t in LOCALES} | {"index.html", "index-pt-BR.html", "index-es-MX.html", "./"}
    reference = {}
    for tag in LOCALES:
        loc = locales[tag]
        if not isinstance(loc, dict) or set(loc) != set(CHROME) | {"pages"}:
            problems.append(f"{tag}: must have exactly {', '.join(CHROME)} and pages")
            continue
        for key in CHROME:
            problems += text_problems(f"{tag}.{key}", loc[key])
        if not isinstance(loc["pages"], dict) or set(loc["pages"]) != set(PAGES):
            problems.append(f"{tag}.pages must be exactly {', '.join(PAGES)}")
            continue
        for page in PAGES:
            entry, where = loc["pages"][page], f"{tag}.{page}"
            if not isinstance(entry, dict):
                problems.append(f"{where} must be an object")
                continue
            wanted = PAGE_KEYS if page in DATED else PAGE_KEYS - {"effective"}
            if set(entry) != wanted:
                problems.append(f"{where} must have exactly {', '.join(sorted(wanted))}")
                continue
            for key in ("title", "description", "eyebrow", "intro"):
                problems += text_problems(f"{where}.{key}", entry[key])
            if page in DATED:
                problems += text_problems(f"{where}.effective", entry["effective"])
                if isinstance(entry["effective"], str) and entry["effective"].count("{date}") != 1:
                    problems.append(f"{where}.effective must hold {{date}} once (the date is effective.{page})")
            sections = entry["sections"]
            if not isinstance(sections, list) or not sections:
                problems.append(f"{where}.sections must be a non-empty list")
                continue
            ids = []
            for i, section in enumerate(sections):
                at = f"{where}.sections[{i}]"
                if not isinstance(section, dict) or set(section) != {"id", "title", "html"}:
                    problems.append(f"{at} must be {{\"id\", \"title\", \"html\"}}")
                    continue
                if not isinstance(section["id"], str) or not SECTION_ID.fullmatch(section["id"]):
                    problems.append(f"{at}.id must be a short lowercase id")
                ids.append(section["id"])
                problems += text_problems(f"{at}.title", section["title"])
                body_problems = text_problems(f"{at}.html", section["html"])
                if not body_problems:
                    parser = Fragment(local, contact)
                    parser.feed(section["html"])
                    parser.close()
                    body_problems = [f"{at}.html: {p}" for p in parser.problems]
                problems += body_problems
            if len(set(ids)) != len(ids):
                problems.append(f"{where}: two sections share an id")
            if page in reference and ids != reference[page]:
                problems.append(f"{where}: the sections are not the ones of en-US, in the same order ({', '.join(reference[page])})")
            reference.setdefault(page, ids)
    return problems


def attr(value):
    return html.escape(value, quote=True)


def text(value):
    return html.escape(value, quote=False)


def render(template, doc, page, tag):
    loc, entry = doc["locales"][tag], doc["locales"][tag]["pages"][page]
    url = BASE + file_name(page, tag)
    alternates = [f'  <link rel="alternate" hreflang="{t}" href="{BASE + file_name(page, t)}">' for t in LOCALES]
    alternates.append(f'  <link rel="alternate" hreflang="x-default" href="{BASE + file_name(page, "en-US")}">')
    og_alternates = [f'  <meta property="og:locale:alternate" content="{LOCALES[t]["og"]}">' for t in LOCALES if t != tag]
    effective = ""
    if page in DATED:
        iso = doc["effective"][page]
        effective = f'    <time class="effective" datetime="{iso}">{text(entry["effective"].replace("{date}", long_date(iso, tag)))}</time>\n'
    languages = "".join(
        f'<li><a href="{file_name(page, t)}" lang="{t}"' + (' aria-current="page"' if t == tag else "") + f'>{LOCALES[t]["name"]}</a></li>'
        for t in LOCALES)
    sections = "".join(
        f'<section class="section" aria-labelledby="{s["id"]}-heading"><h2 id="{s["id"]}-heading">{text(s["title"])}</h2>{s["html"]}</section>'
        for s in entry["sections"])
    footer_links = "".join(f'<a href="{file_name(p, tag)}">{text(loc["pages"][p]["title"])}</a>' for p in PAGES)
    values = {
        "lang": tag, "description": attr(entry["description"]), "title": text(entry["title"]), "url": url,
        "alternates": "\n".join(alternates), "og_locale": LOCALES[tag]["og"], "og_alternates": "\n".join(og_alternates),
        "og_image_alt": attr(loc["og_image_alt"]), "home": text(loc["home"]), "eyebrow": text(entry["eyebrow"]),
        "intro": text(entry["intro"]), "effective": effective, "language": attr(loc["language"]), "languages": languages,
        "sections": sections, "footer": attr(loc["footer"]), "footer_links": footer_links, "contact": text(loc["contact"]),
        "contact_email": doc["contact"],
    }
    out = re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], template)
    return out


def build(root=ROOT):
    """{file name: html} of the nine pages. Raises BuildError."""
    try:
        doc = json.loads((root / "_src" / "legal.json").read_text(encoding="utf-8"))
        template = (root / "_src" / "legal.html").read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise BuildError(f"cannot read the sources: {exc}")
    problems = validate(doc)
    unknown = set(re.findall(r"\{\{(\w+)\}\}", template)) - {
        "lang", "description", "title", "url", "alternates", "og_locale", "og_alternates", "og_image_alt", "home", "eyebrow",
        "intro", "effective", "language", "languages", "sections", "footer", "footer_links", "contact", "contact_email"}
    if unknown:
        problems.append("the template has unknown placeholders: " + ", ".join(sorted(unknown)))
    if problems:
        raise BuildError("; ".join(problems))
    return {file_name(page, tag): render(template, doc, page, tag) for page in PAGES for tag in LOCALES}


def check(root=ROOT):
    """Problems: a page that is missing or differs from what _src/ builds (a hand edit or a stale build)."""
    root = Path(root)
    try:
        pages = build(root)
    except BuildError as exc:
        return [f"the legal pages cannot be built: {exc}"]
    problems = []
    for name, page in pages.items():
        path = root / name
        if not path.is_file():
            problems.append(f"{name}: missing; run _tools/build-legal.py")
        elif path.read_text(encoding="utf-8") != page:
            problems.append(f"{name}: differs from what _src/ builds; edit _src/legal.json and run _tools/build-legal.py, not the page")
    return problems


def main(argv):
    if argv not in ([], ["--check"]):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        pages = build()
    except BuildError as exc:
        print(f"build-legal: {exc}", file=sys.stderr)
        return 1
    if argv == ["--check"]:
        problems = check()
        for problem in problems:
            print(f"build-legal: {problem}")
        return 1 if problems else 0
    for name, page in pages.items():
        (ROOT / name).write_text(page, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
