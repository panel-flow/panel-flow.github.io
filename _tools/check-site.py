#!/usr/bin/env python3
"""Check the Panel Flow site before it is published (and, with --live, after).

    python3 _tools/check-site.py [--live] [--base URL]

Offline (default), run from anywhere: reads the HTML files of the repository and checks the nine pages the app links to
(privacy-policy-, terms- and support- plus en, es-MX or pt-BR; generated, so they must equal what build-legal.py makes of
_src/legal.json), the canonical and hreflang links, Open Graph tags, local links and images, leftover [[PLACEHOLDER]]
markers, references to the old address, the contact email on the support pages, the three generated landing pages (see
build-landing.py: they must equal what _src/ builds, one h1, hreflang, canonical, alt and size on every image, no leftover
i18n), the sitemap and robots.txt. Prints one line per problem and `PASS` or `FAIL`; exit code 1 on FAIL.

--live also fetches the landing and the nine pages from --base (default https://panel-flow.github.io/) and expects HTTP 200
plus the expected canonical link, and the contact email on the support pages.
"""
import html
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = "https://panel-flow.github.io/"
OLD_HOST = "sciasxp.github.io"
EMAIL = "sciasxp@gmail.com"
GROUPS = ["privacy-policy", "terms", "support"]
LOCALES = {"en": "en-US", "es-MX": "es-MX", "pt-BR": "pt-BR"}
PAGES = [f"{g}-{k}.html" for g in GROUPS for k in LOCALES]
TITLE_MAX, DESC_MAX, LANDING_DESC_MIN = 60, 155, 70  # what a search result shows before it cuts; the landing says more than a legal page


def _builder(name="build-landing"):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _builder()
LEGAL_BUILDER = _builder("build-legal")
LANDING = {tag: page["file"] for tag, page in BUILDER.PAGES.items()}  # tag -> file; en-US is the root
STORE_ID = BUILDER.STORE_URL.rsplit("/id", 1)[1]


def page_meta(text):
    """(title, description) of a page, unescaped; None for what is missing."""
    title = re.search(r"<title>([^<]+)</title>", text)
    desc = re.search(r'<meta name="description" content="([^"]*)"', text)
    return (html.unescape(title.group(1)) if title else None, html.unescape(desc.group(1)) if desc else None)


def og_content(text, prop):
    found = re.search(r'<meta property="%s" content="([^"]*)"' % re.escape(prop), text)
    return html.unescape(found.group(1)) if found else None


def check_search_text(name, text, add, landing_page=False):
    """Length of the title and description the way a search result shows them, and the social tags saying the same."""
    title, desc = page_meta(text)
    if title and len(title) > TITLE_MAX:
        add(name, f"the title has {len(title)} characters, above {TITLE_MAX}")
    if desc is not None:
        if len(desc) > DESC_MAX:
            add(name, f"the meta description has {len(desc)} characters, above {DESC_MAX}")
        if landing_page and len(desc) < LANDING_DESC_MIN:
            add(name, f"the meta description has {len(desc)} characters, below {LANDING_DESC_MIN}")
    for prop, value in (("og:title", title), ("og:description", desc)):
        have = og_content(text, prop)
        if have is not None and value is not None and have != value:
            add(name, f"{prop} differs from the page's own {'title' if prop == 'og:title' else 'meta description'}")


