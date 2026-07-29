# Embedded typeface

[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) v2.304, subset to
only the characters each graphic actually draws and inlined into the SVGs as a
base64 `@font-face`. Regenerate with `python scripts/make_fonts.py`.

Why inline it at all:

* **Metrics.** Every character grid here assumes an advance width of exactly
  0.600 em. JetBrains Mono is 600/1000 units, so the geometry is unchanged — but
  a viewer whose default monospace is narrower (Consolas is ≈0.55) would
  otherwise see the wordmark about 7% too narrow. Inlining pins it.
* **An external font URL cannot work.** These SVGs are loaded through `<img>`,
  and a browser refuses to fetch subresources for an image document. A base64
  data URI is the only mechanism — and it keeps the page free of third-party
  requests.

| file | weight | covers |
|---|---|---|
| `jbmono-ramp.woff2` | 800 | the 13 ramp characters in `ascii.svg` |
| `jbmono-head.woff2` | 600 | the letters the section headings spell |
| `jbmono-400.woff2` | 400 | basic latin, for the stat graphics |
| `jbmono-600.woff2` | 600 | basic latin, for the stat graphics |

The `.ttf` sources these are cut from are build inputs only — nothing ships
them — so `scripts/jbmono.py` downloads them into this directory on demand and
`.gitignore` keeps them out of the repository. The release tag is pinned, so a
rebuild from a clean checkout produces byte-identical subsets.

Licensed under the SIL Open Font License 1.1 — see `OFL.txt`. Subsetting and
redistribution in this form are permitted, and the reserved font name is
unchanged.
