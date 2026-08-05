#!/usr/bin/env python3
"""Draw the profile README's stat graphics straight from the GitHub GraphQL API.

Standard library only -- no third-party service sits between the data and the
page, so nothing here can rate-limit, change its output, or go dark. That is the
whole point: every graphic is generated and committed, not hotlinked.

Outputs, all sharing one visual language with the wordmark:
    stats.svg   contributions total, active days, best week, weekly sparkline
    clock.svg   commits by hour of day
    recent.svg  the repositories most recently pushed to
    stack.svg   what the page says it works in
    streak.svg  current and longest run of contributing days
    langs.svg   top languages, by bytes written and by repo count
    heatmap.svg the last year as the familiar grid of contribution boxes
    hd-*.svg    section headings, so they carry the page's typeface

Motion is declarative because GitHub strips <script> from READMEs: SMIL for
most graphics, CSS keyframes for heatmap.svg so its 365 moving parts can be
put behind prefers-reduced-motion.

Env:
    GITHUB_TOKEN  required
    GH_LOGIN      user to summarise (default: OnePaperHoon)
    OUT_DIR       where to write   (default: repository root)
"""
import base64
import functools
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

ENDPOINT = "https://api.github.com/graphql"

# Two things are pinned deliberately:
#   privacy: PUBLIC  -- a personal token sees private repos and the workflow
#     token does not, so without this the language totals disagree run to run.
#   isFork: false    -- forks would count someone else's bytes as yours.
QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date weekday } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 privacy: PUBLIC) {
      nodes {
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    recent: repositories(first: 20, ownerAffiliations: OWNER, isFork: false,
                         privacy: PUBLIC,
                         orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes {
        name
        pushedAt
        primaryLanguage { name }
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 100) {
                nodes { committedDate author { user { login } } }
              }
            }
          }
        }
      }
    }
  }
}
"""

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")

# One ink for data, one for emphasis, one for muted labels, plus a hairline and
# the page surface. Kept close to GitHub's own greys so the page sits in its
# container rather than on top of it.
PALETTE = {
    "light": dict(ink="#6e7681", strong="#424a53", muted="#8c959f",
                  line="#d8dee4", surface="#ffffff", wash=0.13),
    "dark": dict(ink="#c9d1d9", strong="#f0f6fc", muted="#8b949e",
                 line="#30363d", surface="#0d1117", wash=0.16),
}
FONT_STACK = ("JBMono,ui-monospace,SFMono-Regular,Menlo,Consolas,"
              "&apos;Liberation Mono&apos;,monospace")

COL = 820                       # every graphic shares one column width
GUTTER = 0                      # content origin -- markdown text and the section
                                # headings both start at the image's left edge,
                                # so every drawn block has to start there too or
                                # it reads as indented against them
DAY_GUTTER = 26                 # ...except the heatmap, whose weekday labels
                                # hang in a margin. Its leftmost ink is the
                                # label, and that is what lines up at GUTTER.
ROW = 24                        # row pitch. GitHub sets markdown's line box to
                                # 16px x 1.5 = 24px, so a drawn block on any
                                # other pitch beats against the prose around it
BODY = 12                       # body text inside a drawn block
LABEL = 9                       # the small-caps label above one

SWEEP = 1.25                    # seconds for a full left-to-right reveal
RAMP = [" ", ":", "+", "#", "@"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]


# ------------------------------------------------------------------ typeface

@functools.lru_cache(maxsize=None)
def _face(filename, weight):
    with open(os.path.join(FONT_DIR, filename), "rb") as fh:
        blob = base64.b64encode(fh.read()).decode("ascii")
    return (f"@font-face{{font-family:JBMono;font-style:normal;"
            f"font-weight:{weight};font-display:block;"
            f"src:url(data:font/woff2;base64,{blob}) format('woff2')}}")


def face_body():
    """Both weights of basic latin -- numbers and labels."""
    return _face("jbmono-400.woff2", 400) + _face("jbmono-600.woff2", 600)


def face_heading():
    """Only the letters the section headings spell."""
    return _face("jbmono-head.woff2", 600)


# ---------------------------------------------------------------------- data

def utc_window():
    """A whole-day window, so the buckets do not drift with request time.

    Measuring "the past year" from the current instant shifts days between week
    buckets, which nudges the sparkline a fraction of a pixel and commits noise
    every single night.
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    return f"{start.isoformat()}T00:00:00Z", f"{today.isoformat()}T23:59:59Z"


