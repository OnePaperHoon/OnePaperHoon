#!/usr/bin/env python3
"""Fetch the JetBrains Mono sources the other scripts cut their subsets from.

The `.ttf` files are build inputs only -- nothing ships them, the SVGs carry
woff2 subsets instead -- so they are cached here and kept out of the repository
rather than committed. The release tag is pinned, so a rebuild years from now
produces byte-identical subsets.
"""
import io
import os
import urllib.request
import zipfile

VERSION = "2.304"
RELEASE = ("https://github.com/JetBrains/JetBrainsMono/releases/download/"
           f"v{VERSION}/JetBrainsMono-{VERSION}.zip")

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "fonts")


def ensure(*names):
    """Return local paths for the named .ttf files, downloading once if needed."""
    paths = {n: os.path.join(CACHE, n) for n in names}
    missing = [n for n, p in paths.items() if not os.path.exists(p)]
    if missing:
        print(f"fetching JetBrains Mono {VERSION} for {', '.join(missing)}")
        with urllib.request.urlopen(RELEASE, timeout=60) as response:
            blob = response.read()
        archive = zipfile.ZipFile(io.BytesIO(blob))
        wanted = {os.path.basename(m): m for m in archive.namelist()
                  if m.endswith(".ttf")}
        for name in missing:
            if name not in wanted:
                raise SystemExit(f"{name} is not in the release archive")
            with open(paths[name], "wb") as fh:
                fh.write(archive.read(wanted[name]))
            print(f"  cached {name}")
    return paths
