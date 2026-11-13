#!/usr/bin/env python3
"""thrill.com MATCH RESULT scoreboard (1080x1350), regular tournaments.

Same structure as the FIP World Cup scoreboard, in the thrill.com navy / lime colourway.

Usage:
    python3 score_render.py data.json out.png photo.jpg

data.json:
{
  "teams": [
    {"seed": 5,  "players": [{"name": "J. Nieto",  "flag": "es"}, {"name": "M. Yanguas", "flag": "es"}]},
    {"seed": 12, "players": [{"name": "E. Alonso", "flag": "es"}, {"name": "A. Goñi",    "flag": "es"}]}
  ],
  "sets": [[4, 6], [3, 6]],            # per set: [top team games, bottom team games]; tie-break: [7, 6, [7, 5]]
  "winner": 1,                         # 0 = top team, 1 = bottom team
  "tournament": "Paris Major",         # footer, left
  "round": "R16",                      # footer, right (R64, R32, R16, QF, SF, F ...)
  "logo": "logo_paris_major.png",      # tournament logo (from GitHub), top-right; optional
  "category": "",                      # optional small label after the tournament name (e.g. "WOMEN")
  "theme": "electric_bright",          # colourway (default electric_bright); others: court, ocean, steel, royal, electric, midnight, forest, graphite, mono, navy
  "accent": "mint",                    # optional: mint (default), white, ice, gold, coral, lime
  "seed_style": "badge",               # optional: badge (default) or label
  "bg_focus_y": 0.35, "bg_focus_x": 0.5, "bg_zoom": 1.0, "bw": false
}
Flags: ISO 3166 two-letter codes (es, ar, pt, fr, it, ...). One flag per player.
"""
import io, json, os, re, sys, urllib.request
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1350
HERE = os.path.dirname(os.path.abspath(__file__))
EDIT = None        # studio_editor.Scene while the editor page is being built (see studio_editor.py)
_FRAMING = {}      # exact photo framing of the last render (zoom, fx, fy), for the editor