def fetch(login, token):
    since, until = utc_window()
    payload = json.dumps({
        "query": QUERY,
        "variables": {"login": login, "from": since, "to": until},
    }).encode()
    request = urllib.request.Request(ENDPOINT, data=payload, headers={
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": f"{login}-profile-stats",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    if "errors" in body:
        raise SystemExit(f"GraphQL errors: {body['errors']}")
    user = (body.get("data") or {}).get("user")
    if not user:
        raise SystemExit(f"no such user: {login}")
    return user


def short_date(iso):
    d = date.fromisoformat(iso)
    return f"{MONTHS[d.month - 1]} {d.day}"


def find_streaks(days):
    """Longest and current runs of days carrying at least one contribution.

    A zero on the final day does not end the current streak -- that day is still
    in progress. Any earlier zero does.
    """
    longest = dict(length=0, start=None, end=None)
    run = 0
    run_start = None
    for day in days:
        if day["contributionCount"] > 0:
            run += 1
            run_start = run_start or day["date"]
            if run > longest["length"]:
                longest = dict(length=run, start=run_start, end=day["date"])
        else:
            run, run_start = 0, None

    current = dict(length=0, start=None, end=None)
    trail = days[:-1] if days and days[-1]["contributionCount"] == 0 else days
    for day in reversed(trail):
        if day["contributionCount"] == 0:
            break
        current["length"] += 1
        current["start"] = day["date"]
        current["end"] = current["end"] or day["date"]
    return current, longest


def rank_languages(repos):
    """Totals by bytes written, and counts by each repo's primary language."""
    bytes_by = {}
    repos_by = {}
    for node in repos:
        edges = (node.get("languages") or {}).get("edges") or []
        for edge in edges:
            name = edge["node"]["name"]
            bytes_by[name] = bytes_by.get(name, 0) + edge["size"]
        if edges:
            primary = edges[0]["node"]["name"]
            repos_by[primary] = repos_by.get(primary, 0) + 1

    def top5(table):
        # name is the tiebreak, so equal values never swap places between runs
        return sorted(table.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    return top5(bytes_by), top5(repos_by)


def commit_clock(repos, login, offset_hours):
    """Commits bucketed by local hour of day, across the recently pushed repos.

    Authorship is filtered here rather than in the query: the history connection
    takes an author id, which this query has no way to reference before it has
    fetched it. Bot and co-author commits would otherwise land in the histogram.
    """
    hours = [0] * 24
    counted = 0
    for repo in repos:
        branch = repo.get("defaultBranchRef")
        if not branch or not branch.get("target"):
            continue
        for commit in branch["target"]["history"]["nodes"]:
            who = ((commit.get("author") or {}).get("user") or {}).get("login")
            if who != login:
                continue
            stamp = datetime.fromisoformat(
                commit["committedDate"].replace("Z", "+00:00"))
            hours[(stamp.hour + offset_hours) % 24] += 1
            counted += 1
    return hours, counted


def recent_pushes(repos, limit=5):
    today = datetime.now(timezone.utc).date()
    out = []
    for repo in repos[:limit]:
        pushed = date.fromisoformat(repo["pushedAt"][:10])
        days = (today - pushed).days
        if days <= 0:
            ago = "today"
        elif days == 1:
            ago = "yesterday"
        elif days < 30:
            ago = f"{days}d ago"
        elif days < 365:
            ago = f"{days // 30}mo ago"
        else:
            ago = f"{days // 365}y ago"
        out.append(dict(name=repo["name"],
                        lang=(repo.get("primaryLanguage") or {}).get("name", ""),
                        ago=ago))
    return out


def summarise(user, login, tz_offset):
    calendar = user["contributionsCollection"]["contributionCalendar"]
    weeks = [w["contributionDays"] for w in calendar["weeks"]]
    days = [d for week in weeks for d in week]
    weekly = [sum(d["contributionCount"] for d in week) for week in weeks]
    current, longest = find_streaks(days)
    by_bytes, by_repos = rank_languages(user["repositories"]["nodes"])
    recent = user["recent"]["nodes"]
    hours, clock_total = commit_clock(recent, login, tz_offset)
    return dict(
        hours=hours,
        clock_total=clock_total,
        recent=recent_pushes(recent),
        total=calendar["totalContributions"],
        active=sum(1 for d in days if d["contributionCount"] > 0),
        span=len(days),
        best_week=max(weekly) if weekly else 0,
        weekly=weekly,
        weeks=weeks,
        current=current,
        longest=longest,
        by_bytes=by_bytes,
        by_repos=by_repos,
    )


# ------------------------------------------------------------------- drawing

def _classes(theme):
    t = PALETTE[theme]
    return (f".ink{{fill:{t['ink']}}}.ink-s{{stroke:{t['ink']}}}"
            f".strong{{fill:{t['strong']}}}.muted{{fill:{t['muted']}}}"
            f".rule{{stroke:{t['line']}}}.knockout{{stroke:{t['surface']}}}"
            f".wash{{fill:{t['ink']};opacity:{t['wash']}}}")


def open_svg(width, height, font=None):
    css = (f"<style>{font or face_body()}{_classes('light')}"
           f"@media(prefers-color-scheme:dark){{{_classes('dark')}}}</style>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" fill="none" '
            f'font-family="{FONT_STACK}">{css}')


def appear(at, dur=0.45):
    return (f'<animate attributeName="opacity" from="0" to="1" '
            f'begin="{at:.2f}s" dur="{dur}s" fill="freeze"/>')


def sweep(name, x, y, w, h, at, dur=SWEEP):
    """A left-to-right clip reveal, plus the cursor block riding its edge."""
    clip = (f'<clipPath id="{name}"><rect x="{x}" y="{y}" height="{h}" '
            f'width="0"><animate attributeName="width" from="0" to="{w}" '
            f'begin="{at:.2f}s" dur="{dur}s" fill="freeze"/></rect></clipPath>')
    cursor = (f'<rect y="{y}" width="2" height="{h}" class="ink" opacity="0">'
              f'<animate attributeName="x" from="{x}" to="{x + w}" '
              f'begin="{at:.2f}s" dur="{dur}s" fill="freeze"/>'
              f'<set attributeName="opacity" to="0.55" begin="{at:.2f}s"/>'
              f'<set attributeName="opacity" to="0" '
              f'begin="{at + dur:.2f}s"/></rect>')
    return clip, cursor


def text(x, y, body, size=11, cls="muted", anchor="start", extra=""):
    align = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}"'
            f'{align}{extra}>{body}</text>')


def bar(x, y, w, h, radius=3.0):
    """Rounded at the data end, square at the baseline it grows from."""
    if w <= 0.6:
        return ""
    r = min(radius, h / 2.0, w)
    return (f'<path d="M{x:.1f} {y:.1f}H{x + w - r:.1f}'
            f'Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + r:.1f}'
            f'V{y + h - r:.1f}Q{x + w:.1f} {y + h:.1f} {x + w - r:.1f} {y + h:.1f}'
            f'H{x:.1f}Z" class="ink"/>')


def bar_up(x, y, w, h, radius=2.5):
    """Vertical bar: rounded at the data end on top, square on the baseline."""
    if h <= 0.6:
        return ""
    r = min(radius, w / 2.0, h)
    return (f'<path d="M{x:.1f} {y + h:.1f}V{y + r:.1f}'
            f'Q{x:.1f} {y:.1f} {x + r:.1f} {y:.1f}'
            f'H{x + w - r:.1f}Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + r:.1f}'
            f'V{y + h:.1f}Z" class="ink"/>')


def draw_stats(s):
    height = 148
    weekly = s["weekly"] or [0]
    peak = max(weekly) or 1

    out = [open_svg(COL, height)]
    out.append(f'<g opacity="0">{appear(0.10)}'
               + text(0, 50, s["total"], 52, "strong", extra=' font-weight="600"')
               + text(0, 72, "contributions in the last year", 12) + "</g>")
    for i, (value, caption) in enumerate([(s["active"], "active days"),
                                          (s["best_week"], "best week")]):
        out.append(f'<g opacity="0">{appear(0.30 + i * 0.12)}'
                   + text(COL, 30 + i * 40, value, 19, "strong", "end",
                          ' font-weight="600"')
                   + text(COL, 47 + i * 40, caption, 11, "muted", "end") + "</g>")

    floor, ceiling = height - 10, height - 58
    reach = floor - ceiling
    stride = COL / max(len(weekly) - 1, 1)
    points = [(i * stride, floor - (v / peak) * reach)
              for i, v in enumerate(weekly)]

    clip, cursor = sweep("sp", 0, ceiling - 6, COL, reach + 8, 0.50)
    out.append(clip)
    out.append('<g clip-path="url(#sp)">')
    out.append(f'<path d="M{points[0][0]:.1f} {floor:.1f}'
               + "".join(f"L{x:.1f} {y:.1f}" for x, y in points)
               + f'L{points[-1][0]:.1f} {floor:.1f}Z" class="wash"/>')
    out.append(f'<path d="M{points[0][0]:.1f} {points[0][1]:.1f}'
               + "".join(f"L{x:.1f} {y:.1f}" for x, y in points[1:])
               + '" class="ink-s" stroke-width="2" stroke-linejoin="round" '
                 'stroke-linecap="round"/>')
    out.append("</g>")
    out.append(cursor)
    ex, ey = points[-1]
    out.append(f'<circle cx="{ex - 2:.1f}" cy="{ey:.1f}" r="4.5" '
               f'class="strong knockout" stroke-width="2" opacity="0">'
               f'{appear(0.50 + SWEEP, 0.35)}</circle>')
    out.append("</svg>")
    return "".join(out)


def draw_streak(s):
    height = 96
    panels = []
    for key, caption in (("current", "current streak"),
                         ("longest", "longest streak")):
        run = s[key]
        window = (f"{short_date(run['start'])} &#8211; {short_date(run['end'])}"
                  if run["length"] else "&#8212;")
        panels.append((run["length"], caption, window))

    out = [open_svg(COL, height)]
    mid = COL / 2
    out.append(f'<line x1="{mid:.0f}" y1="16" x2="{mid:.0f}" y2="80" '
               f'class="rule" stroke-width="1" opacity="0">{appear(0.20)}</line>')
    for i, (value, caption, window) in enumerate(panels):
        x = GUTTER if i == 0 else mid + GUTTER
        out.append(f'<g opacity="0">{appear(0.12 + i * 0.14)}'
                   + text(x, 44, value, 34, "strong", extra=' font-weight="600"')
                   + text(x, 64, caption, 11)
                   + text(x, 80, window, 10) + "</g>")
    out.append("</svg>")
    return "".join(out)


def draw_langs(s):
    lines = max(len(s["by_bytes"]), len(s["by_repos"]), 1)
    height = 26 + lines * ROW + 6
    half = (COL - GUTTER - 30) / 2
    name_col = 92
    bar_room = half - name_col - 48

    out = [open_svg(COL, height)]
    panels = [(GUTTER, "by bytes", s["by_bytes"], True),
              (GUTTER + half + 30, "by repos", s["by_repos"], False)]
    for pi, (px, title, rows, as_share) in enumerate(panels):
        out.append(f'<g opacity="0">{appear(0.10 + pi * 0.10)}'
                   + text(px, 12, title.upper(), LABEL, "muted",
                          extra=' letter-spacing="1.3"') + "</g>")
        if not rows:
            continue
        biggest = max(v for _, v in rows) or 1
        total = sum(v for _, v in rows) or 1
        name = f"lg{pi}"
        clip, cursor = sweep(name, px + name_col, 20, bar_room, lines * ROW,
                             0.34 + pi * 0.12, 0.95)
        out.append(clip)
        for ri, (label, value) in enumerate(rows):
            y = 26 + ri * ROW
            readout = f"{value / total * 100:.0f}%" if as_share else f"{value}"
            out.append(f'<g opacity="0">{appear(0.24 + pi * 0.10 + ri * 0.05)}'
                       + text(px, y + 8, label.lower()[:12], BODY, "strong")
                       + text(px + half - 6, y + 8, readout, BODY, "muted", "end")
                       + "</g>")
            out.append(f'<g clip-path="url(#{name})">'
                       + bar(px + name_col, y, bar_room * value / biggest, 7)
                       + "</g>")
        out.append(cursor)
    out.append("</svg>")
    return "".join(out)


# GitHub's own two ramps. The empty cell is the reason both are needed: at
# #161b22 it is nearly black, which reads as a dark grid stamped on a white page
# for anyone browsing in the light theme.
HEAT_LIGHT = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]
HEAT_DARK = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]


