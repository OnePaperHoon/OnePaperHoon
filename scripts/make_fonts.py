#!/usr/bin/env python3
"""Subset JetBrains Mono to exactly the characters each graphic draws.

Every SVG on the profile page inlines its typeface as base64. That is not a
stylistic choice: the SVGs are loaded through <img>, and a browser refuses to
fetch subresources for an image document, so an external font URL can never
arrive. Inlining also pins the advance width to 0.600 em, which every character
grid here assumes -- a viewer whose default monospace is narrower (Consolas is
about 0.55) would otherwise see the art squeezed.

Subsetting keeps that inlining cheap: the full face is ~270 KB, the ramp needs
thirteen glyphs.

Run after changing which characters a graphic uses. Requires:
    python -m pip install fonttools brotli
"""
import os
import string
import sys

try:
    from fontTools import subset
except ImportError:
    sys.exit("fonttools is required: python -m pip install fonttools brotli")

import jbmono

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")

RAMP = " .`:-=+*cs#%@"
HEADINGS = "about stack projects stats algorithm"

# Space through ~, plus the three punctuation marks the graphics actually reach
# for outside ASCII: en dash joins a streak's start and end, em dash stands in
# for an empty streak, and the middle dot separates the wordmark's tagline.
# Without them the browser falls back per-glyph to some other face, and that one
# character lands in the wrong typeface at the wrong width.
LATIN = string.printable[:95] + "–—·É"

# (source ttf, output woff2, characters to keep)
JOBS = [
    ("JetBrainsMono-ExtraBold.ttf", "jbmono-ramp.woff2", RAMP),
    ("JetBrainsMono-SemiBold.ttf", "jbmono-head.woff2", HEADINGS),
    ("JetBrainsMono-Regular.ttf", "jbmono-400.woff2", LATIN),
    ("JetBrainsMono-SemiBold.ttf", "jbmono-600.woff2", LATIN),
]


def build(src, dst, text):
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.desubroutinize = True
    opts.layout_features = []
    opts.notdef_outline = False
    opts.drop_tables += ["FFTM"]

    font = subset.load_font(os.path.join(FONTS, src), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)

    out = os.path.join(FONTS, dst)
    subset.save_font(font, out, opts)
    em = font["head"].unitsPerEm
    adv = font["hmtx"]["space"][0] if "space" in font.getGlyphOrder() else None
    font.close()
    ratio = f"{adv / em:.3f} em" if adv else "n/a"
    print(f"{dst:22} {os.path.getsize(out):6} bytes   advance {ratio}   from {src}")


def main():
    # One pass over the sources, so the release archive is fetched at most once
    jbmono.ensure(*{src for src, _, _ in JOBS})
    for src, dst, text in JOBS:
        build(src, dst, text)


if __name__ == "__main__":
    main()
