# Landing and legal sources

`index.html`, `index-pt-BR.html` and `index-es-MX.html` are **generated**, and so are the nine legal pages
(`privacy-policy-`, `terms-` and `support-` plus `en`, `es-MX` or `pt-BR`): do not edit them by hand.

- `landing.html`: the page, with `{{placeholders}}` (the CSS is the one of the old page plus a few rules for the static pages).
- `content/<tag>.json`: the texts of one language, the alt texts, the image of each slot and the numbers of the stats bar (`statN_value`, shown above the label `statN`).
- `facts.json`: facts that change with a release (`min_ios`, `year`); the content uses them as `{min_ios}` and `{year}`.
- `legal.html` and `legal.json`: the legal pages. `legal.json` holds the texts of the three languages, the contact address and
  one effective date per dated page (`privacy-policy`, `terms`); each language writes that date in its own words through
  `{date}`. A section body is a small subset of HTML (`p`, `ul`, `ol`, `li`, `strong`, `em`, `br`, `a href`). In the app
  repository this is `marketing/web/site.json`'s `legal`, and the release flow (`/pf-release`, phase 4c) writes it here.
- `assets.json`: the pixel size of each image (`python3 _tools/build-landing.py --assets` rewrites it).

```bash
python3 _tools/build-landing.py          # write the three pages
python3 _tools/build-landing.py --check  # fail if a page differs from what the sources build
python3 _tools/build-legal.py            # write the nine legal pages
python3 _tools/build-legal.py --check    # fail if a legal page differs from what _src/legal.json builds
python3 _tools/check-site.py             # the whole site, which includes both checks
python3 -m unittest discover -s _tools -q
```

GitHub Pages ignores folders that start with an underscore, so `_src/` and `_tools/` are not published.