def draw_heatmap(s):
    """The year as the familiar grid of rounded, coloured boxes.

    Animated with CSS keyframes rather than SMIL. Both survive being loaded
    through <img>, but only CSS can be put behind prefers-reduced-motion, and a
    graphic made of 365 independently moving parts is exactly the kind that
    should hold still when someone has asked for that.
    """
    weeks = s["weeks"]
    gap = 3.0
    room = COL - DAY_GUTTER - 10
    step = room / max(len(weeks), 1)
    cell = step - gap
    top = 58
    height = int(top + 7 * step + 30)

    def level(count):
        for i, cut in enumerate((0, 2, 5, 9)):
            if count <= cut:
                return i
        return 4

    swatch = "".join(f".h{i}{{fill:{c}}}" for i, c in enumerate(HEAT_LIGHT))
    swatch_dark = "".join(f".h{i}{{fill:{c}}}" for i, c in enumerate(HEAT_DARK))
    css = (f"{swatch}"
           f"@media(prefers-color-scheme:dark){{{swatch_dark}}}"
           ".cl{opacity:0;transform-box:fill-box;transform-origin:center;"
           "animation:hm .5s cubic-bezier(.2,.8,.2,1) both}"
           "@keyframes hm{from{opacity:0;transform:scale(.4)}"
           "to{opacity:1;transform:scale(1)}}"
           "@media(prefers-reduced-motion:reduce){"
           ".cl{opacity:1;animation:none}}")

    out = [open_svg(COL, height)]
    out.append(f"<style>{css}</style>")
    out.append(f'<g opacity="0">{appear(0.10)}'
               + text(GUTTER, 16, "THE YEAR", 9, "muted",
                      extra=' letter-spacing="1.3"')
               + text(GUTTER, 32,
                      f"{s['active']} of {s['span']} days had a contribution", 11)
               + "</g>")

    seen, last_x = None, -999.0
    for wi, week in enumerate(weeks):
        month = int(week[0]["date"][5:7])
        x = DAY_GUTTER + wi * step
        if month != seen and wi < len(weeks) - 1 and x - last_x >= 46:
            out.append(text(x, 50, MONTHS[month - 1], 9, "muted"))
            last_x = x
        seen = month

    for row, caption in ((1, "mon"), (3, "wed"), (5, "fri")):
        out.append(text(DAY_GUTTER - 7, top + row * step + cell * 0.78, caption, 9,
                        "muted", "end"))

    longest = (len(weeks) - 1) * 0.022 + 6 * 0.05
    for wi, week in enumerate(weeks):
        x = DAY_GUTTER + wi * step
        for day in week:
            row = day.get("weekday", 0)
            y = top + row * step
            delay = wi * 0.022 + row * 0.05
            out.append(f'<rect class="cl h{level(day["contributionCount"])}" '
                       f'x="{x:.1f}" y="{y:.1f}" width="{cell:.1f}" '
                       f'height="{cell:.1f}" rx="2.2" '
                       f'style="animation-delay:{delay:.3f}s"/>')

    legend_y = top + 7 * step + 8
    lx = COL - 10 - (len(HEAT_LIGHT) * (cell + 2) + 46)
    out.append(f'<g opacity="0">{appear(longest + 0.5)}')
    out.append(text(lx - 6, legend_y + cell * 0.8, "less", 9, "muted", "end"))
    for i in range(len(HEAT_LIGHT)):
        out.append(f'<rect class="h{i}" x="{lx:.1f}" y="{legend_y:.1f}" '
                   f'width="{cell:.1f}" height="{cell:.1f}" rx="2.2"/>')
        lx += cell + 2
    out.append(text(lx + 4, legend_y + cell * 0.8, "more", 9, "muted"))
    out.append("</g>")

    out.append("</svg>")
    return "".join(out)