# --- colourway (from the classic thrill.com scoreboard) ---
# --- colour themes: every theme keeps the fonts and the lime winner highlight ---
THEMES = {
    # the first draft
    "navy":     dict(ink=(3, 12, 34), mid=(10, 32, 72), top=(2, 8, 24), glow=(24, 90, 210), glow_a=120,
                     win_a=(34, 118, 64, 236), win_b=(12, 52, 44, 226), lose=(255, 255, 255, 22), lose_b=(255, 255, 255, 10),
                     lose_txt=(205, 214, 226), set_lost=(140, 156, 178), seed=(196, 206, 220), glass=False),
    # near-black, neutral, frosted cards
    "midnight": dict(ink=(8, 9, 10), mid=(14, 16, 17), top=(6, 7, 8), glow=(70, 90, 30), glow_a=70,
                     win_a=(40, 70, 20, 205), win_b=(18, 26, 14, 200), lose=(255, 255, 255, 26), lose_b=(255, 255, 255, 12),
                     lose_txt=(200, 200, 200), set_lost=(120, 122, 124), seed=(170, 172, 174), glass=True),
    # deep forest green, green-black base
    "forest":   dict(ink=(4, 16, 11), mid=(8, 30, 20), top=(3, 12, 8), glow=(60, 140, 40), glow_a=90,
                     win_a=(46, 120, 40, 225), win_b=(14, 46, 26, 220), lose=(255, 255, 255, 20), lose_b=(255, 255, 255, 8),
                     lose_txt=(200, 214, 204), set_lost=(118, 140, 126), seed=(170, 190, 176), glass=True),
    # pure black, white type, lime only as accent (outline winner card)
    "mono":     dict(ink=(0, 0, 0), mid=(8, 8, 8), top=(0, 0, 0), glow=(0, 0, 0), glow_a=0,
                     win_a=(190, 240, 40, 34), win_b=(190, 240, 40, 10), lose=(255, 255, 255, 16), lose_b=(255, 255, 255, 6),
                     lose_txt=(185, 185, 185), set_lost=(105, 105, 105), seed=(150, 150, 150), glass=True),
    # warm graphite with a hint of olive
    "graphite": dict(ink=(16, 17, 14), mid=(26, 28, 22), top=(10, 10, 9), glow=(150, 180, 60), glow_a=55,
                     win_a=(70, 96, 28, 215), win_b=(28, 34, 18, 205), lose=(255, 255, 255, 24), lose_b=(255, 255, 255, 10),
                     lose_txt=(210, 208, 200), set_lost=(128, 128, 118), seed=(176, 176, 166), glass=True),
}
# blue family (padel court blues)
THEMES.update({
    # very dark ocean blue, cyan-ish glow, frosted cards
    "ocean":    dict(ink=(3, 8, 20), mid=(8, 22, 52), top=(2, 6, 16), glow=(20, 120, 200), glow_a=70,
                     win_a=(40, 120, 70, 215), win_b=(12, 40, 44, 205), lose=(140, 190, 255, 22), lose_b=(140, 190, 255, 8),
                     lose_txt=(198, 212, 232), set_lost=(110, 132, 166), seed=(160, 180, 210), glass=True, grain=True),
    # padel-court blue: rich court blue fading to near black
    "court":    dict(ink=(4, 14, 40), mid=(14, 52, 128), top=(4, 12, 34), glow=(40, 110, 230), glow_a=95,
                     win_a=(46, 130, 66, 222), win_b=(14, 52, 60, 212), lose=(255, 255, 255, 24), lose_b=(255, 255, 255, 10),
                     lose_txt=(214, 226, 244), set_lost=(132, 156, 196), seed=(176, 196, 226), glass=True, grain=True),
    # steel / ice: desaturated blue-grey, cool and premium
    "steel":    dict(ink=(10, 15, 22), mid=(22, 33, 46), top=(8, 12, 18), glow=(90, 130, 170), glow_a=55,
                     win_a=(56, 110, 50, 210), win_b=(20, 34, 36, 200), lose=(200, 220, 255, 20), lose_b=(200, 220, 255, 8),
                     lose_txt=(206, 214, 224), set_lost=(120, 134, 150), seed=(168, 180, 194), glass=True, grain=True),
    # royal: deep royal blue with a soft violet edge
    "royal":    dict(ink=(6, 8, 30), mid=(18, 30, 92), top=(5, 7, 24), glow=(70, 80, 220), glow_a=85,
                     win_a=(50, 124, 64, 220), win_b=(16, 40, 62, 210), lose=(255, 255, 255, 22), lose_b=(255, 255, 255, 9),
                     lose_txt=(210, 216, 240), set_lost=(128, 140, 190), seed=(176, 184, 226), glass=True, grain=True),
    # electric: near-black base, electric blue glow, blue-tinted winner card with lime numbers
    "electric": dict(ink=(2, 4, 12), mid=(6, 14, 40), top=(2, 4, 10), glow=(30, 90, 255), glow_a=110,
                     win_a=(28, 80, 200, 200), win_b=(10, 26, 70, 195), lose=(255, 255, 255, 18), lose_b=(255, 255, 255, 7),
                     lose_txt=(200, 210, 230), set_lost=(110, 124, 160), seed=(160, 172, 205), glass=True, grain=True),
})
DEFAULT_THEME = "electric_bright"
TEX_FROM = 1150                 # texture starts just under the cards (footer area)
TEX_STRENGTH = 0.5
LIME = (190, 240, 40)
LIME_D = (150, 196, 30)
# accent colour: winner outline + bar, winning set scores, round label, divider
ACCENTS = {
    "lime":  (190, 240, 40),
    "white": (255, 255, 255),
    "ice":   (120, 220, 255),
    "gold":  (255, 196, 64),
    "coral": (255, 112, 80),
    "mint":  (90, 245, 190),
}
THEMES["electric_bright"] = dict(ink=(5, 10, 34), mid=(14, 36, 110), top=(3, 7, 22), glow=(40, 115, 255), glow_a=160,
                                 win_a=(44, 112, 255, 225), win_b=(16, 44, 140, 210), lose=(170, 200, 255, 26), lose_b=(170, 200, 255, 10),
                                 lose_txt=(214, 224, 246), set_lost=(126, 146, 196), seed=(178, 194, 232), glass=True, grain=True,
                                 accent="mint", black_top=True)

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