def check_offline(root=ROOT, base=DEFAULT_BASE, landing=True):
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
        check_search_text(page, text, add)

    index = root / "index.html"
    if not index.is_file():
        add("index.html", "missing")
    elif not landing:
        text = index.read_text(encoding="utf-8")
        if f'<link rel="canonical" href="{base}">' not in text:
            add("index.html", f"canonical link should be {base}")
        if "application/ld+json" not in text:
            add("index.html", "structured data is missing")

    if landing:
        problems += check_landing(root, base)
        problems += [f"legal: {p}" for p in LEGAL_BUILDER.check(root)]

    sitemap = root / "sitemap.xml"
    if not sitemap.is_file():
        add("sitemap.xml", "missing")
    else:
        text = sitemap.read_text(encoding="utf-8")
        for page in PAGES:
            if f"<loc>{base}{page}</loc>" not in text:
                add("sitemap.xml", f"does not list {page}")
        if landing:
            for tag, file in LANDING.items():
                url = base if file == "index.html" else base + file
                block = re.search(r"<url>\s*<loc>%s</loc>(.*?)</url>" % re.escape(url), text, re.S)
                if not block:
                    add("sitemap.xml", f"does not list the landing page {url}")
                    continue
                for other, ofile in LANDING.items():
                    ourl = base if ofile == "index.html" else base + ofile
                    if f'hreflang="{other}" href="{ourl}"' not in block.group(1):
                        add("sitemap.xml", f"the entry of {url} lacks the alternate {other}")
                if f'hreflang="x-default" href="{base}"' not in block.group(1):
                    add("sitemap.xml", f"the entry of {url} lacks x-default")
    seen = {}
    for name in PAGES + (list(LANDING.values()) if landing else []):
        path = root / name
        if not path.is_file():
            continue
        for kind, value in zip(("title", "meta description"), page_meta(path.read_text(encoding="utf-8"))):
            if value is None:
                continue
            if (kind, value) in seen:
                add(name, f"the {kind} is the same as the one of {seen[(kind, value)]}")
            else:
                seen[(kind, value)] = name
    robots = root / "robots.txt"
    if not robots.is_file() or f"Sitemap: {base}sitemap.xml" not in robots.read_text(encoding="utf-8"):
        add("robots.txt", "missing or does not name the sitemap")
    return problems