def draw_clock(s, tz_label):
    """Commits by hour of day, as vertical bars.

    The page already spends its character ramp on the heatmap; showing the day
    the same way would read as a second calendar. Bars keep the two apart.
    """
    height = 132
    hours = s["hours"]
    peak = max(hours) or 1
    total = s["clock_total"]

    left = GUTTER
    room = COL - left - 10
    slot = room / 24.0
    bar_w = slot * 0.62
    floor, top = height - 30, 42

    out = [open_svg(COL, height)]
    out.append(f'<g opacity="0">{appear(0.10)}'
               + text(left, 16, "THE DAY", 9, "muted",
                      extra=' letter-spacing="1.3"')
               + text(left, 32,
                      f"{total} commits by hour, {tz_label}", 11) + "</g>")

    busiest = hours.index(peak)
    out.append(f'<g opacity="0">{appear(1.20)}'
               + text(COL - 6, 32, f"busiest around {busiest:02d}:00", 9,
                      "muted", "end") + "</g>")

    clip, cursor = sweep("cl", left, top - 6, room, floor - top + 8, 0.34, 1.00)
    out.append(clip)
    out.append('<g clip-path="url(#cl)">')
    for h, count in enumerate(hours):
        x = left + h * slot + (slot - bar_w) / 2
        tall = (count / peak) * (floor - top)
        # a hairline base keeps an empty hour visible as a considered zero
        out.append(f'<rect x="{x:.1f}" y="{floor - 1:.1f}" width="{bar_w:.1f}" '
                   f'height="1" class="wash"/>')
        if tall > 0.5:
            out.append(bar_up(x, floor - tall, bar_w, tall))
    out.append("</g>")
    out.append(cursor)

    for h in range(0, 24, 3):
        x = left + h * slot + slot / 2
        out.append(text(x, floor + 15, f"{h:02d}", 9, "muted", "middle"))
    out.append("</svg>")
    return "".join(out)


