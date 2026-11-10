#!/usr/bin/env python3
"""thrill.com TOURNAMENT BRACKET (1080x1350), Round of 16 / Quarter-finals / Semi-finals to the Final.

Usage:
    python3 bracket_render.py data.json out.png          (carousel layout writes out_slide01.png, out_slide02.png)

data.json:
{
  "round": "QF",                       # first round shown: "R16", "QF" or "SF"
  "layout": "carousel",                # R16 only: "carousel" (default, 2 slides sharing the final), "column" or "mirrored"
  "date": "Nov 13", "city": "Dubai",   # line under the title (day of that round + city)
  "tournament": "Dubai P1", "logo": "logo_dubai_p1.png", "category": "",
  "texture": "streaks",                # background: streaks, court, ink
  "matches": [                         # first round, in draw order (top to bottom)
    {"teams": [{"seed": 1, "players": [{"name": "A. Coello", "flag": "es"}, {"name": "A. Tapia", "flag": "ar"}]},
               {"players": [{"name": "J. Nieto", "flag": "es"}, {"name": "M. Yanguas", "flag": "es"}]}],
     "sets": [[6, 3], [6, 4]], "winner": 0},          # sets/winner only once the match is played
    ...
  ],
  "results": {"SF": [{"sets": [[6, 4], [7, 5]], "winner": 0}, ...], "F": [...]}   # optional, later rounds
}
Winners move into the next round automatically; open slots show "WINNER QF1" etc.
"""
import io, json, math, os, re, sys, urllib.request
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

W, H = 1080, 1350
HERE = os.path.dirname(os.path.abspath(__file__))
ACCENT = (90, 245, 190)            # mint (same as the scoreboard)
ACCENT_D = (60, 170, 135)
INK = (3, 6, 18)
CARD_FILL = (8, 16, 44, 170)
WHITE = (255, 255, 255)
DIM = (150, 164, 196)
ROUND_NAMES = {"R16": "ROUND OF 16", "QF": "QUARTER-FINALS", "SF": "SEMI-FINALS", "F": "FINAL"}
NEXT = {"R16": "QF", "QF": "SF", "SF": "F"}
SHORT = {"R16": "R16-", "QF": "QF", "SF": "SF", "F": "F"}
LABEL = {"QF": "QUARTER-FINAL", "SF": "SEMI-FINAL", "F": "FINAL"}

SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
DOWNLOADS = {
    "Anton.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    "Poppins-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
    "Inter-var.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
}


def inter(weight, size):
    f = ImageFont.truetype(asset("Inter-var.ttf"), size)
    f.set_variation_by_name(weight)
    return f
FLAG_SVG = "https://raw.githubusercontent.com/lipis/flag-icons/main/flags/4x3/{}.svg"


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def asset(name, required=True):
    stem, ext = os.path.splitext(name)
    key = _norm(stem)
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                fs, fe = os.path.splitext(f)
                if fe.lower() == ext.lower() and _norm(fs).startswith(key):
                    return os.path.join(d, f)
    if name in DOWNLOADS:
        dst = os.path.join(HERE, name)
        urllib.request.urlretrieve(DOWNLOADS[name], dst)
        return dst
    if required:
        raise FileNotFoundError(f"Missing asset: {name}")
    return None


def font(name, size):
    return ImageFont.truetype(asset(name), size)


# ---------- helpers (same as the World Cup scoreboard) ----------
def vgrad(w, h, stops):
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                k = (t - p0) / (p1 - p0) if p1 > p0 else 0
                g.putpixel((0, y), tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(4)))
                break
    return g.resize((w, h))


def hgrad(w, h, c0, c1):
    g = Image.new("RGBA", (w, 1))
    for x in range(w):
        k = x / (w - 1)
        g.putpixel((x, 0), tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(4)))
    return g.resize((w, h))


def rounded(im, r):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.size[0] - 1, im.size[1] - 1), r, fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), m))
    return im


def white_logo(path, size=None, box=None):
    """Logos are white: PNG with transparency, or white on black (luminance becomes alpha)."""
    im = Image.open(path)
    if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 250:
        a = im.getchannel("A")
        out = im.convert("RGBA")
    else:
        a = im.convert("L")
        out = Image.new("RGBA", im.size, (255, 255, 255, 255))
        out.putalpha(a)
    if size:
        out = out.resize(size, Image.LANCZOS)
    if box:
        out.thumbnail(box, Image.LANCZOS)
    return out


_FLAGS = {}


def flag(code, w, h, r=5):
    code = code.lower()
    if code not in _FLAGS:
        p = asset(f"flag_{code}.png", required=False)
        if p:
            im = Image.open(p).convert("RGBA")
        else:
            svg = urllib.request.urlopen(FLAG_SVG.format(code), timeout=15).read()
            try:
                import cairosvg
                im = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg, output_width=w * 3, output_height=h * 3))).convert("RGBA")
            except ImportError:
                import subprocess, tempfile
                with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as t:
                    t.write(svg)
                out = t.name + ".png"
                subprocess.run(["rsvg-convert", "-w", str(w * 3), "-h", str(h * 3), t.name, "-o", out], check=True)
                im = Image.open(out).convert("RGBA")
        _FLAGS[code] = im
    im = _FLAGS[code].resize((w, h), Image.LANCZOS)
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), m))
    return im


