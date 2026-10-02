#!/usr/bin/env python3
"""Build the three landing pages of the Panel Flow site from the sources in _src/.

    python3 _tools/build-landing.py            # write index.html, index-pt-BR.html and index-es-MX.html
    python3 _tools/build-landing.py --check    # exit 1 if a page on disk differs from what the sources produce
    python3 _tools/build-landing.py --assets   # (re)write _src/assets.json: the pixel size of every image the pages use

Sources:  _src/landing.html          the page, with {{placeholders}}
          _src/content/<tag>.json    the texts of one language (en-US, pt-BR, es-MX), the alt texts and the image of each slot
          _src/facts.json            facts that change with the release (minimum iOS, copyright year), used as {min_ios} and {year}
          _src/assets.json           width and height of each image (so the pages can state them; checked against the files)

The pages are generated: do not edit them by hand. `--check` (also run by check-site.py) catches a hand edit or a stale build.
Standard library only. The output is deterministic.

The root `/` is the English page (x-default and en-US); the Portuguese and Spanish pages are index-pt-BR.html and
index-es-MX.html. Each page links the others with hreflang; nothing redirects by language.
"""
import html
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://panel-flow.github.io/"
STORE_URL = "https://apps.apple.com/app/id6755895197"
OG_IMAGE = BASE + "img/og-card.png"
# tag -> page file, switcher label, og:locale and the suffix of its legal pages
PAGES = {
    "en-US": {"file": "index.html", "url": BASE, "href": "./", "label": "EN", "og": "en_US", "legal": "en"},
    "pt-BR": {"file": "index-pt-BR.html", "url": BASE + "index-pt-BR.html", "href": "index-pt-BR.html", "label": "PT", "og": "pt_BR", "legal": "pt-BR"},
    "es-MX": {"file": "index-es-MX.html", "url": BASE + "index-es-MX.html", "href": "index-es-MX.html", "label": "ES", "og": "es_MX", "legal": "es-MX"},
}
SWITCHER_ORDER = ("pt-BR", "en-US", "es-MX")  # the order of the old switcher
FACTS = ("min_ios", "year")
LEGAL_STYLE = ('style="margin-top:8px;display:flex;flex-wrap:wrap;justify-content:center;gap:6px 18px"')
LINK_STYLE = ('style="color:var(--text-muted);font-size:0.8rem;transition:color 0.3s" onmouseover="this.style.color=\'#E8566C\'" '
              'onmouseout="this.style.color=\'\'"')
SLOTS = ("hero", "ai", "trans", "reading", "guided")
# optional decorative art: a background of the hero and of the closing section, under a fixed dark overlay (see landing.html)
ART_SLOTS = ("hero", "cta")
ART_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./@-]*\.(?:webp|png|jpe?g)")
# optional demo videos for the two sections that show the app in use: {"src": "release/reading-en-US.mp4", "poster": "release/reading-en-US.jpg"}
# under `videos` in the content (src is under video/, poster under img/). No autoplay: a control to pause is needed for moving content.
VIDEO_SLOTS = ("reading", "guided")
VIDEO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./@-]*\.mp4")


class BuildError(ValueError):
    pass


def image_size(path):
    """(width, height) of a PNG, WebP or JPEG, from the file header."""
    data = Path(path).read_bytes()[:40]
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8 ":
            width, height = struct.unpack("<HH", data[26:30])
            return width & 0x3FFF, height & 0x3FFF
        if kind == b"VP8L":
            b = data[21:25]
            return 1 + (b[0] | (b[1] & 0x3F) << 8), 1 + ((b[1] >> 6) | b[2] << 2 | (b[3] & 0xF) << 10)
        if kind == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if data[:2] == b"\xff\xd8":  # JPEG: the size is in the first start-of-frame segment
        raw = Path(path).read_bytes()
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                height, width = struct.unpack(">HH", raw[i + 5:i + 9])
                return width, height
            i += 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
    raise BuildError(f"{path}: not a PNG, WebP or JPEG image")


