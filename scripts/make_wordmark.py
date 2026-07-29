#!/usr/bin/env python3
"""Draw the profile README's ASCII wordmark.

The name is rasterised in JetBrains Mono, then resampled onto a character grid
and re-drawn with a density ramp -- so the letterforms are made of the same
typeface the rest of the page uses, at a much finer grain than a figlet banner.

Like the portrait it replaces, this is a one-off artifact: run it when the
wordmark or its resolution changes, then commit the SVG. Nothing regenerates it
on a schedule.

Motion is SMIL because GitHub strips <script> from READMEs. The font is inlined
as base64 because these SVGs are loaded through <img>, and a browser refuses to
fetch subresources for an image document -- that also pins the advance width to
0.600 em, which the character grid assumes.

Env:
  TEXT      what to draw            (default: OnePaperHoon)
  COLS      grid width              (default: 160)
  TAGLINE   second line, or empty   (default: systems . backend . seoul)
  OUT       output path             (default: ascii.svg beside this script's parent)
"""
import base64
import os
import re
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow is required: python -m pip install pillow")

import jbmono

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TTF_NAME = "JetBrainsMono-ExtraBold.ttf"
FONT_WOFF2 = os.path.join(HERE, "fonts", "jbmono-ramp.woff2")
TAG_WOFF2 = os.path.join(HERE, "fonts", "jbmono-400.woff2")

# Quiet to loud. Thirteen steps, and the only characters the subset carries.
RAMP = " .`:-=+*cs#%@"

# The grid. CW is 0.600 em at FS, which is JetBrains Mono's advance width, so
# the glyphs tile exactly. LH is looser than the advance to keep the ramp from
# smearing vertically.
FS, CW, LH = 12.9, 7.74, 15.0
PAD_X, PAD_Y = 14, 10

LIGHT = "#6e7681"
DARK = "#c9d1d9"
MUTED_LIGHT = "#8c959f"
MUTED_DARK = "#8b949e"

TAG_FS = 14        # tagline type size
TAG_TRACK = 3.2    # tagline letter-spacing
TAG_LEAD = 34      # space opened beneath the wordmark for it
MONO = ("JBMono,ui-monospace,SFMono-Regular,Menlo,Consolas,"
        "&apos;Liberation Mono&apos;,monospace")

STEP = 0.11        # seconds between rows
DUR = 0.16         # seconds a single row takes to sweep


def raster(text, px=600):
    """Render the text as tall as practical, cropped tight to its ink."""
    font = ImageFont.truetype(jbmono.ensure(TTF_NAME)[TTF_NAME], px)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    margin = px // 12
    img = Image.new("L", (right - left + margin * 2, bottom - top + margin * 2), 0)
    ImageDraw.Draw(img).text((margin - left, margin - top), text, font=font, fill=255)
    return img.crop(img.getbbox())


def to_rows(img, cols):
    """Resample onto the character grid, one ramp step per cell."""
    rows = max(1, round(cols * CW / LH * img.height / img.width))
    small = img.resize((cols, rows), Image.LANCZOS)
    px = small.load()
    out = []
    for y in range(rows):
        line = "".join(
            RAMP[min(len(RAMP) - 1, int(px[x, y] / 255.0 * (len(RAMP) - 1) + 0.5))]
            for x in range(cols))
        out.append(line.rstrip())
    return out


def font_face(path, weight):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (f"@font-face{{font-family:JBMono;font-style:normal;"
            f"font-weight:{weight};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")


def build(rows, cols, tagline=""):
    w = round(PAD_X * 2 + cols * CW)
    h = round(PAD_Y * 2 + len(rows) * LH + (TAG_LEAD if tagline else 0))

    faces = font_face(FONT_WOFF2, 800)
    if tagline:
        # The ramp subset carries thirteen glyphs and no letters, so a tagline
        # set as real type needs the text face inlined alongside it.
        faces += font_face(TAG_WOFF2, 400)

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
         f'viewBox="0 0 {w} {h}" fill="none" font-family="{MONO}">',
         f'<style>{faces}.a{{fill:{LIGHT}}}.t{{fill:{MUTED_LIGHT}}}'
         f'@media(prefers-color-scheme:dark){{.a{{fill:{DARK}}}'
         f'.t{{fill:{MUTED_DARK}}}}}</style>']

    for i, line in enumerate(rows):
        if not line:
            continue
        y = PAD_Y + i * LH
        wpx = len(line) * CW
        begin = i * STEP
        safe = line.replace("&", "&amp;").replace("<", "&lt;")
        p.append(f'<clipPath id="r{i}"><rect x="{PAD_X}" y="{y:.1f}" '
                 f'height="{LH}" width="0"><animate attributeName="width" '
                 f'from="0" to="{wpx:.1f}" begin="{begin:.2f}s" dur="{DUR}s" '
                 f'fill="freeze"/></rect></clipPath>')
        p.append(f'<g clip-path="url(#r{i})"><text xml:space="preserve" '
                 f'x="{PAD_X}" y="{y + FS - 0.6:.1f}" class="a" '
                 f'font-size="{FS}">{safe}</text></g>')
        # the cursor block riding this row's reveal edge
        p.append(f'<rect y="{y:.1f}" width="{CW:.2f}" height="{LH}" class="a" '
                 f'opacity="0"><animate attributeName="x" from="{PAD_X}" '
                 f'to="{PAD_X + wpx:.1f}" begin="{begin:.2f}s" dur="{DUR}s" '
                 f'fill="freeze"/>'
                 f'<set attributeName="opacity" to="0.8" begin="{begin:.2f}s"/>'
                 f'<set attributeName="opacity" to="0" '
                 f'begin="{begin + DUR:.2f}s"/></rect>')

    if tagline:
        # Set as real type, not ramp art: at this size an ASCII rendering of a
        # sentence needs more grid columns than the wordmark, not fewer, so it
        # would come out both wider and illegible.
        y = PAD_Y + len(rows) * LH + TAG_LEAD - 4
        after = len(rows) * STEP + DUR
        p.append(f'<text x="{PAD_X}" y="{y:.1f}" class="t" font-size="{TAG_FS}" '
                 f'letter-spacing="{TAG_TRACK}" opacity="0">{tagline}'
                 f'<animate attributeName="opacity" from="0" to="1" '
                 f'begin="{after:.2f}s" dur="0.5s" fill="freeze"/></text>')

    p.append("</svg>")
    return "".join(p)


def main():
    text = os.environ.get("TEXT", "OnePaperHoon")
    cols = int(os.environ.get("COLS", "160"))
    tagline = os.environ.get("TAGLINE", "systems  ·  backend  ·  seoul")
    out = os.environ.get("OUT", os.path.join(ROOT, "ascii.svg"))

    rows = to_rows(raster(text), cols)
    svg = build(rows, cols, tagline)

    old = ""
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            old = f.read()
    if old == svg:
        print(f"{out}: unchanged")
        return
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    dims = re.search(r'width="(\d+)" height="(\d+)"', svg)
    print(f"{out}: {cols}x{len(rows)} grid, "
          f"{dims.group(1)}x{dims.group(2)}px, {len(svg) // 1024} KB"
          + (f', tagline "{tagline}"' if tagline else ""))


if __name__ == "__main__":
    main()
