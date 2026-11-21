#!/usr/bin/env python3
"""Generate docs/demo.gif: a fake terminal drawn with Pillow from REAL BitSearch output
recorded in docs/demo_*.ansi (no screen capture, no metadata in the GIF).

Re-record the outputs (public sources only, empty HOME so no private config is used):
    H=$(mktemp -d)
    HOME=$H script -qec "stty cols 112; python3 bitsearch.py ubuntu 24.04 --public -n 8" /dev/null | tr -d '\\r' > docs/demo_1.ansi
    ...
Usage: python3 docs/make_demo.py   (needs Pillow)
"""
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 13)
CW, CH = 8, 17
COLS, ROWS = 124, 22
W, H = COLS * CW + 20, ROWS * CH + 44
BG, FG, BAR = (24, 20, 32), (205, 200, 215), (44, 36, 60)
LIGHT = (240, 235, 250)
ANSI = re.compile(r"\x1b\[([0-9;]*)m")


def xterm256(n):
    """xterm 256-color index -> RGB."""
    if n < 16:
        base = [(0, 0, 0), (205, 49, 49), (13, 188, 121), (229, 229, 16), (36, 114, 200),
                (188, 63, 188), (17, 168, 205), (229, 229, 229)]
        return base[n % 8]
    if n >= 232:
        v = 8 + (n - 232) * 10
        return (v, v, v)
    n -= 16
    lv = [0, 95, 135, 175, 215, 255]
    return (lv[n // 36], lv[(n // 6) % 6], lv[n % 6])


def parse(text):
    """ANSI text -> list of lines, each a list of (char, color)."""
    lines, cur, col, pos = [], [], FG, 0

    def put(chunk):
        nonlocal cur
        for ch in chunk:
            if ch == "\n":
                lines.append(cur)
                cur = []
            else:
                cur.append((ch, col))

    for m in ANSI.finditer(text):
        put(text[pos:m.start()])
        pos = m.end()
        p = m.group(1)
        if p in ("0", ""):
            col = FG
        elif p.startswith("38;5;"):
            col = xterm256(int(p.split(";")[2]))
    put(text[pos:])
    if cur:
        lines.append(cur)
    return lines


def render(lines, cursor=True):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 24], fill=BAR)
    for i, c in enumerate([(200, 70, 60), (210, 180, 60), (120, 90, 200)]):
        d.ellipse([10 + i * 18, 7, 20 + i * 18, 17], fill=c)
    d.text((W // 2 - 50, 5), "bitsearch - demo", font=FONT, fill=(160, 150, 185))
    lines = lines[-ROWS:]
    for y, line in enumerate(lines):
        for x, (ch, col) in enumerate(line[:COLS]):
            d.text((10 + x * CW, 32 + y * CH), ch, font=FONT, fill=col)
    if cursor and lines:
        x0 = 10 + min(len(lines[-1]), COLS) * CW
        y0 = 32 + (len(lines) - 1) * CH
        d.rectangle([x0, y0, x0 + CW - 2, y0 + CH - 3], fill=(177, 140, 255))
    return im


frames, durs = [], []


def add(lines, ms, cursor=True):
    frames.append(render(lines, cursor))
    durs.append(ms)


def typed(lines, text, ms=45):
    for i in range(1, len(text) + 1):
        add(lines[:-1] + [lines[-1] + [(c, LIGHT) for c in text[:i]]], ms)
    lines[-1] = lines[-1] + [(c, LIGHT) for c in text]


def scene(cmd, ansi_file, line_ms=(110, 230), hold=2600, note=None):
    screen = [[(c, (150, 135, 190)) for c in "$ "]]
    add(screen, 500)
    typed(screen, cmd)
    add(screen, 500, False)
    out = [ln for ln in parse((HERE / ansi_file).read_text())]
    banner_rows = 5 if ansi_file == "demo_1.ansi" else 0
    for i, ln in enumerate(out):
        screen.append(ln)
        add(screen, line_ms[0] if i < banner_rows else line_ms[1], False)
    if note:
        screen += [[], [(c, (130, 120, 160)) for c in note]]
        add(screen, 300, False)
    add(screen, hold, False)


scene("bitsearch ubuntu 24.04 --public -n 8", "demo_1.ansi")
scene("bitsearch ubuntu 24.04 --public --min-seeders 10 --no-banner", "demo_2.ansi", hold=2200)
scene('bitsearch "linux mint" -s archive.org -n 4 --no-banner', "demo_3.ansi", hold=3200,
      note="# real output, public sources only, free / Linux content")

frames[0].save(HERE / "demo.gif", save_all=True, append_images=frames[1:], duration=durs,
               loop=0, optimize=True)
print(f"{len(frames)} frames -> docs/demo.gif")