def load(root):
    root = Path(root)
    src = root / "_src"
    template = (src / "landing.html").read_text(encoding="utf-8")
    content = {tag: json.loads((src / "content" / f"{tag}.json").read_text(encoding="utf-8")) for tag in PAGES}
    facts = json.loads((src / "facts.json").read_text(encoding="utf-8"))
    assets = json.loads((src / "assets.json").read_text(encoding="utf-8")) if (src / "assets.json").is_file() else {}
    return template, content, facts, assets


def esc(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def with_facts(text, facts):
    def sub(m):
        if m.group(1) not in facts:
            raise BuildError(f"unknown fact {{{m.group(1)}}} in the content")
        return str(facts[m.group(1)])
    return re.sub(r"\{(\w+)\}", sub, text)


def art_attributes(slot, own, root, assets):
    """The attributes that put the art of a slot behind its section: empty when the content has none, so a page without art is
    exactly the page it was before the slot existed."""
    name = (own.get("images") or {}).get(f"art_{slot}")
    if not name:
        return ""
    if not ART_NAME.fullmatch(name) or ".." in name.split("/"):
        raise BuildError(f"art_{slot}: '{name}' is not a plain image path")
    if not (Path(root) / "img" / name).is_file():
        raise BuildError(f"art_{slot}: img/{name} does not exist")
    if name not in assets:
        raise BuildError(f"art_{slot}: img/{name} is not in _src/assets.json (run --assets)")
    return f' data-art style="--art:url(img/{name})"'


def media(tag, slot, own, root, assets):
    """The image of a slot, or its demo video when the content has one (poster, controls, no autoplay). With no video this is
    exactly the <img> the template always had, so a page without videos is the page it was before the slot existed."""
    images = own.get("images") or {}
    video = (own.get("videos") or {}).get(slot)
    if video is not None:
        if (not isinstance(video, dict) or set(video) != {"src", "poster"} or not VIDEO_NAME.fullmatch(str(video["src"]))
                or not ART_NAME.fullmatch(str(video["poster"])) or ".." in (str(video["src"]) + "/" + str(video["poster"])).split("/")):
            raise BuildError(f"{tag}: videos.{slot} must be {{src: a plain .mp4 path, poster: a plain image path}}")
        if not (Path(root) / "video" / video["src"]).is_file():
            raise BuildError(f"{tag}: video/{video['src']} does not exist")
        if not (Path(root) / "img" / video["poster"]).is_file():
            raise BuildError(f"{tag}: img/{video['poster']} does not exist")
        if video["poster"] not in assets:
            raise BuildError(f"{tag}: img/{video['poster']} is not in _src/assets.json (run --assets)")
        width, height = assets[video["poster"]]
        return (f'<video controls muted playsinline preload="none" poster="img/{video["poster"]}" width="{width}" height="{height}" '
                f'aria-label="{esc(own[f"alt_{slot}"])}"><source src="video/{video["src"]}" type="video/mp4"></video>')
    name = images.get(slot)
    if not name:
        raise BuildError(f"{tag}: no image for the slot '{slot}'")
    if not (Path(root) / "img" / name).is_file():
        raise BuildError(f"{tag}: img/{name} does not exist")
    if name not in assets:
        raise BuildError(f"{tag}: img/{name} is not in _src/assets.json (run --assets)")
    return (f'<img src="img/{name}" width="{assets[name][0]}" height="{assets[name][1]}" alt="{esc(own[f"alt_{slot}"])}" '
            'loading="lazy" decoding="async">')


def alternates():
    tags = [f'<link rel="alternate" hreflang="{tag}" href="{PAGES[tag]["url"]}">' for tag in ("en-US", "pt-BR", "es-MX")]
    tags.append(f'<link rel="alternate" hreflang="x-default" href="{PAGES["en-US"]["url"]}">')
    return "\n  ".join(tags)


def lang_switcher(tag, content):
    items = []
    for other in SWITCHER_ORDER:
        page = PAGES[other]
        active = ' aria-current="page"' if other == tag else ""
        css = "lang-btn active" if other == tag else "lang-btn"
        items.append(f'<a class="{css}" href="{page["href"]}" hreflang="{other}" lang="{other}"{active}>{page["label"]}</a>')
    return ('<div class="lang-switcher" role="group" aria-label="' + esc(content["switcher_label"]) + '">\n          '
            + "\n          ".join(items) + "\n        </div>")


def legal_nav(tag, content):
    suffix = PAGES[tag]["legal"]
    links = [("privacy-policy", content["footer_privacy"]), ("terms", content["footer_terms"]), ("support", content["footer_support"])]
    anchors = "".join(f'<a href="{name}-{suffix}.html" {LINK_STYLE}>{esc(label)}</a>' for name, label in links)
    # not a <nav>: the page CSS pins every <nav> element to the top of the window, where it would cover the real navigation
    return f'<div role="navigation" aria-label="Legal" {LEGAL_STYLE}>{anchors}</div>'


def json_ld(tag, content):
    doc = {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Panel Flow",
           "applicationCategory": "EntertainmentApplication", "operatingSystem": "iOS, iPadOS",
           "description": content["meta_description"], "url": PAGES[tag]["url"], "image": OG_IMAGE,
           "downloadUrl": STORE_URL, "inLanguage": tag}
    return json.dumps(doc, ensure_ascii=False).replace("</", "<\\/")


def render(tag, template, content, facts, assets, root):
    page = PAGES[tag]
    own = {k: (with_facts(v, facts) if isinstance(v, str) else v) for k, v in content[tag].items()}
    own["year"] = str(facts["year"])
    computed = {
        "html_lang": tag, "canonical": page["url"], "alternates": alternates(), "og_locale": page["og"],
        "og_locale_alternates": "\n  ".join(f'<meta property="og:locale:alternate" content="{p["og"]}">'
                                            for t, p in PAGES.items() if t != tag),
        "json_ld": json_ld(tag, own), "lang_switcher": lang_switcher(tag, own), "legal_nav": legal_nav(tag, own),
        "store_url": STORE_URL, "year": own["year"],
        **{f"art_{slot}": art_attributes(slot, own, root, assets) for slot in ART_SLOTS},
        **{f"media_{slot}": media(tag, slot, own, root, assets) for slot in VIDEO_SLOTS},
    }

    def sub(m):
        key = m.group(1)
        if ":" in key:
            kind, slot = key.split(":", 1)
            name = own.get("images", {}).get(slot)
            if kind not in ("src", "w", "h") or not name:
                raise BuildError(f"{tag}: no image for the slot '{slot}'")
            if not (Path(root) / "img" / name).is_file():
                raise BuildError(f"{tag}: img/{name} does not exist")
            if name not in assets:
                raise BuildError(f"{tag}: img/{name} is not in _src/assets.json (run --assets)")
            return {"src": f"img/{name}", "w": str(assets[name][0]), "h": str(assets[name][1])}[kind]
        if key in computed:
            return computed[key]
        if key in own and isinstance(own[key], str):
            return esc(own[key])
        raise BuildError(f"{tag}: the template needs '{key}' and the content has none")
    return re.sub(r"\{\{([^{}]+)\}\}", sub, template)



def check_sources(content):
    """The three languages have the same keys, every slot has an image, nothing is empty."""
    problems = []
    keys = {tag: set(c) for tag, c in content.items()}
    reference = keys["en-US"]
    for tag, k in keys.items():
        for missing in sorted(reference - k):
            problems.append(f"{tag}: missing the key '{missing}'")
        for extra in sorted(k - reference):
            problems.append(f"{tag}: has the key '{extra}', which en-US does not")
        for key, value in content[tag].items():
            if key not in ("images", "videos") and (not isinstance(value, str) or not value.strip()):
                problems.append(f"{tag}: '{key}' is empty")
        for slot in SLOTS:
            if not (content[tag].get("images") or {}).get(slot):
                problems.append(f"{tag}: the slot '{slot}' has no image")
        for key in sorted(k for k in (content[tag].get("images") or {}) if k not in SLOTS):
            if key not in {f"art_{s}" for s in ART_SLOTS}:
                problems.append(f"{tag}: '{key}' is not an image slot or an art slot")
        videos = content[tag].get("videos")
        if videos is not None:
            if not isinstance(videos, dict) or set(videos) - set(VIDEO_SLOTS):
                problems.append(f"{tag}: 'videos' must be an object of {', '.join(VIDEO_SLOTS)}")
    slots = {tag: sorted((c.get("videos") or {}) if isinstance(c.get("videos") or {}, dict) else []) for tag, c in content.items()}
    if len({tuple(v) for v in slots.values()}) > 1:
        problems.append("the videos differ between the languages: " + "; ".join(f"{t}: {v}" for t, v in slots.items()))
    art = {tag: {k for k in (c.get("images") or {}) if k.startswith("art_")} for tag, c in content.items()}
    if len({frozenset(v) for v in art.values()}) > 1:
        problems.append("the art slots differ between the languages: " + "; ".join(f"{t}: {sorted(v)}" for t, v in art.items()))
    return problems


def build(root=ROOT):
    """{page file: text} for the three pages."""
    template, content, facts, assets = load(root)
    problems = check_sources(content)
    if problems:
        raise BuildError("; ".join(problems))
    for fact in FACTS:
        if fact not in facts:
            raise BuildError(f"_src/facts.json has no '{fact}'")
    return {PAGES[tag]["file"]: render(tag, template, content, facts, assets, root) for tag in PAGES}


def images_used(root=ROOT):
    content = load(root)[1]
    names = {name for c in content.values() for name in (c.get("images") or {}).values()}
    names |= {v["poster"] for c in content.values() for v in (c.get("videos") or {}).values() if isinstance(v, dict) and "poster" in v}
    return sorted(names)


def write_assets(root=ROOT):
    sizes = {name: list(image_size(Path(root) / "img" / name)) for name in images_used(root)}
    (Path(root) / "_src" / "assets.json").write_text(json.dumps(sizes, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return sizes


def check(root=ROOT):
    """Problems: a page that is missing or differs from the build, an asset size that is not the real one."""
    root = Path(root)
    problems = []
    try:
        pages = build(root)
    except (BuildError, OSError, ValueError, KeyError) as exc:
        return [f"the landing cannot be built: {exc}"]
    for name, text in pages.items():
        path = root / name
        if not path.is_file():
            problems.append(f"{name}: missing; run _tools/build-landing.py")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"{name}: differs from what _src/ builds; edit the sources and run _tools/build-landing.py, not the page")
    assets = json.loads((root / "_src" / "assets.json").read_text(encoding="utf-8"))
    for name in images_used(root):
        try:
            real = list(image_size(root / "img" / name))
        except (BuildError, OSError) as exc:
            problems.append(f"img/{name}: {exc}")
            continue
        if assets.get(name) != real:
            problems.append(f"_src/assets.json has {assets.get(name)} for img/{name}, which is {real}; run --assets")
    return problems


def main(argv):
    try:
        if "--assets" in argv:
            sizes = write_assets()
            print(f"assets: {len(sizes)} image(s)")
            return 0
        if "--check" in argv:
            problems = check()
            for p in problems:
                print(f"FAIL {p}")
            print("PASS" if not problems else f"FAIL: {len(problems)} problem(s)")
            return 1 if problems else 0
        for name, text in build().items():
            (ROOT / name).write_text(text, encoding="utf-8")
            print(f"wrote {name}")
        return 0
    except (BuildError, OSError, ValueError, KeyError) as exc:
        print(f"build-landing: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