def draw_recent(s):
    """The last handful of repositories to receive a push."""
    rows = s["recent"] or []
    height = 26 + max(len(rows), 1) * ROW + 6

    out = [open_svg(COL, height)]
    out.append(f'<g opacity="0">{appear(0.10)}'
               + text(GUTTER, 12, "RECENTLY PUSHED", LABEL, "muted",
                      extra=' letter-spacing="1.3"') + "</g>")
    for i, repo in enumerate(rows):
        y = 26 + i * ROW
        out.append(f'<g opacity="0">{appear(0.20 + i * 0.07)}'
                   + text(GUTTER, y + 8, repo["name"][:28], BODY, "strong")
                   + text(GUTTER + 300, y + 8, repo["lang"].lower(), BODY, "muted")
                   + text(COL - 6, y + 8, repo["ago"], BODY, "muted", "end")
                   + "</g>")
    out.append("</svg>")
    return "".join(out)


# What the page says it works in. Authored, not derived -- langs.svg already
# reports what the bytes actually say, and the two answer different questions.
# Named apart from FONT_STACK on purpose: they collided once, and the list
# silently became the font-family of every graphic on the page.
TECH_STACK = [
    ("languages", "typescript  c  c++  rust"),
    ("runtime", "node  react  react native"),
    ("data", "cloudflare d1  drizzle  sqlite  mongodb"),
    ("infra", "cloudflare workers  docker  nginx  linux  git"),
]