def check_landing(root, base):
    """The three landing pages: equal to what _src/ builds, and sound on their own."""
    problems = [f"landing: {p}" for p in BUILDER.check(root)]
    pages = BUILDER.PAGES
    for tag, spec in pages.items():
        name = spec["file"]
        path = root / name
        if not path.is_file():
            continue  # the builder check above already says so
        text = path.read_text(encoding="utf-8")
        url = base if name == "index.html" else base + name

        def add(message, name=name):
            problems.append(f"{name}: {message}")
        if f'<html lang="{tag}"' not in text:
            add(f"html lang should be {tag}")
        if f'<link rel="canonical" href="{url}">' not in text:
            add(f"canonical link should be {url}")
        for other, ospec in pages.items():
            ourl = base if ospec["file"] == "index.html" else base + ospec["file"]
            if f'hreflang="{other}" href="{ourl}"' not in text:
                add(f"hreflang {other} is missing or wrong")
        if f'hreflang="x-default" href="{base}"' not in text:
            add("hreflang x-default is missing or wrong")
        if len(re.findall(r"<h1[\s>]", text)) != 1:
            add("the page must have exactly one h1")
        if len(re.findall(r"<nav[\s>]", text)) != 1:
            add("the page must have exactly one <nav> element (the CSS pins every <nav> to the top of the window)")
        if "data-i18n" in text or "const translations" in text:
            add("leftover client-side translation (data-i18n or translations)")
        videos = re.findall(r"<video\b[^>]*>.*?</video>|<video\b[^>]*>", text, re.S)
        if len(videos) > len(BUILDER.VIDEO_SLOTS):
            add(f"{len(videos)} <video> elements on the page; at most {len(BUILDER.VIDEO_SLOTS)} (one per demo slot)")
        for video in videos:  # a demo video is allowed only as the builder writes it: to be paused, silent, not preloaded and with a poster
            tagtext = re.match(r"<video\b[^>]*>", video).group(0)
            for need in ("controls", "muted", "playsinline", 'preload="none"'):
                if not re.search(r"(?<![\w-])" + re.escape(need) + r"(?![\w-])", tagtext):
                    add(f"a <video> lacks {need}: {tagtext[:70]}")
            for banned in ("autoplay", "loop"):
                if re.search(r"(?<![\w-])" + banned + r"(?![\w-])", tagtext):
                    add(f"a <video> has {banned}: moving content that starts or repeats by itself needs a way to stop it")
            if not re.search(r'\baria-label="[^"]+"', tagtext):
                add("a <video> has no aria-label")
            if not (re.search(r'\bwidth="\d+"', tagtext) and re.search(r'\bheight="\d+"', tagtext)):
                add("a <video> has no width and height")
            poster = re.search(r'\bposter="([^"]+)"', tagtext)
            if not poster:
                add("a <video> has no poster")
            elif not (root / poster.group(1)).is_file():
                add(f"the poster {poster.group(1)} does not exist")
            sources = re.findall(r"<source\b[^>]*>", video)
            if len(sources) != 1:
                add("a <video> needs exactly one <source>")
            for source in sources:
                src = re.search(r'\bsrc="(video/[^"]+\.mp4)"', source)
                if not src or 'type="video/mp4"' not in source:
                    add(f"a <source> must be an mp4 under video/: {source[:70]}")
                elif not (root / src.group(1)).is_file():
                    add(f"the video {src.group(1)} does not exist")
        if not re.search(r"<title>[^<]+</title>", text):
            add("no <title>")
        if not re.search(r'<meta name="description" content="[^"]{20,}"', text):
            add("no meta description")
        check_search_text(name, text, lambda where, message: add(message), landing_page=True)
        if og_content(text, "og:locale") != spec["og"]:
            add(f"og:locale should be {spec['og']}")
        if f'<meta name="apple-itunes-app" content="app-id={STORE_ID}"' not in text:
            add(f"the Smart App Banner (apple-itunes-app, app-id={STORE_ID}) is missing")
        for tagname in ("og:title", "og:description", "og:image"):
            if f'property="{tagname}"' not in text:
                add(f"{tagname} is missing")
        if f'property="og:url" content="{url}"' not in text:
            add(f"og:url should be {url}")
        for img in re.findall(r"<img\b[^>]*>", text):
            if not re.search(r'\balt="[^"]+"', img):
                add(f"an <img> has no alt text: {img[:60]}")
            if not (re.search(r'\bwidth="\d+"', img) and re.search(r'\bheight="\d+"', img)):
                add(f"an <img> has no width and height: {img[:60]}")
        for ref in re.findall(r"url\(([^)]+)\)", text):  # decorative art is a CSS background: no <img>, so no alt; the file must exist
            ref = ref.strip("'\"")
            if not re.match(r"^(?:[a-z][a-z0-9+.-]*:|#|//)", ref) and not (root / ref.split("?", 1)[0]).is_file():
                add(f"url({ref}) points to a file that does not exist")
        ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
        try:
            data = json.loads(ld.group(1)) if ld else None
        except ValueError:
            data = None
        if not data:
            add("structured data is missing or not JSON")
        else:
            if data.get("url") != url:
                add(f"structured data url should be {url}")
            if data.get("inLanguage") != tag:
                add(f"structured data inLanguage should be {tag}")
            if data.get("@context") != "https://schema.org" or data.get("@type") != "SoftwareApplication":
                add("structured data should be a schema.org SoftwareApplication")
            for field in ("name", "applicationCategory", "operatingSystem"):
                if not data.get(field):
                    add(f"structured data lacks {field}")
            if data.get("downloadUrl") != BUILDER.STORE_URL:
                add(f"structured data downloadUrl should be {BUILDER.STORE_URL}")
            if data.get("image") != og_content(text, "og:image"):
                add("structured data image differs from og:image")
            if data.get("description") != page_meta(text)[1]:
                add("structured data description differs from the meta description")
        if BUILDER.STORE_URL not in text:
            add("the App Store link is missing")
    return problems


def check_live(base):
    problems = []
    targets = [(base, "index.html")] + [(base + f, f) for f in LANDING.values() if f != "index.html"] + [(base + p, p) for p in PAGES]
    for url, page in targets:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "check-site"}), timeout=25) as r:
                status, body = r.status, r.read().decode("utf-8", "replace")
        except Exception as exc:  # HTTPError, URLError, timeout: all mean the page is not served
            problems.append(f"{url}: {getattr(exc, 'code', type(exc).__name__)}")
            continue
        if status != 200:
            problems.append(f"{url}: HTTP {status}")
        want = base if page == "index.html" else base + (page or "")
        if page and f'<link rel="canonical" href="{want}">' not in body:
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