def text_spaced(d, xy, s, f, fill, spacing, anchor="ls"):
    x, y = xy
    for ch in s:
        d.text((x, y), ch, font=f, fill=fill, anchor=anchor)
        x += d.textlength(ch, font=f) + spacing
    return x


def name_caps(n):
    return n.strip().upper()


def draw_seed(base, xy, num, won, accent, style="badge"):
    """Seed as a small modern badge: rounded square, number in Inter, accent tint on the winner."""
    x, cy = xy
    if style == "label":  # minimal: tiny SEED caption over the number
        f_cap, f_num = inter("SemiBold", 12), inter("ExtraBold", 32)
        d = ImageDraw.Draw(base)
        col = accent if won else (200, 212, 236)
        text_spaced(d, (x + 1, cy - 14), "SEED", f_cap, col + (200,) if len(col) == 3 else col, 2)
        d.text((x, cy + 18), num, font=f_num, fill=(255, 255, 255) if won else (220, 228, 244), anchor="ls")
        return
    f_num = inter("Bold", 25 if len(num) < 2 else 22)
    w, h, r = 50, 44, 12
    badge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    if won:
        bd.rounded_rectangle((0, 0, w - 1, h - 1), r, fill=accent + (48,), outline=accent + (210,), width=2)
        tc = (255, 255, 255)
    else:
        bd.rounded_rectangle((0, 0, w - 1, h - 1), r, fill=(255, 255, 255, 22), outline=(255, 255, 255, 70), width=2)
        tc = (228, 234, 248)
    bd.text((w / 2, h / 2 + 1), num, font=f_num, fill=tc, anchor="mm")
    base.alpha_composite(badge, (int(x), int(cy - h / 2)))