def draw_stack():
    """The stack as drawn type, so it carries the page's face like the headings.

    Left as markdown it would render in GitHub's own monospace -- the one place
    on the page where the typeface would break.
    """
    height = 12 + len(TECH_STACK) * ROW + 6
    out = [open_svg(COL, height)]
    for i, (label, items) in enumerate(TECH_STACK):
        y = 12 + i * ROW
        out.append(f'<g opacity="0">{appear(0.10 + i * 0.09)}'
                   + text(GUTTER, y + 12, label.upper(), LABEL, "muted",
                          extra=' letter-spacing="1.3"')
                   + text(GUTTER + 110, y + 12, items, BODY, "strong")
                   + "</g>")
    out.append("</svg>")
    return "".join(out)


# Where I have been. Drawn rather than written as markdown for one reason: the
# date column only lines up because every row starts with a fixed-width span,
# and centring the page would centre each <samp> line independently and pull
# that column apart. Inside an image the rows keep their own left edge.
CAREER = [
    ("2026.05 &#8211; present", "Shopinx", "서비스 개발"),
    ("2025.06 &#8211; 2025.12", "Newtonz", "개발 총괄"),
    ("2025.03 &#8211; present", "42Seoul", "member"),
    ("2023.09 &#8211; 2025.03", "42Seoul", "learner (&#201;cole 42)"),
]


