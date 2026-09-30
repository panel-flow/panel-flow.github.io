#!/usr/bin/env python3
"""Check the Panel Flow site before it is published (and, with --live, after).

    python3 _tools/check-site.py [--live] [--base URL]

Offline (default), run from anywhere: reads the HTML files of the repository and checks the pages the app links to
(privacy-policy- and support- plus en, es-MX or pt-BR; terms- is held back in _drafts/), the canonical and hreflang links, Open Graph tags, local
links and images, leftover [[PLACEHOLDER]] markers, references to the old address, the contact email on the support
pages, the sitemap and robots.txt. Prints one line per problem and `PASS` or `FAIL`; exit code 1 on FAIL.

--live also fetches the landing and the pages from --base (default https://panel-flow.github.io/) and expects HTTP 200
plus the expected canonical link, and the contact email on the support pages.
"""
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = "https://panel-flow.github.io/"
OLD_HOST = "sciasxp.github.io"
EMAIL = "sciasxp@gmail.com"
# "terms" joins this list when _drafts/terms-*.html move back to the root (see docs in the release plan).
GROUPS = ["privacy-policy", "support"]
LOCALES = {"en": "en-US", "es-MX": "es-MX", "pt-BR": "pt-BR"}
PAGES = [f"{g}-{k}.html" for g in GROUPS for k in LOCALES]


def check_offline(root=ROOT, base=DEFAULT_BASE):
    problems = []

    def add(where, message):
        problems.append(f"{where}: {message}")

    all_html = sorted(root.glob("*.html"))
    for path in all_html:
        text = path.read_text(encoding="utf-8")
        if OLD_HOST in text:
            add(path.name, f"still references the old address {OLD_HOST}")
        for marker in sorted(set(re.findall(r"\[\[[A-Z_]+\]\]", text))):
            add(path.name, f"placeholder {marker} is still in the page")
        for ref in re.findall(r'(?:href|src)="([^"#?]+)', text):
            if re.match(r"(https?:|mailto:|tel:|data:|//)", ref):
                if ref.startswith(base) and not (root / ref[len(base):].rstrip("/") or root).exists():
                    add(path.name, f"links to {ref}, which is not in the repository")
                continue
            if ref and not (root / ref).exists():
                add(path.name, f"links to {ref}, which does not exist")

    for page in PAGES:
        path = root / page
        if not path.is_file():
            add(page, "missing (the app links to it)")
            continue
        text = path.read_text(encoding="utf-8")
        key = next(k for k in LOCALES if page.endswith(f"-{k}.html"))
        group = page[: -len(f"-{key}.html")]
        if not re.search(r"<title>[^<]+</title>", text):
            add(page, "no <title>")
        if f'<html lang="{LOCALES[key]}"' not in text:
            add(page, f"html lang should be {LOCALES[key]}")
        if f'<link rel="canonical" href="{base}{page}">' not in text:
            add(page, f"canonical link should be {base}{page}")
        for k, hreflang in LOCALES.items():
            if f'hreflang="{hreflang}" href="{base}{group}-{k}.html"' not in text:
                add(page, f"hreflang {hreflang} is missing or wrong")
        if f'hreflang="x-default" href="{base}{group}-en.html"' not in text:
            add(page, "hreflang x-default is missing or wrong")
        for tag in ("og:title", "og:description", "og:url", "og:image"):
            if f'property="{tag}"' not in text:
                add(page, f"{tag} is missing")
        if group == "support" and f"mailto:{EMAIL}" not in text:
            add(page, f"the contact email {EMAIL} is missing")

    index = root / "index.html"
    if not index.is_file():
        add("index.html", "missing")
    else:
        text = index.read_text(encoding="utf-8")
        if f'<link rel="canonical" href="{base}">' not in text:
            add("index.html", f"canonical link should be {base}")
        if "application/ld+json" not in text:
            add("index.html", "structured data is missing")

    sitemap = root / "sitemap.xml"
    if not sitemap.is_file():
        add("sitemap.xml", "missing")
    else:
        text = sitemap.read_text(encoding="utf-8")
        for page in PAGES:
            if f"<loc>{base}{page}</loc>" not in text:
                add("sitemap.xml", f"does not list {page}")
    robots = root / "robots.txt"
    if not robots.is_file() or f"Sitemap: {base}sitemap.xml" not in robots.read_text(encoding="utf-8"):
        add("robots.txt", "missing or does not name the sitemap")
    return problems


def check_live(base):
    problems = []
    targets = [(base, None)] + [(base + p, p) for p in PAGES]
    for url, page in targets:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "check-site"}), timeout=25) as r:
                status, body = r.status, r.read().decode("utf-8", "replace")
        except Exception as exc:  # HTTPError, URLError, timeout: all mean the page is not served
            problems.append(f"{url}: {getattr(exc, 'code', type(exc).__name__)}")
            continue
        if status != 200:
            problems.append(f"{url}: HTTP {status}")
        if page and f'<link rel="canonical" href="{base}{page}">' not in body:
            problems.append(f"{url}: the served page has a different canonical link")
        if page and page.startswith("support-") and f"mailto:{EMAIL}" not in body:
            problems.append(f"{url}: the contact email is missing")
    return problems


def main(argv):
    live = "--live" in argv
    base = DEFAULT_BASE
    if "--base" in argv:
        base = argv[argv.index("--base") + 1].rstrip("/") + "/"
    problems = check_offline(base=base)
    if live:
        problems += check_live(base)
    for line in problems:
        print("FAIL", line)
    print("PASS" if not problems else f"FAIL: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