# ---------- render ----------
def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A background photo is required: score_render.py data.json out.png photo.jpg")
    bg = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    if data.get("bw"):
        bg = ImageOps.grayscale(bg).convert("RGB")
    k = max(W / bg.width, H / bg.height) * data.get("bg_zoom", 1.0)
    bg = bg.resize((round(bg.width * k), round(bg.height * k)), Image.LANCZOS)
    fx, fy = data.get("bg_focus_x", 0.5), data.get("bg_focus_y", 0.35)
    x0, y0 = round((bg.width - W) * fx), round((bg.height - H) * fy)
    base = bg.crop((x0, y0, x0 + W, y0 + H)).convert("RGBA")
    if EDIT is not None:
        base = EDIT.photo(photo, data.get("bg_zoom", 1.0), fx, fy, bool(data.get("bw")))

    # cinematic grading (same structure as the World Cup version, navy instead of maroon)
    T = THEMES[data.get("theme", DEFAULT_THEME)]
    acc = data.get("accent") or T.get("accent", "lime")
    A = ACCENTS.get(acc, ACCENTS["lime"]) if isinstance(acc, str) else tuple(acc)
    A_D = tuple(int(c * 0.8) for c in A)
    base.alpha_composite(vgrad(W, H, [(0, T["top"] + (170,)), (0.13, T["top"] + (40,)), (0.45, (0, 0, 0, 0)), (1, (0, 0, 0, 0))]))
    if T.get("black_top"):
        # photo -> black fade above the cards (no colour near the photo); the blue only starts lower down
        base.alpha_composite(vgrad(W, H, [(0, (0, 0, 0, 0)), (0.47, (0, 0, 0, 0)), (0.62, (0, 0, 0, 215)), (0.69, (0, 0, 0, 250)),
                                          (0.80, T["ink"] + (255,)), (1, T["mid"] + (255,))]))
        glow_box = (-200, 1160, 1280, 1760)
    else:
        base.alpha_composite(vgrad(W, H, [(0, (0, 0, 0, 0)), (0.50, (0, 0, 0, 0)), (0.63, T["mid"] + (215,)), (0.68, T["ink"] + (253,)), (1, T["ink"] + (255,))]))
        glow_box = (-200, 1050, 1280, 1650)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(glow_box, fill=T["glow"] + (T["glow_a"],))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))
    tex_mode = data.get("texture", "screen")
    if tex_mode and tex_mode != "none":
        # electric-blue brush texture + court-line details at the bottom (the tennis layers, recoloured), lightening the blue
        import numpy as np
        tex = Image.open(asset(data.get("texture_file", "score_texture_padel.png"))).convert("RGBA")
        b = np.array(base, np.float32) / 255; t = np.array(tex, np.float32) / 255
        k = data.get("texture_strength", TEX_STRENGTH)
        a = t[..., 3:4] * np.clip((np.arange(H)[:, None, None] - TEX_FROM) / 70, 0, 1)   # only below the cards: they stay as clean as before
        lum = t[..., :3].max(2, keepdims=True)
        tint = np.array([0.35, 0.62, 1.0]) * lum * 1.9 * k
        scr = 1 - (1 - b[..., :3]) * (1 - np.clip(tint, 0, 1))
        b[..., :3] = b[..., :3] * (1 - a) + scr * a
        base = Image.fromarray((np.clip(b, 0, 1) * 255).astype(np.uint8), "RGBA")
    # soft dark patch top-right, only behind a tournament logo (keeps it readable on any photo)
    if data.get("logo"):
        patch = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(patch).rounded_rectangle((650, 0, 1100, 150), 50, fill=T["top"] + (255,))
        base.alpha_composite(patch.filter(ImageFilter.GaussianBlur(18)))
    if T.get("grain"):
        import numpy as np
        rng = np.random.default_rng(3)
        n = (rng.normal(0, 1, (H, W)) * 7).astype(np.float32)
        mask = np.clip((np.arange(H) - 0.55 * H) / (0.15 * H), 0, 1)[:, None]
        arr = np.array(base, np.float32)
        arr[..., :3] = np.clip(arr[..., :3] + (n * mask)[..., None], 0, 255)
        base = Image.fromarray(arr.astype(np.uint8), "RGBA")
    d = ImageDraw.Draw(base)

    # logos
    base.alpha_composite(white_logo(asset("thrill_logo.png"), size=(285, round(285 * 68 / 285))), (50, 50))
    if data.get("logo"):
        lp = asset(data["logo"], required=False)
        if lp:
            tl = white_logo(lp, box=(260, 101))
            base.alpha_composite(tl, (W - 52 - tl.width, 46 + (101 - tl.height) // 2))

    # team rows
    teams, sets, winner = data["teams"], data["sets"], data.get("winner", 0)
    f_name, f_set, f_tb = font("Anton.ttf", 48), font("Anton.ttf", 88), font("Anton.ttf", 26)
    seed_style = data.get("seed_style", "badge")
    x0c, x1c, rh = 60, 1020, 132
    ys = [884, 1028]
    any_seed = any(t.get("seed") for t in teams)
    col_w = 92
    cols = [x1c - 30 - col_w * (len(sets) - i) + col_w / 2 for i in range(len(sets))]
    fw, fh = 46, 31
    seed_x = x0c + 24
    flag_x = x0c + (92 if any_seed else 30)
    name_x = flag_x + fw + 18
    for i, (t, y) in enumerate(zip(teams, ys)):
        won = i == winner
        card = Image.new("RGBA", (x1c - x0c, rh), (0, 0, 0, 0))
        if T["glass"]:  # frosted glass: blur what is behind the card
            card = base.crop((x0c, y, x1c, y + rh)).filter(ImageFilter.GaussianBlur(18))
            card.alpha_composite(Image.new("RGBA", card.size, (0, 0, 0, 60)))
        if won:
            card.alpha_composite(hgrad(x1c - x0c, rh, T["win_a"], T["win_b"]))
        else:
            card.alpha_composite(hgrad(x1c - x0c, rh, T["lose"], T["lose_b"]))
        card = rounded(card, 18)
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((0, 0, x1c - x0c - 1, rh - 1), 18, outline=(A + (230,)) if won else (255, 255, 255, 40), width=2)
        if won:
            cd.rectangle((0, 22, 6, rh - 22), fill=A + (255,))
        base.alpha_composite(card, (x0c, y))
        if t.get("seed"):
            draw_seed(base, (seed_x, y + rh / 2), str(t["seed"]), won, A, seed_style)
            d = ImageDraw.Draw(base)
        nc = (255, 255, 255) if won else T["lose_txt"]
        for j, p in enumerate(t["players"][:2]):
            cy = y + rh / 2 + (-30 if j == 0 else 30)
            if p.get("flag"):
                base.alpha_composite(flag(p["flag"], fw, fh), (flag_x, int(cy - fh / 2)))
            d.text((name_x, cy), name_caps(p["name"]), font=f_name, fill=nc, anchor="lm")
        for kk, s in enumerate(sets):
            mine, theirs = s[i], s[1 - i]
            c = A if mine > theirs else T["set_lost"]
            bb = d.textbbox((0, 0), str(mine), font=f_set, anchor="ls")
            d.text((cols[kk] - (bb[0] + bb[2]) / 2, y + rh / 2 - (bb[1] + bb[3]) / 2), str(mine), font=f_set, fill=c, anchor="ls")
            if len(s) > 2 and s[2] is not None and mine < theirs:  # tie-break points only for the set loser
                d.text((cols[kk] + 30, y + rh / 2 - 30), str(s[2][i]), font=f_tb, fill=c, anchor="lm")

    # divider + footer
    div = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(div).line((60, 1200, 1020, 1200), fill=A_D + (150,), width=2)
    base.alpha_composite(div)
    d = ImageDraw.Draw(base)
    f_ft = font("Anton.ttf", 44)
    tour = data.get("tournament", "").upper()
    d.text((60, 1290), tour, font=f_ft, fill=(255, 255, 255), anchor="ls")
    if data.get("category"):
        f_cat = font("Poppins-Bold.ttf", 15)
        text_spaced(d, (60 + d.textlength(tour, font=f_ft) + 14, 1290), data["category"].upper(), f_cat, A, 5)
    d.text((1020, 1290), data.get("round", "").upper(), font=f_ft, fill=A, anchor="rs")

    if EDIT is not None:
        EDIT.static(base)
    base.convert("RGB").save(out_path, quality=95)
    return {"winner": winner, "sets": sets, "tournament": tour, "round": data.get("round", "")}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--editor"]
    if len(args) < 2:
        print(__doc__); sys.exit(1)
    data = json.load(open(args[0], encoding="utf-8"))
    photo = args[2] if len(args) > 2 else None
    info = render(data, args[1], photo)
    if "--editor" in sys.argv or data.get("editor"):
        # interactive page to drag / zoom the photos: <out>_editor.html (see studio_editor.py)
        import studio_editor
        info["editor"] = studio_editor.run(sys.modules[__name__], data, args[1], photo, accent="#2E7BFF")
    print(json.dumps(info, ensure_ascii=False))