def draw_career():
    height = 12 + len(CAREER) * ROW + 6
    out = [open_svg(COL, height)]
    for i, (span, org, role) in enumerate(CAREER):
        y = 12 + i * ROW
        out.append(f'<g opacity="0">{appear(0.10 + i * 0.08)}'
                   + text(GUTTER, y + 12, span, BODY, "muted")
                   + text(GUTTER + 150, y + 12, org, BODY, "strong")
                   + text(GUTTER + 232, y + 12, "&#183;", BODY, "muted")
                   + text(GUTTER + 256, y + 12, role, BODY, "muted")
                   + "</g>")
    out.append("</svg>")
    return "".join(out)


def draw_heading(word):
    """A section label in the page's own typeface, with a rule running right.

    GitHub strips <style> and style= from markdown, so a real markdown heading
    can only ever render in GitHub's sans. An image is the only way to put this
    page's face on it. The rule starts past the widest plausible advance, so a
    narrower fallback font opens a slightly bigger gap rather than colliding.
    """
    size, height = 16, 26
    ends_at = len(word) * size * 0.6 + 18
    out = [open_svg(COL, height, font=face_heading())]
    out.append(text(0, 18, word, size, "strong", extra=' font-weight="600"'))
    out.append(f'<line x1="{ends_at:.0f}" y1="12.5" x2="{COL}" y2="12.5" '
               f'class="rule" stroke-width="1"/>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------- main

def write_if_changed(path, svg):
    previous = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            previous = fh.read()
    if previous == svg:
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return True


HEADINGS = ["about", "stack", "projects", "stats", "algorithm"]


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    login = os.environ.get("GH_LOGIN", "OnePaperHoon")
    out_dir = os.environ.get("OUT_DIR", ".")
    tz_offset = int(os.environ.get("TZ_OFFSET", "9"))
    tz_label = os.environ.get("TZ_LABEL", "KST")

    s = summarise(fetch(login, token), login, tz_offset)
    files = {
        "stats.svg": draw_stats(s),
        "streak.svg": draw_streak(s),
        "langs.svg": draw_langs(s),
        "heatmap.svg": draw_heatmap(s),
        "clock.svg": draw_clock(s, tz_label),
        "recent.svg": draw_recent(s),
        "stack.svg": draw_stack(),
        "career.svg": draw_career(),
    }
    for word in HEADINGS:
        files[f"hd-{word.replace(' ', '-')}.svg"] = draw_heading(word)

    # Every graphic inlines its typeface, so every graphic must actually ask for
    # it. This shipped broken once -- a constant named STACK was shadowed by a
    # list of the same name and became the font-family of the whole page -- and
    # nothing about the output looked wrong enough to notice.
    # Checked against a literal, not against FONT_STACK: comparing the output to
    # the same constant that produced it passes no matter what that constant
    # holds, which is precisely how this shipped broken the first time.
    for name, svg in files.items():
        if 'font-family="JBMono,' not in svg:
            sys.exit(f"{name}: font-family is not the JBMono stack -- "
                     f"the inlined face would never be selected")

    changed = [name for name, svg in files.items()
               if write_if_changed(os.path.join(out_dir, name), svg)]

    print(f"{s['total']} contributions, {s['active']}/{s['span']} active days, "
          f"best week {s['best_week']}, current streak {s['current']['length']}, "
          f"longest {s['longest']['length']}")
    print("by bytes: " + (", ".join(f"{n} {v}" for n, v in s["by_bytes"]) or "-"))
    print(f"clock: {s['clock_total']} authored commits, busiest "
          f"{s['hours'].index(max(s['hours'])):02d}:00 {tz_label}")
    print("recent: " + ", ".join(f"{r['name']} ({r['ago']})" for r in s["recent"]))
    print("updated: " + (", ".join(sorted(changed)) if changed else "nothing"))


if __name__ == "__main__":
    main()