# ---------- background textures ----------
def _noise(scale, seed, Wd=W):
    rng = np.random.default_rng(seed)
    small = rng.random((max(2, H // scale), max(2, Wd // scale))).astype(np.float32)
    return np.array(Image.fromarray((small * 255).astype(np.uint8)).resize((Wd, H), Image.BICUBIC), np.float32) / 255


def background(kind, Wd=W):
    yy = np.linspace(0, 1, H)[:, None]
    base = np.zeros((H, Wd, 3), np.float32)
    top, bot = np.array([3, 6, 18]), np.array([10, 28, 92])
    base[:] = top * (1 - yy[..., None] ** 1.3) + bot * (yy[..., None] ** 1.3)
    img = Image.fromarray(base.astype(np.uint8)).convert("RGBA")
    layer = Image.new("RGBA", (Wd, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if kind == "streaks":
        # soft diagonal light streaks + big blurred "bokeh" circles
        bands = [(-200, 260, 34), (260, 140, 22), (620, 320, 28), (980, 180, 20)]
        if Wd > W:
            bands += [(x + W, w_, a) for x, w_, a in bands]
        for x, w_, a in bands:
            d.polygon([(x, H), (x + w_, H), (x + w_ + 900, 0), (x + 900, 0)], fill=(60, 130, 255, a))
        layer = layer.filter(ImageFilter.GaussianBlur(60))
        b = Image.new("RGBA", (Wd, H), (0, 0, 0, 0)); bd = ImageDraw.Draw(b)
        circles = [(860, 520, 150, 40), (980, 980, 110, 34), (130, 820, 90, 26), (720, 1180, 70, 30), (300, 420, 60, 18)]
        if Wd > W:
            circles = [(c[0], c[1], c[2], c[3]) for c in circles[:3]] + [(W + 1080 - c[0], c[1] + 60, c[2], c[3]) for c in circles]
        for cx, cy, r, a in circles:
            bd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(120, 180, 255, a), width=10)
            bd.ellipse((cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8), fill=(70, 130, 255, a // 3))
        layer.alpha_composite(b.filter(ImageFilter.GaussianBlur(14)))
    elif kind == "court":
        # faint padel-court lines in perspective, glowing
        L = Image.new("RGBA", (Wd, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(L)
        vx, vy = 540, 520
        def p(u, v):  # u: -1..1 across, v: 0 (far) .. 1 (near)
            z = 0.35 + v * 1.9
            return (vx + u * 520 * z, vy + v * 1100)
        for u in (-1, -0.5, 0, 0.5, 1):
            ld.line([p(u, 0), p(u, 1)], fill=(140, 190, 255, 70 if u in (-1, 1) else 45), width=5)
        for v in (0, 0.18, 0.5, 0.82, 1):
            ld.line([p(-1, v), p(1, v)], fill=(140, 190, 255, 60 if v == 0.5 else 40), width=5 if v != 0.5 else 8)
        glow = L.filter(ImageFilter.GaussianBlur(10))
        layer.alpha_composite(glow); layer.alpha_composite(L.filter(ImageFilter.GaussianBlur(1.5)))
        g = Image.new("RGBA", (Wd, H), (0, 0, 0, 0))
        ImageDraw.Draw(g).ellipse((90, 700, 990, 1500), fill=(40, 110, 255, 70))
        layer.alpha_composite(g.filter(ImageFilter.GaussianBlur(120)))
    elif kind == "ink":
        # brushed electric-blue texture along the edges (like the quote overlay)
        n = 0.55 * _noise(6, 1, Wd) + 0.3 * _noise(24, 2, Wd) + 0.15 * _noise(90, 3, Wd)
        xs = np.linspace(-1, 1, Wd)[None, :]; ys = np.linspace(-1, 1, H)[:, None]
        edge = np.clip((np.maximum(abs(xs) * 1.05, abs(ys) * 0.95) - 0.55) / 0.45, 0, 1)
        streak = np.clip((n - 0.52) * 6, 0, 1) * edge
        a = (streak * 120).astype(np.uint8)
        ink = Image.new("RGBA", (Wd, H), (60, 140, 255, 0)); ink.putalpha(Image.fromarray(a, "L"))
        layer.alpha_composite(ink.filter(ImageFilter.GaussianBlur(0.8)))
        g = Image.new("RGBA", (Wd, H), (0, 0, 0, 0))
        ImageDraw.Draw(g).ellipse((-300, 900, 700, 1700), fill=(40, 110, 255, 80))
        ImageDraw.Draw(g).ellipse((600, -300, 1400, 500), fill=(40, 110, 255, 45))
        layer.alpha_composite(g.filter(ImageFilter.GaussianBlur(140)))
    img.alpha_composite(layer)
    # vignette + grain
    xs = np.tile(np.linspace(-1, 1, W), Wd // W)[None, :]; ys = np.linspace(-1, 1, H)[:, None]
    vig = (np.clip(np.sqrt(xs ** 2 * 0.6 + ys ** 2 * 0.6) - 0.45, 0, 1) * 150).astype(np.uint8)
    v = Image.new("RGBA", (Wd, H), (0, 0, 0, 255)); v.putalpha(Image.fromarray(vig, "L"))
    img.alpha_composite(v)
    arr = np.array(img, np.float32)
    arr[..., :3] = np.clip(arr[..., :3] + np.random.default_rng(5).normal(0, 6, (H, Wd))[..., None], 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


# ---------- text helpers ----------
def surname(name):
    parts = name.strip().split()
    return parts[-1] if len(parts) > 1 else name


def pair_runs(team, short=False):
    """[(flag, NAME), ...] for a team; short=True uses surnames only."""
    return [(p.get("flag"), (surname(p["name"]) if short else p["name"]).upper()) for p in team["players"][:2]]


def pair_width(runs, f, fh):
    fw = round(fh * 1.5)
    sep = f.getlength(" / ")
    w = 0
    for i, (fl, n) in enumerate(runs):
        if i:
            w += sep
        if fl:
            w += fw + fh * 0.4
        w += f.getlength(n)
    return w


def draw_pair(base, x, cy, runs, max_w, fs_max, fs_min, color, sep_color, font_name="Anton.ttf"):
    fs = fs_max
    while fs > fs_min:
        f = font(font_name, fs); fh = round(fs * 0.62)
        if pair_width(runs, f, fh) <= max_w:
            break
        fs -= 1
    f = font(font_name, fs); fh = round(fs * 0.62); fw = round(fh * 1.5)
    d = ImageDraw.Draw(base)
    for i, (fl, n) in enumerate(runs):
        if i:
            d.text((x, cy), " / ", font=f, fill=sep_color, anchor="lm"); x += f.getlength(" / ")
        if fl:
            try:
                base.alpha_composite(flag(fl, fw, fh, 3), (int(x), int(cy - fh / 2)))
            except Exception:
                pass
            x += fw + fh * 0.4
        d.text((x, cy), n, font=f, fill=color, anchor="lm"); x += f.getlength(n)
    return x


# All pairs in a layout use the same name size: the size at which this (very long) pair fits.
REF_FULL = [("es", "M. DEL CASTILLO"), ("ar", "L. CAMPAGNOLO")]
REF_SHORT = [(None, "DEL CASTILLO"), (None, "CAMPAGNOLO")]
REF_PLAYER = [("es", "M. DEL CASTILLO")]


def ref_size(avail, fs_max, fs_min, runs=REF_FULL, font_name="Anton.ttf"):
    fs = fs_max
    while fs > fs_min:
        f = font(font_name, fs)
        if pair_width(runs, f, round(fs * 0.62)) <= avail:
            break
        fs -= 1
    return fs


def small_seed(base, x, cy, num, won, size=30):
    f = inter("Bold", int(size * 0.56) if len(num) < 2 else int(size * 0.5))
    w, h = int(size * 1.12), size
    b = Image.new("RGBA", (w, h), (0, 0, 0, 0)); bd = ImageDraw.Draw(b)
    if won:
        bd.rounded_rectangle((0, 0, w - 1, h - 1), int(size * 0.27), fill=ACCENT + (48,), outline=ACCENT + (210,), width=2)
    else:
        bd.rounded_rectangle((0, 0, w - 1, h - 1), int(size * 0.27), fill=(255, 255, 255, 22), outline=(255, 255, 255, 70), width=2)
    bd.text((w / 2, h / 2 + 1), num, font=f, fill=WHITE, anchor="mm")
    base.alpha_composite(b, (int(x), int(cy - h / 2)))
    return w


def rrect(base, box, r, fill=None, outline=None, width=2):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, r, fill=fill, outline=outline, width=width)
    base.alpha_composite(layer)


def glass(base, box, r, tint=CARD_FILL):
    x0, y0, x1, y1 = [int(v) for v in box]
    crop = base.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(14))
    crop.alpha_composite(Image.new("RGBA", crop.size, tint))
    m = Image.new("L", crop.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, crop.width - 1, crop.height - 1), r, fill=255)
    base.paste(crop, (x0, y0), m)


# ---------- bracket data ----------
def build_rounds(data):
    """List of rounds; each round = list of slots {teams:[t0,t1] (or None), sets, winner, code}."""
    first = data["round"].upper()
    order = ["R16", "QF", "SF", "F"]
    rounds = order[order.index(first):]
    out = []
    prev = None
    for ri, rn in enumerate(rounds):
        if ri == 0:
            slots = [dict(m, code=f"{SHORT[rn]}{i + 1}") for i, m in enumerate(data["matches"])]
        else:
            slots = []
            for i in range(len(prev) // 2):
                a, b = prev[2 * i], prev[2 * i + 1]
                teams = [winner_team(a), winner_team(b)]
                s = dict(teams=teams, code=f"{SHORT[rn]}{i + 1}", feeds=[a["code"], b["code"]])
                slots.append(s)
        for sl in slots:
            check_slot(sl)
        out.append((rn, slots))
        prev = slots
    return out


def check_slot(slot):
    """Sets and winner must agree (catches reading mistakes)."""
    st, w = slot.get("sets"), slot.get("winner")
    if st and w is not None:
        won = [sum(1 for x in st if x[i] > x[1 - i]) for i in (0, 1)]
        if won[w] <= won[1 - w]:
            raise SystemExit(f"{slot.get('code')}: winner={w} doesn't match the sets {st}. Check the screenshot.")


def winner_team(slot):
    w = slot.get("winner")
    if w is None or not slot.get("teams") or slot["teams"][w] is None:
        return None
    return slot["teams"][w]


def sets_for(slot, i):
    s = slot.get("sets")
    return [str(x[i]) for x in s] if s else None


# ---------- drawing a match ----------
def fit_fs(runs, avail, fs_start, fs_min, font_name="Anton.ttf"):
    fs = fs_start
    while fs > fs_min and pair_width(runs, font(font_name, fs), round(fs * 0.62)) > avail:
        fs -= 1
    return fs


def draw_card(base, box, slot, fs_max, fs_min, seed_size, show_label=False, label_left=False,
              mirror=False, scores=True):
    """Full card (first round): two rows with seed, flags + one-line names, set scores (or '–').
    mirror=True: everything right-aligned, seed badge on the right (slide 2 of the R16 carousel).
    scores=False: no score column at all (draw announcement), names get that space."""
    x0, y0, x1, y1 = box
    glass(base, box, 14)
    rrect(base, box, 14, outline=(255, 255, 255, 55), width=2)
    rh = (y1 - y0) / 2
    d = ImageDraw.Draw(base)
    d.line((x0 + 14, y0 + rh, x1 - 14, y0 + rh), fill=(255, 255, 255, 40), width=1)
    played = slot.get("winner") is not None
    sc_size = int(fs_max * 0.85)
    f_sc = font("Anton.ttf", sc_size)
    gap = sc_size * 0.42
    reserve = (3 * f_sc.getlength("7") + 2 * gap + 18) if scores else 4   # room for 3 sets, always
    seed_w = int(seed_size * 1.12) + 12
    if not mirror:
        name_x0, name_x1 = x0 + 16 + seed_w, x1 - reserve - 12
    else:
        name_x0, name_x1 = x0 + reserve + 12, x1 - 16 - seed_w
    avail = name_x1 - name_x0
    fs_names = ref_size(avail, fs_max, fs_min)
    for i, t in enumerate(slot["teams"]):
        cy = y0 + rh * (i + 0.5)
        won = played and slot["winner"] == i
        lost = played and not won
        col = WHITE if not lost else DIM
        if won:
            bx = (x0 + 3, x0 + 7) if not mirror else (x1 - 7, x1 - 3)
            rrect(base, (bx[0], cy - rh * 0.32, bx[1], cy + rh * 0.32), 2, fill=ACCENT + (255,))
        if t.get("seed"):
            sx = x0 + 16 if not mirror else x1 - 16 - int(seed_size * 1.12)
            small_seed(base, sx, cy, str(t["seed"]), won, seed_size)
        sc = sets_for(slot, i) if scores else None
        if sc:
            if not mirror:
                xs = x1 - 18
                for k in range(len(sc) - 1, -1, -1):
                    mine, theirs = slot["sets"][k][i], slot["sets"][k][1 - i]
                    ImageDraw.Draw(base).text((xs, cy), sc[k], font=f_sc, fill=ACCENT if mine > theirs else DIM, anchor="rm")
                    xs -= f_sc.getlength(sc[k]) + gap
            else:
                xs = x0 + 18
                for k in range(len(sc)):
                    mine, theirs = slot["sets"][k][i], slot["sets"][k][1 - i]
                    ImageDraw.Draw(base).text((xs, cy), sc[k], font=f_sc, fill=ACCENT if mine > theirs else DIM, anchor="lm")
                    xs += f_sc.getlength(sc[k]) + gap
        elif scores:
            dx = (x1 - 44, x1 - 20) if not mirror else (x0 + 20, x0 + 44)
            ImageDraw.Draw(base).rounded_rectangle((dx[0], cy - 3, dx[1], cy + 2), 2, fill=ACCENT_D + (255,))
        runs = pair_runs(t)
        fs = fit_fs(runs, avail, fs_names, fs_min)
        if not mirror:
            draw_pair(base, name_x0, cy, runs, avail, fs, fs_min, col, (120, 140, 180))
        else:
            wdt = pair_width(runs, font("Anton.ttf", fs), round(fs * 0.62))
            draw_pair(base, name_x1 - wdt, cy, runs, avail, fs, fs_min, col, (120, 140, 180))
    if show_label:
        f = font("Poppins-Bold.ttf", 15)
        lx = x0 + 6 if label_left else x1 - 6 - 46
        text_spaced(ImageDraw.Draw(base), (lx, y0 - 12), slot["code"], f, ACCENT, 4)


def draw_box(base, box, slot, final=False, fs=22, align="left", reserve_sets=None):
    """Later-round box: the pairs that advanced (surnames) or 'WINNER QF1' placeholders. Never scores:
    those matches haven't been played yet."""
    x0, y0, x1, y1 = box
    if final:
        g = hgrad(int(x1 - x0), int(y1 - y0), ACCENT + (255,), (52, 196, 150, 255))
        m = Image.new("L", g.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, g.width - 1, g.height - 1), 12, fill=255)
        base.paste(g, (int(x0), int(y0)), m)
        txt, line = (6, 22, 30), (6, 40, 40, 90)
    else:
        glass(base, box, 12, (8, 18, 52, 190))
        rrect(base, box, 12, outline=ACCENT_D + (170,), width=2)
        txt, line = WHITE, (255, 255, 255, 45)
    rh = (y1 - y0) / 2
    d = ImageDraw.Draw(base)
    d.line((x0 + 12, y0 + rh, x1 - 12, y0 + rh), fill=line, width=1)
    stacked = (y1 - y0) >= 140          # tall box: one player per line, flag + full name (much bigger)
    avail = x1 - x0 - 32
    if stacked:
        fs_n = min(fs, ref_size(avail, 40, 12, REF_PLAYER))
    else:
        fs_n = ref_size(avail, fs, 12, REF_SHORT)
    # placeholder size: fits "WINNER R16-8" in the box, capped
    ph = 22
    while ph > 12 and font("Poppins-Bold.ttf", ph).getlength("WINNER R16-8") + 1.5 * 11 > avail:
        ph -= 1
    f_ph = font("Poppins-Bold.ttf", ph)
    for i in range(2):
        cy = y0 + rh * (i + 0.5)
        t = slot["teams"][i] if slot.get("teams") else None
        if t is None:
            label = f"WINNER {slot['feeds'][i]}" if slot.get("feeds") else "TBD"
            text_spaced(d, (x0 + 16, cy + f_ph.size * 0.36), label, f_ph, txt if final else (210, 220, 240), 1.5)
        elif stacked:
            for j, p_ in enumerate(t["players"][:2]):
                ly = cy + (j - 0.5) * rh * 0.42
                draw_pair(base, x0 + 16, ly, [(p_.get("flag"), p_["name"].upper())], avail, fs_n, 11, txt, txt)
            d = ImageDraw.Draw(base)
        else:
            runs = [(None, n) for _, n in pair_runs(t, short=True)]
            draw_pair(base, x0 + 16, cy, runs, avail, fs_n, 11, txt, DIM if not final else (20, 60, 50))
            d = ImageDraw.Draw(base)


def connector(base, a_right, b_right, target_left, mirror=False):
    """Two feeder points (x, y) -> elbow -> target (x, y)."""
    L = Image.new("RGBA", base.size, (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    (ax, ay), (bx, by), (tx, ty) = a_right, b_right, target_left
    mx = (max(ax, bx) + tx) / 2 if not mirror else (min(ax, bx) + tx) / 2
    c = ACCENT_D + (190,)
    d.line([(ax, ay), (mx, ay), (mx, by), (bx, by)], fill=c, width=2)
    d.line([(mx, ty), (tx, ty)], fill=c, width=2)
    base.alpha_composite(L)


def round_label(base, x_center, y, text, final=False, size=30):
    f = font("Anton.ttf", size)
    ImageDraw.Draw(base).text((x_center, y), text, font=f, fill=ACCENT if final else WHITE, anchor="ms")


# ---------- header / footer ----------
def header(base, data, title, subtitle_extra=""):
    lg = white_logo(asset("thrill_logo.png"), size=(285, 68))
    base.alpha_composite(lg, (50, 50))
    if data.get("logo"):
        lp = asset(data["logo"], required=False)
        if lp:
            tl = white_logo(lp, box=(260, 101))
            base.alpha_composite(tl, (W - 52 - tl.width, 46 + (101 - tl.height) // 2))
    d = ImageDraw.Draw(base)
    size = 118
    f = font("Anton.ttf", size)
    while f.getlength(title) > 960 and size > 60:
        size -= 4; f = font("Anton.ttf", size)
    # title with a soft glow
    t = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(t).text((W / 2, 262), title, font=f, fill=WHITE, anchor="ms")
    glow = Image.new("RGBA", (W, H), ACCENT + (0,)); glow.putalpha(t.getchannel("A").filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.35)))
    base.alpha_composite(glow); base.alpha_composite(t)
    parts = [p for p in [data.get("date", ""), data.get("city", "")] if p]
    sub = "  ·  ".join(parts).upper() + subtitle_extra
    if sub:
        fs = font("Poppins-Bold.ttf", 24)
        sp = 8
        tw = sum(d.textlength(c, font=fs) + sp for c in sub) - sp
        x = W / 2 - tw / 2
        text_spaced(d, (x, 318), sub, fs, (225, 232, 248), sp)
        d.line((x - 90, 309, x - 24, 309), fill=ACCENT + (255,), width=3)
        d.line((x + tw + 24, 309, x + tw + 90, 309), fill=ACCENT + (255,), width=3)


def footer(base, data):
    d = ImageDraw.Draw(base)
    L = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(L).line((60, 1238, 1020, 1238), fill=ACCENT_D + (150,), width=2)
    base.alpha_composite(L)
    d = ImageDraw.Draw(base)
    f = font("Anton.ttf", 44)
    tour = data.get("tournament", "").upper()
    d.text((60, 1302), tour, font=f, fill=WHITE, anchor="ls")
    if data.get("category"):
        text_spaced(d, (60 + d.textlength(tour, font=f) + 14, 1302), data["category"].upper(), font("Poppins-Bold.ttf", 15), ACCENT, 5)


# ---------- layouts ----------
def layout_column(base, rounds, top=380, bottom=1210, scores=True):
    """Classic left-to-right bracket (the World Cup structure): QF -> SF -> F, or SF -> F."""
    n0 = len(rounds[0][1])
    if n0 == 4:
        cols = [(40, 585), (612, 846), (868, 1046)] if scores else [(40, 555), (586, 846), (868, 1046)]
        card_h, fs_max, seed = 134, 34, 32
        box_h = {"SF": 196, "F": 150}; box_fs = {"SF": 34, "F": 26}
    else:  # SF -> F
        cols = [(50, 660), (710, 1036)] if scores else [(50, 640), (690, 1036)]
        card_h, fs_max, seed = 190, 46, 40
        box_h = {"F": 230}; box_fs = {"F": 38}
    pitch = (bottom - top) / n0
    card_h = min(pitch - 34, card_h)
    centers = [top + pitch * (i + 0.5) + 12 for i in range(n0)]
    prev_pts = prev_cy = None
    for ri, (rn, slots) in enumerate(rounds):
        x0, x1 = cols[ri]
        if ri == 0:
            pts = []
            for i, s in enumerate(slots):
                cy = centers[i]
                draw_card(base, (x0, cy - card_h / 2, x1, cy + card_h / 2), s, fs_max, 14, seed,
                          show_label=True, scores=scores)
                pts.append((x1, cy))
            prev_cy = centers
        else:
            cys = [(prev_cy[2 * i] + prev_cy[2 * i + 1]) / 2 for i in range(len(slots))]
            bh, final = box_h[rn], rn == "F"
            pts = []
            for i, s in enumerate(slots):
                cy = cys[i]
                connector(base, prev_pts[2 * i], prev_pts[2 * i + 1], (x0, cy))
                draw_box(base, (x0, cy - bh / 2, x1, cy + bh / 2), s, final=final, fs=box_fs[rn])
                pts.append((x1, cy))
                round_label(base, (x0 + x1) / 2, cy - bh / 2 - 14, LABEL[rn], final=final, size=40 if final else 34)
            prev_cy = cys
        prev_pts = pts


def layout_mirrored(base, rounds, top=380, bottom=1210):
    """R16 split in two halves facing each other; semis and final in the centre column."""
    (r16n, r16), (qfn, qf), (sfn, sf), (fn, fin) = rounds
    pitch = (bottom - top) / 4
    card_h = 92
    xL0, xL1 = 18, 318
    xR0, xR1 = 762, 1062
    qL = (330, 430); qR = (650, 750)
    cX0, cX1 = 444, 636
    centers = [top + pitch * (i + 0.5) for i in range(4)]
    ptsL, ptsR = [], []
    for i in range(4):
        cy = centers[i]
        draw_card(base, (xL0, cy - card_h / 2, xL1, cy + card_h / 2), r16[i], 22, 12, 24)
        draw_card(base, (xR0, cy - card_h / 2, xR1, cy + card_h / 2), r16[4 + i], 22, 12, 24)
        ptsL.append((xL1, cy)); ptsR.append((xR0, cy))
    qcy = [(centers[0] + centers[1]) / 2, (centers[2] + centers[3]) / 2]
    bh = 70
    for i in range(2):
        connector(base, ptsL[2 * i], ptsL[2 * i + 1], (qL[0], qcy[i]))
        draw_box(base, (qL[0], qcy[i] - bh / 2, qL[1], qcy[i] + bh / 2), qf[i], fs=15)
        connector(base, ptsR[2 * i], ptsR[2 * i + 1], (qR[1], qcy[i]), mirror=True)
        draw_box(base, (qR[0], qcy[i] - bh / 2, qR[1], qcy[i] + bh / 2), qf[2 + i], fs=15)
    round_label(base, (qL[0] + qL[1]) / 2, qcy[0] - bh / 2 - 12, "QF", size=24)
    round_label(base, (qR[0] + qR[1]) / 2, qcy[0] - bh / 2 - 12, "QF", size=24)
    mid = (top + bottom) / 2
    sfL_cy, f_cy, sfR_cy = mid - 230, mid, mid + 230
    sbh = 84
    L = Image.new("RGBA", base.size, (0, 0, 0, 0)); d = ImageDraw.Draw(L); c = ACCENT_D + (190,)
    # left QFs -> SF (left, top of the centre column)
    mx = (qL[1] + cX0) / 2
    d.line([(qL[1], qcy[0]), (mx, qcy[0]), (mx, qcy[1]), (qL[1], qcy[1])], fill=c, width=2)
    d.line([(mx, sfL_cy), (cX0, sfL_cy)], fill=c, width=2)
    mx2 = (qR[0] + cX1) / 2
    d.line([(qR[0], qcy[0]), (mx2, qcy[0]), (mx2, qcy[1]), (qR[0], qcy[1])], fill=c, width=2)
    d.line([(mx2, sfR_cy), (cX1, sfR_cy)], fill=c, width=2)
    cx = (cX0 + cX1) / 2
    d.line([(cx, sfL_cy + sbh / 2), (cx, f_cy - 52)], fill=c, width=2)
    d.line([(cx, sfR_cy - sbh / 2), (cx, f_cy + 52)], fill=c, width=2)
    base.alpha_composite(L)
    draw_box(base, (cX0, sfL_cy - sbh / 2, cX1, sfL_cy + sbh / 2), sf[0], fs=20)
    draw_box(base, (cX0, sfR_cy - sbh / 2, cX1, sfR_cy + sbh / 2), sf[1], fs=20)
    draw_box(base, (cX0 - 10, f_cy - 52, cX1 + 10, f_cy + 52), fin[0], final=True, fs=22)
    round_label(base, cx, sfL_cy - sbh / 2 - 14, "SEMI-FINAL", size=28)
    round_label(base, cx, sfR_cy + sbh / 2 + 40, "SEMI-FINAL", size=28)
    round_label(base, cx, f_cy - 66, "FINAL", final=True, size=40)


def render(data, out_path):
    mode = data.get("mode") or ("scores" if any(m.get("sets") for m in data["matches"]) else "draw")
    if mode == "draw":  # draw announcement: no scores anywhere
        data = dict(data, matches=[{k: v for k, v in m.items() if k not in ("sets", "winner")} for m in data["matches"]])
    rounds = build_rounds(data)
    first = data["round"].upper()
    layout = data.get("layout", "carousel") if first == "R16" else "column"
    texture = data.get("texture", "streaks")
    title = ROUND_NAMES[first]
    outs = []
    if layout == "carousel":
        return render_split(data, rounds, out_path, texture, title)  # scores column only in "scores" mode
    base = background(texture)
    header(base, data, title)
    if layout == "mirrored":
        layout_mirrored(base, rounds)
    else:
        layout_column(base, rounds, scores=(mode == "scores"))
    footer(base, data)
    base.convert("RGB").save(out_path, quality=95)
    return {"file": out_path, "round": first, "layout": layout, "mode": mode}


def render_split(data, rounds, out_path, texture, title, top=380, bottom=1210):
    """Round of 16 as 2 slides on one 2160-wide canvas: slide 1 runs left->right (top half of the draw),
    slide 2 runs right->left (bottom half). The final box sits on the seam, under the semi-finals,
    so each slide shows half of it."""
    (r16n, r16), (qfn, qf), (sfn, sf), (fn, fin) = rounds
    WW = 2 * W
    base = background(texture, WW)
    pitch = (bottom - top) / 4
    card_h = 128
    centers = [top + pitch * (i + 0.5) + 10 for i in range(4)]
    R16 = (30, 565); QF = (592, 802); SFB = (830, 1044)
    mirror = lambda box: (WW - box[1], WW - box[0])
    qcy = [(centers[0] + centers[1]) / 2, (centers[2] + centers[3]) / 2]
    scy = (qcy[0] + qcy[1]) / 2 - 70
    fcy = scy + 270
    qbh, sbh, fbh = 150, 160, 104
    for side in (0, 1):
        m = (lambda b: b) if side == 0 else mirror
        cards = r16[side * 4:(side + 1) * 4]
        rx0, rx1 = m(R16); qx0, qx1 = m(QF); sx0, sx1 = m(SFB)
        inner = (lambda x0, x1: x1) if side == 0 else (lambda x0, x1: x0)   # side facing the centre
        outer = (lambda x0, x1: x0) if side == 0 else (lambda x0, x1: x1)
        pts = []
        has_scores = any(m.get("sets") for m in r16)   # draw announcement -> no score column
        for i, slot in enumerate(cards):
            draw_card(base, (rx0, centers[i] - card_h / 2, rx1, centers[i] + card_h / 2), slot, 32, 14, 30,
                      show_label=True, label_left=(side == 1), mirror=(side == 1), scores=has_scores)
            pts.append((inner(rx0, rx1), centers[i]))
        qpts = []
        for i in range(2):
            connector(base, pts[2 * i], pts[2 * i + 1], (outer(qx0, qx1), qcy[i]), mirror=(side == 1))
            draw_box(base, (qx0, qcy[i] - qbh / 2, qx1, qcy[i] + qbh / 2), qf[side * 2 + i], fs=28,
                     reserve_sets=any(q.get("sets") for q in qf))
            qpts.append((inner(qx0, qx1), qcy[i]))
        round_label(base, (qx0 + qx1) / 2, qcy[0] - qbh / 2 - 14, "QUARTER-FINAL", size=26)
        connector(base, qpts[0], qpts[1], (outer(sx0, sx1), scy), mirror=(side == 1))
        draw_box(base, (sx0, scy - sbh / 2, sx1, scy + sbh / 2), sf[side], fs=28,
                 reserve_sets=any(q.get("sets") for q in sf))
        round_label(base, (sx0 + sx1) / 2, scy - sbh / 2 - 14, "SEMI-FINAL", size=30)
        # semi-final -> final (straight down)
        cx = (sx0 + sx1) / 2
        L = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(L).line([(cx, scy + sbh / 2), (cx, fcy - fbh / 2)], fill=ACCENT_D + (190,), width=2)
        base.alpha_composite(L)
    # shared final box on the seam: left half = finalist from slide 1, right half = finalist from slide 2
    fx0, fx1 = W - 248, W + 248
    g = hgrad(fx1 - fx0, fbh, ACCENT + (255,), (52, 196, 150, 255))
    mk = Image.new("L", g.size, 0); ImageDraw.Draw(mk).rounded_rectangle((0, 0, g.width - 1, g.height - 1), 14, fill=255)
    base.paste(g, (fx0, int(fcy - fbh / 2)), mk)
    d = ImageDraw.Draw(base)
    d.line((W, fcy - fbh / 2 + 16, W, fcy + fbh / 2 - 16), fill=(6, 40, 40, 255), width=2)
    final = fin[0]
    played = final.get("winner") is not None
    for side in (0, 1):
        t = final["teams"][side] if final.get("teams") else None
        hx0, hx1 = (fx0, W) if side == 0 else (W, fx1)
        cxh = (hx0 + hx1) / 2
        if t is None:
            f_ph = font("Poppins-Bold.ttf", 17)
            label = f"WINNER SF{side + 1}"
            tw = sum(d.textlength(c, font=f_ph) + 2 for c in label) - 2
            text_spaced(d, (cxh - tw / 2, fcy + 6), label, f_ph, (6, 22, 30), 2)
        else:
            won = played and final["winner"] == side
            col = (6, 22, 30) if (not played or won) else (30, 80, 70)
            runs = [(None, n) for _, n in pair_runs(t, short=True)]
            fs_n = ref_size(hx1 - hx0 - 36, 26, 12, REF_SHORT)
            f = font("Anton.ttf", fs_n)
            wdt = pair_width(runs, f, 0)
            draw_pair(base, cxh - wdt / 2, fcy, runs, hx1 - hx0 - 36, fs_n, 11, col, (20, 60, 50))
            d = ImageDraw.Draw(base)
    round_label(base, W, fcy - fbh / 2 - 16, "FINAL", final=True, size=40)
    # split into the two slides, then header/footer on each
    stem, ext = os.path.splitext(out_path)
    outs = []
    for side in (0, 1):
        slide = base.crop((side * W, 0, (side + 1) * W, H))
        header(slide, data, title, f"  ·  {side + 1}/2")
        footer(slide, data)
        p = f"{stem}_slide{side + 1:02d}{ext}"
        slide.convert("RGB").save(p, quality=95); outs.append(p)
    return {"slides": outs, "round": "R16", "layout": "carousel"}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(render(data, sys.argv[2]), ensure_ascii=False))
