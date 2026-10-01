# Landing sources

`index.html`, `index-pt-BR.html` and `index-es-MX.html` are **generated**: do not edit them by hand.

- `landing.html`: the page, with `{{placeholders}}` (the CSS is the one of the old page plus a few rules for the static pages).
- `content/<tag>.json`: the texts of one language, the alt texts and the image of each slot.
- `facts.json`: facts that change with a release (`min_ios`, `year`); the content uses them as `{min_ios}` and `{year}`.
- `assets.json`: the pixel size of each image (`python3 _tools/build-landing.py --assets` rewrites it).

```bash
python3 _tools/build-landing.py          # write the three pages
python3 _tools/build-landing.py --check  # fail if a page differs from what the sources build
python3 _tools/check-site.py             # the whole site, which includes that check
python3 -m unittest discover -s _tools -q
```

GitHub Pages ignores folders that start with an underscore, so `_src/` and `_tools/` are not published.
